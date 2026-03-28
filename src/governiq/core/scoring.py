"""Scoring Engine — Merges CBM and Webhook pipeline results.

The Scoring Engine is the only component that sees output from both pipelines.
It produces the final scorecard for the admin dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    INFO = "info"
    UNTESTABLE = "untestable"


class EvidenceCardColor(str, Enum):
    GREEN = "green"
    RED = "red"
    AMBER = "amber"
    GREY = "grey"
    BLUE = "blue"


@dataclass
class CheckResult:
    """A single evaluation check result."""
    check_id: str
    task_id: str
    pipeline: str              # "cbm" or "webhook"
    label: str                 # Human-readable check description
    status: CheckStatus
    details: str = ""          # Plain English explanation
    evidence: str = ""         # Supporting data
    score: float = 0.0         # 0.0 to 1.0
    weight: float = 1.0


@dataclass
class EvidenceCard:
    """Visual evidence card for the dashboard."""
    card_id: str
    task_id: str
    title: str
    content: str
    color: EvidenceCardColor
    pipeline: str              # "cbm", "webhook", or "state_inspector"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskScore:
    """Aggregated score for a single task."""
    task_id: str
    task_name: str
    cbm_checks: list[CheckResult] = field(default_factory=list)
    webhook_checks: list[CheckResult] = field(default_factory=list)
    evidence_cards: list[EvidenceCard] = field(default_factory=list)

    @property
    def cbm_score(self) -> float:
        scored = [c for c in self.cbm_checks if c.status != CheckStatus.UNTESTABLE]
        if not scored:
            return 0.0
        total_weight = sum(c.weight for c in scored)
        if total_weight == 0:
            return 0.0
        return sum(c.score * c.weight for c in scored) / total_weight

    @property
    def webhook_score(self) -> float:
        scored = [c for c in self.webhook_checks if c.status != CheckStatus.UNTESTABLE]
        if not scored:
            return 0.0
        total_weight = sum(c.weight for c in scored)
        if total_weight == 0:
            return 0.0
        return sum(c.score * c.weight for c in scored) / total_weight

    @property
    def combined_score(self) -> float:
        """Webhook is the authority for scoring. CBM is informational only.

        If webhook checks exist, score comes from webhook only.
        If no webhook checks exist, the task is untested (score = 0).
        CBM score is still computed and shown in the report for reference,
        but it does NOT contribute to the pass/fail decision.
        """
        if self.webhook_checks:
            return self.webhook_score
        # No webhook = untested = cannot pass
        return 0.0

    @property
    def webhook_tested(self) -> bool:
        """Whether this task has been tested via webhook."""
        return bool(self.webhook_checks)

    @property
    def all_passed(self) -> bool:
        """A task passes only if webhook tests pass. CBM alone cannot qualify.

        WARNING is treated as non-blocking (used for optional items that are
        desirable but not required — their absence does not constitute failure).
        """
        if not self.webhook_checks:
            return False  # Cannot pass without webhook testing
        return all(
            c.status in (CheckStatus.PASS, CheckStatus.WARNING, CheckStatus.INFO, CheckStatus.UNTESTABLE)
            for c in self.webhook_checks
        )


@dataclass
class ComplianceResult:
    """Result of a compliance check."""
    check_id: str
    label: str
    status: CheckStatus
    cbm_field: str
    actual_value: Any = None
    required_state: str = ""
    critical: bool = False
    tooltip: str = ""


@dataclass
class Scorecard:
    """The complete evaluation scorecard — final output of the scoring engine."""
    session_id: str
    candidate_id: str
    manifest_id: str
    assessment_name: str

    task_scores: list[TaskScore] = field(default_factory=list)
    compliance_results: list[ComplianceResult] = field(default_factory=list)
    faq_score: float = 0.0

    # Live FAQ evaluation results — list[FAQEvalResult] from faq_evaluator.
    # Typed as list to avoid circular import; populated by engine after webhook pipeline.
    # When populated, engine computes faq_score from these and overwrites the
    # structural faq_score set in Step 5.
    faq_scores: list = field(default_factory=list)

    # Flags
    state_seeded: bool = False
    state_seed_tasks: list[str] = field(default_factory=list)
    plagiarism_flag: bool = False
    plagiarism_message: str = ""

    # Kore.ai public API insights (bot details, analytics, intent stats)
    kore_api_insights: dict[str, Any] = field(default_factory=dict)

    # Per-task analytics data from analytics pipeline
    analytics_by_task: dict[str, Any] = field(default_factory=dict)

    # Manifest tooltips — copied at evaluation time so the report can render the CBM Map legend
    tooltips: list[dict[str, str]] = field(default_factory=list)

    # Tasks that completed successfully — used by resume_evaluation to skip re-running them
    completed_tasks: list[str] = field(default_factory=list)

    # Deferred analytics — persisted so refresh can be triggered any time after evaluation
    # task_sessions: { task_id -> [kore_session_id, from_id] }
    task_sessions: dict[str, list[str]] = field(default_factory=dict)
    # eval_window: { "from": ISO-str, "to": ISO-str }
    eval_window: dict[str, str] = field(default_factory=dict)
    # analytics_status: "pending" | "partial" | "available"
    analytics_status: str = "pending"
    # ISO timestamp of last refresh attempt (None = never refreshed)
    analytics_last_checked_at: str | None = None

    # Manifest scoring config — consumed at construction, never serialised.
    # Must be the last field so Python's dataclass ordering rules are satisfied
    # (fields with defaults must follow fields without defaults).
    scoring_config: dict | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Derive weight attributes from scoring_config or apply legacy defaults."""
        import logging as _logging

        _LEGACY_WEBHOOK = 0.80
        _LEGACY_COMPLIANCE = 0.10
        _LEGACY_FAQ = 0.10
        _LEGACY_THRESHOLD = 0.70

        if self.scoring_config:
            ww = float(self.scoring_config.get("webhook_functional_weight", _LEGACY_WEBHOOK))
            cw = float(self.scoring_config.get("compliance_weight", _LEGACY_COMPLIANCE))
            fw = float(self.scoring_config.get("faq_weight", _LEGACY_FAQ))
            pt = float(self.scoring_config.get("pass_threshold", _LEGACY_THRESHOLD))

            # Validate pass_threshold
            if not (0.5 <= pt <= 1.0):
                _logging.getLogger(__name__).warning(
                    "Scorecard: pass_threshold %.2f out of range [0.5, 1.0], using 0.70", pt
                )
                pt = _LEGACY_THRESHOLD

            # Normalise weights if they don't sum to 1.0
            total = ww + cw + fw
            if total > 0 and abs(total - 1.0) > 0.01:
                ww, cw, fw = ww / total, cw / total, fw / total
        else:
            ww, cw, fw, pt = _LEGACY_WEBHOOK, _LEGACY_COMPLIANCE, _LEGACY_FAQ, _LEGACY_THRESHOLD

        self._webhook_weight: float = ww
        self._compliance_weight: float = cw
        self._faq_weight: float = fw
        self._pass_threshold: float = pt

    @property
    def overall_score(self) -> float:
        """Compute weighted overall score.

        Webhook is the authority. CBM is informational.
        Tasks without webhook testing score 0 (untested).

        If faq_score is None, FAQ pipeline did not run — redistribute its
        weight to webhook. If faq_score is 0.0 (ran but scored zero), no
        redistribution occurs.
        """
        if not self.task_scores:
            return 0.0
        # Exclude FAQ task from main task scoring (it has its own weight)
        main_tasks = [t for t in self.task_scores if t.task_id != "faq"]
        if main_tasks:
            task_avg = sum(t.combined_score for t in main_tasks) / len(main_tasks)
        else:
            task_avg = 0.0
        compliance_score = self._compliance_score()

        faq_w = self._faq_weight
        webhook_w = self._webhook_weight
        if self.faq_score is None and faq_w > 0:
            webhook_w = webhook_w + faq_w
            faq_w = 0.0

        faq_contribution = (self.faq_score or 0.0) * faq_w
        return task_avg * webhook_w + compliance_score * self._compliance_weight + faq_contribution

    @property
    def any_webhook_tested(self) -> bool:
        """Whether any task was tested via webhook."""
        return any(t.webhook_tested for t in self.task_scores)

    def _compliance_score(self) -> float:
        if not self.compliance_results:
            return 1.0
        passed = sum(
            1 for c in self.compliance_results if c.status == CheckStatus.PASS
        )
        return passed / len(self.compliance_results)

    @property
    def has_critical_failures(self) -> bool:
        return any(
            c.critical and c.status == CheckStatus.FAIL
            for c in self.compliance_results
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize scorecard for API / persistence."""
        return {
            "session_id": self.session_id,
            "candidate_id": self.candidate_id,
            "manifest_id": self.manifest_id,
            "assessment_name": self.assessment_name,
            "overall_score": round(self.overall_score, 4),
            "has_critical_failures": self.has_critical_failures,
            "any_webhook_tested": self.any_webhook_tested,
            "state_seeded": self.state_seeded,
            "task_scores": [
                {
                    "task_id": ts.task_id,
                    "task_name": ts.task_name,
                    "cbm_score": round(ts.cbm_score, 4),
                    "webhook_score": round(ts.webhook_score, 4),
                    "combined_score": round(ts.combined_score, 4),
                    "all_passed": ts.all_passed,
                    "webhook_tested": ts.webhook_tested,
                    "cbm_checks": [
                        {
                            "check_id": c.check_id,
                            "label": c.label,
                            "status": c.status.value,
                            "details": c.details,
                            "score": c.score,
                        }
                        for c in ts.cbm_checks
                    ],
                    "webhook_checks": [
                        {
                            "check_id": c.check_id,
                            "label": c.label,
                            "status": c.status.value,
                            "details": c.details,
                            "score": c.score,
                        }
                        for c in ts.webhook_checks
                    ],
                    "evidence_cards": [
                        {
                            "card_id": ec.card_id,
                            "title": ec.title,
                            "content": ec.content,
                            "color": ec.color.value,
                            "pipeline": ec.pipeline,
                        }
                        for ec in ts.evidence_cards
                    ],
                }
                for ts in self.task_scores
            ],
            "compliance_results": [
                {
                    "check_id": cr.check_id,
                    "label": cr.label,
                    "status": cr.status.value,
                    "cbm_field": cr.cbm_field,
                    "actual_value": cr.actual_value,
                    "required_state": cr.required_state,
                    "critical": cr.critical,
                }
                for cr in self.compliance_results
            ],
            "faq_score": round(self.faq_score, 4) if self.faq_score is not None else None,
            "faq_scores": [r.to_evidence_dict() for r in self.faq_scores],
            "kore_api_insights": self.kore_api_insights,
            "analytics_by_task": self.analytics_by_task,
            "tooltips": self.tooltips,
            "completed_tasks": self.completed_tasks,
            "task_sessions": self.task_sessions,
            "eval_window": self.eval_window,
            "analytics_status": self.analytics_status,
            "analytics_last_checked_at": self.analytics_last_checked_at,
            "plagiarism_flag": self.plagiarism_flag,
            "plagiarism_message": self.plagiarism_message,
        }
