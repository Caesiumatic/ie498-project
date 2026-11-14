"""Offline delivery checks; synthetic rows never enter the formal experiment."""
from copy import deepcopy
import csv
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from ie498.memory import digest
from ie498.paper_execution import PROTOCOL
from ie498.storage import Store, atomic_json


_SPEC = spec_from_file_location("paper_package", Path(__file__).resolve().parents[1] / "scripts/package_paper_replication.py")
package = module_from_spec(_SPEC)
_SPEC.loader.exec_module(package)


@pytest.fixture
def complete_rows(tmp_path):
    """A compact synthetic database for completion gates, not an empirical archive."""
    store = Store(tmp_path / "synthetic", budget=None)
    manifest = {"protocol": PROTOCOL, "transport": "chatgpt_subscription", "runs": []}
    attempts = []
    periods = []
    for run, (prefix, alpha) in sorted(package.EXPECTED_CONFIG.items()):
        config = {"prefix": prefix, "alpha": alpha, "T": 300, "H": 100, "model": "gpt-6-luna",
                  "architecture": "paper_replication", "reasoning_effort": "none", "transport": manifest["transport"]}
        manifest["runs"].append({"id": run, "config": config})
        store.add_run(run, config, "synthetic", "synthetic")
        store.status(run, "completed")
        for t in range(1, 301):
            periods.append((run, t, json.dumps({"t": t})))
            for seller in (0, 1):
                attempts.append((f"{run}-{t}-{seller}", f"{run}:{t}:{seller}:seller", run, t, seller))
    with store.db:
        store.db.executemany("INSERT INTO rounds VALUES(?,?,?)", periods)
        store.db.executemany("""INSERT INTO api_attempts
            (id,call_id,attempt,run_id,t,agent,purpose,status,request_hash,request_json,reserved,created)
            VALUES(?,?,1,?,?,?,'seller','accepted','synthetic','{}',0,0)""", attempts)
    yield store, manifest
    store.close()


def test_completion_gate_requires_exact_full_six_cell_sample(complete_rows):
    store, manifest = complete_rows
    assert len(package.require_complete(store, manifest)) == 3600
    # The synthetically complete count alone cannot make a deliverable: no raw evidence exists.
    with pytest.raises(ValueError, match="raw response path"):
        package.attempt_files(store, package.require_complete(store, manifest), manifest["transport"])


@pytest.mark.parametrize("failure", ["unfinished", "missing_period", "pending", "missing_accepted", "mock", "wrong_condition"])
def test_completion_gate_rejects_partial_pending_or_relabelled_data(complete_rows, failure):
    store, manifest = complete_rows
    run = sorted(package.EXPECTED)[0]
    with store.db:
        if failure == "unfinished":
            store.db.execute("UPDATE runs SET status='running' WHERE id=?", (run,))
        elif failure == "missing_period":
            store.db.execute("DELETE FROM rounds WHERE run_id=? AND t=150", (run,))
        elif failure == "pending":
            store.db.execute("UPDATE api_attempts SET status='pending' WHERE run_id=? AND t=300 AND agent=0", (run,))
        elif failure == "missing_accepted":
            store.db.execute("UPDATE api_attempts SET status='invalid' WHERE run_id=? AND t=300 AND agent=0", (run,))
        else:
            row = next(r for r in manifest["runs"] if r["id"] == run)
            row["config"]["provider" if failure == "mock" else "prefix"] = "mock" if failure == "mock" else "P2"
            store.db.execute("UPDATE runs SET config=? WHERE id=?", (json.dumps(row["config"]), run))
    with pytest.raises(ValueError):
        package.require_complete(store, manifest)


def evidence_fixture(tmp_path):
    store = Store(tmp_path / "evidence", budget=None)
    run = "paper-p1-a1-r1"
    request = {"model": "gpt-6-luna", "input": [{"role": "user", "content": "Offline fixture"}]}
    row = {"id": "offline-attempt", "run_id": run, "t": 1, "agent": 0, "purpose": "seller",
           "call_id": f"{run}:1:0:seller", "request_json": json.dumps(request), "request_hash": digest(request),
           "status": "accepted", "raw_path": "raw/offline-attempt.json"}
    raw = {"terminal_event": "response.completed", "response": {"model": "gpt-6-luna", "reasoning": {"effort": "none"}},
           "experiment_provenance": {"protocol": PROTOCOL, "transport": "chatgpt_subscription",
                                     "logical_call_id": row["call_id"], "request_hash": row["request_hash"]}}
    atomic_json(store.root / "requests/offline-attempt.json", request)
    atomic_json(store.root / row["raw_path"], raw)
    row["raw_sha256"] = digest((store.root / row["raw_path"]).read_text())
    return store, row, raw


@pytest.mark.parametrize("failure", ["none", "raw_missing", "request_changed", "raw_corrupt", "mock", "symlink"])
def test_attempt_evidence_whitelist_and_integrity(tmp_path, failure):
    store, row, raw = evidence_fixture(tmp_path)
    path = store.root / row["raw_path"]
    try:
        if failure == "raw_missing":
            path.unlink()
        elif failure == "request_changed":
            atomic_json(store.root / "requests/offline-attempt.json", {"model": "wrong"})
        elif failure == "raw_corrupt":
            path.write_text(path.read_text() + " ")
        elif failure == "mock":
            raw["response"]["id"] = "mock-not-empirical"
            atomic_json(path, raw)
            row["raw_sha256"] = digest(path.read_text())
        elif failure == "symlink":
            secret = tmp_path / "auth" / "token.json"
            secret.parent.mkdir()
            secret.write_text("DO_NOT_READ_THIS_SECRET")
            path.unlink()
            path.symlink_to(secret)
        if failure == "none":
            assert set(package.attempt_files(store, [row], "chatgpt_subscription")) == {
                "requests/offline-attempt.json", "raw/offline-attempt.json"}
        else:
            with pytest.raises(ValueError):
                package.attempt_files(store, [row], "chatgpt_subscription")
    finally:
        store.close()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "data/auth/token.json", "cookies/session.json", ".env", "x/.env.local", "x\\y"])
def test_archive_paths_exclude_credentials_and_traversal(name):
    with pytest.raises(ValueError):
        package.safe_name(name)


def archive_fixture(tmp_path):
    database = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE evidence (value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('offline fixture')")
    report = tmp_path / "report.md"
    report.write_text("Standalone fixture report")
    files = {f"{package.DATA_REL}/experiments.sqlite": (database, tmp_path), "reports/report.md": (report, tmp_path)}
    output = tmp_path / "delivery.zip"
    package.write_archive(output, files)
    return output, files


def test_archive_roundtrip_verifies_hashes_crc_and_temporary_sqlite_restore(tmp_path):
    output, files = archive_fixture(tmp_path)
    result = package.verify_archive(output)
    assert result == {"payload_files": 2, "all_file_checksums_matched": True, "zip_crc_checked": True, "sqlite_integrity": "ok"}
    with zipfile.ZipFile(output) as archive:
        index = json.loads(archive.read(f"{package.ARCHIVE_ROOT}/DELIVERY_MANIFEST.json"))
        assert set(index["files"]) == set(files)
        assert not any(name.endswith(("-wal", "-shm")) for name in archive.namelist())


def test_archive_detects_payload_change_even_with_a_valid_rebuilt_zip_crc(tmp_path):
    output, _ = archive_fixture(tmp_path)
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(changed, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            target.writestr(name, payload + b"modified" if name.endswith("report.md") else payload)
    with pytest.raises(ValueError, match="checksum mismatch"):
        package.verify_archive(changed)


def test_streaming_secret_scan_rejects_credential_payload(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("sk-proj-" + "A" * 80)
    with pytest.raises(ValueError, match="Credential-like"):
        package.write_archive(tmp_path / "rejected.zip", {"report.md": (report, tmp_path)})


def completed_report_fixture(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"protocol":"fixture"}')
    for name in package.REPORT_FILES:
        (reports / name).write_text("offline fixture")
    with (reports / "run_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["run_id", "complete", "rounds_completed", "accepted_calls"])
        writer.writeheader()
        writer.writerows({"run_id": run, "complete": True, "rounds_completed": 300, "accepted_calls": 600}
                         for run in package.EXPECTED)
    atomic_json(reports / "protocol_manifest.json", {"source_manifest_sha256": package.sha256(manifest)})
    fingerprints = {"data_fingerprint": "1" * 64, "accepted_fingerprint": "2" * 64}
    atomic_json(reports / package.BUILD_RECEIPT, {
        "schema": "ie498-paper-report-build-v1", "complete": True, "complete_runs": 6, "saved_periods": 1800,
        "source_manifest_sha256": package.sha256(manifest), **fingerprints,
        "files": {name: package.sha256(reports / name) for name in package.REPORT_FILES},
    })
    return reports, manifest, fingerprints


def test_final_report_must_match_the_completed_sample_and_frozen_manifest(tmp_path):
    reports, manifest, fingerprints = completed_report_fixture(tmp_path)
    package.require_final_report(reports, manifest, **fingerprints)
    manifest.write_text('{"protocol":"changed"}')
    with pytest.raises(ValueError, match="stale"):
        package.require_final_report(reports, manifest, **fingerprints)


@pytest.mark.parametrize("changed_file", ["report.md", "trajectories.png", "final50.png"])
def test_complete_csv_and_matching_protocol_cannot_hide_stale_report_or_figures(tmp_path, changed_file):
    reports, manifest, fingerprints = completed_report_fixture(tmp_path)
    # The complete run_summary.csv and matching public protocol remain unchanged.
    (reports / changed_file).write_text("STALE INTERIM OUTPUT FROM AN EARLIER BUILD")
    with pytest.raises(ValueError, match="differs from its completed build receipt"):
        package.require_final_report(reports, manifest, **fingerprints)


def test_missing_last_written_build_receipt_rejects_apparently_complete_outputs(tmp_path):
    reports, manifest, fingerprints = completed_report_fixture(tmp_path)
    (reports / package.BUILD_RECEIPT).unlink()
    with pytest.raises(ValueError):
        package.require_final_report(reports, manifest, **fingerprints)


@pytest.mark.parametrize("changed_input", ["data_fingerprint", "accepted_fingerprint"])
def test_report_receipt_cannot_describe_different_history_or_accepted_evidence(tmp_path, changed_input):
    reports, manifest, fingerprints = completed_report_fixture(tmp_path)
    fingerprints[changed_input] = "3" * 64
    with pytest.raises(ValueError, match="stale relative to the experiment inputs"):
        package.require_final_report(reports, manifest, **fingerprints)


def test_incomplete_build_receipt_cannot_be_relabelled_by_complete_csv(tmp_path):
    reports, manifest, fingerprints = completed_report_fixture(tmp_path)
    path = reports / package.BUILD_RECEIPT
    receipt = json.loads(path.read_text())
    receipt["complete"] = False
    atomic_json(path, receipt)
    with pytest.raises(ValueError, match="complete report build receipt"):
        package.require_final_report(reports, manifest, **fingerprints)


def test_packager_and_report_builder_fingerprint_the_same_database_inputs(tmp_path):
    store, row, raw = evidence_fixture(tmp_path)
    config = {"prefix": "P1", "alpha": 1., "T": 300, "H": 100, "model": "gpt-6-luna",
              "architecture": "paper_replication", "reasoning_effort": "none", "transport": "chatgpt_subscription"}
    store.add_run(row["run_id"], config, "fixture-commit", "fixture-prompt")
    store.reserve({**row, "attempt": 1, "reserved": 0})
    store.finish_attempt(row["id"], "accepted", 0, parsed={"price": 1.8}, raw_path=row["raw_path"])
    spec = spec_from_file_location("report_fingerprint_test", package.ROOT / "scripts/report_paper_replication.py")
    builder = module_from_spec(spec)
    spec.loader.exec_module(builder)
    try:
        runs, histories, sampling, _ = builder.load_runs(store.root)
        before = package.report_input_fingerprints(store)
        assert before == (builder.fingerprint_runs(runs, histories), builder.fingerprint_sampling(sampling))
        # A sampling-metadata change leaves the market state unchanged but invalidates evidence freshness.
        raw["response"]["top_p"] = .5
        atomic_json(store.root / row["raw_path"], raw)
        store.finish_attempt(row["id"], "accepted", 0, parsed={"price": 1.8}, raw_path=row["raw_path"])
        after = package.report_input_fingerprints(store)
        assert after[0] == before[0] and after[1] != before[1]
    finally:
        store.close()


def test_initial_scheduler_source_is_checked_against_its_own_frozen_hash(tmp_path, monkeypatch):
    root, data, stage = tmp_path / "repo", tmp_path / "data", tmp_path / "stage"
    root.mkdir()
    data.mkdir()
    stage.mkdir()
    source = b"# original six-request scheduler\n"
    commit = "a" * 40
    atomic_json(data / "manifest.initial-concurrency6.json", {"code_commit": commit,
                "source_hashes": {"src/ie498/paper_execution.py": hashlib.sha256(source).hexdigest()}})
    observed = []

    def git_show(args, *, cwd):
        observed.append((args, cwd))
        return source

    monkeypatch.setattr(package.subprocess, "check_output", git_show)
    files = package.initial_execution_source(root, data, stage)
    assert observed == [(["git", "show", f"{commit}:src/ie498/paper_execution.py"], root)]
    assert files["provenance/initial-paper_execution.py"][0].read_bytes() == source
    monkeypatch.setattr(package.subprocess, "check_output", lambda *args, **kwargs: b"changed")
    with pytest.raises(ValueError, match="initial frozen hash"):
        package.initial_execution_source(root, data, stage)
