"""Tests for CBM Evaluator — structural evaluation against manifest."""

import json
from pathlib import Path

import pytest

from governiq.cbm.evaluator import evaluate_compliance, evaluate_task_cbm, evaluate_faqs_structural
from governiq.cbm.parser import parse_bot_export
from governiq.core.manifest import Manifest
from governiq.core.scoring import CheckStatus


SAMPLE_EXPORT = Path(__file__).parent / "sample_bot_export.json"
MANIFEST_PATH = Path(__file__).parent.parent / "manifests" / "medical_appointment_basic.json"


@pytest.fixture
def cbm():
    with SAMPLE_EXPORT.open("r") as f:
        data = json.load(f)
    return parse_bot_export(data)


@pytest.fixture
def manifest():
    with MANIFEST_PATH.open("r") as f:
        data = json.load(f)
    return Manifest(**data)


class TestCBMEvaluator:

    def test_welcome_task_passes(self, cbm, manifest):
        task = manifest.get_task("task1")
        result = evaluate_task_cbm(cbm, task)
        assert result.task_id == "task1"
        # Dialog should be found
        dialog_check = next(c for c in result.cbm_checks if "dialog" in c.check_id.lower())
        assert dialog_check.status == CheckStatus.PASS

    def test_booking_task_has_agent_node(self, cbm, manifest):
        task = manifest.get_task("task2_booking1")
        result = evaluate_task_cbm(cbm, task)
        agent_check = [c for c in result.cbm_checks if "agent" in c.label.lower()]
        # Agent node should exist
        assert any(c.status == CheckStatus.PASS for c in agent_check)

    def test_booking_task_has_post_service(self, cbm, manifest):
        task = manifest.get_task("task2_booking1")
        result = evaluate_task_cbm(cbm, task)
        post_check = [c for c in result.cbm_checks if "post" in c.check_id.lower()]
        assert any(c.status == CheckStatus.PASS for c in post_check)

    def test_booking_task_has_entities(self, cbm, manifest):
        task = manifest.get_task("task2_booking1")
        result = evaluate_task_cbm(cbm, task)
        entity_checks = [c for c in result.cbm_checks if "entity" in c.check_id.lower()]
        passed = sum(1 for c in entity_checks if c.status == CheckStatus.PASS)
        assert passed >= 5  # Most entities should be found

    def test_retrieve_task_has_get_service(self, cbm, manifest):
        task = manifest.get_task("task3_retrieve")
        result = evaluate_task_cbm(cbm, task)
        get_check = [c for c in result.cbm_checks if "get" in c.check_id.lower()]
        assert any(c.status == CheckStatus.PASS for c in get_check)

    def test_modify_task_has_put_service(self, cbm, manifest):
        task = manifest.get_task("task4_modify")
        result = evaluate_task_cbm(cbm, task)
        put_check = [c for c in result.cbm_checks if "put" in c.check_id.lower()]
        assert any(c.status == CheckStatus.PASS for c in put_check)

    def test_cancel_task_has_delete_service(self, cbm, manifest):
        task = manifest.get_task("task4_cancel")
        result = evaluate_task_cbm(cbm, task)
        delete_check = [c for c in result.cbm_checks if "delete" in c.check_id.lower()]
        assert any(c.status == CheckStatus.PASS for c in delete_check)

    def test_evidence_cards_generated(self, cbm, manifest):
        task = manifest.get_task("task2_booking1")
        result = evaluate_task_cbm(cbm, task)
        assert len(result.evidence_cards) > 0
        ref_panel = [c for c in result.evidence_cards if "reference panel" in c.title.lower()]
        assert len(ref_panel) == 1

    def test_compliance_dialoggpt_passes(self, cbm, manifest):
        results = evaluate_compliance(cbm, manifest.compliance_checks)
        dialoggpt_result = next(r for r in results if r.check_id == "compliance_dialoggpt")
        assert dialoggpt_result.status == CheckStatus.PASS

    def test_faq_structural_check(self, cbm, manifest):
        checks, cards = evaluate_faqs_structural(cbm, manifest)
        assert len(checks) > 0
        # All 3 required FAQs should be found
        passed = sum(1 for c in checks if c.status == CheckStatus.PASS)
        assert passed >= 3
