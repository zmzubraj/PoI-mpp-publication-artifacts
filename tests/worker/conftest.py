from __future__ import annotations

import pytest

from poi_mpp.evidence.models import EvidenceOrigin
from poi_mpp.protocol.types import TaskClass, TaskSpec


@pytest.fixture()
def task() -> TaskSpec:
    return TaskSpec(
        task_id=9,
        task_root="0x" + "09" * 32,
        worker_id="0x0000000000000000000000000000000000002009",
        task_class=TaskClass.CONSENSUS,
        active=True,
        registered=True,
        credit_budget=50,
        epoch=3,
        deadline=144,
        commitment_height=20,
        commitment_finality_depth=4,
        challenge_window_blocks=8,
        audit_domain_size=16,
    )


@pytest.fixture()
def synthetic_origin() -> EvidenceOrigin:
    return EvidenceOrigin.SYNTHETIC_NON_EVIDENCE
