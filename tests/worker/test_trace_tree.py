from __future__ import annotations

import pytest

from poi_mpp.worker.trace_schema import TraceEvent
from poi_mpp.worker.trace_tree import trace_root


def _event(*, index: int, output_hash: str) -> TraceEvent:
    return TraceEvent(
        event_index=index,
        op_name="decode_step",
        input_hashes=("0x" + "11" * 32,),
        output_hash=output_hash,
        metadata={"token_id": index, "surface": "SYNTHETIC_NON_EVIDENCE"},
    )


def test_trace_root_changes_when_one_event_changes() -> None:
    trace_events = [
        _event(index=0, output_hash="0x" + "12" * 32),
        _event(index=1, output_hash="0x" + "13" * 32),
    ]
    original = trace_root(trace_events)
    trace_events[0] = trace_events[0].model_copy(update={"output_hash": "0x" + "00" * 32})
    assert trace_root(trace_events) != original


def test_trace_root_is_stable_for_same_inputs() -> None:
    trace_events = (
        _event(index=0, output_hash="0x" + "12" * 32),
        _event(index=1, output_hash="0x" + "13" * 32),
    )
    assert trace_root(trace_events) == trace_root(trace_events)


def test_trace_event_rejects_private_metadata() -> None:
    with pytest.raises(ValueError, match="safe public metadata"):
        TraceEvent(
            event_index=0,
            op_name="decode_step",
            input_hashes=("0x" + "11" * 32,),
            output_hash="0x" + "12" * 32,
            metadata={"debug_path": "/Users/rainbow/private/model.bin"},
        )
