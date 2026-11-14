#!/usr/bin/env python3
"""Build descriptive reports for the separate six-condition paper replication.

This command never makes model calls or writes to the experiment database. It
does not import results from the historical memory experiment. Only a completed
300-period run has an endpoint; partial paths are displayed solely as progress.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/ie498-paper-replication-mpl")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ie498.paper_replication import (  # noqa: E402
    PERIODS,
    RECONSTRUCTION_POLICIES,
    PaperCondition,
    normalized_final_metrics,
)


EXPECTED = [
    (f"paper-{prefix.lower()}-a{label}-r1", prefix, alpha)
    for prefix in ("P1", "P2")
    for label, alpha in (("1", 1.0), ("3p2", 3.2), ("10", 10.0))
]
ENDPOINT_FIELDS = [
    "evaluation_start", "evaluation_end",
    "mean_price_firm1", "mean_price_firm2", "mean_price",
    "mean_normalized_price_firm1", "mean_normalized_price_firm2",
    "mean_normalized_price", "mean_price_difference",
    "mean_normalized_price_difference", "mean_absolute_normalized_price_gap",
    "mean_profit_firm1", "mean_profit_firm2", "mean_total_profit",
    "mean_normalized_profit_firm1", "mean_normalized_profit_firm2",
    "mean_normalized_total_profit", "mean_profit_difference",
    "mean_normalized_profit_difference", "mean_absolute_normalized_profit_gap",
]
ROUND_FIELDS = [
    "run_id", "prefix", "alpha", "run_complete", "period", "firm",
    "price", "normalized_price", "quantity", "profit", "normalized_profit",
    "ceiling_exceeded",
]
MANIFEST_FIELDS = (
    "source_url", "source_sha256", "paper_url", "paper_sha256", "source_version",
    "prompt_hash", "prompt_hashes", "render_policy", "rendering_policy",
    "ceiling_policy", "model", "reasoning_effort", "temperature", "interface",
    "transport_version", "transport_limitations", "limitations",
    "reconstruction_policies", "explicit_differences", "documented_deviations",
    "transport", "source_hashes", "sampling_limitations", "reconstruction_limitations",
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_text(path, content):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def _csv(path, frame):
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temp, index=False)
    temp.replace(path)


def _table(frame, columns, labels=None):
    if frame.empty:
        return "No eligible observations.\n"
    labels = labels or columns

    def display(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "—"
        if isinstance(value, (bool, np.bool_)):
            return "yes" if value else "no"
        if isinstance(value, (float, np.floating)):
            return f"{value:.5f}".rstrip("0").rstrip(".")
        return str(value).replace("|", "\\|").replace("\n", " ")

    rows = ["| " + " | ".join(labels) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    rows.extend("| " + " | ".join(display(row.get(c)) for c in columns) + " |" for _, row in frame.iterrows())
    return "\n".join(rows) + "\n"


def _config_metadata(config):
    """Only named non-secret scientific/transport fields enter the report."""
    return {
        name: config.get(name)
        for name in (
            "model", "provider", "architecture", "temperature", "reasoning_effort",
            "interface", "transport", "top_p", "transport_version", "protocol_version", "ceiling_policy",
        )
    }


def load_runs(data_root):
    database = data_root / "experiments.sqlite"
    if not database.is_file():
        return {}, {}, {}, False
    db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # A consistent read snapshot, including a live WAL.
        runs = {row["id"]: dict(row) for row in db.execute("SELECT * FROM runs ORDER BY id")}
        unexpected = set(runs) - {item[0] for item in EXPECTED}
        if unexpected:
            raise ValueError("Input contains runs outside the isolated six-condition suite: " + ", ".join(sorted(unexpected)))
        histories, sampling = {}, {}
        for run_id, run in runs.items():
            run["config"] = json.loads(run["config"])
            rows = db.execute("SELECT t,payload FROM rounds WHERE run_id=? ORDER BY t", (run_id,)).fetchall()
            history = []
            for expected_t, row in enumerate(rows, 1):
                payload = json.loads(row["payload"])
                if row["t"] != expected_t or payload.get("t") != expected_t:
                    raise ValueError(f"{run_id}: saved rounds are not consecutive from 1")
                for key in ("prices", "profits", "quantities"):
                    values = np.asarray(payload.get(key), dtype=float)
                    if values.shape != (2,) or not np.isfinite(values).all():
                        raise ValueError(f"{run_id}, period {expected_t}: invalid {key}")
                history.append(payload)
            if len(history) > PERIODS:
                raise ValueError(f"{run_id}: more than {PERIODS} periods")
            if run["status"] == "completed" and len(history) != PERIODS:
                raise ValueError(f"{run_id}: completed status disagrees with period count")
            histories[run_id] = history
            observed = {"accepted_calls": 0, "unavailable_response_files": 0}
            fields = ("temperature", "top_p", "reasoning_effort")
            values = {field: set() for field in fields}
            missing = {field: 0 for field in fields}
            for attempt in db.execute("SELECT raw_path,raw_sha256 FROM api_attempts WHERE run_id=? AND status='accepted'", (run_id,)):
                observed["accepted_calls"] += 1
                response = {}
                raw_path = attempt["raw_path"]
                if raw_path:
                    path = (data_root / raw_path).resolve()
                    if not path.is_relative_to((data_root / "raw").resolve()):
                        raise ValueError(f"{run_id}: response path leaves the isolated raw-data directory")
                    if path.is_file():
                        if attempt["raw_sha256"] and _sha256(path) != attempt["raw_sha256"]:
                            raise ValueError(f"{run_id}: archived response checksum mismatch")
                        envelope = json.loads(path.read_text())
                        response = envelope.get("response", envelope)
                    else:
                        observed["unavailable_response_files"] += 1
                else:
                    observed["unavailable_response_files"] += 1
                if not isinstance(response, dict):
                    response = {}
                reasoning = response.get("reasoning")
                extracted = {"temperature": response.get("temperature"), "top_p": response.get("top_p"),
                             "reasoning_effort": reasoning.get("effort") if isinstance(reasoning, dict) else response.get("reasoning_effort")}
                for field, value in extracted.items():
                    valid = (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)) if field != "reasoning_effort" else value in ("none", "minimal", "low", "medium", "high", "xhigh")
                    if valid:
                        values[field].add(value)
                    else:
                        missing[field] += 1
            for field in fields:
                observed[f"reported_{field}_values"] = json.dumps(sorted(values[field]))
                observed[f"reported_{field}_missing"] = missing[field]
            sampling[run_id] = observed
        return runs, histories, sampling, True
    finally:
        db.close()


def summarize(runs, histories, sampling):
    summary, rounds, conditions = [], [], {}
    for run_id, prefix, alpha in EXPECTED:
        run = runs.get(run_id)
        history = histories.get(run_id, [])
        row = {
            "run_id": run_id, "prefix": prefix, "alpha": alpha,
            "status": run["status"] if run else "not_started",
            "rounds_completed": len(history), "complete": False,
            "prompt_hash": run.get("prompt_hash") if run else None,
            "commit_hash": run.get("commit_hash") if run else None,
        }
        row.update(dict.fromkeys(ENDPOINT_FIELDS))
        if run:
            config = run["config"]
            condition = PaperCondition(config["prefix"], config["alpha"], config["ceiling_policy"])
            if condition.prefix != prefix or condition.alpha != alpha:
                raise ValueError(f"{run_id}: condition disagrees with declared run ID")
            if config.get("T") != PERIODS:
                raise ValueError(f"{run_id}: configured horizon must be {PERIODS}")
            if config.get("model") != "gpt-6-luna":
                raise ValueError(f"{run_id}: expected the declared GPT-6 Luna model")
            if config.get("architecture") != "paper_replication":
                raise ValueError(f"{run_id}: not an independent core-paper reconstruction")
            if config.get("provider") == "mock":
                raise ValueError("Mock runs cannot be reported as replication observations")
            if run.get("parent") or run.get("checkpoint", 0):
                raise ValueError(f"{run_id}: core replication runs must start independently")
            conditions[run_id] = condition
            row.update(_config_metadata(config))
            row.update(sampling.get(run_id, {}))
            row["textual_ceiling"] = round(condition.ceiling, 2)
            row["complete"] = run["status"] == "completed" and len(history) == PERIODS
            if row["complete"]:
                metrics = normalized_final_metrics(condition, history)
                prices = np.asarray([r["prices"] for r in history[-50:]], dtype=float)
                profits = np.asarray([r["profits"] for r in history[-50:]], dtype=float)
                row.update({
                    "evaluation_start": 251, "evaluation_end": 300,
                    "mean_price_firm1": float(prices[:, 0].mean()),
                    "mean_price_firm2": float(prices[:, 1].mean()),
                    "mean_price": float(prices.mean()),
                    "mean_normalized_price_firm1": metrics["mean_normalized_prices"][0],
                    "mean_normalized_price_firm2": metrics["mean_normalized_prices"][1],
                    "mean_normalized_price": float(prices.mean() / alpha),
                    "mean_price_difference": float((prices[:, 0] - prices[:, 1]).mean()),
                    "mean_normalized_price_difference": float((prices[:, 0] - prices[:, 1]).mean() / alpha),
                    "mean_absolute_normalized_price_gap": float(np.abs(prices[:, 0] - prices[:, 1]).mean() / alpha),
                    "mean_profit_firm1": float(profits[:, 0].mean()),
                    "mean_profit_firm2": float(profits[:, 1].mean()),
                    "mean_total_profit": float(profits.sum(axis=1).mean()),
                    "mean_normalized_profit_firm1": metrics["mean_normalized_profits"][0],
                    "mean_normalized_profit_firm2": metrics["mean_normalized_profits"][1],
                    "mean_normalized_total_profit": metrics["mean_normalized_total_profit"],
                    "mean_profit_difference": float((profits[:, 0] - profits[:, 1]).mean()),
                    "mean_normalized_profit_difference": metrics["mean_normalized_profit_difference"],
                    "mean_absolute_normalized_profit_gap": float(np.abs(profits[:, 0] - profits[:, 1]).mean() / alpha),
                })
            for record in history:
                for seller in (0, 1):
                    rounds.append({
                        "run_id": run_id, "prefix": prefix, "alpha": alpha,
                        "run_complete": row["complete"], "period": record["t"], "firm": seller + 1,
                        "price": record["prices"][seller],
                        "normalized_price": record["prices"][seller] / alpha,
                        "quantity": record["quantities"][seller],
                        "profit": record["profits"][seller],
                        "normalized_profit": record["profits"][seller] / alpha,
                        "ceiling_exceeded": record.get("ceiling_exceeded", [None, None])[seller],
                    })
        summary.append(row)
    return pd.DataFrame(summary), pd.DataFrame(rounds, columns=ROUND_FIELDS), conditions


def _save_figure(fig, path):
    temp = path.with_suffix(".tmp.png")
    fig.savefig(temp, dpi=170, bbox_inches="tight")
    plt.close(fig)
    temp.replace(path)


def plot_trajectories(summary, histories, destination):
    # All economic benchmarks coincide after dividing by the currency scale.
    benchmark = PaperCondition("P1", 1.0, "footnote_18").market.benchmarks()
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), sharex=True)
    for ax, (run_id, prefix, alpha) in zip(axes.flat, EXPECTED):
        history = histories.get(run_id, [])
        row = summary.loc[summary.run_id == run_id].iloc[0]
        if history:
            t = [r["t"] for r in history]
            prices = np.asarray([r["prices"] for r in history]) / alpha
            for seller, color in enumerate(("#2468ae", "#dc7523")):
                ax.plot(t, prices[:, seller], label=f"Firm {seller + 1}", lw=1.1, color=color, alpha=.85)
        else:
            ax.text(.5, .5, "Not started", transform=ax.transAxes, ha="center", color="#555555")
        ax.axhline(benchmark["nash_price"][0], color="#444444", ls="--", lw=1, label="Nash price")
        ax.axhline(benchmark["joint_price"][0], color="#2b8846", ls=":", lw=1.3, label="Joint-monopoly price")
        ax.axvspan(250.5, 300.5, color="#555555", alpha=.06)
        status = "complete" if row.complete else f"INCOMPLETE: {row.rounds_completed}/300"
        ax.set(title=f"{prefix} | alpha = {alpha:g} | {status}", xlim=(1, 300), ylabel="Price / alpha")
        ax.grid(alpha=.15)
    for ax in axes[1]:
        ax.set_xlabel("Period")
    handles, labels = [], []
    for ax in axes.flat:
        hs, ls = ax.get_legend_handles_labels()
        for h, label in zip(hs, ls):
            if label not in labels:
                handles.append(h)
                labels.append(label)
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False)
    fig.suptitle("Core paper replication: normalized price paths (one run per condition)")
    fig.tight_layout(rect=(0, .055, 1, .96))
    _save_figure(fig, destination / "trajectories.png")


def plot_endpoints(summary, destination):
    complete = summary[summary.complete]
    benchmark = PaperCondition("P1", 1.0, "footnote_18").market.benchmarks()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))
    for prefix, marker, color in (("P1", "s", "#2468ae"), ("P2", "^", "#dc7523")):
        group = complete[complete.prefix == prefix]
        for ax, metric in zip(axes, ("price", "profit")):
            ax.scatter(group[f"mean_normalized_{metric}_firm1"], group[f"mean_normalized_{metric}_firm2"],
                       marker=marker, color=color, s=65, edgecolors="white", linewidth=.6, label=prefix, zorder=4)
            for _, row in group.iterrows():
                ax.annotate(f"a={row.alpha:g}", (row[f"mean_normalized_{metric}_firm1"], row[f"mean_normalized_{metric}_firm2"]),
                            xytext=(5, 6 if prefix == "P1" else -13), textcoords="offset points", fontsize=8, color=color)
    for ax, metric, title in zip(axes, ("price", "profit"), ("Mean normalized prices", "Mean normalized profits")):
        nash = benchmark[f"nash_{metric}"]
        joint = benchmark[f"joint_{metric}"]
        ax.axvline(nash[0], color="#444444", ls="--", lw=1)
        ax.axhline(nash[1], color="#444444", ls="--", lw=1, label="Nash per firm")
        ax.scatter([joint[0]], [joint[1]], marker="x", color="#2b8846", s=60, label="Symmetric joint optimum")
        if metric == "price":
            ax.axvline(joint[0], color="#2b8846", ls=":", lw=1)
            ax.axhline(joint[1], color="#2b8846", ls=":", lw=1)
        else:
            left, right = ax.get_xlim()
            bottom, top = ax.get_ylim()
            xs = np.linspace(left, right, 150)
            for total, color, style, label in (
                (sum(nash), "#444444", "-.", "Nash total profit"),
                (sum(joint), "#2b8846", ":", "Maximum total profit"),
            ):
                ys = total - xs
                mask = (ys >= bottom) & (ys <= top)
                ax.plot(xs[mask], ys[mask], color=color, ls=style, lw=1, label=label)
            ax.set_xlim(left, right)
            ax.set_ylim(bottom, top)
        if complete.empty:
            ax.text(.5, .85, "No completed 300-period runs", transform=ax.transAxes, ha="center")
        ax.set(xlabel=f"Firm 1: {metric} / alpha", ylabel=f"Firm 2: {metric} / alpha", title=title)
        ax.grid(alpha=.15)
        ax.legend(fontsize=8, loc="best")
    qualifier = "complete suite" if len(complete) == len(EXPECTED) else f"INCOMPLETE suite: {len(complete)}/6 endpoints"
    fig.suptitle(f"Periods 251–300 | {qualifier} | descriptive observations only")
    fig.tight_layout(rect=(0, 0, 1, .95))
    _save_figure(fig, destination / "final50.png")


def _link(path, destination):
    return Path(os.path.relpath(path, destination)).as_posix()


def make_report(summary, histories, data_root, destination, manifest_path, manifest, has_database):
    completed = summary[summary.complete]
    total_rounds = int(summary.rounds_completed.sum())
    all_complete = len(completed) == len(EXPECTED)
    state = "COMPLETE" if all_complete else "INCOMPLETE"
    parts = [
        "# Core Paper Replication with GPT-6 Luna\n",
        f"**Status: {state}.** {len(completed)}/6 runs completed; {total_rounds}/1,800 periods saved. "
        f"Report generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}.\n",
        "This is a separate reconstruction of the paper's core duopoly experiment. "
        "The sample contains one independent run in each of six cells: P1/P2 crossed with "
        "currency scales alpha = 1, 3.2, and 10. The paper used seven runs per scale and "
        "prefix, or 21 per prefix. This reconstruction therefore has three runs per prefix, "
        "one at each scale. It does not pool or reuse the earlier memory experiments.\n",
    ]
    if not all_complete:
        parts.append("**The suite is unfinished.** Partial paths indicate progress only; they do not receive "
                     "final-50 metrics. Any displayed endpoints belong only to individually completed "
                     "300-period runs. No complete-suite comparison or conclusion is available.\n")
    if not has_database:
        parts.append("The isolated experiment database does not yet exist. All cells are shown as not started.\n")
    parts += [
        "## Design and reporting contract\n",
        "The source is Fish, Gonczarowski, and Shorrer, [Algorithmic Collusion by Large Language Models, "
        "arXiv:2404.00806v6](https://arxiv.org/abs/2404.00806v6), sections 2–3, Appendix B, "
        "and prompts G.1/G.2.1. The replacement model is GPT-6 Luna. Each independent "
        "300-period duopoly run starts with empty market history and private files. "
        "Agents receive up to 100 recent periods and their own latest PLANS/INSIGHTS; "
        "they replace those files each period. There is no external compressor.\n",
        "Demand uses a1 = a2 = 2, a0 = 0, mu = 0.25, beta = 100, and marginal cost "
        "alpha for each firm. Prices and profits are divided by alpha for comparison "
        "across currency scales; quantities are not scaled. Settlement uses the submitted "
        "prices without rounding or enforcing the textual ceiling as a hard cap.\n",
        "The primary endpoints are each firm's mean price and mean profit over periods "
        "251–300, mean total profit, and firm differences. Signed differences are Firm 1 "
        "minus Firm 2; absolute gaps are period-by-period absolute differences averaged "
        "over the same window. Both original-currency and normalized values are retained "
        "in the CSV files. Each full run is one observation. One run per cell does not "
        "estimate that cell's sampling variability. This report gives no inferential "
        "p-values, confidence intervals, or success rates and applies none of the earlier "
        "project's price/profit success thresholds.\n",
        "## Completion and provenance\n",
        _table(summary, ["run_id", "prefix", "alpha", "status", "rounds_completed", "complete"],
               ["Run", "Prefix", "alpha", "Status", "Periods", "Endpoint eligible"]),
        f"Input: `{data_root.as_posix()}/experiments.sqlite`, opened with SQLite `mode=ro` "
        "and a consistent read transaction. Unknown run IDs, discontinuous rounds, "
        "contradictory completed status, incorrect model/condition metadata, and mock "
        "providers are rejected. Existing results are never altered.\n",
        "## Normalized price paths\n",
        "![Normalized price paths for all six conditions](trajectories.png)\n",
        "The shaded interval marks periods 251–300. Dashed lines show the static Nash "
        "price; dotted lines show the joint-monopoly price. Panels retain independent "
        "vertical scales to keep each trajectory legible.\n",
        "## Completed-run endpoints: periods 251–300\n",
        "### Prices\n",
        _table(completed, ["prefix", "alpha", "mean_price_firm1", "mean_price_firm2",
                           "mean_normalized_price_firm1", "mean_normalized_price_firm2",
                           "mean_normalized_price_difference"],
               ["Prefix", "alpha", "Raw price 1", "Raw price 2", "Price 1 / alpha", "Price 2 / alpha", "Normalized difference"]),
        "### Profits\n",
        _table(completed, ["prefix", "alpha", "mean_profit_firm1", "mean_profit_firm2",
                           "mean_normalized_profit_firm1", "mean_normalized_profit_firm2",
                           "mean_normalized_total_profit", "mean_normalized_profit_difference"],
               ["Prefix", "alpha", "Raw profit 1", "Raw profit 2", "Profit 1 / alpha", "Profit 2 / alpha", "Total / alpha", "Normalized difference"]),
        "![Completed-run normalized endpoint comparison](final50.png)\n",
        "Each point is one completed run, labeled by currency scale. The profit panel "
        "shows firm-specific profits and constant-total-profit benchmark lines. These "
        "benchmarks are calculated from the demand model, not inferred from the observed "
        "paths. High prices by themselves need not imply high profits.\n",
    ]
    if all_complete:
        comparisons = []
        for alpha in (1.0, 3.2, 10.0):
            pair = completed[completed.alpha == alpha].set_index("prefix")
            comparisons.append({
                "alpha": alpha,
                "price_difference": pair.loc["P1", "mean_normalized_price"] - pair.loc["P2", "mean_normalized_price"],
                "profit_difference": pair.loc["P1", "mean_normalized_total_profit"] - pair.loc["P2", "mean_normalized_total_profit"],
            })
        parts += ["## Observed P1–P2 differences at each scale\n",
                  _table(pd.DataFrame(comparisons), ["alpha", "price_difference", "profit_difference"],
                         ["alpha", "Mean normalized price: P1 minus P2", "Normalized total profit: P1 minus P2"]),
                  "These are differences between two sampled trajectories at each scale. They do "
                  "not establish a stable prompt effect or reproduce the original study's "
                  "21-run-per-prefix statistical evidence.\n"]
    parts.append("## Source, prompt rendering, and interface limitations\n")
    paper = ROOT / "docs/sources/paper-v6.pdf"
    if paper.is_file():
        parts.append(f"Pinned local source PDF SHA-256: `{_sha256(paper)}`.\n")
    parts.append("No official author code/data package was identified in the bounded "
                 "[source search](../../docs/paper_replication_source_search.md). Consequently, "
                 "PDF text rendering and parsing choices are explicit reconstruction decisions, "
                 "not a claim of byte-for-byte reproduction of unpublished original code.\n")
    if manifest_path and manifest_path.is_file():
        parts.append(f"Frozen execution manifest: [{manifest_path.name}]({_link(manifest_path, destination)}); "
                     f"SHA-256 `{_sha256(manifest_path)}`.\n")
        rows = []
        for field in MANIFEST_FIELDS:
            if field in manifest:
                value = manifest[field]
                rows.append({"field": field, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value})
        if rows:
            parts.append(_table(pd.DataFrame(rows), ["field", "value"], ["Manifest field", "Recorded value"]))
    else:
        parts.append("No execution manifest was supplied or found at the selected path. "
                     "This report does not infer missing transport settings or claim they match the paper.\n")
    present = summary[summary.run_id.isin(runs_id for runs_id in histories)]
    columns = ["run_id", "model", "transport", "temperature", "top_p", "reasoning_effort", "ceiling_policy"]
    for column in columns:
        if column not in present:
            present = present.assign(**{column: None})
    parts += [_table(present, columns)]
    if manifest.get("transport") == "chatgpt_subscription" or ("transport" in present and (present.transport == "chatgpt_subscription").any()):
        parts.append("**Authorized sampling difference:** this suite uses the Pro subscription "
                     "Responses interface with reasoning `none`. That interface does not permit "
                     "explicit `temperature` or `top_p`, so these request parameters are omitted. "
                     "The paper's temperature 1 is therefore not fixed by this experiment. "
                     "Server-reported values below are observations, not enforced settings. "
                     "This is a reconstruction with disclosed sampling and implementation "
                     "differences, not a replication differing only in model and repetitions.\n")
    sampling_columns = ["run_id", "accepted_calls", "reported_temperature_values", "reported_temperature_missing",
                        "reported_top_p_values", "reported_top_p_missing", "reported_reasoning_effort_values",
                        "unavailable_response_files"]
    for column in sampling_columns:
        if column not in present:
            present = present.assign(**{column: None})
    parts += ["Observed metadata from archived accepted responses (only named sampling fields are read into this table):\n",
              _table(present, sampling_columns),
              "Empty value lists mean the field was not observed. Missing counts are over "
              "accepted responses; unavailable raw files are listed separately. All observed "
              "distinct values are retained, so a changing server default is visible.\n",
              "The original core experiment used GPT-4-0613 at temperature 1. The configured "
              "reasoning level and selected interface are model/transport settings, not features "
              "of the original GPT-4 protocol. A blank field above means it was not recorded in "
              "the run configuration. No interface equivalence or bitwise sampling equivalence "
              "is claimed. Provider behavior and model replacement limit direct comparability.\n",
              "Documented reconstruction policies:\n",
              _table(pd.DataFrame([{"policy": k, "value": v} for k, v in RECONSTRUCTION_POLICIES.items() if k != "sampling"]), ["policy", "value"]),
              "Per-run prompt and code identifiers:\n",
              _table(summary, ["run_id", "prompt_hash", "commit_hash"]),
              "## Files\n",
              "- [run_summary.csv](run_summary.csv): all six cells; endpoint fields remain empty for unfinished runs.\n"
              "- [rounds.csv](rounds.csv): saved periods, one row per firm, with raw and normalized values and completion labels.\n"
              "- [trajectories.png](trajectories.png): normalized price paths.\n"
              "- [final50.png](final50.png): completed-run endpoint comparisons.\n",
              "The original memory-study report and data remain separate and unchanged.\n"]
    return "\n".join(parts)


def build_report(data_root, destination, manifest_path=None):
    data_root, destination = Path(data_root).resolve(), Path(destination).resolve()
    manifest_path = Path(manifest_path).resolve() if manifest_path else data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path and manifest_path.is_file() else {}
    if not isinstance(manifest, dict):
        raise ValueError("The execution manifest must be a JSON object")
    runs, histories, sampling, has_database = load_runs(data_root)
    frozen = {row["id"]: row for row in manifest.get("runs", [])}
    if frozen and set(frozen) != {row[0] for row in EXPECTED}:
        raise ValueError("Frozen manifest does not contain exactly the six declared conditions")
    for run_id, run in runs.items():
        if frozen and (run["config"] != frozen[run_id]["config"] or run["prompt_hash"] != manifest.get("prompt_hash")):
            raise ValueError(f"{run_id}: database differs from the frozen manifest")
    summary, rounds, _ = summarize(runs, histories, sampling)
    destination.mkdir(parents=True, exist_ok=True)
    _csv(destination / "run_summary.csv", summary)
    _csv(destination / "rounds.csv", rounds)
    plot_trajectories(summary, histories, destination)
    plot_endpoints(summary, destination)
    report = make_report(summary, histories, data_root, destination, manifest_path, manifest, has_database)
    _atomic_text(destination / "report.md", report)
    return {"complete_runs": int(summary.complete.sum()), "saved_periods": int(summary.rounds_completed.sum()),
            "report": str(destination / "report.md")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/runs/paper_replication")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/paper_replication")
    parser.add_argument("--manifest", type=Path, help="Frozen protocol/execution manifest (default: DATA/manifest.json)")
    args = parser.parse_args()
    print(json.dumps(build_report(args.data, args.out, args.manifest), indent=2))


if __name__ == "__main__":
    main()
