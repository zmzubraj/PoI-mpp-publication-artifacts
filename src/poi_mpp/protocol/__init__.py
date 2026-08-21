"""Python reference protocol kernel for commitments, audits, and receipts."""

from poi_mpp.protocol.audit_compiler import AuditPolicy, compile_audit
from poi_mpp.protocol.availability import (
    ErasureParameters,
    LocalShardStore,
    SampleCertificate,
    SamplingAssumption,
    SamplingMode,
    ShardLayout,
    issue_sample_certificate,
)
from poi_mpp.protocol.committee import sample_committee
from poi_mpp.protocol.commitment import commit_response
from poi_mpp.protocol.credit import CreditAllocation, allocate_credit, derive_active_weight
from poi_mpp.protocol.receipt import (
    ActivateReceipt,
    ExpireReceipt,
    OpenChallenge,
    RecordAudit,
    RecordDataAvailability,
    SlashReceipt,
)
from poi_mpp.protocol.reference_machine import InvalidTransition, transition
from poi_mpp.protocol.types import (
    AuditDecision,
    AuditPlan,
    ModelManifest,
    Receipt,
    ReceiptState,
    ResponseCommitment,
    TaskClass,
    TaskSpec,
    TransitionContext,
)

__all__ = [
    "ActivateReceipt",
    "AuditDecision",
    "AuditPlan",
    "AuditPolicy",
    "CreditAllocation",
    "ExpireReceipt",
    "ErasureParameters",
    "InvalidTransition",
    "LocalShardStore",
    "ModelManifest",
    "OpenChallenge",
    "Receipt",
    "ReceiptState",
    "RecordAudit",
    "RecordDataAvailability",
    "ResponseCommitment",
    "SampleCertificate",
    "SamplingAssumption",
    "SamplingMode",
    "SlashReceipt",
    "ShardLayout",
    "TaskClass",
    "TaskSpec",
    "TransitionContext",
    "allocate_credit",
    "commit_response",
    "compile_audit",
    "derive_active_weight",
    "issue_sample_certificate",
    "sample_committee",
    "transition",
]
