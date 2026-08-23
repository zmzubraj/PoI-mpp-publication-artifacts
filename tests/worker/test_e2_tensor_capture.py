from __future__ import annotations

from poi_mpp.evidence.config import approved_schema_hash
from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.evidence.config import RunConfig
from poi_mpp.protocol.types import TaskClass, TaskSpec
from poi_mpp.worker.deterministic_decode import DeterministicDecodePolicy
from poi_mpp.worker.e2_tensor_capture import TensorCaptureSpec, build_real_e2_bundle, derive_tensor_product_capture
from poi_mpp.worker.model_manifest import PinnedModelManifest


def _manifest() -> PinnedModelManifest:
    return PinnedModelManifest(
        model_id="local-qwen-1.5b",
        repository="Qwen/Qwen2.5-1.5B-Instruct",
        revision="9" * 40,
        tokenizer_id="Qwen/Qwen2.5-1.5B-Instruct",
        tokenizer_revision="9" * 40,
        license_id="apache-2.0",
        parameter_scale="1.5B",
        precision="bfloat16",
        quantization="none",
        runtime_name="transformers",
        runtime_version="5.14.1",
        model_file_hashes={"model.safetensors": "2" * 64},
        tokenizer_file_hashes={"tokenizer.json": "3" * 64},
    )


def _task() -> TaskSpec:
    return TaskSpec(
        task_id=22,
        task_root="0xaa" + "22" * 31,
        worker_id="0x0000000000000000000000000000000000002022",
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=90,
        epoch=7,
        deadline=500,
        commitment_height=120,
        commitment_finality_depth=5,
        challenge_window_blocks=9,
        audit_domain_size=16,
    )


def _run_config() -> RunConfig:
    return RunConfig.model_validate(
        {
            "schema_version": "POI_MPP_RUN_CONFIG_V1",
            "schema_hash": approved_schema_hash(),
            "run_id": "run-real-e2",
            "experiment_id": "E2",
            "origin": EvidenceOrigin.REAL_MODEL_EXECUTION.value,
            "authorization_scope": "PUBLICATION_EVIDENCE_AUTHORIZED",
            "model_hash": "a" * 64,
            "dataset_hash": "b" * 64,
            "parent_hashes": [],
            "data_availability": {"total_shards": 8, "samples": 2, "replacement": False},
        }
    )


def test_derive_tensor_product_capture_builds_consistent_exact_and_float_surfaces() -> None:
    capture = derive_tensor_product_capture(
        activation_rows=((1.25, -0.5, 2.0),),
        weight_rows=(
            (2.0, 4.0, 6.0),
            (1.0, 3.0, 5.0),
        ),
        spec=TensorCaptureSpec(
            layer_path="model.layers.0.mlp.down_proj",
            activation_token_index=0,
            input_width=3,
            output_width=2,
            fixed_point_scale=1000,
        ),
    )

    assert capture.float_matrix_a == ((1.25, -0.5, 2.0),)
    assert capture.float_matrix_b == (
        (2.0, 1.0),
        (4.0, 3.0),
        (6.0, 5.0),
    )
    assert capture.float_matrix_c == ((12.5, 9.75),)

    assert capture.field_matrix_a == ((1250, 2147483147, 2000),)
    assert capture.field_matrix_b == (
        (2000, 1000),
        (4000, 3000),
        (6000, 5000),
    )
    assert capture.field_matrix_c == ((12500000, 9750000),)


def test_tensor_capture_spec_rejects_zero_slice_width() -> None:
    try:
        TensorCaptureSpec(
            layer_path="model.layers.0.mlp.down_proj",
            activation_token_index=0,
            input_width=0,
            output_width=2,
        )
    except ValueError as error:
        assert "input_width" in str(error)
    else:
        raise AssertionError("expected TensorCaptureSpec to reject zero-width slices")


def test_build_real_e2_bundle_uses_authorized_session_boundary_and_current_trace_contract() -> None:
    class FakeLayer:
        def __init__(self) -> None:
            self.weight = [[2.0, 4.0, 6.0], [1.0, 3.0, 5.0]]
            self._hook = None

        def register_forward_hook(self, hook):
            self._hook = hook

            class _Handle:
                def remove(self_nonlocal) -> None:
                    self._hook = None

            return _Handle()

    class FakeModel:
        def __init__(self) -> None:
            self.model = type(
                "_Root",
                (),
                {
                    "layers": [type("_LayerContainer", (), {"mlp": type("_MLP", (), {"down_proj": FakeLayer()})()})()],
                },
            )()

    class FakeRuntime:
        def encode_task(self, loaded_tokenizer, task):
            del loaded_tokenizer
            return (task.task_id, task.epoch, task.credit_budget)

        def generate(self, loaded_model, prompt_token_ids, policy):
            del prompt_token_ids, policy
            layer = loaded_model.model.layers[0].mlp.down_proj
            if layer._hook is not None:
                layer._hook(layer, ([[1.25, -0.5, 2.0]],), None)
            return (101, 102, 103)

        def decode(self, loaded_tokenizer, token_ids):
            del loaded_tokenizer, token_ids
            return "héllo deterministic world"

    class FakeSession:
        def __init__(self) -> None:
            self.called = False
            self._runtime = FakeRuntime()
            self._loaded_model = FakeModel()
            self._loaded_tokenizer = object()
            self._loaded_manifest = _manifest()

        def __call__(self, **kwargs):
            self.called = True
            assert kwargs["local_files_only"] is True
            return type(
                "_VerifiedResult",
                (),
                {
                    "response": "héllo deterministic world",
                    "warmup_ms": 3.0,
                },
            )()

    session_holder: dict[str, FakeSession] = {}

    def session_factory() -> FakeSession:
        session = FakeSession()
        session_holder["session"] = session
        return session

    bundle, capture = build_real_e2_bundle(
        run_config=_run_config(),
        task=_task(),
        manifest=_manifest(),
        policy=DeterministicDecodePolicy(seed=7, max_new_tokens=24),
        model_path="/tmp/model",
        tokenizer_path="/tmp/tokenizer",
        capture_spec=TensorCaptureSpec(
            layer_path="model.layers.0.mlp.down_proj",
            activation_token_index=0,
            input_width=3,
            output_width=2,
            fixed_point_scale=1000,
        ),
        receipt_id="receipt-real-e2-0001",
        session_factory=session_factory,
        clock=iter((10.0, 10.25)).__next__,
    )

    assert session_holder["session"].called is True
    assert capture.float_matrix_c == ((12.5, 9.75),)
    assert bundle.response_hash.startswith("0x")
    assert bundle.trace_root.startswith("0x")
    assert bundle.model_manifest.model_manifest_hash.startswith("0x")
