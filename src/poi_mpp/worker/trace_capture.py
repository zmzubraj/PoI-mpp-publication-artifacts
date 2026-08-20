"""Immutable trace sidecar capture helpers."""

from __future__ import annotations

from pydantic import model_validator

from poi_mpp.worker.model_manifest import _FrozenWorkerModel
from poi_mpp.worker.trace_schema import TraceEvent
from poi_mpp.worker.trace_tree import trace_root


class TraceSidecar(_FrozenWorkerModel):
    schema_version: str = "POI_MPP_TRACE_SIDECAR_V1"
    events: tuple[TraceEvent, ...]
    trace_root: str

    @model_validator(mode="after")
    def require_consistent_root(self) -> "TraceSidecar":
        if not self.events:
            raise ValueError("trace sidecar must contain at least one event")
        expected = trace_root(self.events)
        if self.trace_root != expected:
            raise ValueError("trace_root does not match events")
        return self


def build_trace_sidecar(events: tuple[TraceEvent, ...] | list[TraceEvent]) -> TraceSidecar:
    frozen_events = tuple(events)
    return TraceSidecar(events=frozen_events, trace_root=trace_root(frozen_events))
