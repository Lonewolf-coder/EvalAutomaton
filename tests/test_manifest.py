"""Tests for manifest schema and defect detection rules."""

import json
from pathlib import Path

import pytest

from governiq.core.manifest import EnginePattern, Manifest
from governiq.core.manifest_validator import Severity, validate_manifest


MANIFEST_DIR = Path(__file__).parent.parent / "manifests"


class TestManifestSchema:
    """Test manifest loading and validation."""

    def test_load_medical_manifest(self):
        path = MANIFEST_DIR / "medical_appointment_basic.json"
        with path.open("r") as f:
            data = json.load(f)
        manifest = Manifest(**data)
        assert manifest.manifest_id == "medical-appointment-basic-v1"
        assert manifest.assessment_type == "medical"
        assert len(manifest.tasks) == 7

    def test_load_travel_manifest(self):
        path = MANIFEST_DIR / "travel_agent_basic.json"
        with path.open("r") as f:
            data = json.load(f)
        manifest = Manifest(**data)
        assert manifest.manifest_id == "travel-agent-basic-v1"
        assert manifest.assessment_type == "travel"

    def test_get_task_by_id(self):
        path = MANIFEST_DIR / "medical_appointment_basic.json"
        with path.open("r") as f:
            data = json.load(f)
        manifest = Manifest(**data)
        task = manifest.get_task("task2_booking1")
        assert task is not None
        assert task.pattern == EnginePattern.CREATE

    def test_get_tasks_by_pattern(self):
        path = MANIFEST_DIR / "medical_appointment_basic.json"
        with path.open("r") as f:
            data = json.load(f)
        manifest = Manifest(**data)
        create_tasks = manifest.get_tasks_by_pattern(EnginePattern.CREATE)
        assert len(create_tasks) == 2  # task1 + task2_booking1


class TestManifestDefectDetection:
    """Test MD-01 through MD-12 rules."""

    def test_valid_manifest_passes(self):
        path = MANIFEST_DIR / "medical_appointment_basic.json"
        with path.open("r") as f:
            data = json.load(f)
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        assert result.valid is True

    def test_md01_exact_dialog_name_warning(self):
        """MD-01: Warn on exact dialog name policy."""
        data = _minimal_manifest_dict()
        data["tasks"][0]["dialog_name_policy"] = "exact"
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        md01 = [d for d in result.defects if d.rule_id == "MD-01"]
        assert len(md01) == 1
        assert md01[0].severity == Severity.WARNING

    def test_md03_amendment_without_pattern(self):
        """MD-03: Error if CREATE_WITH_AMENDMENT has no amendment_config."""
        data = _minimal_manifest_dict()
        data["tasks"][0]["pattern"] = "CREATE_WITH_AMENDMENT"
        # No amendment_config
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        md03 = [d for d in result.defects if d.rule_id == "MD-03"]
        assert len(md03) == 1
        assert md03[0].severity == Severity.ERROR

    def test_md10_duplicate_task_ids(self):
        """MD-10: Error on duplicate task IDs."""
        data = _minimal_manifest_dict()
        data["tasks"].append(data["tasks"][0].copy())
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        md10 = [d for d in result.defects if d.rule_id == "MD-10"]
        assert len(md10) == 1

    def test_md11_scoring_weights_warning(self):
        """MD-11: Warn if scoring weights don't sum to 1.0."""
        data = _minimal_manifest_dict()
        data["scoring_config"] = {
            "cbm_structural_weight": 0.50,
            "webhook_functional_weight": 0.50,
            "compliance_weight": 0.10,
            "faq_weight": 0.10,
        }
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        md11 = [d for d in result.defects if d.rule_id == "MD-11"]
        assert len(md11) == 1

    def test_md12_edge_case_no_negative_tests(self):
        """MD-12: Error if EDGE_CASE has no negative tests."""
        data = _minimal_manifest_dict()
        data["tasks"][0]["pattern"] = "EDGE_CASE"
        data["tasks"][0]["required_entities"] = []
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
        md12 = [d for d in result.defects if d.rule_id == "MD-12"]
        assert len(md12) == 1


def _minimal_manifest_dict(**overrides) -> dict:
    return {
        "manifest_id": "test-manifest",
        "assessment_name": "Test",
        "assessment_type": "test",
        "tasks": [
            {
                "task_id": "task1",
                "task_name": "Test Task",
                "pattern": "CREATE",
                "dialog_name": "Test Dialog",
                "required_entities": [
                    {
                        "entity_key": "testEntity",
                        "semantic_hint": "test",
                        "value_pool": ["val1", "val2"],
                    }
                ],
            }
        ],
        **overrides,
    }


def _minimal_manifest(**overrides) -> Manifest:
    return Manifest(**_minimal_manifest_dict(**overrides))
