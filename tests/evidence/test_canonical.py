import math
import json
from pathlib import Path

import pytest

from poi_mpp.evidence.canonical import canonical_bytes, digest


def test_hash_is_key_order_independent_and_domain_separated():
    assert digest("TASK", {"b": 2, "a": 1}) == digest("TASK", {"a": 1, "b": 2})
    assert digest("TASK", {"a": 1}) != digest("MODEL", {"a": 1})


def test_canonical_bytes_use_the_versioned_domain_prefix_and_compact_json():
    assert canonical_bytes("TASK", {"b": 2, "a": 1}) == b'POI_MPP_V1|TASK|{"a":1,"b":2}'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value):
    with pytest.raises(ValueError):
        canonical_bytes("TASK", {"value": value})


@pytest.mark.parametrize("domain", ["", "task", "TASK|MODEL", "TASK-1"])
def test_invalid_domain_is_rejected(domain):
    with pytest.raises(ValueError):
        canonical_bytes(domain, {"a": 1})


def test_fixed_cross_language_vectors_are_regenerated_by_the_canonical_contract():
    fixture_path = Path(__file__).parents[1] / "fixtures" / "hash_vectors.json"
    vectors = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert vectors["format"] == "POI_MPP_V1_SHA256_HEX"
    for vector in vectors["vectors"]:
        assert canonical_bytes(vector["domain"], vector["value"]).decode("utf-8") == vector[
            "canonical_utf8"
        ]
        assert digest(vector["domain"], vector["value"]) == vector["sha256"]
