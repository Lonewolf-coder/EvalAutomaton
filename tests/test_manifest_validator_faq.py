import json
from pathlib import Path
import pytest
from governiq.core.manifest import FAQTask, Manifest
from governiq.core.manifest_validator import Severity, validate_manifest

_MANIFEST_PATH = Path(__file__).parent.parent / "manifests" / "medical_appointment_basic.json"


def _manifest_with_faq_tasks(extra_tasks=None):
    """Load manifest and inject faq_tasks."""
    data = json.loads(_MANIFEST_PATH.read_text())
    data["faq_tasks"] = extra_tasks or [
        {
            "task_id": "FAQ-HOURS",
            "question": "What are your hours?",
            "expected_answer": "9 AM to 5 PM.",
            "similarity_threshold": 0.80,
        }
    ]
    return Manifest(**data)


class TestMD13:
    def test_valid_faq_task_no_defect(self):
        m = _manifest_with_faq_tasks()
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert md13 == []

    def test_empty_expected_answer_raises_error(self):
        m = _manifest_with_faq_tasks([
            {
                "task_id": "FAQ-HOURS",
                "question": "What are your hours?",
                "expected_answer": "",
                "similarity_threshold": 0.80,
            }
        ])
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert len(md13) == 1
        assert md13[0].severity == Severity.ERROR
        assert md13[0].task_id == "FAQ-HOURS"

    def test_empty_question_raises_error(self):
        m = _manifest_with_faq_tasks([
            {
                "task_id": "FAQ-X",
                "question": "",
                "expected_answer": "valid answer",
                "similarity_threshold": 0.80,
            }
        ])
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert len(md13) == 1
        assert md13[0].task_id == "FAQ-X"

    def test_no_faq_tasks_no_defect(self):
        data = json.loads(_MANIFEST_PATH.read_text())
        m = Manifest(**data)
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert md13 == []

    def test_whitespace_only_treated_as_empty(self):
        m = _manifest_with_faq_tasks([
            {
                "task_id": "FAQ-WS",
                "question": "   ",
                "expected_answer": "valid",
                "similarity_threshold": 0.80,
            }
        ])
        result = validate_manifest(m)
        md13 = [d for d in result.defects if d.rule_id == "MD-13"]
        assert len(md13) == 1
