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
import httpx
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .eval_logger import EvalLogger
from .exceptions import EvaluationHaltedError
from .gate0 import Gate0Checker, Gate0CheckStatus, Gate0Result
from .manifest import EnginePattern, Manifest, UIPolicy
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
from .cbm_checker import check_faq_cbm_coverage
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
        eval_logger: EvalLogger | None = None,
    ):
        self.manifest = manifest
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.kore_bearer_token = kore_bearer_token
        self.kore_credentials = kore_credentials
        self._eval_logger = eval_logger

        self.driver = LLMConversationDriver(
            api_key=llm_api_key,
            model=llm_model,
            base_url=llm_base_url,
            api_format=llm_api_format,
            eval_logger=eval_logger,
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
        self.gate0_result: Gate0Result | None = None

    async def run_gate0(self) -> Gate0Result:
        """Run Gate 0 connectivity checks. Must be called before run_full_evaluation().

        Raises ValueError with actionable messages if any check fails.
        Stores result in self.gate0_result for downstream use (e.g. web channel skipping).
        """
        checker = Gate0Checker(
            webhook_url=self.manifest.webhook_url,
            bot_id=getattr(self.kore_credentials, "bot_id", ""),
            backend_api_url=self.manifest.mock_api_base_url,
            kore_api_client=self.kore_api_client,
        )
        result = await checker.run()
        self.gate0_result = result

        if not result.can_proceed:
            failed = [
                f"[{check}] {msg}"
                for check, status in result.checks.items()
                if status == Gate0CheckStatus.FAIL
                for msg in [result.messages.get(check, "")]
            ]
            raise ValueError(
                "Gate 0 failed — evaluation cannot start:\n" + "\n".join(failed)
            )
        return result

    async def run_full_evaluation(
        self,
        bot_export: dict[str, Any] | str | Path,
        candidate_id: str = "",
        session_id: str | None = None,
    ) -> Scorecard:
        """Run the complete dual-pipeline evaluation.

        Args:
            bot_export: Bot export JSON data, or path to the JSON file.
            candidate_id: Candidate identifier.
            session_id: Caller-supplied session ID (full UUID from the outer handler).
                If not provided, a new UUID is generated — this should only happen
                in tests; production callers must always supply the ID so that the
                scorecard, log, and RuntimeContext files all share the same name.

        Returns:
            Complete Scorecard with all results.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

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
            # Copy tooltips so the report can render the CBM Map legend without
            # needing to re-load the manifest file at report-render time.
            tooltips=[{"node_type": t.node_type, "text": t.text}
                      for t in self.manifest.tooltips],
            scoring_config=self.manifest.scoring_config.model_dump(),
        )
        logger.info(
            "Scoring weights: webhook=%.0f%% compliance=%.0f%% faq=%.0f%% pass_threshold=%.0f%%",
            scorecard._webhook_weight * 100,
            scorecard._compliance_weight * 100,
            scorecard._faq_weight * 100,
            scorecard._pass_threshold * 100,
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

        # Step 5A: FAQ CBM coverage check — verify faq_tasks are configured in the bot's CBM
        if self.manifest.faq_tasks and cbm.faqs is not None:
            cbm_faq_dicts = [
                {
                    "question": f.question,
                    "alternatives": list(f.alternate_questions),
                    "answer": f.answer,
                }
                for f in cbm.faqs
            ]
            faq_coverage_defects = check_faq_cbm_coverage(
                self.manifest.faq_tasks,
                cbm_faq_dicts,
                min_alternatives=self.manifest.faq_config.min_alternate_questions,
            )
            if faq_coverage_defects:
                faq_coverage_score = TaskScore(task_id="faq_coverage", task_name="FAQ Coverage")
                for defect in faq_coverage_defects:
                    faq_coverage_score.cbm_checks.append(CheckResult(
                        check_id=defect["check_id"],
                        task_id=defect["task_id"],
                        pipeline="cbm",
                        label=f"FAQ Coverage: {defect['task_id']}",
                        status=CheckStatus.WARNING,
                        details=defect["message"],
                    ))
                scorecard.task_scores.append(faq_coverage_score)
                logger.info("FAQ CBM coverage: %d authoring gap(s) found.", len(faq_coverage_defects))

        # Step 5B: NLP pre-flight checks (gated internally on kore_api_client)
        await self._run_nlp_preflight(cbm, scorecard)

        # Step 6: Run Webhook Pipeline (Pipeline B) — all tasks
        # Pre-Gate 2: re-check webhook connectivity (bot may have gone offline after submission)
        if self.manifest.webhook_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as _probe:
                    probe_resp = await _probe.head(self.manifest.webhook_url)
                if probe_resp.status_code == 404:
                    raise ValueError(
                        "FAILED_CONNECTIVITY: Webhook endpoint returned 404. "
                        "The endpoint may have gone offline since submission. Resubmit."
                    )
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
                raise ValueError(
                    f"FAILED_CONNECTIVITY: Webhook endpoint unreachable before Gate 2: {e}. "
                    "Verify webhook is active and resubmit."
                )
        logger.info("=== Pipeline B: Webhook Journey ===")
        eval_start_time = datetime.now(timezone.utc)
        if self.manifest.webhook_url or self.kore_bearer_token:
            task_sessions = await self._run_webhook_pipeline(context, scorecard)
        else:
            logger.info("No webhook URL or Kore credentials — skipping webhook pipeline.")
            task_sessions = {}
        eval_end_time = datetime.now(timezone.utc)

        # Step 6b: FAQ live evaluation (after webhook tasks complete)
        if self.manifest.faq_tasks:
            logger.info("=== FAQ Live Evaluation (%d tasks) ===", len(self.manifest.faq_tasks))
            from ..webhook.faq_evaluator import FAQEvaluator
            faq_evaluator = FAQEvaluator(
                webhook_driver=self.webhook_client,
                submission_id=session_id,
            )
            faq_results = await faq_evaluator.evaluate_all(self.manifest.faq_tasks)
            # Store in faq_scores for separate weighted scoring
            scorecard.faq_scores = faq_results
            # Compute faq_score from live results — overwrites the structural value from Step 5
            if faq_results:
                faq_pass_count = sum(1 for r in faq_results if r.passed)
                faq_score_raw = faq_pass_count / len(faq_results)
                scorecard.faq_score = faq_score_raw
            else:
                faq_weight = scorecard._faq_weight
                if faq_weight > 0:
                    logger.warning(
                        "Manifest declares faq_weight=%.2f but no FAQ tasks ran. "
                        "FAQ score contribution will be 0.",
                        faq_weight,
                    )

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

        # Step 7B: Embed conversation log entries into task evidence cards
        _embed_log_as_evidence(
            session_id=scorecard.session_id,
            task_scores=scorecard.task_scores,
            logs_dir=self.persist_dir / "logs",
        )

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
        session_id: str | None = None,
    ) -> Scorecard:
        """Run CBM pipeline only (Phase 1 — no webhook needed)."""
        if session_id is None:
            session_id = str(uuid.uuid4())

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
            scoring_config=self.manifest.scoring_config.model_dump(),
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

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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

    async def resume_evaluation(
        self,
        source_session_id: str,
        new_session_id: str | None = None,
    ) -> Scorecard:
        """Resume a partially-completed evaluation from its last checkpoint.

        Loads the saved RuntimeContext and Scorecard from disk, then re-runs
        only the webhook tasks that have not yet completed (i.e. not present in
        ``scorecard.completed_tasks``).  CBM and compliance results are kept as-is.

        Safe to call after any kind of mid-run failure (network drop, bot crash,
        process kill). Entity values from completed CREATE tasks are preserved in
        RuntimeContext, so downstream RETRIEVE/MODIFY/DELETE tasks still have the
        correct cross-task identifiers.

        Args:
            source_session_id: The session_id of the interrupted evaluation run
                (used to locate the saved scorecard and RuntimeContext on disk).
            new_session_id: Session ID to assign to the resumed run's output.
                Defaults to source_session_id (in-place resume, backward compatible).

        Returns:
            Updated Scorecard with the newly-completed tasks merged in.

        Raises:
            FileNotFoundError: If no saved scorecard or RuntimeContext can be found.
        """
        # Backward-compatible: if no new_session_id provided, resume in-place
        output_session_id = new_session_id if new_session_id else source_session_id

        # --- Load saved artefacts ---
        results_dir = self.persist_dir / "results"
        scorecard_path = results_dir / f"scorecard_{source_session_id}.json"
        if not scorecard_path.exists():
            raise FileNotFoundError(f"Scorecard not found for session '{source_session_id}'.")

        context_dir = self.persist_dir / "runtime_contexts"
        context_path = context_dir / f"context_{source_session_id}.json"
        if not context_path.exists():
            raise FileNotFoundError(f"RuntimeContext not found for session '{source_session_id}'.")

        with scorecard_path.open("r", encoding="utf-8") as f:
            saved_data = json.load(f)

        context = RuntimeContext.load(context_path)
        # Redirect context output to new session
        context.session_id = output_session_id
        already_done: set[str] = set(saved_data.get("completed_tasks", []))

        logger.info(
            "Resuming evaluation '%s' as '%s' — %d/%d tasks already completed: %s",
            source_session_id,
            output_session_id,
            len(already_done),
            len(self.manifest.tasks),
            sorted(already_done),
        )

        # Re-build a lightweight Scorecard that carries the completed results
        scorecard = Scorecard(
            session_id=output_session_id,
            candidate_id=saved_data.get("candidate_id", ""),
            manifest_id=saved_data.get("manifest_id", ""),
            assessment_name=saved_data.get("assessment_name", ""),
            completed_tasks=list(already_done),
            task_sessions={k: list(v) for k, v in saved_data.get("task_sessions", {}).items()},
            eval_window=saved_data.get("eval_window", {}),
            analytics_status=saved_data.get("analytics_status", "pending"),
            analytics_last_checked_at=saved_data.get("analytics_last_checked_at"),
            kore_api_insights=saved_data.get("kore_api_insights", {}),
            analytics_by_task=saved_data.get("analytics_by_task", {}),
            state_seeded=saved_data.get("state_seeded", False),
            state_seed_tasks=saved_data.get("state_seed_tasks", []),
            faq_score=saved_data.get("faq_score", 0.0),
            scoring_config=self.manifest.scoring_config.model_dump(),
        )
        # Restore task scores so we can extend them
        for ts_data in saved_data.get("task_scores", []):
            scorecard.task_scores.append(
                TaskScore(task_id=ts_data["task_id"], task_name=ts_data["task_name"])
            )

        # --- Run only incomplete tasks ---
        eval_start_time = datetime.now(timezone.utc)
        if self.manifest.webhook_url or self.kore_bearer_token:
            new_sessions = await self._run_webhook_pipeline(
                context, scorecard, skip_task_ids=already_done
            )
        else:
            new_sessions = {}
        eval_end_time = datetime.now(timezone.utc)

        # Merge new session IDs (keep old ones for already-done tasks)
        for tid, v in new_sessions.items():
            scorecard.task_sessions[tid] = list(v)
        if not scorecard.eval_window:
            scorecard.eval_window = {
                "from": eval_start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "to": eval_end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }

        context.save(self.persist_dir / "runtime_contexts")
        self._save_scorecard(scorecard)

        logger.info(
            "Resume complete for session '%s' — %d tasks now completed.",
            output_session_id, len(scorecard.completed_tasks),
        )
        return scorecard

    async def _run_webhook_pipeline(
        self,
        context: RuntimeContext,
        scorecard: Scorecard,
        skip_task_ids: set[str] | None = None,
    ) -> dict[str, tuple[str, str]]:
        """Execute the stateful webhook journey across all tasks.

        Args:
            context: RuntimeContext for this session.
            scorecard: Scorecard to append results to.
            skip_task_ids: Task IDs to skip (already completed in a previous run).

        Returns a mapping of task_id -> (kore_session_id, from_id) for
        use in the analytics pipeline.
        """
        task_sessions: dict[str, tuple[str, str]] = {}
        _skip: set[str] = skip_task_ids or set()

        for task in self.manifest.tasks:
            # Skip tasks that were completed in a previous (interrupted) run
            if task.task_id in _skip:
                logger.info(
                    "Webhook: skipping already-completed task '%s'", task.task_id
                )
                continue

            # Skip web_driver tasks when web channel is not available (Gate 0 WARN/FAIL)
            if (
                task.ui_policy == UIPolicy.WEB_DRIVER
                and self.gate0_result is not None
                and not self.gate0_result.web_channel_available
            ):
                logger.warning(
                    "Task %s requires web driver but web channel not enabled — skipping.",
                    task.task_id,
                )
                continue

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

            # Execute the pattern — EvaluationHaltedError propagates up
            try:
                if self._eval_logger:
                    self._eval_logger.log(
                        task_id=task.task_id,
                        level="info",
                        event="task_start",
                        detail=f"Starting task {task.task_id} ({task.pattern})",
                    )
                pattern_result = await executor.execute()
                kore_sid = getattr(self.webhook_client, "_kore_session_id", None)
                from_id = getattr(self.webhook_client, "_from_id", "")
                if kore_sid:
                    task_sessions[task.task_id] = (kore_sid, from_id)
                # Record as completed so resume_evaluation can skip it on retry
                if pattern_result.success and task.task_id not in scorecard.completed_tasks:
                    scorecard.completed_tasks.append(task.task_id)
                    # Checkpoint: save partial context so a crash on the next task
                    # doesn't lose this task's records
                    context.save(self.persist_dir / "runtime_contexts")
                if self._eval_logger:
                    self._eval_logger.log(
                        task_id=task.task_id,
                        level="info",
                        event="task_complete",
                        detail=f"Success: {pattern_result.success}",
                    )
            except EvaluationHaltedError as halt_err:
                if self._eval_logger:
                    self._eval_logger.log(
                        task_id=halt_err.task_id,
                        level="error",
                        event="evaluation_halted",
                        detail=halt_err.reason,
                    )
                context.save(self.persist_dir / "runtime_contexts")
                raise
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
                    try:
                        await self._attempt_state_seeding(task, context, scorecard)
                    except Exception as seed_err:
                        logger.warning(
                            "State seeding failed for task '%s' (non-fatal): %s",
                            task.task_id, seed_err,
                        )

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
            if not entity.value_pool:
                continue
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


def _embed_log_as_evidence(
    session_id: str,
    task_scores: list,
    logs_dir: Path | None = None,
) -> None:
    """Read JSONL log and append conversation transcript to each TaskScore's evidence_cards.

    Reads the session's JSONL log file, groups entries by task_id, and appends
    a single EvidenceCard per task containing the formatted conversation transcript.
    Non-fatal: silently returns if the log file is absent or unreadable.
    """
    logs_dir = logs_dir or Path("./data/logs")
    log_file = logs_dir / f"eval_{session_id}.jsonl"
    if not log_file.exists():
        return

    # Group entries by task_id
    by_task: dict[str, list[dict]] = {}
    try:
        for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            tid = entry.get("task_id", "unknown")
            by_task.setdefault(tid, []).append(entry)
    except Exception:
        return

    ts_map = {ts.task_id: ts for ts in task_scores}
    for task_id, entries in by_task.items():
        ts = ts_map.get(task_id)
        if not ts:
            continue
        # Build a conversation summary string from message events
        lines = []
        for e in entries:
            if e.get("event") in ("bot_message", "user_message"):
                prefix = "BOT" if e["event"] == "bot_message" else "USER"
                lines.append(f"[{e['ts'][11:19]}] {prefix}: {e.get('detail', '')}")
        if lines:
            card = EvidenceCard(
                card_id=f"log_{task_id}",
                task_id=task_id,
                title="Conversation Transcript",
                content="\n".join(lines),
                color=EvidenceCardColor.BLUE,
                pipeline="webhook",
            )
            ts.evidence_cards.append(card)
