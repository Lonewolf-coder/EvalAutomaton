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

import asyncio
import json
import logging
import uuid
from datetime import datetime
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
            webhook_config=manifest.webhook_config,
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

        # Step 5B: NLP pre-flight checks (gated internally on kore_api_client)
        await self._run_nlp_preflight(cbm, scorecard)

        # Step 6: Run Webhook Pipeline (Pipeline B) — all tasks
        logger.info("=== Pipeline B: Webhook Journey ===")
        eval_start_time = datetime.utcnow()
        if self.manifest.webhook_url or self.kore_bearer_token:
            task_sessions = await self._run_webhook_pipeline(context, scorecard)
        else:
            logger.info("No webhook URL or Kore credentials — skipping webhook pipeline.")
            task_sessions = {}
        eval_end_time = datetime.utcnow()

        # Step 7A: Persist session IDs + eval window for deferred analytics refresh.
        # Analytics are NOT fetched now — Kore.ai can take up to 10 hours to process data.
        # Use POST /api/v1/evaluations/{session_id}/refresh-analytics to fetch when ready.
        scorecard.task_sessions = {tid: list(v) for tid, v in task_sessions.items()}
        scorecard.eval_window = {
            "from": eval_start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "to": eval_end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        }
        scorecard.analytics_status = "pending"

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

    async def run_analytics_refresh(self, session_id: str) -> dict[str, Any]:
        """Fetch analytics for a completed evaluation session on demand.

        Safe to call multiple times at any interval. Each call overwrites the
        previous analytics_by_task data with the latest results from Kore.ai.

        Returns a summary dict indicating current analytics_status and
        analytics_last_checked_at so callers can decide whether to retry.
        """
        results_dir = self.persist_dir / "results"
        path = results_dir / f"scorecard_{session_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scorecard not found: {session_id}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        task_sessions_raw: dict[str, list[str]] = data.get("task_sessions", {})
        eval_window: dict[str, str] = data.get("eval_window", {})

        if not task_sessions_raw or not eval_window:
            return {
                "session_id": session_id,
                "analytics_status": "pending",
                "analytics_last_checked_at": None,
                "message": "No session data stored — was this evaluation run without webhook?",
            }

        if not self.kore_api_client:
            return {
                "session_id": session_id,
                "analytics_status": data.get("analytics_status", "pending"),
                "analytics_last_checked_at": data.get("analytics_last_checked_at"),
                "message": "No Kore.ai credentials configured — cannot fetch analytics.",
            }

        from_dt = datetime.strptime(eval_window["from"], "%Y-%m-%dT%H:%M:%S.000Z")
        to_dt = datetime.strptime(eval_window["to"], "%Y-%m-%dT%H:%M:%S.000Z")

        # Reconstruct task_sessions as dict[task_id -> (kore_sid, from_id)]
        task_sessions: dict[str, tuple[str, str]] = {
            tid: (v[0], v[1]) for tid, v in task_sessions_raw.items() if len(v) >= 2
        }

        # Rebuild a minimal scorecard shell to pass to the analytics pipeline
        scorecard = Scorecard(
            session_id=data["session_id"],
            candidate_id=data.get("candidate_id", ""),
            manifest_id=data.get("manifest_id", ""),
            assessment_name=data.get("assessment_name", ""),
            analytics_by_task=data.get("analytics_by_task", {}),
            task_sessions=task_sessions_raw,
            eval_window=eval_window,
        )
        # Restore existing task_scores so analytics CheckResults attach correctly
        for ts_data in data.get("task_scores", []):
            scorecard.task_scores.append(
                TaskScore(task_id=ts_data["task_id"], task_name=ts_data["task_name"])
            )

        await self._run_analytics_pipeline(task_sessions, from_dt, to_dt, scorecard)

        # Determine status from results
        total_tasks = len(task_sessions)
        tasks_with_data = sum(
            1
            for td in scorecard.analytics_by_task.values()
            if isinstance(td.get("analytics"), dict)
            and "error" not in td["analytics"]
            and any(
                (td["analytics"].get(t) or {}).get("logs")
                for t in ["successintent", "failintent", "unhandledutterance",
                          "tasksuccess", "taskfailure"]
            )
        )

        if tasks_with_data == 0:
            status = "pending"
        elif tasks_with_data < total_tasks:
            status = "partial"
        else:
            status = "available"

        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        scorecard.analytics_status = status
        scorecard.analytics_last_checked_at = now_iso

        # Merge analytics results back into the full saved scorecard and re-save
        data["analytics_by_task"] = scorecard.analytics_by_task
        data["analytics_status"] = status
        data["analytics_last_checked_at"] = now_iso
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(
            "Analytics refresh complete for session '%s': status=%s, tasks_with_data=%d/%d",
            session_id, status, tasks_with_data, total_tasks,
        )

        return {
            "session_id": session_id,
            "analytics_status": status,
            "analytics_last_checked_at": now_iso,
            "tasks_with_data": tasks_with_data,
            "total_tasks": total_tasks,
            "analytics_by_task": scorecard.analytics_by_task,
        }

    async def _run_webhook_pipeline(
        self, context: RuntimeContext, scorecard: Scorecard
    ) -> dict[str, tuple[str, str]]:
        """Execute the stateful webhook journey across all tasks.

        Returns a mapping of task_id -> (kore_session_id, from_id) for
        use in the analytics pipeline.
        """
        task_sessions: dict[str, tuple[str, str]] = {}

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
                kore_api=self.kore_api_client,
            )

            # Execute the pattern
            try:
                pattern_result = await executor.execute()
                kore_sid = getattr(self.webhook_client, "_kore_session_id", None)
                from_id = getattr(self.webhook_client, "_from_id", "")
                if kore_sid:
                    task_sessions[task.task_id] = (kore_sid, from_id)
            except Exception as e:
                logger.error("Pattern execution failed for task '%s': %s", task.task_id, e)
                # Create a synthetic failure result instead of silently skipping
                from ..patterns.base import PatternResult
                pattern_result = PatternResult(
                    task_id=task.task_id,
                    pattern=task.pattern.value,
                    success=False,
                    error=str(e),
                )
                pattern_result.checks.append(CheckResult(
                    check_id=f"webhook.{task.task_id}.execution",
                    task_id=task.task_id,
                    pipeline="webhook",
                    label="Pattern execution",
                    status=CheckStatus.FAIL,
                    details=f"Pattern execution error: {e}",
                    score=0.0,
                ))
                pattern_result.evidence_cards.append(EvidenceCard(
                    card_id=f"webhook.{task.task_id}.error",
                    task_id=task.task_id,
                    title=f"Webhook Error — {task.task_name}",
                    content=f"Pattern: {task.pattern.value}\nError: {e}",
                    color=EvidenceCardColor.RED,
                    pipeline="webhook",
                ))

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

            # State Inspector verification — only if webhook succeeded
            # (running after failure just adds confusing "Record not found" checks)
            if task.state_assertion and task.state_assertion.enabled:
                if pattern_result.success:
                    si_checks, si_cards = await self.state_inspector.verify_task(task, context)
                    if task_score:
                        task_score.webhook_checks.extend(si_checks)
                        task_score.evidence_cards.extend(si_cards)

            # State seeding check for CREATE tasks
            if task.pattern in (EnginePattern.CREATE, EnginePattern.CREATE_WITH_AMENDMENT):
                if not pattern_result.success and task.record_alias:
                    await self._attempt_state_seeding(task, context, scorecard)

        context.save(self.persist_dir / "runtime_contexts")
        return task_sessions

    async def _run_nlp_preflight(
        self, cbm: Any, scorecard: Scorecard
    ) -> None:
        """Run NLP intent pre-flight check via find_intent for each task.

        Non-fatal — never raises. Appends PASS/WARNING CheckResults to each
        task's cbm_checks with pipeline="cbm".
        """
        if not self.kore_api_client:
            return
        try:
            bot_name = getattr(cbm, "bot_name", "") or ""
            for task in self.manifest.tasks:
                utterance = task.conversation_starter or f"I want to {task.task_name.lower()}"
                try:
                    response = await self.kore_api_client.find_intent(utterance, bot_name)
                    if "error" in response:
                        logger.debug("NLP preflight find_intent error for task '%s': %s",
                                     task.task_id, response["error"])
                        continue
                    result_type = response.get("result", "")
                    matched_intent = (response.get("intent") or {}).get("name", "")
                    dialog_lower = task.dialog_name.lower()
                    intent_match = dialog_lower in matched_intent.lower()
                    task_score = next(
                        (ts for ts in scorecard.task_scores if ts.task_id == task.task_id),
                        None,
                    )
                    if not task_score:
                        continue
                    task_score.cbm_checks.append(CheckResult(
                        check_id=f"cbm.{task.task_id}.nlp_preflight",
                        task_id=task.task_id,
                        pipeline="cbm",
                        label="NLP pre-flight: intent detection",
                        status=(
                            CheckStatus.PASS
                            if result_type == "successintent" and intent_match
                            else CheckStatus.WARNING
                        ),
                        details=(
                            f"Utterance '{utterance}' matched intent '{matched_intent}' "
                            f"(result: {result_type})."
                        ),
                        score=1.0 if (result_type == "successintent" and intent_match) else 0.0,
                        weight=0.0,
                    ))
                except Exception as task_e:
                    logger.debug("NLP preflight error for task '%s': %s", task.task_id, task_e)
        except Exception as e:
            logger.warning("NLP preflight pipeline failed: %s", e)

    async def _run_analytics_pipeline(
        self,
        task_sessions: dict[str, tuple[str, str]],
        from_dt: datetime,
        to_dt: datetime,
        scorecard: Scorecard,
    ) -> None:
        """Fetch per-task analytics and messages concurrently, store in scorecard.

        Non-fatal — never raises. Appends INFO CheckResults to each task's
        webhook_checks with pipeline="analytics".
        """
        if not self.kore_api_client or not task_sessions:
            return
        try:
            # Launch all analytics and messages calls concurrently across all tasks
            analytics_coros = [
                self.kore_api_client.get_all_analytics_for_session(kore_sid, from_dt, to_dt)
                for _, (kore_sid, _) in task_sessions.items()
            ]
            messages_coros = [
                self.kore_api_client.get_messages_for_session(kore_sid, from_id)
                for _, (kore_sid, from_id) in task_sessions.items()
            ]
            task_ids = list(task_sessions.keys())
            all_results = await asyncio.gather(
                *analytics_coros, *messages_coros, return_exceptions=True
            )
            n = len(task_ids)
            analytics_results = all_results[:n]
            messages_results = all_results[n:]

            for i, task_id in enumerate(task_ids):
                analytics = (
                    {"error": str(analytics_results[i])}
                    if isinstance(analytics_results[i], Exception)
                    else analytics_results[i]
                )
                messages = (
                    {"error": str(messages_results[i])}
                    if isinstance(messages_results[i], Exception)
                    else messages_results[i]
                )
                scorecard.analytics_by_task[task_id] = {
                    "analytics": analytics,
                    "messages": messages,
                }

                task_score = next(
                    (ts for ts in scorecard.task_scores if ts.task_id == task_id),
                    None,
                )
                if not task_score:
                    continue

                # Summarise into a CheckResult
                success_count = 0
                fail_count = 0
                unhandled_count = 0
                if isinstance(analytics, dict) and "error" not in analytics:
                    success_count = len(
                        (analytics.get("successintent") or {}).get("logs", [])
                    )
                    fail_count = len(
                        (analytics.get("failintent") or {}).get("logs", [])
                    )
                    unhandled_count = len(
                        (analytics.get("unhandledutterance") or {}).get("logs", [])
                    )

                task_score.webhook_checks.append(CheckResult(
                    check_id=f"analytics.{task_id}.summary",
                    task_id=task_id,
                    pipeline="analytics",
                    label="Analytics pipeline summary",
                    status=CheckStatus.INFO,
                    details=(
                        f"success={success_count}, fail={fail_count}, "
                        f"unhandled={unhandled_count}"
                    ),
                    score=0.0,
                    weight=0.0,
                ))
        except Exception as e:
            logger.warning("Analytics pipeline failed: %s", e)

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
