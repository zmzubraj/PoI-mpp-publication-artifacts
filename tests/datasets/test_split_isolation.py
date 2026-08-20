from __future__ import annotations

import pytest

from poi_mpp.datasets import (
    DatasetLeakageError,
    DatasetManifest,
    DatasetRecord,
    DatasetSplit,
    assert_confirmatory_isolation,
)
from poi_mpp.evidence.models import EvidenceOrigin


def _record(
    record_id: str,
    *,
    split: DatasetSplit,
    origin: EvidenceOrigin = EvidenceOrigin.REAL_MODEL_EXECUTION,
    source_family: str = "paper-a",
    source_hash: str = "a" * 64,
    content_hash: str = "b" * 64,
) -> DatasetRecord:
    return DatasetRecord(
        record_id=record_id,
        split=split,
        origin=origin,
        source_family=source_family,
        source_hash=source_hash,
        content_hash=content_hash,
    )


def test_confirmation_ids_cannot_overlap_development_ids():
    with pytest.raises(DatasetLeakageError):
        assert_confirmatory_isolation({"x"}, {"x"})


def test_confirmatory_isolation_rejects_content_overlap():
    development = DatasetManifest(
        dataset_id="development",
        split=DatasetSplit.DEVELOPMENT,
        records=(
            _record(
                "dev-1",
                split=DatasetSplit.DEVELOPMENT,
                source_hash="a" * 64,
                content_hash="1" * 64,
            ),
        ),
    )
    confirmatory = DatasetManifest(
        dataset_id="confirmatory",
        split=DatasetSplit.CONFIRMATORY,
        records=(
            _record(
                "conf-1",
                split=DatasetSplit.CONFIRMATORY,
                source_family="paper-b",
                source_hash="b" * 64,
                content_hash="1" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetLeakageError, match="content hash overlap"):
        assert_confirmatory_isolation(development, confirmatory)


def test_confirmatory_isolation_rejects_source_hash_overlap():
    development = DatasetManifest(
        dataset_id="development",
        split=DatasetSplit.DEVELOPMENT,
        records=(
            _record(
                "dev-1",
                split=DatasetSplit.DEVELOPMENT,
                source_family="paper-a",
                source_hash="f" * 64,
                content_hash="1" * 64,
            ),
        ),
    )
    confirmatory = DatasetManifest(
        dataset_id="confirmatory",
        split=DatasetSplit.CONFIRMATORY,
        records=(
            _record(
                "conf-1",
                split=DatasetSplit.CONFIRMATORY,
                source_family="paper-b",
                source_hash="f" * 64,
                content_hash="2" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetLeakageError, match="source hash overlap"):
        assert_confirmatory_isolation(development, confirmatory)


def test_confirmatory_isolation_rejects_source_family_overlap():
    development = DatasetManifest(
        dataset_id="development",
        split=DatasetSplit.DEVELOPMENT,
        records=(
            _record(
                "dev-1",
                split=DatasetSplit.DEVELOPMENT,
                source_family="shared-paper",
                source_hash="a" * 64,
                content_hash="1" * 64,
            ),
        ),
    )
    confirmatory = DatasetManifest(
        dataset_id="confirmatory",
        split=DatasetSplit.CONFIRMATORY,
        records=(
            _record(
                "conf-1",
                split=DatasetSplit.CONFIRMATORY,
                source_family="shared-paper",
                source_hash="b" * 64,
                content_hash="2" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetLeakageError, match="source family overlap"):
        assert_confirmatory_isolation(development, confirmatory)


def test_manifest_rejects_duplicate_record_ids():
    with pytest.raises(ValueError, match="duplicate record_id"):
        DatasetManifest(
            dataset_id="development",
            split=DatasetSplit.DEVELOPMENT,
            records=(
                _record("dup", split=DatasetSplit.DEVELOPMENT),
                _record(
                    "dup",
                    split=DatasetSplit.DEVELOPMENT,
                    source_hash="c" * 64,
                    content_hash="d" * 64,
                ),
            ),
        )


def test_manifest_rejects_duplicate_content_hashes_within_split():
    with pytest.raises(ValueError, match="duplicate content_hash"):
        DatasetManifest(
            dataset_id="confirmatory",
            split=DatasetSplit.CONFIRMATORY,
            records=(
                _record(
                    "conf-1",
                    split=DatasetSplit.CONFIRMATORY,
                    source_hash="a" * 64,
                    content_hash="1" * 64,
                ),
                _record(
                    "conf-2",
                    split=DatasetSplit.CONFIRMATORY,
                    source_hash="b" * 64,
                    content_hash="1" * 64,
                ),
            ),
        )


def test_manifest_rejects_duplicate_source_hashes_within_split():
    with pytest.raises(ValueError, match="duplicate source_hash"):
        DatasetManifest(
            dataset_id="confirmatory",
            split=DatasetSplit.CONFIRMATORY,
            records=(
                _record(
                    "conf-1",
                    split=DatasetSplit.CONFIRMATORY,
                    source_hash="a" * 64,
                    content_hash="1" * 64,
                ),
                _record(
                    "conf-2",
                    split=DatasetSplit.CONFIRMATORY,
                    source_hash="a" * 64,
                    content_hash="2" * 64,
                ),
            ),
        )


def test_source_family_is_case_normalized_before_isolation():
    development = DatasetManifest(
        dataset_id="development",
        split=DatasetSplit.DEVELOPMENT,
        records=(
            _record(
                "dev-1",
                split=DatasetSplit.DEVELOPMENT,
                source_family="Paper-A",
                source_hash="a" * 64,
                content_hash="1" * 64,
            ),
        ),
    )
    confirmatory = DatasetManifest(
        dataset_id="confirmatory",
        split=DatasetSplit.CONFIRMATORY,
        records=(
            _record(
                "conf-1",
                split=DatasetSplit.CONFIRMATORY,
                source_family="paper-a",
                source_hash="b" * 64,
                content_hash="2" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetLeakageError, match="source family overlap"):
        assert_confirmatory_isolation(development, confirmatory)


def test_source_family_is_unicode_normalized_before_isolation():
    development = DatasetManifest(
        dataset_id="development",
        split=DatasetSplit.DEVELOPMENT,
        records=(
            _record(
                "dev-1",
                split=DatasetSplit.DEVELOPMENT,
                source_family=" Café-Paper ",
                source_hash="a" * 64,
                content_hash="1" * 64,
            ),
        ),
    )
    confirmatory = DatasetManifest(
        dataset_id="confirmatory",
        split=DatasetSplit.CONFIRMATORY,
        records=(
            _record(
                "conf-1",
                split=DatasetSplit.CONFIRMATORY,
                source_family="cafe\u0301-paper",
                source_hash="b" * 64,
                content_hash="2" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetLeakageError, match="source family overlap"):
        assert_confirmatory_isolation(development, confirmatory)


def test_manifest_rejects_missing_hashes():
    with pytest.raises(ValueError, match="source_hash"):
        DatasetRecord(
            record_id="dev-1",
            split=DatasetSplit.DEVELOPMENT,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            source_family="paper-a",
            source_hash="",
            content_hash="b" * 64,
        )


def test_plumbing_split_requires_synthetic_non_evidence():
    with pytest.raises(ValueError, match="plumbing fixtures"):
        DatasetRecord(
            record_id="fixture-1",
            split=DatasetSplit.PLUMBING,
            origin=EvidenceOrigin.REAL_MODEL_EXECUTION,
            source_family="fixture",
            source_hash="a" * 64,
            content_hash="b" * 64,
        )


def test_confirmatory_split_rejects_synthetic_origin():
    with pytest.raises(ValueError, match="synthetic non-evidence"):
        DatasetRecord(
            record_id="fixture-1",
            split=DatasetSplit.CONFIRMATORY,
            origin=EvidenceOrigin.SYNTHETIC_NON_EVIDENCE,
            source_family="fixture",
            source_hash="a" * 64,
            content_hash="b" * 64,
        )
