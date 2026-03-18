"""Tests for the plagiarism fingerprint and detection modules."""

import copy
import importlib
import json
from pathlib import Path

import pytest

from governiq.plagiarism.fingerprint import (
    compute_fingerprint,
    normalize_dialog_name,
    extract_service_urls,
    extract_entity_keys,
)
from governiq.plagiarism.detector import (
    PlagiarismRisk,
    PlagiarismReport,
    detect,
)

SAMPLE_EXPORT = Path(__file__).parent / "sample_bot_export.json"


@pytest.fixture
def sample_export():
    with SAMPLE_EXPORT.open() as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------

class TestFingerprint:

    def test_fingerprint_is_deterministic(self, sample_export):
        fp1 = compute_fingerprint(sample_export)
        fp2 = compute_fingerprint(sample_export)
        assert fp1 == fp2

    def test_fingerprint_is_sha256_hex(self, sample_export):
        fp = compute_fingerprint(sample_export)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_identical_bots_same_fingerprint(self, sample_export):
        clone = copy.deepcopy(sample_export)
        assert compute_fingerprint(sample_export) == compute_fingerprint(clone)

    def test_different_dialog_name_different_fingerprint(self, sample_export):
        modified = copy.deepcopy(sample_export)
        # Change dialog name — fingerprint must change
        modified["dialogs"][0]["localeData"]["en"]["name"] = "Completely Different Name"
        assert compute_fingerprint(sample_export) != compute_fingerprint(modified)

    def test_different_node_types_different_fingerprint(self, sample_export):
        modified = copy.deepcopy(sample_export)
        # Add a node with a different type to first dialog
        modified["dialogs"][0]["nodes"].append({"type": "extranode", "componentId": "x"})
        assert compute_fingerprint(sample_export) != compute_fingerprint(modified)

    def test_empty_export_does_not_crash(self):
        fp = compute_fingerprint({})
        assert len(fp) == 64  # still returns valid SHA-256

    def test_normalize_dialog_name_strips_trailing_digits(self):
        assert normalize_dialog_name("Book a Flight 0001") == "book a flight"
        assert normalize_dialog_name("  Cancel  ") == "cancel"
        assert normalize_dialog_name("Welcome") == "welcome"

    def test_extract_service_urls_from_sample(self, sample_export):
        urls = extract_service_urls(sample_export)
        assert len(urls) > 0
        # All from mockapi.io
        assert all("mockapi.io" in u for u in urls)

    def test_extract_entity_keys_from_sample(self, sample_export):
        keys = extract_entity_keys(sample_export)
        assert len(keys) > 0
        assert "contactnumber" in keys or "contactNumber".lower() in keys

    def test_fingerprint_module_does_not_import_cbm(self):
        """Architectural constraint: fingerprint module must be CBM-independent."""
        import governiq.plagiarism.fingerprint as fp_mod
        # Check via module namespace — CBM types must not be present
        for cbm_symbol in ("CBMObject", "CBMDialog", "CBMNode", "parse_bot_export"):
            assert cbm_symbol not in fp_mod.__dict__, (
                f"fingerprint.py imported '{cbm_symbol}' — breaks CBM independence"
            )


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------

class TestDetector:

    def test_first_submission_is_none_risk(self, sample_export, tmp_path):
        report = detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        assert report.risk_level == PlagiarismRisk.NONE
        assert report.matching_submission_ids == []

    def test_identical_submission_high_risk(self, sample_export, tmp_path):
        # First submission
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        # Identical bot submitted by a different candidate
        report = detect(sample_export, "medical", "sub_002", data_dir=str(tmp_path))
        assert report.risk_level == PlagiarismRisk.HIGH

    def test_matching_submission_ids_populated(self, sample_export, tmp_path):
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        report = detect(sample_export, "medical", "sub_002", data_dir=str(tmp_path))
        assert "sub_001" in report.matching_submission_ids

    def test_same_submission_id_not_flagged(self, sample_export, tmp_path):
        """Re-running same submission_id should not self-flag."""
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        report = detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        # sub_001 may be in store but shouldn't flag itself
        assert "sub_001" not in report.matching_submission_ids

    def test_saves_fingerprint_on_detect(self, sample_export, tmp_path):
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        store_path = tmp_path / "fingerprints" / "medical.json"
        assert store_path.exists()
        with store_path.open() as f:
            store = json.load(f)
        assert "sub_001" in store
        assert "fingerprint" in store["sub_001"]

    def test_different_assessment_types_isolated(self, sample_export, tmp_path):
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        # Same bot in a different assessment type — should NOT flag
        report = detect(sample_export, "travel", "sub_002", data_dir=str(tmp_path))
        assert report.risk_level == PlagiarismRisk.NONE

    def test_report_has_fingerprint(self, sample_export, tmp_path):
        report = detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        assert len(report.current_fingerprint) == 64

    def test_different_bot_structure_is_none_risk(self, sample_export, tmp_path):
        detect(sample_export, "medical", "sub_001", data_dir=str(tmp_path))
        # Significantly different bot
        different = {"dialogs": [{"localeData": {"en": {"name": "UniqueDialog"}}, "nodes": []}], "dialogComponents": []}
        report = detect(different, "medical", "sub_002", data_dir=str(tmp_path))
        assert report.risk_level == PlagiarismRisk.NONE
