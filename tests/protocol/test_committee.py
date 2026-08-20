from __future__ import annotations

import pytest

from poi_mpp.protocol.committee import sample_committee


def test_same_seed_produces_same_committee():
    weights = {"worker-a": 10, "worker-b": 20, "worker-c": 30}
    first = sample_committee(weights, committee_size=2, seed=b"epoch-1")
    second = sample_committee(weights, committee_size=2, seed=b"epoch-1")
    assert first == second


def test_zero_total_weight_is_rejected():
    with pytest.raises(ValueError, match="total active weight"):
        sample_committee({"worker-a": 0, "worker-b": 0}, committee_size=1, seed=b"epoch-1")


def test_zero_weight_workers_are_not_selected():
    committee = sample_committee(
        {"worker-a": 0, "worker-b": 0, "worker-c": 5},
        committee_size=1,
        seed=b"epoch-1",
    )
    assert committee == ("worker-c",)


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError, match="negative"):
        sample_committee({"worker-a": -1, "worker-b": 5}, committee_size=1, seed=b"epoch-1")


def test_empty_weights_and_oversized_committee_are_rejected():
    with pytest.raises(ValueError, match="total active weight"):
        sample_committee({}, committee_size=1, seed=b"epoch-1")
    with pytest.raises(ValueError, match="committee_size"):
        sample_committee({"worker-a": 3}, committee_size=2, seed=b"epoch-1")
