from __future__ import annotations


from poi_mpp.protocol.audit_compiler import compile_audit


def test_compile_audit_is_deterministic_for_same_inputs(task, commitment, policy):
    first = compile_audit(policy, task, commitment, b"beacon", 2)
    second = compile_audit(policy, task, commitment, b"beacon", 2)
    assert first == second
    assert len(first.sample_indices) == policy.sample_count
    assert all(0 <= item < task.audit_domain_size for item in first.sample_indices)


def test_compile_audit_changes_with_beacon_or_round(task, commitment, policy):
    first = compile_audit(policy, task, commitment, b"beacon-a", 0)
    second = compile_audit(policy, task, commitment, b"beacon-b", 0)
    third = compile_audit(policy, task, commitment, b"beacon-a", 1)
    assert first.sample_indices != second.sample_indices
    assert first.sample_indices != third.sample_indices
