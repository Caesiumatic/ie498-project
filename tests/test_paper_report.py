"""Offline regression checks for the separate paper-reconstruction report."""

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ie498.paper_replication import PaperCondition, PaperDecision, settle_round


_SPEC = spec_from_file_location(
    "paper_report", Path(__file__).resolve().parents[1] / "scripts/report_paper_replication.py"
)
report = module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


def completed_fixture():
    """One synthetic trajectory with a different price before the final window."""
    run_id = "paper-p1-a3p2-r1"
    condition = PaperCondition("P1", 3.2, "footnote_18")
    history = []
    for t in range(1, 301):
        prices = ((1.5 if t <= 250 else 1.8) * 3.2, 1.75 * 3.2)
        decisions = [PaperDecision("Synthetic test", "", "", price) for price in prices]
        history.append(settle_round(condition, t, decisions))
    run = {"id": run_id, "status": "completed", "prompt_hash": "test-prompt", "commit_hash": "test-commit",
           "config": {"prefix": "P1", "alpha": 3.2, "ceiling_policy": "footnote_18", "T": 300,
                      "model": "gpt-6-luna", "architecture": "paper_replication", "transport": "chatgpt_subscription"}}
    sampling = {"accepted_calls": 600, "unavailable_response_files": 0}
    return run_id, run, history, sampling


def scientific_manifest():
    return {
        "protocol": "test-protocol", "scope": "Six core conditions", "transport": "chatgpt_subscription",
        "source_hashes": {"src/ie498/paper_execution.py": "a" * 64},
        "sampling_limitations": ["Explicit temperature and top_p omitted"],
        "runs": [{"id": run_id, "config": {"prefix": prefix, "alpha": alpha, "model": "gpt-6-luna",
                                            "T": 300, "H": 100, "transport": "chatgpt_subscription"}}
                 for run_id, prefix, alpha in report.EXPECTED],
        "runtime_amendments": [{"date_utc": "2026-11-14T00:00:00Z", "change": "Concurrency only",
                                "checkpoints": {"paper-p1-a1-r1": 8},
                                "old_source_hashes": {"src/ie498/paper_execution.py": "b" * 64}}],
    }


def fake_figures(monkeypatch):
    """Keep artifact/receipt tests focused on provenance, not rendering speed."""
    monkeypatch.setattr(report, "plot_trajectories", lambda summary, histories, out:
                        (out / "trajectories.png").write_bytes(b"synthetic trajectory fixture"))
    monkeypatch.setattr(report, "plot_endpoints", lambda summary, out:
                        (out / "final50.png").write_bytes(b"synthetic endpoint fixture"))


def test_figure_two_profit_coordinates_and_nash_isoprofit_equations(monkeypatch, tmp_path):
    rows = []
    for i, (_, prefix, alpha) in enumerate(report.EXPECTED):
        profit1, profit2 = 20. + 2 * i, 25. - i
        rows.append({"complete": True, "prefix": prefix, "alpha": alpha,
                     "mean_normalized_price_firm1": 1.6 + .02 * i,
                     "mean_normalized_price_firm2": 1.8 - .01 * i,
                     "mean_normalized_profit_difference": profit1 - profit2,
                     "mean_normalized_total_profit": profit1 + profit2})
    frame = pd.DataFrame(rows)
    captured = []
    monkeypatch.setattr(report, "_save_figure", lambda fig, path: captured.append(fig))
    report.plot_endpoints(frame, tmp_path)
    fig = captured[0]
    try:
        ax = fig.axes[1]
        for collection, prefix in zip(ax.collections[:2], ("P1", "P2")):
            group = frame[frame.prefix == prefix]
            expected = np.column_stack([group.mean_normalized_profit_difference, group.mean_normalized_total_profit])
            assert np.allclose(collection.get_offsets(), expected)
        benchmark = PaperCondition("P1", 1., "footnote_18").market.benchmarks()
        lines = {line.get_label(): line for line in ax.lines}
        x, y = lines["Firm 1 profit = Nash"].get_data()
        assert len(x) > 0 and np.allclose(y + x, 2 * benchmark["nash_profit"][0])
        x, y = lines["Firm 2 profit = Nash"].get_data()
        assert len(x) > 0 and np.allclose(y - x, 2 * benchmark["nash_profit"][1])
        joint_total = sum(benchmark["joint_profit"])
        assert np.allclose(lines["Joint-monopoly total profit"].get_ydata(), joint_total)
        assert np.allclose(ax.collections[2].get_offsets(), [[0, joint_total]])
    finally:
        report.plt.close(fig)


def test_final_window_currency_normalization_and_partial_endpoint_exclusion():
    run_id, run, history, sampling = completed_fixture()
    summary, rounds, _ = report.summarize({run_id: run}, {run_id: history}, {run_id: sampling})
    result = summary[summary.run_id == run_id].iloc[0]
    assert result.complete
    assert result.mean_price_firm1 == pytest.approx(5.76)
    assert result.mean_normalized_price_firm1 == pytest.approx(1.8)
    assert result.mean_normalized_price_firm2 == pytest.approx(1.75)
    assert result.mean_normalized_price_difference == pytest.approx(.05)
    assert result.mean_normalized_total_profit == pytest.approx(result.mean_total_profit / 3.2)
    assert result.mean_normalized_profit_difference == pytest.approx(result.mean_profit_difference / 3.2)
    assert len(rounds) == 600
    # Neither a partial trajectory nor an unfinalized 300-period trajectory is an endpoint.
    for count in (100, 300):
        unfinished = dict(run, status="running")
        summary, _, _ = report.summarize({run_id: unfinished}, {run_id: history[:count]}, {run_id: sampling})
        result = summary[summary.run_id == run_id].iloc[0]
        assert not result.complete
        assert all(pd.isna(result[field]) for field in report.ENDPOINT_FIELDS)


def test_complete_report_rejects_missing_accepted_calls_or_raw_evidence():
    run_id, run, history, _ = completed_fixture()
    for sampling in ({"accepted_calls": 599, "unavailable_response_files": 0},
                     {"accepted_calls": 600, "unavailable_response_files": 1}):
        with pytest.raises(ValueError, match="600 accepted calls with available raw responses"):
            report.summarize({run_id: run}, {run_id: history}, {run_id: sampling})


def test_public_manifest_excludes_unknown_nested_secret_fields():
    manifest = scientific_manifest()
    secret = "DUMMY_SECRET_MUST_NOT_BE_EXPORTED"
    manifest["api_key"] = secret
    manifest["runs"][0]["authorization"] = secret
    manifest["runs"][0]["config"]["access_token"] = secret
    manifest["runtime_amendments"][0]["refresh_token"] = secret
    manifest["runtime_amendments"][0]["checkpoints"]["private_key"] = secret
    manifest["runtime_amendments"][0]["old_source_hashes"]["data/auth/private.json"] = secret
    manifest["reconstruction_policies"] = {"history_numbers": "rounding policy", "password": secret}
    manifest["prompt_hashes"] = {"p1.txt": "c" * 64, "api_key": secret}
    manifest["source_hashes"]["api_key"] = secret
    original = deepcopy(manifest)
    public = report.public_protocol_manifest(manifest, "d" * 64)
    assert secret not in json.dumps(public)
    assert len(public["runs"]) == 6
    assert public["runs"][0]["config"]["alpha"] == 1
    assert public["runtime_amendments"][0]["checkpoints"] == {"paper-p1-a1-r1": 8}
    assert public["source_hashes"] == {"src/ie498/paper_execution.py": "a" * 64}
    assert public["source_manifest_sha256"] == "d" * 64
    assert manifest == original


def test_report_links_published_manifest_without_modifying_local_source(monkeypatch, tmp_path):
    data, out = tmp_path / "data", tmp_path / "public-report"
    data.mkdir()
    source = data / "manifest.json"
    source.write_text(json.dumps(scientific_manifest()))
    original = source.read_bytes()
    fake_figures(monkeypatch)
    result = report.build_report(data, out)
    text = (out / "report.md").read_text()
    published = out / "protocol_manifest.json"
    assert "[protocol_manifest.json](protocol_manifest.json)" in text
    assert report._sha256(published) in text
    assert "local data archive" in text
    assert "**Status: INCOMPLETE.**" in text and result["complete_runs"] == 0
    assert "Observed P1–P2 differences at each scale" not in text
    assert source.read_bytes() == original
    assert not (data / "experiments.sqlite").exists()
    receipt = json.loads((out / "build_receipt.json").read_text())
    assert receipt["schema"] == "ie498-paper-report-build-v1"
    assert receipt["complete"] is False and receipt["complete_runs"] == receipt["saved_periods"] == 0
    assert receipt["source_manifest_sha256"] == report._sha256(source)
    assert receipt["data_fingerprint"] == report.fingerprint_runs({}, {})
    assert receipt["accepted_fingerprint"] == report.fingerprint_sampling({})
    assert receipt["files"] == {name: report._sha256(out / name) for name in report.REPORT_FILES}


def test_snapshot_fingerprints_are_order_independent_and_bind_scientific_evidence():
    run_id, run, history, _ = completed_fixture()
    histories = {run_id: history}
    expected = report.fingerprint_runs({run_id: run}, histories)
    encoded = dict(run, config=json.dumps(run["config"]))
    assert report.fingerprint_runs([encoded], histories) == expected
    changed = deepcopy(histories)
    changed[run_id][-1]["prices"][0] += .01
    assert report.fingerprint_runs({run_id: run}, changed) != expected
    changed_run = deepcopy(run)
    changed_run["config"]["temperature"] = .5
    assert report.fingerprint_runs([changed_run], histories) != expected
    private_metadata = deepcopy(run)
    private_metadata["config"]["api_key"] = "synthetic private field"
    assert report.fingerprint_runs([private_metadata], histories) == expected

    attempts = [{"id": f"attempt-{i}", "call_id": f"call-{i}", "attempt": 1, "run_id": run_id,
                 "t": 1, "agent": i, "purpose": "seller", "request_hash": "a" * 64,
                 "raw_path": f"raw/attempt-{i}.json", "raw_sha256": "b" * 64} for i in (0, 1)]
    accepted = report.fingerprint_accepted(attempts)
    assert report.fingerprint_accepted(list(reversed(attempts))) == accepted
    baseline = report.fingerprint_sampling({run_id: {"accepted_response_fingerprint": accepted}})
    attempts[0]["raw_sha256"] = "c" * 64
    changed = report.fingerprint_accepted(attempts)
    assert changed != accepted
    assert report.fingerprint_sampling({run_id: {"accepted_response_fingerprint": changed}}) != baseline


def test_interrupted_final_build_cannot_leave_a_valid_receipt_for_mixed_artifacts(monkeypatch, tmp_path):
    data, out = tmp_path / "data", tmp_path / "report"
    fake_figures(monkeypatch)
    writes = []
    atomic_text = report._atomic_text

    def record_write(path, content):
        writes.append(path.name)
        return atomic_text(path, content)

    monkeypatch.setattr(report, "_atomic_text", record_write)
    report.build_report(data, out)
    assert writes[-1] == "build_receipt.json"
    old_receipt = (out / "build_receipt.json").read_bytes()

    # Supply a synthetic fully completed suite to the read-only input boundary.
    _, base_run, base_history, _ = completed_fixture()
    runs, histories, sampling = {}, {}, {}
    for run_id, prefix, alpha in report.EXPECTED:
        run = deepcopy(base_run)
        run["id"] = run_id
        run["config"].update(prefix=prefix, alpha=alpha)
        history = deepcopy(base_history)
        for period in history:
            for field in ("prices", "profits"):
                period[field] = [value * alpha / 3.2 for value in period[field]]
            for action in period["actions"]:
                action["price"] *= alpha / 3.2
        runs[run_id], histories[run_id] = run, history
        sampling[run_id] = {"accepted_calls": 600, "unavailable_response_files": 0,
                            "accepted_response_fingerprint": "f" * 64}
    monkeypatch.setattr(report, "load_runs", lambda path: (runs, histories, sampling, True))

    def interrupt_before_markdown(path, content):
        if path.name == "report.md":
            raise RuntimeError("Synthetic interruption after CSV/figure replacement")
        return atomic_text(path, content)

    monkeypatch.setattr(report, "_atomic_text", interrupt_before_markdown)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        report.build_report(data, out)
    assert pd.read_csv(out / "run_summary.csv").complete.all()
    assert "**Status: INCOMPLETE.**" in (out / "report.md").read_text()
    assert (out / "build_receipt.json").read_bytes() == old_receipt
    receipt = json.loads(old_receipt)
    assert receipt["complete"] is False
    assert receipt["files"]["run_summary.csv"] != report._sha256(out / "run_summary.csv")
    assert receipt["data_fingerprint"] != report.fingerprint_runs(runs, histories)
