#!/usr/bin/env python3
"""Package only the completed six-condition paper replication, without credentials."""
import argparse
from contextlib import closing
import csv
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ie498.paper_execution import PROTOCOL, audit
from ie498.memory import digest
from ie498.runner import coordinator_lock
from ie498.storage import Store, atomic_json

EXPECTED_CONFIG = {f"paper-{prefix.lower()}-a{label}-r1": (prefix, alpha)
                   for prefix in ("P1", "P2") for label, alpha in (("1", 1.), ("3p2", 3.2), ("10", 10.))}
EXPECTED = set(EXPECTED_CONFIG)
ARCHIVE_ROOT = "ie498-paper-replication"
DATA_REL = "data/runs/paper_replication"
RECEIPTS = ("manifest.json", "manifest.initial-concurrency6.json", "scheduling-amendment.json",
            "audit-before-concurrency-resume.json", "status.json")
REPORT_FILES = ("report.md", "trajectories.png", "final50.png", "run_summary.csv", "rounds.csv", "protocol_manifest.json")
BUILD_RECEIPT = "build_receipt.json"
CODE_FILES = ("pyproject.toml", "uv.lock", "scripts/run_paper_replication.py",
              "scripts/report_paper_replication.py", "scripts/package_paper_replication.py",
              "tests/test_paper_replication.py", "tests/test_paper_execution.py", "tests/test_paper_report.py", "tests/test_paper_package.py",
              "docs/paper_replication_protocol.md", "docs/paper_replication_source_search.md",
              "docs/sources/paper-v6.pdf", "docs/sources/paper-v6.txt", "docs/sources/manifest.json",
              "docs/sources/latest-model.html", "docs/sources/model-6luna.html")
FORBIDDEN = {"auth", "credentials", "secrets", "cookies", ".git", ".codex", ".aws", ".ssh", ".netrc"}
SECRET_PATTERN = re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")


def sha256(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    parts = [part.lower() for part in path.parts]
    if (not name or path.is_absolute() or ".." in parts or "\\" in name or str(path) != name
            or any(part in FORBIDDEN or part == ".env" or part.startswith(".env.") for part in parts)):
        raise ValueError(f"Unsafe or credential-bearing archive path: {name}")
    return path


def safe_file(path, base):
    """Reject symlinks, credential paths, and escapes before reading file content."""
    path, base = Path(path).absolute(), Path(base).absolute()
    if not path.is_relative_to(base):
        raise ValueError("Package input escapes its permitted source directory")
    safe_name(path.relative_to(base).as_posix())
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("Package inputs must not contain symlinks")
    if any(part.lower() in FORBIDDEN for part in path.parts) or not path.is_file():
        raise ValueError(f"Missing, non-file, or credential input: {path.name}")
    return path


def require_complete(store, manifest):
    if manifest.get("protocol") != PROTOCOL or manifest.get("transport") not in ("api_key", "chatgpt_subscription"):
        raise ValueError("Unknown or mock paper protocol")
    frozen = manifest.get("runs", [])
    if len(frozen) != 6 or {row["id"] for row in frozen} != EXPECTED:
        raise ValueError("Manifest must contain the six declared paper conditions")
    rows = store.rows("SELECT id,status,config FROM runs")
    if len(rows) != 6 or {r["id"] for r in rows} != EXPECTED:
        raise ValueError("Database must contain only the six declared paper conditions")
    configs = {row["id"]: row["config"] for row in frozen}
    for row in rows:
        config = json.loads(row["config"])
        if (config != configs[row["id"]] or config.get("T") != 300 or config.get("model") != "gpt-6-luna"
                or config.get("architecture") != "paper_replication" or config.get("provider") == "mock"
                or config.get("mock") or config.get("transport") != manifest["transport"]
                or (config.get("prefix"), config.get("alpha")) != EXPECTED_CONFIG[row["id"]]
                or config.get("H") != 100 or config.get("reasoning_effort") != "none"):
            raise ValueError("Unrecognized, mock, or altered condition configuration")
        periods = [r["t"] for r in store.rows("SELECT t FROM rounds WHERE run_id=? ORDER BY t", (row["id"],))]
        if row["status"] != "completed" or periods != list(range(1, 301)):
            raise ValueError(f"Incomplete condition: {row['id']}")
    attempts = store.rows("SELECT * FROM api_attempts ORDER BY id")
    if any(row["status"] == "pending" for row in attempts):
        raise ValueError("Pending attempts must be reconciled before packaging")
    accepted = [row for row in attempts if row["status"] == "accepted"]
    expected_calls = {f"{run}:{t}:{seller}:seller" for run in EXPECTED for t in range(1, 301) for seller in (0, 1)}
    if len(accepted) != 3600 or {row["call_id"] for row in accepted} != expected_calls:
        raise ValueError("Exactly 3,600 accepted seller calls are required")
    return attempts


def attempt_files(store, attempts, transport):
    """Whitelist only durable evidence referenced by the dedicated database."""
    files = {}
    for row in attempts:
        identifier = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("Unsafe attempt identifier")
        if row["run_id"] not in EXPECTED or not 1 <= row["t"] <= 300 or row["agent"] not in (0, 1) or row["purpose"] != "seller":
            raise ValueError("Attempt lies outside the six-condition seller experiment")
        if row["raw_path"] != f"raw/{identifier}.json":
            raise ValueError("Missing or unexpected raw response path")
        request_name, raw_name = f"requests/{identifier}.json", row["raw_path"]
        request_path, raw_path = (safe_file(store.root / rel, store.root) for rel in (request_name, raw_name))
        body = json.loads(request_path.read_text())
        if body != json.loads(row["request_json"]) or digest(body) != row["request_hash"]:
            raise ValueError("Saved request does not match its database fingerprint")
        raw_text = raw_path.read_text()
        if digest(raw_text) != row["raw_sha256"]:
            raise ValueError("Raw response fingerprint mismatch")
        raw = json.loads(raw_text)
        response = raw.get("response", {})
        if (raw.get("mock") or raw.get("model") == "mock" or str(raw.get("id", "")).startswith("mock-")
                or response.get("mock") or str(response.get("id", "")).startswith("mock-")):
            raise ValueError("Mock responses cannot be delivered as empirical evidence")
        provenance = raw.get("experiment_provenance", {})
        if provenance != {"protocol": PROTOCOL, "transport": transport, "logical_call_id": row["call_id"],
                          "request_hash": row["request_hash"]}:
            raise ValueError("Missing or inconsistent empirical response provenance")
        if row["status"] == "accepted":
            if transport == "chatgpt_subscription":
                response = raw.get("response", {})
                if (raw.get("error") or raw.get("terminal_event") != "response.completed"
                        or response.get("model") != "gpt-6-luna" or response.get("reasoning", {}).get("effort") != "none"):
                    raise ValueError("Accepted subscription sample lacks expected terminal/model evidence")
            elif raw.get("model") != "gpt-6-luna":
                raise ValueError("Accepted API sample lacks expected model evidence")
        files[request_name], files[raw_name] = request_path, raw_path
    return files


def report_input_fingerprints(store):
    """Bind market data, accepted evidence, and all execution outcomes to the report."""
    spec = spec_from_file_location("paper_report_delivery", ROOT / "scripts/report_paper_replication.py")
    builder = module_from_spec(spec)
    spec.loader.exec_module(builder)
    runs = {row["id"]: {**row, "config": json.loads(row["config"])} for row in store.rows("SELECT * FROM runs ORDER BY id")}
    histories = {run: store.history(run) for run in runs}
    sampling = {}
    for run in runs:
        attempts = store.rows("SELECT * FROM api_attempts WHERE run_id=? ORDER BY id", (run,))
        sampling[run] = {
            "accepted_response_fingerprint": builder.fingerprint_accepted([row for row in attempts if row["status"] == "accepted"]),
            "execution_attempt_fingerprint": builder.fingerprint_execution(attempts),
        }
    return (builder.fingerprint_runs(runs, histories), builder.fingerprint_sampling(sampling),
            builder.fingerprint_execution_summary(sampling))


def require_final_report(report_root, manifest_path, *, data_fingerprint, accepted_fingerprint, execution_fingerprint):
    for name in REPORT_FILES:
        safe_file(report_root / name, report_root)
    receipt = json.loads(safe_file(report_root / BUILD_RECEIPT, report_root).read_text())
    if (receipt.get("schema") != "ie498-paper-report-build-v1" or receipt.get("complete") is not True
            or receipt.get("complete_runs") != 6 or receipt.get("saved_periods") != 1800):
        raise ValueError("A last-written complete report build receipt is required")
    if (receipt.get("source_manifest_sha256") != sha256(manifest_path)
            or receipt.get("data_fingerprint") != data_fingerprint
            or receipt.get("accepted_fingerprint") != accepted_fingerprint
            or receipt.get("execution_fingerprint") != execution_fingerprint):
        raise ValueError("Report build receipt is stale relative to the experiment inputs")
    if set(receipt.get("files", {})) != set(REPORT_FILES) or any(
            receipt["files"][name] != sha256(report_root / name) for name in REPORT_FILES):
        raise ValueError("Report output differs from its completed build receipt")
    with (report_root / "run_summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 6 or {r["run_id"] for r in rows} != EXPECTED or any(
        r["complete"].lower() != "true" or int(r["rounds_completed"]) != 300 or int(r["accepted_calls"]) != 600
        for r in rows
    ):
        raise ValueError("The report is not the completed six-run report")
    public = json.loads((report_root / "protocol_manifest.json").read_text())
    if public.get("source_manifest_sha256") != sha256(manifest_path):
        raise ValueError("Report protocol manifest is stale")


def initial_execution_source(root, data_root, stage):
    """Retain the tiny pre-concurrency-amendment source, verified against its freeze."""
    prior_path = data_root / "manifest.initial-concurrency6.json"
    if not prior_path.exists():
        return {}
    prior = json.loads(safe_file(prior_path, data_root).read_text())
    commit = prior.get("code_commit", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Initial code commit is not a full Git commit identifier")
    source_name = "src/ie498/paper_execution.py"
    archived_source = root / "provenance/initial-paper_execution.py"
    source = (safe_file(archived_source, root).read_bytes() if archived_source.exists()
              else subprocess.check_output(["git", "show", f"{commit}:{source_name}"], cwd=root))
    expected = prior["source_hashes"][source_name]
    if hashlib.sha256(source).hexdigest() != expected:
        raise ValueError("Historical execution source does not match the initial frozen hash")
    for name, checksum in prior["source_hashes"].items():
        if name != source_name and sha256(safe_file(root / name, root)) != checksum:
            raise ValueError("Additional historical source change needs its own preserved source")
    path = stage / "initial-paper_execution.py"
    path.write_bytes(source)
    receipt = stage / "SOURCE_PROVENANCE.json"
    atomic_json(receipt, {"initial_code_commit": commit, "source_path": source_name,
                         "source_sha256": expected, "archive_copy": "provenance/initial-paper_execution.py"})
    return {"provenance/initial-paper_execution.py": (path, stage), "SOURCE_PROVENANCE.json": (receipt, stage)}


def write_archive(output, files):
    checksums = {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, (path, base) in sorted(files.items()):
            safe_name(name)
            safe_file(path, base)
            checksum, carry = hashlib.sha256(), b""
            with Path(path).open("rb") as source, archive.open(f"{ARCHIVE_ROOT}/{name}", "w", force_zip64=True) as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    if SECRET_PATTERN.search(carry + chunk):
                        raise ValueError(f"Credential-like content detected in {name}")
                    checksum.update(chunk)
                    target.write(chunk)
                    carry = chunk[-512:]
            checksums[name] = checksum.hexdigest()
        archive.writestr(f"{ARCHIVE_ROOT}/DELIVERY_MANIFEST.json", json.dumps({
            "format": "ie498-paper-replication-delivery-v1", "files": checksums,
            "note": "Every payload file is hashed; this index does not hash itself.",
        }, indent=2))
    return checksums


def verify_archive(path):
    """Read every payload, checking its hash and ZIP CRC, then check restored SQLite."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entry")
        for name in names:
            safe_name(name)
            if stat.S_ISLNK(archive.getinfo(name).external_attr >> 16):
                raise ValueError("Symbolic links cannot occur in the delivery")
        index_name = f"{ARCHIVE_ROOT}/DELIVERY_MANIFEST.json"
        index = json.loads(archive.read(index_name))
        expected = {f"{ARCHIVE_ROOT}/{name}" for name in index["files"]} | {index_name}
        if set(names) != expected:
            raise ValueError("ZIP inventory differs from the checksum manifest")
        for name, checksum in index["files"].items():
            observed = hashlib.sha256()
            with archive.open(f"{ARCHIVE_ROOT}/{name}") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    observed.update(chunk)
            if observed.hexdigest() != checksum:
                raise ValueError(f"ZIP payload checksum mismatch: {name}")
        with tempfile.TemporaryDirectory(prefix="ie498-paper-verify-") as temp:
            database = Path(temp) / "experiments.sqlite"
            with archive.open(f"{ARCHIVE_ROOT}/{DATA_REL}/experiments.sqlite") as source, database.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
            with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Restored SQLite integrity check failed")
    return {"payload_files": len(index["files"]), "all_file_checksums_matched": True,
            "zip_crc_checked": True, "sqlite_integrity": "ok"}


README = """# IE498: six-condition paper replication

This delivery contains only the new P1/P2 x alpha 1, 3.2, 10 experiment: one
300-period trajectory per condition, 1,800 periods, and 3,600 successful seller
calls. See reports/paper_replication/report.md and docs/paper_replication_protocol.md
for results and disclosed differences from the original paper. Historical memory
experiments and account credentials are excluded. This is a portable local copy,
not a claim that an independent remote backup exists.

Unzip into a new directory, preserving the directory layout. The database in
data/runs/paper_replication/experiments.sqlite was created with SQLite's backup
API; no live WAL/SHM files are needed. Every payload file has a SHA-256 entry in
DELIVERY_MANIFEST.json. All entries and their ZIP CRCs were read back and checked;
a temporary extraction of the database passed SQLite integrity_check.

To reproduce analysis, use Python 3.12+ and uv from the extracted project root:

    uv sync --extra dev
    uv run python scripts/run_paper_replication.py audit
    uv run python scripts/report_paper_replication.py
    uv run pytest tests/test_paper_replication.py tests/test_paper_execution.py tests/test_paper_report.py tests/test_paper_package.py -q

These commands audit or analyze existing data and do not call a model. The exact
source files and prompt files are included; recorded source hashes and code
commit identifiers provide provenance. Model-service randomness means a fresh
inference run is not expected to reproduce the saved text or actions verbatim.
No credentials are needed to audit or analyze the saved experiment.
"""


def package(root=ROOT, *, data_root=None, report_root=None, output=None):
    root = Path(root).absolute()
    data_root = Path(data_root or root / DATA_REL).absolute()
    report_root = Path(report_root or root / "reports/paper_replication").absolute()
    output = Path(output or root.parent / "IE498_Paper_Replication.zip").absolute()
    safe_file(data_root / "experiments.sqlite", data_root)
    safe_file(data_root / "manifest.json", data_root)
    store = Store(data_root, readonly=True)
    try:
        with coordinator_lock(store):
            manifest = json.loads((data_root / "manifest.json").read_text())
            attempts = require_complete(store, manifest)
            evidence = attempt_files(store, attempts, manifest["transport"])
            data_fingerprint, accepted_fingerprint, execution_fingerprint = report_input_fingerprints(store)
            require_final_report(report_root, data_root / "manifest.json", data_fingerprint=data_fingerprint,
                                 accepted_fingerprint=accepted_fingerprint, execution_fingerprint=execution_fingerprint)
            audited = audit(store)
            if not audited.get("passed") or audited.get("checked_calls") != 3600:
                raise ValueError("A full successful paper audit is required")
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".ie498-paper-package-", dir=output.parent) as temp:
                stage = Path(temp)
                database = stage / "experiments.sqlite"
                with closing(sqlite3.connect(database)) as target:
                    store.db.backup(target)
                    target.execute("PRAGMA journal_mode=DELETE")
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("SQLite backup integrity check failed")
                atomic_json(stage / "PACKAGE_AUDIT.json", audited)
                (stage / "README.md").write_text(README)
                files = {f"{DATA_REL}/{name}": (path, data_root) for name, path in evidence.items()}
                for name in RECEIPTS:
                    path = data_root / name
                    if path.exists():
                        files[f"{DATA_REL}/{name}"] = (path, data_root)
                for name in REPORT_FILES + (BUILD_RECEIPT,):
                    files[f"reports/paper_replication/{name}"] = (report_root / name, report_root)
                for name in CODE_FILES:
                    files[name] = (root / name, root)
                for folder in (root / "src/ie498", root / "experiments/paper_replication/prompts"):
                    for path in sorted(folder.glob("*.py" if folder.name == "ie498" else "*.txt")):
                        files[path.relative_to(root).as_posix()] = (path, root)
                files[f"{DATA_REL}/experiments.sqlite"] = (database, stage)
                files["README.md"] = (stage / "README.md", stage)
                files["PACKAGE_AUDIT.json"] = (stage / "PACKAGE_AUDIT.json", stage)
                files.update(initial_execution_source(root, data_root, stage))
                temporary = stage / "delivery.zip"
                write_archive(temporary, files)
                verified = verify_archive(temporary)
                temporary.replace(output)
            receipt = {"archive": str(output), "sha256": sha256(output), "bytes": output.stat().st_size,
                       "source_data": str(data_root), "source_report": str(report_root), **verified,
                       "credentials_included": False, "independent_backup": False}
            atomic_json(report_root / "delivery_receipt.json", receipt)
            return receipt
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--reports", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path, help="Verify an existing archive instead of creating one")
    args = parser.parse_args()
    result = verify_archive(args.verify) if args.verify else package(data_root=args.data, report_root=args.reports, output=args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
