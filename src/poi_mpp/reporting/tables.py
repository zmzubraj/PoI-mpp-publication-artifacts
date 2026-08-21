"""Editable deterministic publication tables."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from poi_mpp.reporting.load import LoadedBundle, LoadedExperiment
from poi_mpp.reporting.statistics import csv_cell, deterministic_sort_key


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    headers = sorted({key for row in rows for key in row})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in sorted(rows, key=deterministic_sort_key):
        writer.writerow({key: csv_cell(row.get(key)) for key in headers})
    return buffer.getvalue().encode("utf-8")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _table_rows(experiment: LoadedExperiment) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in experiment.table_rows:
        enriched = dict(row)
        enriched.setdefault("origin", experiment.origin or "")
        enriched.setdefault("run_id", experiment.run_id or "")
        enriched.setdefault("config_hash", experiment.config_hash or "")
        enriched.setdefault("sample_size", experiment.sample_size or 0)
        enriched.setdefault("claim_disposition", experiment.disposition)
        enriched.setdefault("uncertainty", experiment.uncertainty or "N/A")
        enriched.setdefault("source_hashes", "|".join(experiment.source_hashes))
        rows.append(enriched)
    return rows


def claim_matrix_rows(bundle: LoadedBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for experiment in bundle.experiments:
        rows.append(
            {
                "artifact_id": experiment.table_id or "",
                "experiment_id": experiment.experiment_id,
                "claim_id": experiment.claim_id,
                "disposition": experiment.disposition,
                "origin": experiment.origin or "",
                "scope": experiment.scope or "",
                "maturity": experiment.maturity,
                "run_id": experiment.run_id or "",
                "config_hash": experiment.config_hash or "",
                "source_hashes": "|".join(experiment.source_hashes),
                "limits": "|".join(experiment.limits),
                "omission_reason": experiment.omission_reason or "",
            }
        )
    return rows


def omission_rows(bundle: LoadedBundle) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for experiment in bundle.experiments:
        if experiment.omission_reason is None:
            continue
        artifact_ids = [artifact_id for artifact_id in (experiment.table_id, *experiment.figure_ids) if artifact_id]
        for artifact_id in artifact_ids:
            rows.append(
                {
                    "artifact_id": artifact_id,
                    "experiment_id": experiment.experiment_id,
                    "disposition": experiment.disposition,
                    "origin": experiment.origin or "",
                    "reason": experiment.omission_reason,
                }
            )
    return rows


def table_artifacts(bundle: LoadedBundle) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {
        "tables/claim_matrix.csv": _csv_bytes(claim_matrix_rows(bundle)),
        "tables/omissions.csv": _csv_bytes(omission_rows(bundle)),
        "tables/claim_matrix.json": _json_bytes(claim_matrix_rows(bundle)),
        "tables/omissions.json": _json_bytes(omission_rows(bundle)),
    }
    for experiment in bundle.experiments:
        if experiment.table_id is None or not experiment.table_rows:
            continue
        rows = _table_rows(experiment)
        suffix = {
            "T10": "watcher_dispute_economics",
            "T11": "sybil_economics",
            "T12": "evm_boundedness",
            "T13": "consensus_safety",
        }.get(experiment.table_id, experiment.table_id.lower())
        outputs[f"tables/{experiment.table_id}_{suffix}.csv"] = _csv_bytes(rows)
        outputs[f"tables/{experiment.table_id}_{suffix}.json"] = _json_bytes(rows)
    return outputs


__all__ = ["claim_matrix_rows", "omission_rows", "table_artifacts"]
