from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_cli_module():
    path = REPO_ROOT / "experiments" / "e7_evm_boundedness.py"
    spec = importlib.util.spec_from_file_location("e7_evm_boundedness_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Dumpable:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.payload


def test_e7_cli_public_summary_does_not_leak_absolute_bundle_path(tmp_path, monkeypatch) -> None:
    module = _load_cli_module()
    bundle_path = tmp_path / "external-bundle.json"
    summary_path = tmp_path / "summary.json"
    run_config_path = tmp_path / "run.yaml"
    run_config_path.write_text("stub", encoding="utf-8")

    monkeypatch.setattr(module, "load_run_config", lambda _: object())
    monkeypatch.setattr(module, "assert_cli_authority_boundary", lambda _: None)
    monkeypatch.setattr(
        module,
        "collect_and_summarize_e7_publication",
        lambda **_: SimpleNamespace(
            bundle=SimpleNamespace(rows=()),
            summary=_Dumpable({"claim_disposition": "SUPPORTED"}),
            parity_verification=_Dumpable(
                {
                    "source_closure_hash": "a" * 64,
                    "source_paths": ["src/poi_mpp/protocol/hashing.py"],
                    "protocol_vectors_path": str(tmp_path / "protocol_vectors.json"),
                    "protocol_vectors_hash": "b" * 64,
                    "protocol_witness_path": str(tmp_path / "protocol_witnesses.json"),
                    "protocol_witness_hash": "c" * 64,
                    "export_vectors_transcript": {
                        "command": [str(tmp_path / "python"), "scripts/export_solidity_vectors.py"],
                        "cwd": str(tmp_path),
                    },
                    "hashvectors_test_transcript": {
                        "command": ["forge", "test"],
                        "cwd": str(tmp_path / "contracts"),
                    },
                    "python_parity_transcript": {
                        "command": [str(tmp_path / "python"), "-m", "pytest"],
                        "cwd": str(tmp_path),
                    },
                }
            ),
        ),
    )
    monkeypatch.setattr(module, "t12_rows", lambda _: ())
    monkeypatch.setattr(module, "f12_points", lambda _: ())

    assert module.main(
        [
            "--run-config",
            str(run_config_path),
            "--bundle-out",
            str(bundle_path),
            "--summary-out",
            str(summary_path),
        ]
    ) == 0

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["bundle_path"] == "external-bundle.json"
    assert str(tmp_path) not in summary_path.read_text(encoding="utf-8")


def test_reporting_entrypoint_rejects_tampered_hash_before_any_subprocess(monkeypatch, tmp_path) -> None:
    from poi_mpp.evidence.config import load_run_config
    from poi_mpp.experiments.e7_evm import AuthorityBoundaryError
    from poi_mpp.reporting import e7 as reporting

    run_config = load_run_config(REPO_ROOT / "configs" / "publication_foundry" / "e7.run.yaml")
    tampered = run_config.model_copy(update={"dataset_hash": "0" * 64})
    monkeypatch.setattr(
        reporting,
        "verify_current_e7_parity",
        lambda **_: (_ for _ in ()).throw(AssertionError("parity subprocess must not start")),
    )
    monkeypatch.setattr(
        reporting,
        "collect_foundry_measurements",
        lambda **_: (_ for _ in ()).throw(AssertionError("Foundry subprocess must not start")),
    )

    with pytest.raises(AuthorityBoundaryError, match="dataset_hash"):
        reporting.collect_and_summarize_e7_publication(
            contracts_root=REPO_ROOT / "contracts",
            run_config=tampered,
            bundle_output_path=tmp_path / "bundle.json",
        )
