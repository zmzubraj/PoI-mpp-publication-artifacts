"""Deterministic SVG generation for publication reporting."""

from __future__ import annotations

from collections import defaultdict
import html
import json
from typing import Any

from poi_mpp.reporting.load import LoadedBundle, LoadedExperiment
from poi_mpp.reporting.statistics import canonical_decimal, require_finite_number


_WIDTH = 960
_HEIGHT = 540
_PLOT_LEFT = 90
_PLOT_TOP = 60
_PLOT_WIDTH = 780
_PLOT_HEIGHT = 360
_COLORS = ("#1f77b4", "#000000", "#d95f02", "#7570b3", "#66a61e")
_DASHES = ("none", "8 4", "3 3", "10 3 2 3", "2 5")


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _status_svg(*, title: str, subtitle: str, artifact_id: str, source_hashes: tuple[str, ...]) -> bytes:
    lines = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{_WIDTH}' height='{_HEIGHT}' viewBox='0 0 {_WIDTH} {_HEIGHT}'>",
        "<rect width='100%' height='100%' fill='#ffffff'/>",
        "<rect x='40' y='40' width='880' height='460' fill='#f8f8f8' stroke='#111111' stroke-width='2'/>",
        f"<text x='70' y='110' font-family='Menlo, monospace' font-size='30' fill='#111111'>{_escape(artifact_id)} { _escape(title) }</text>",
        f"<text x='70' y='170' font-family='Menlo, monospace' font-size='22' fill='#444444'>{_escape(subtitle)}</text>",
        f"<text x='70' y='470' font-family='Menlo, monospace' font-size='14' fill='#444444'>source_hashes: {_escape(','.join(source_hashes))}</text>",
        "</svg>",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _series_svg(
    *,
    artifact_id: str,
    title: str,
    subtitle: str,
    x_label: str,
    y_label: str,
    x_values: list[str],
    series: dict[str, list[tuple[str, float]]],
    source_hashes: tuple[str, ...],
) -> bytes:
    if not x_values:
        return _status_svg(
            title=title,
            subtitle="No validated points available",
            artifact_id=artifact_id,
            source_hashes=source_hashes,
        )
    unique_x = list(dict.fromkeys(x_values))
    y_max = max(point[1] for points in series.values() for point in points)
    y_max = 1.0 if y_max <= 0 else y_max
    x_step = _PLOT_WIDTH / max(1, len(unique_x) - 1)
    lines = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{_WIDTH}' height='{_HEIGHT}' viewBox='0 0 {_WIDTH} {_HEIGHT}'>",
        "<rect width='100%' height='100%' fill='#ffffff'/>",
        f"<text x='60' y='35' font-family='Menlo, monospace' font-size='26' fill='#111111'>{_escape(artifact_id)} {_escape(title)}</text>",
        f"<text x='60' y='58' font-family='Menlo, monospace' font-size='14' fill='#444444'>{_escape(subtitle)}</text>",
        f"<line x1='{_PLOT_LEFT}' y1='{_PLOT_TOP + _PLOT_HEIGHT}' x2='{_PLOT_LEFT + _PLOT_WIDTH}' y2='{_PLOT_TOP + _PLOT_HEIGHT}' stroke='#111111' stroke-width='2'/>",
        f"<line x1='{_PLOT_LEFT}' y1='{_PLOT_TOP}' x2='{_PLOT_LEFT}' y2='{_PLOT_TOP + _PLOT_HEIGHT}' stroke='#111111' stroke-width='2'/>",
        f"<text x='{_PLOT_LEFT + (_PLOT_WIDTH / 2)}' y='470' text-anchor='middle' font-family='Menlo, monospace' font-size='16'>{_escape(x_label)}</text>",
        f"<text x='24' y='{_PLOT_TOP + (_PLOT_HEIGHT / 2)}' text-anchor='middle' transform='rotate(-90 24,{_PLOT_TOP + (_PLOT_HEIGHT / 2)})' font-family='Menlo, monospace' font-size='16'>{_escape(y_label)}</text>",
    ]
    for index, x_value in enumerate(unique_x):
        x = _PLOT_LEFT + (index * x_step if len(unique_x) > 1 else (_PLOT_WIDTH / 2))
        lines.append(f"<line x1='{x}' y1='{_PLOT_TOP + _PLOT_HEIGHT}' x2='{x}' y2='{_PLOT_TOP + _PLOT_HEIGHT + 6}' stroke='#111111' stroke-width='1'/>")
        lines.append(f"<text x='{x}' y='{_PLOT_TOP + _PLOT_HEIGHT + 24}' text-anchor='middle' font-family='Menlo, monospace' font-size='12'>{_escape(x_value)}</text>")
    for tick in range(0, 6):
        y_value = y_max * tick / 5
        y = _PLOT_TOP + _PLOT_HEIGHT - (_PLOT_HEIGHT * tick / 5)
        lines.append(f"<line x1='{_PLOT_LEFT - 6}' y1='{y}' x2='{_PLOT_LEFT}' y2='{y}' stroke='#111111' stroke-width='1'/>")
        lines.append(f"<text x='{_PLOT_LEFT - 10}' y='{y + 4}' text-anchor='end' font-family='Menlo, monospace' font-size='12'>{_escape(canonical_decimal(y_value))}</text>")
    for series_index, (series_name, points) in enumerate(sorted(series.items())):
        color = _COLORS[series_index % len(_COLORS)]
        dash = _DASHES[series_index % len(_DASHES)]
        segments: list[str] = []
        for x_value, y_value in sorted(points, key=lambda item: unique_x.index(item[0])):
            require_finite_number(y_value, label=f"{artifact_id}.{series_name}")
            x = _PLOT_LEFT + (unique_x.index(x_value) * x_step if len(unique_x) > 1 else (_PLOT_WIDTH / 2))
            y = _PLOT_TOP + _PLOT_HEIGHT - ((y_value / y_max) * _PLOT_HEIGHT)
            segments.append(f"{canonical_decimal(x)},{canonical_decimal(y)}")
            lines.append(f"<circle cx='{canonical_decimal(x)}' cy='{canonical_decimal(y)}' r='4' fill='{color}' stroke='#111111' stroke-width='1'/>")
        lines.append(
            f"<polyline fill='none' stroke='{color}' stroke-width='3' stroke-dasharray='{dash}' points='{' '.join(segments)}'/>"
        )
        legend_y = 95 + (series_index * 22)
        lines.append(f"<line x1='700' y1='{legend_y}' x2='736' y2='{legend_y}' stroke='{color}' stroke-width='3' stroke-dasharray='{dash}'/>")
        lines.append(f"<text x='744' y='{legend_y + 4}' font-family='Menlo, monospace' font-size='13'>{_escape(series_name)}</text>")
    lines.append(f"<text x='60' y='510' font-family='Menlo, monospace' font-size='13'>source_hashes: {_escape(','.join(source_hashes))}</text>")
    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _experiment_figure_outputs(experiment: LoadedExperiment) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}
    if experiment.experiment_id == "E8" and experiment.figure_points:
        grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
        x_values: list[str] = []
        for point in experiment.figure_points:
            series_name = f"{point['estimand']}:{point['threshold']}"
            x_label = point["scenario_id"]
            grouped[series_name].append((x_label, require_finite_number(point["probability"], label="E8 probability")))
            x_values.append(x_label)
        outputs["figures/F11_consensus_dynamics.svg"] = _series_svg(
            artifact_id="F11",
            title="Consensus Dynamics",
            subtitle="REPRODUCIBLE_SIMULATION next-epoch probabilities",
            x_label="Scenario",
            y_label="Probability",
            x_values=x_values,
            series=grouped,
            source_hashes=experiment.source_hashes,
        )
        outputs["figures/F11_consensus_dynamics.json"] = (json.dumps(experiment.figure_points, sort_keys=True, indent=2) + "\n").encode("utf-8")
    elif experiment.experiment_id == "E7" and experiment.figure_points:
        grouped = defaultdict(list)
        x_values = []
        for point in experiment.figure_points:
            series_name = point["operation"]
            x_label = str(point["batch_size"])
            grouped[series_name].append((x_label, require_finite_number(point["gas_used"], label="E7 gas")))
            x_values.append(x_label)
        outputs["figures/F12_evm_gas_state_scaling.svg"] = _series_svg(
            artifact_id="F12",
            title="EVM Gas and State Scaling",
            subtitle="FOUNDRY_MEASUREMENT local boundedness",
            x_label="Batch Size",
            y_label="Gas Used",
            x_values=x_values,
            series=grouped,
            source_hashes=experiment.source_hashes,
        )
        outputs["figures/F12_evm_gas_state_scaling.json"] = (json.dumps(experiment.figure_points, sort_keys=True, indent=2) + "\n").encode("utf-8")
    elif experiment.omission_reason is not None:
        for artifact_id in experiment.figure_ids:
            filename = {
                "F5": "F5_single_pass_cost.svg",
                "F6": "F6_audit_soundness.svg",
                "F7": "F7_semantic_verification_quality.svg",
                "F8": "F8_da_withholding.svg",
                "F9": "F9_sybil_advantage.svg",
                "F10": "F10_economic_security.svg",
                "F11": "F11_consensus_dynamics.svg",
                "F12": "F12_evm_gas_state_scaling.svg",
            }[artifact_id]
            outputs[f"figures/{filename}"] = _status_svg(
                title="Status",
                subtitle=experiment.omission_reason,
                artifact_id=artifact_id,
                source_hashes=experiment.source_hashes,
            )
    return outputs


def figure_artifacts(bundle: LoadedBundle) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {}
    for experiment in bundle.experiments:
        outputs.update(_experiment_figure_outputs(experiment))
    return outputs


__all__ = ["figure_artifacts"]
