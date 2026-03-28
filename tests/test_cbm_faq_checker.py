import pytest
from unittest.mock import MagicMock
from governiq.core.cbm_checker import check_faq_cbm_coverage
from governiq.core.manifest import FAQTask


def make_faq_task(task_id="FAQ-HOURS", question="What are your opening hours?"):
    return FAQTask(
        task_id=task_id,
        question=question,
        expected_answer="Open 9 AM to 5 PM.",
        similarity_threshold=0.80,
    )


class TestFAQCBMCoverage:
    def test_pass_when_faq_node_found_with_alternatives(self):
        faq_tasks = [make_faq_task()]
        cbm_faqs = [{
            "question": "What are your opening hours?",
            "alternatives": ["When are you open?", "What time do you open?"],
            "answer": "We are open Monday to Saturday, 9 AM to 5 PM.",
        }]
        result = check_faq_cbm_coverage(faq_tasks, cbm_faqs, min_alternatives=2)
        assert result == []  # no defects

    def test_warn_when_no_matching_faq_node(self):
        faq_tasks = [make_faq_task()]
        cbm_faqs = []  # bot has no FAQ configured at all
        result = check_faq_cbm_coverage(faq_tasks, cbm_faqs, min_alternatives=2)
        assert len(result) == 1
        assert result[0]["task_id"] == "FAQ-HOURS"
        assert "not found" in result[0]["message"].lower()

    def test_warn_when_insufficient_alternatives(self):
        faq_tasks = [make_faq_task()]
        cbm_faqs = [{
            "question": "What are your opening hours?",
            "alternatives": ["When are you open?"],  # only 1, need 2
            "answer": "Open 9 AM to 5 PM.",
        }]
        result = check_faq_cbm_coverage(faq_tasks, cbm_faqs, min_alternatives=2)
        assert len(result) == 1
        assert "alternative" in result[0]["message"].lower()

    def test_warn_when_answer_empty(self):
        faq_tasks = [make_faq_task()]
        cbm_faqs = [{
            "question": "What are your opening hours?",
            "alternatives": ["When are you open?", "Are you open weekends?"],
            "answer": "",  # empty answer
        }]
        result = check_faq_cbm_coverage(faq_tasks, cbm_faqs, min_alternatives=2)
        assert len(result) == 1
        assert "answer" in result[0]["message"].lower()
