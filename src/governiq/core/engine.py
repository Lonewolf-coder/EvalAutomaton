"""Evaluation Engine — Orchestrates the full dual-pipeline evaluation.

The engine is the central orchestrator. It:
1. Validates the manifest (pre-flight MD rules)
2. Parses the CBM export (Pipeline A)
3. Runs CBM structural evaluation per task
4. Runs compliance checks
5. Runs webhook journey per task using engine patterns (Pipeline B)
6. Runs State Inspector verifications
7. Handles state seeding if needed
8. Merges results via the Scoring Engine
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from .manifest import EnginePattern, Manifest
from .manifest_validator import ValidationResult, validate_manifest
from .runtime_context import RuntimeContext, TaskRecord
from .scoring import (
    CheckResult,
    CheckStatus,
    ComplianceResult,
    EvidenceCard,
    EvidenceCardColor,
    Scorecard,
    TaskScore,
)
from ..cbm.evaluator import (
    evaluate_compliance,
    evaluate_faqs_structural,
    evaluate_task_cbm,
)
from ..cbm.parser import CBMObject, parse_bot_export, parse_bot_export_file
from ..patterns import get_pattern_executor
from ..webhook.driver import KoreWebhookClient, LLMConversationDriver
from ..webhook.jwt_auth import KoreCredentials
from ..webhook.kore_api import KoreAPIClient
from ..webhook.state_inspector import StateInspector

logger = logging.getLogger(__name__)


class EvaluationEngine:
    """The GovernIQ Universal Evaluation Engine.

    Domain-agnostic. Knows six patterns. Manifest tells it everything else.
    Webhook is the authority for pass/fail. CBM is informational only.
    """

    def __init__(
        self,
        manifest: Manifest,
        llm_api_key: str = "",
        llm_model: str = "claude-haiku-4-5-20251001",
        llm_base_url: str = "https://api.anthropic.com/v1",
        llm_api_format: str = "anthropic",
        persist_dir: str = "./data",
        kore_bearer_token: str = "",
        kore_credentials: KoreCredentials | None = None,
    ):
        self.manifest = manifest
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.kore_bearer_token = kore_bearer_token
        self.kore_credentials = kore_credentials

        self.driver = LLMConversationDriver(
            api_key=llm_api_key,
            model=llm_model,
            base_url=llm_base_url,
            api_format=llm_api_format,
        )
        self.webhook_client = KoreWebhookClient(
            webhook_url=manifest.webhook_url,
            bearer_token=kore_bearer_token,
            kore_credentials=kore_credentials,
        )
        self.state_inspector = StateInspector()
        self.kore_api_client: KoreAPIClient | None = None
        if kore_credentials and kore_bearer_token:
            self.kore_api_client = KoreAPIClient(kore_credentials)

    async def run_full_evaluation(
        self,
        bot_export: dict[str, Any] | str | Path,
        candidate_id: str = "",
    ) -> Scorecard:
        """Run the complete dual-pipeline evaluation.

        Args:
            bot_export: Bot export JSON data, or path to the JSON file.
            candidate_id: Candidate identifier.

        Returns:
            Complete Scorecard with all results.
        """
        session_id = str(uuid.uuid4())[:8]

        # Step 0: Validate manifest (pre-flight)
        validation = validate_manifest(self.manifest)
        if not validation.valid:
            error_msgs = [f"[{d.rule_id}] {d.message}" for d in validation.errors]
            raise ValueError(
                f"Manifest validation failed with {len(validation.errors)} error(s):\n"
                + "\n".join(error_msgs)
            )
        if validation.warnings:
            for w in validation.warnings:
                logger.warning("Manifest warning [%s]: %s", w.rule_id, w.message)

        # Step 1: Parse CBM export
        if isinstance(bot_export, (str, Path)):
            cbm = parse_bot_export_file(bot_export)
        else:
            cbm = parse_bot_export(bot_export)

        # Step 2: Initialize RuntimeContext
        context = RuntimeContext(
            session_id=session_id,
            candidate_id=candidate_id,
            manifest_id=self.manifest.manifest_id,
        )

        # Step 3: Run CBM Pipeline (Pipeline A) — all tasks
        scorecard = Scorecard(
            session_id=session_id,
            candidate_id=candidate_id,
            manifest_id=self.manifest.manifest_id,
            assessment_name=self.manifest.assessment_name,
        )

        logger.info("=== Pipeline A: CBM Structural Evaluation ===")
        for task in self.manifest.tasks:
            task_score = evaluate_task_cbm(cbm, task)
            scorecard.task_scores.append(task_score)

        # Step 4: Compliance checks
        logger.info("=== Compliance Checks ===")
        scorecard.compliance_results = evaluate_compliance(cbm, self.manifest.compliance_checks)

        # Step 5: FAQ structural checks
        logger.info("=== FAQ Structural Checks ===")
        faq_checks, faq_cards = evaluate_faqs_structural(cbm, self.manifest)
        if faq_checks:
            faq_task_score = TaskScore(task_id="faq", task_name="FAQs")
            faq_task_score.cbm_checks = faq_checks
            faq_task_score.evidence_cards = faq_cards
            scorecard.task_scores.append(faq_task_score)
            # Compute faq_score from the FAQ check results
            scored = [c for c in faq_checks if c.status != CheckStatus.UNTESTABLE]
            if scored:
                total_w = sum(c.weight for c in scored)
                scorecard.faq_score = sum(c.score * c.weight for c in scored) / total_w if total_w else 0.0

        # Step 6: Run Webhook Pipeline (Pipeline B) — all tasks
        logger.info("=== Pipeline B: Webhook Journey ===")
        if self.manifest.webhook_url or self.kore_bearer_token:
            await self._run_webhook_pipeline(context, scorecard)
        else:
            logger.info("No webhook URL or Kore credentials — skipping webhook pipeline.")

        # Step 7: Fetch Kore.ai public API insights
        if self.kore_api_client:
            logger.info("=== Kore.ai Public API Insights ===")
            try:
                insights = await self.kore_api_client.get_all_insights()
                scorecard.kore_api_insights = insights
                logger.info("Kore.ai API insights captured: %s", list(insights.keys()))
            except Exception as e:
                logger.warning("Failed to fetch Kore.ai API insights: %s", e)
                scorecard.kore_api_insights = {"error": str(e)}

        # Step 8: Persist context and results
        context.save(self.persist_dir / "runtime_contexts")
        self._save_scorecard(scorecard)

        # Cleanup
        await self.driver.close()
        await self.webhook_client.close()
        await self.state_inspector.close()

        return scorecard

    async def run_cbm_only(
        self,
        bot_export: dict[str, Any] | str | Path,
        candidate_id: str = "",
    ) -> Scorecard:
        """Run CBM pipeline only (Phase 1 — no webhook needed)."""
        session_id = str(uuid.uuid4())[:8]

        validation = validate_manifest(self.manifest)
        if not validation.valid:
            error_msgs = [f"[{d.rule_id}] {d.message}" for d in validation.errors]
            raise ValueError(
                f"Manifest validation failed:\n" + "\n".join(error_msgs)
            )

        if isinstance(bot_export, (str, Path)):
            cbm = parse_bot_export_file(bot_export)
        else:
            cbm = parse_bot_export(bot_export)

        scorecard = Scorecard(
            session_id=session_id,
            candidate_id=candidate_id,
            manifest_id=self.manifest.manifest_id,
            assessment_name=self.manifest.assessment_name,
        )

        for task in self.manifest.tasks:
            task_score = evaluate_task_cbm(cbm, task)
            scorecard.task_scores.append(task_score)

        scorecard.compliance_results = evaluate_compliance(cbm, self.manifest.compliance_checks)

        faq_checks, faq_cards = evaluate_faqs_structural(cbm, self.manifest)
        if faq_checks:
            faq_task_score = TaskScore(task_id="faq", task_name="FAQs")
            faq_task_score.cbm_checks = faq_checks
            faq_task_score.evidence_cards = faq_cards
            scorecard.task_scores.append(faq_task_score)
            scored = [c for c in faq_checks if c.status != CheckStatus.UNTESTABLE]
            if scored:
                total_w = sum(c.weight for c in scored)
                scorecard.faq_score = sum(c.score * c.weight for c in scored) / total_w if total_w else 0.0

        self._save_scorecard(scorecard)
        return scorecard

    async def _run_webhook_pipeline(
        self, context: RuntimeContext, scorecard: Scorecard
    ) -> None:
        """Execute the stateful webhook journey across all tasks."""
        for task in self.manifest.tasks:
            logger.info("Webhook: executing task '%s' (pattern: %s)",
                        task.task_id, task.pattern.value)

            # Get the pattern executor
            pattern_cls = get_pattern_executor(task.pattern)
            executor = pattern_cls(
                task=task,
                context=context,
                webhook=self.webhook_client,
                driver=self.driver,
            )

            # Execute the pattern
            try:
                pattern_result = await executor.execute()
            except Exception as e:
                logger.error("Pattern execution failed for task '%s': %s", task.task_id, e)
                continue

            # Find the matching task score and add webhook results
            task_score = next(
                (ts for ts in scorecard.task_scores if ts.task_id == task.task_id),
                None,
            )
            if task_score:
                task_score.webhook_checks.extend(pattern_result.checks)
                task_score.evidence_cards.extend(pattern_result.evidence_cards)
            else:
                new_ts = TaskScore(
                    task_id=task.task_id,
                    task_name=task.task_name,
                    webhook_checks=pattern_result.checks,
                    evidence_cards=pattern_result.evidence_cards,
                )
                scorecard.task_scores.append(new_ts)

            # State Inspector verification
            if task.state_assertion and task.state_assertion.enabled:
                si_checks, si_cards = await self.state_inspector.verify_task(task, context)
                if task_score:
                    task_score.webhook_checks.extend(si_checks)
                    task_score.evidence_cards.extend(si_cards)

            # State seeding check for CREATE tasks
            if task.pattern in (EnginePattern.CREATE, EnginePattern.CREATE_WITH_AMENDMENT):
                if not pattern_result.success and task.record_alias:
                    await self._attempt_state_seeding(task, context, scorecard)

        context.save(self.persist_dir / "runtime_contexts")

    async def _attempt_state_seeding(
        self, task, context: RuntimeContext, scorecard: Scorecard
    ) -> None:
        """Attempt state seeding when a CREATE task fails."""
        if not self.manifest.state_seeding_config.enabled:
            return

        seed_endpoint = self.manifest.state_seeding_config.seed_endpoint
        if not seed_endpoint:
            seed_endpoint = self.manifest.mock_api_base_url

        if not seed_endpoint:
            return

        # Build synthetic record from manifest entity definitions
        synthetic_fields: dict[str, str] = {}
        for entity in task.required_entities:
            value = context.select_value(task.task_id, entity.entity_key, entity.value_pool)
            synthetic_fields[entity.entity_key] = value

        success = await self.state_inspector.seed_state(seed_endpoint, synthetic_fields)
        if success:
            record = TaskRecord(
                record_alias=task.record_alias or task.task_id,
                task_id=task.task_id,
                fields=synthetic_fields,
                seeded=True,
            )
            context.cache_record(record)
            scorecard.state_seeded = True
            scorecard.state_seed_tasks.append(task.task_id)
            logger.warning("State seeded for task '%s' — data not created through conversation.", task.task_id)

    def _save_scorecard(self, scorecard: Scorecard) -> None:
        """Persist scorecard to disk."""
        results_dir = self.persist_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / f"scorecard_{scorecard.session_id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(scorecard.to_dict(), f, indent=2)
        logger.info("Scorecard saved to %s", path)
