import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from governiq.webhook.faq_evaluator import FAQEvaluator, FAQEvalResult
from governiq.core.manifest import FAQTask


def make_faq_task(threshold=0.75):
    return FAQTask(
        task_id="FAQ-HOURS",
        question="What are your opening hours?",
        expected_answer="The service is open from 9 AM to 5 PM, Monday to Saturday.",
        similarity_threshold=threshold,
    )


class TestFAQEvalResult:
    def test_pass_when_similarity_above_threshold(self):
        result = FAQEvalResult(
            task_id="FAQ-HOURS",
            similarity=0.82,
            threshold=0.75,
            bot_response="Open 9 to 5, Monday through Saturday.",
            expected_answer="The service is open from 9 AM to 5 PM.",
        )
        assert result.passed is True

    def test_fail_when_similarity_below_threshold(self):
        result = FAQEvalResult(
            task_id="FAQ-HOURS",
            similarity=0.45,
            threshold=0.80,
            bot_response="Please contact our front desk.",
            expected_answer="The service is open from 9 AM to 5 PM.",
        )
        assert result.passed is False


class TestFAQEvaluatorSimilarity:
    """Unit tests for semantic similarity — no network calls."""

    def test_compute_similarity_identical_strings(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "The service is open from 9 AM to 5 PM.",
            "The service is open from 9 AM to 5 PM.",
        )
        assert sim > 0.99

    def test_compute_similarity_paraphrase(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "We are open Monday to Saturday, 9 AM to 5 PM.",
            "The service is open from 9 AM to 5 PM, Monday to Saturday.",
        )
        assert sim > 0.75

    def test_compute_similarity_unrelated(self):
        evaluator = FAQEvaluator.__new__(FAQEvaluator)
        from sentence_transformers import SentenceTransformer
        evaluator._model = SentenceTransformer("paraphrase-multilingual-mpnet-base-v2")
        sim = evaluator._compute_similarity(
            "Please contact our front desk.",
            "The service is open from 9 AM to 5 PM, Monday to Saturday.",
        )
        assert sim < 0.50


class TestFAQEvaluatorWebhook:
    """Integration tests — mock the webhook client."""

    @pytest.mark.asyncio
    async def test_evaluate_single_faq_pass(self):
        task = make_faq_task(threshold=0.70)
        mock_driver = AsyncMock()
        mock_driver.run_faq_turn = AsyncMock(
            return_value="We are open Monday to Saturday from 9 AM to 5 PM."
        )
        evaluator = FAQEvaluator(webhook_driver=mock_driver, submission_id="SUB-001")
        with patch.object(evaluator, "_compute_similarity", return_value=0.85):
            result = await evaluator.evaluate_task(task)
        assert result.passed is True
        assert result.similarity == 0.85

    @pytest.mark.asyncio
    async def test_evaluate_single_faq_fail_generic_deflection(self):
        task = make_faq_task(threshold=0.70)
        mock_driver = AsyncMock()
        mock_driver.run_faq_turn = AsyncMock(
            return_value="Please contact our front desk for that information."
        )
        evaluator = FAQEvaluator(webhook_driver=mock_driver, submission_id="SUB-001")
        with patch.object(evaluator, "_compute_similarity", return_value=0.22):
            result = await evaluator.evaluate_task(task)
        assert result.passed is False
        assert result.similarity == 0.22
