#!/usr/bin/env python3
"""Build clean manuscript PNGs from canonical publication JSON artifacts.

These are presentation derivatives only. Canonical evidence remains the JSON/SVG
and manifest under ``publication/``.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
FIGURE_SOURCE = REPO_ROOT / "publication" / "figures"
TABLE_SOURCE = REPO_ROOT / "publication" / "tables"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "paper_artifacts"
    / "final"
    / "visuals_algorithms"
    / "rendered"
    / "quantitative"
)
COLORS = {
    "blue": "#2166AC",
    "orange": "#D6604D",
    "green": "#1B7837",
    "purple": "#762A83",
    "grey": "#4D4D4D",
}


def _load(name: str) -> list[dict[str, Any]]:
    payload = json.loads((FIGURE_SOURCE / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{name}.json must contain a list")
    return [dict(row) for row in payload]


def _finish(fig: plt.Figure, output: Path, *, name: str) -> None:
    fig.suptitle(name, fontsize=15, fontweight="bold", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(
        output,
        dpi=180,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.16,
        metadata={"Software": "PoI MPP publication artifact pipeline"},
    )
    plt.close(fig)


def _style(ax: plt.Axes) -> None:
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.7, alpha=0.8)
    ax.spines[["top", "right"]].set_visible(False)


def build_f5(output: Path) -> None:
    rows = [row for row in _load("F5_single_pass_cost") if not row.get("is_warmup")]
    pair_ids = sorted({str(row["pair_id"]) for row in rows})
    variants = ["NATIVE_SINGLE", "MPP_SINGLE_PASS", "TWO_RUN_BASELINE"]
    styles = {
        "NATIVE_SINGLE": (COLORS["grey"], "o"),
        "MPP_SINGLE_PASS": (COLORS["blue"], "s"),
        "TWO_RUN_BASELINE": (COLORS["orange"], "^"),
    }
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    for variant in variants:
        values = {
            str(row["pair_id"]): float(row["measured_ms"])
            for row in rows
            if row["variant"] == variant
        }
        color, marker = styles[variant]
        ax.plot(pair_ids, [values[pair] for pair in pair_ids], marker=marker, linewidth=2, color=color, label=variant.replace("_", " ").title())
    ax.set_ylabel("Wall-clock time (ms)")
    ax.set_xlabel("Paired observation")
    ax.legend(frameon=False, ncol=3, fontsize=9, loc="upper center")
    _style(ax)
    _finish(fig, output, name="Figure 5 | E1 single-pass cost pilot")


def build_f6(output: Path) -> None:
    point = _load("F6_audit_soundness")[0]
    rate = float(point["overall_detection_rate"])
    lower = float(point["lower_ci"])
    upper = float(point["upper_ci"])
    fig, ax = plt.subplots(figsize=(7.4, 4.8))
    ax.bar(["Supported audit\nsurfaces"], [rate], width=0.52, color=COLORS["blue"])
    ax.errorbar([0], [rate], yerr=[[rate - lower], [upper - rate]], fmt="none", ecolor="#111111", capsize=8, linewidth=1.5)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Observed detection rate")
    ax.text(0, rate - 0.11, f"{int(point['exact_detected'])} exact + {int(point['empirical_detected'])} empirical\n/ {int(point['denominator'])} attacked observations", ha="center", va="top", color="white", fontweight="bold")
    _style(ax)
    _finish(fig, output, name="Figure 6 | E2 audit detection pilot")


def build_f7(output: Path) -> None:
    with (TABLE_SOURCE / "T8_semantic_verification.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = {row["metric"]: row for row in csv.DictReader(handle)}
    ordered = ("FAR", "FRR", "ABSTAIN", "coverage", "calibration")
    if set(rows) != set(ordered):
        raise ValueError("T8 semantic metric scope must match the attested E3 contract")
    values = [float(rows[metric]["value"]) for metric in ordered]
    labels = ["FAR\n(n=2)", "FRR\n(n=6)", "ABSTAIN\n(n=8)", "Coverage\n(n=8)", "Brier\n(n=7)"]
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    colors = [COLORS["orange"], COLORS["blue"], COLORS["purple"], COLORS["green"], COLORS["grey"]]
    bars = ax.bar(labels, values, width=0.62, color=colors)
    ax.axhline(0.25, color="#111111", linewidth=1.4, linestyle="--", label="Frozen FAR threshold = 0.25")
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Observed metric value")
    ax.legend(frameon=False, fontsize=9, loc="upper center")
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.025, f"{value:.3f}", ha="center", va="bottom", fontsize=9)
    _style(ax)
    _finish(fig, output, name="Figure 7 | E3 externally attested negative result")


def build_f8(output: Path) -> None:
    rows = _load("F8_da_withholding")
    labels = [str(row["mode"]).replace("_", " ").title() for row in rows]
    values = [float(row["miss_probability"]) for row in rows]
    lower = [float(row["lower_bound"]) for row in rows]
    upper = [float(row["upper_bound"]) for row in rows]
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    positions = list(range(len(rows)))
    ax.bar(positions, values, width=0.56, color=[COLORS["blue"], COLORS["orange"]])
    ax.errorbar(
        positions,
        values,
        yerr=[
            [value - bound for value, bound in zip(values, lower, strict=True)],
            [bound - value for value, bound in zip(values, upper, strict=True)],
        ],
        fmt="none",
        ecolor="#111111",
        capsize=7,
        linewidth=1.4,
    )
    ax.set_xticks(positions, labels)
    ax.set_ylim(0, max(0.65, max(upper) * 1.12))
    ax.set_ylabel("Modeled miss probability")
    _style(ax)
    _finish(fig, output, name="Figure 8 | E4 declared DA playback")


def _group(rows: list[dict[str, Any]], value_key: str) -> dict[str, list[tuple[int, float]]]:
    grouped: dict[str, list[tuple[int, float]]] = {}
    for row in rows:
        grouped.setdefault(str(row["capacity_model"]), []).append((int(row["identities"]), float(row[value_key])))
    return {name: sorted(points) for name, points in sorted(grouped.items())}


def build_f9(output: Path) -> None:
    grouped = _group(_load("F9_sybil_advantage"), "normalized_expected_credit")
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    palette = [COLORS["blue"], COLORS["orange"], COLORS["green"]]
    for color, (name, points) in zip(palette, grouped.items(), strict=True):
        ax.plot([p[0] for p in points], [p[1] for p in points], marker="o", linewidth=2.2, color=color, label=name.replace("_", " ").title())
    ax.axhline(1.0, color="#777777", linewidth=1, linestyle="--")
    ax.set_xticks([1, 64])
    ax.set_xlabel("Attacker identity count")
    ax.set_ylabel("Normalized expected credit")
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    _finish(fig, output, name="Figure 9 | E6 identity-splitting simulation")


def build_f10(output: Path) -> None:
    grouped = _group(_load("F10_economic_security"), "estimated_cost_to_target_weight_micros")
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    palette = [COLORS["blue"], COLORS["orange"], COLORS["green"]]
    for color, (name, points) in zip(palette, grouped.items(), strict=True):
        ax.plot([p[0] for p in points], [p[1] / 1_000_000 for p in points], marker="o", linewidth=2.2, color=color, label=name.replace("_", " ").title())
    ax.set_xticks([1, 64])
    ax.set_xlabel("Attacker identity count")
    ax.set_ylabel("Estimated cost to 1/3 target weight (million micros)")
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    _finish(fig, output, name="Figure 10 | E6 modeled economic cost")


def build_f11(output: Path) -> None:
    rows = [
        row
        for row in _load("F11_consensus_dynamics")
        if row["estimand"] == "ATTACKER_COMMITTEE_WEIGHT_SHARE"
    ]
    scenarios = sorted({str(row["scenario_id"]) for row in rows})
    labels = [scenario.replace("-", " ").title() for scenario in scenarios]
    one_third = {
        str(row["scenario_id"]): float(row["probability"])
        for row in rows
        if row["threshold"] == "GE_ONE_THIRD"
    }
    two_thirds = {
        str(row["scenario_id"]): float(row["probability"])
        for row in rows
        if row["threshold"] == "GE_TWO_THIRDS"
    }
    positions = list(range(len(scenarios)))
    height = 0.34
    fig, ax = plt.subplots(figsize=(10.2, 6.1))
    ax.barh(
        [position + height / 2 for position in positions],
        [one_third[scenario] for scenario in scenarios],
        height=height,
        color=COLORS["blue"],
        label="At least one-third",
    )
    ax.barh(
        [position - height / 2 for position in positions],
        [two_thirds[scenario] for scenario in scenarios],
        height=height,
        color=COLORS["orange"],
        label="At least two-thirds",
    )
    ax.set_yticks(positions, labels)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Modeled probability")
    ax.legend(frameon=False, ncol=2, loc="lower right")
    _style(ax)
    _finish(fig, output, name="Figure 11 | E8 modeled next-epoch dynamics")


def build_f12(output: Path) -> None:
    rows = _load("F12_evm_gas_state_scaling")
    batch_one = sorted((row for row in rows if int(row["batch_size"]) == 1), key=lambda row: int(row["gas_used"]), reverse=True)
    credit = sorted((row for row in rows if row["operation"] == "CREDIT_ALLOCATE"), key=lambda row: int(row["batch_size"]))
    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(10.2, 5.1), gridspec_kw={"width_ratios": [1.35, 1]})
    labels = [str(row["operation"]).replace("_", " ").title() for row in batch_one]
    values = [int(row["gas_used"]) for row in batch_one]
    ax_left.barh(labels[::-1], values[::-1], color=COLORS["blue"])
    ax_left.set_xlabel("Gas used (batch size 1)")
    ax_left.tick_params(axis="y", labelsize=8)
    _style(ax_left)
    ax_right.plot([int(row["batch_size"]) for row in credit], [int(row["gas_used"]) for row in credit], marker="o", linewidth=2.2, color=COLORS["green"])
    ax_right.set_xticks([1, 2, 4, 8])
    ax_right.set_xlabel("Credit-allocation batch size")
    ax_right.set_ylabel("Gas used")
    _style(ax_right)
    _finish(fig, output, name="Figure 12 | E7 local EVM gas boundedness")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    builders = {
        "F5_single_pass_cost.png": build_f5,
        "F6_audit_soundness.png": build_f6,
        "F7_semantic_verification_quality.png": build_f7,
        "F8_da_withholding.png": build_f8,
        "F9_sybil_advantage.png": build_f9,
        "F10_economic_security.png": build_f10,
        "F11_consensus_dynamics.png": build_f11,
        "F12_evm_gas_state_scaling.png": build_f12,
    }
    for filename, builder in builders.items():
        builder(args.output_dir / filename)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
