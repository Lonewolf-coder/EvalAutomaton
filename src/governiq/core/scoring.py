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
        scores = []
        if self.cbm_checks:
            scores.append(self.cbm_score)
        if self.webhook_checks:
            scores.append(self.webhook_score)
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def all_passed(self) -> bool:
        all_checks = self.cbm_checks + self.webhook_checks
        return all(
            c.status in (CheckStatus.PASS, CheckStatus.INFO, CheckStatus.UNTESTABLE)
            for c in all_checks
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

    # Flags
    state_seeded: bool = False
    state_seed_tasks: list[str] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        """Compute weighted overall score."""
        if not self.task_scores:
            return 0.0
        task_avg = sum(t.combined_score for t in self.task_scores) / len(self.task_scores)
        compliance_score = self._compliance_score()
        # Simple weighted average — weights come from manifest scoring_config
        return task_avg * 0.80 + compliance_score * 0.10 + self.faq_score * 0.10

    def compute_weighted_score(
        self,
        cbm_weight: float = 0.40,
        webhook_weight: float = 0.40,
        compliance_weight: float = 0.10,
        faq_weight: float = 0.10,
    ) -> float:
        """Compute overall score with explicit weights."""
        if not self.task_scores:
            return 0.0

        cbm_avg = sum(t.cbm_score for t in self.task_scores) / len(self.task_scores)
        webhook_avg = sum(t.webhook_score for t in self.task_scores) / len(self.task_scores)
        comp = self._compliance_score()

        return (
            cbm_avg * cbm_weight
            + webhook_avg * webhook_weight
            + comp * compliance_weight
            + self.faq_score * faq_weight
        )

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
            "state_seeded": self.state_seeded,
            "task_scores": [
                {
                    "task_id": ts.task_id,
                    "task_name": ts.task_name,
                    "cbm_score": round(ts.cbm_score, 4),
                    "webhook_score": round(ts.webhook_score, 4),
                    "combined_score": round(ts.combined_score, 4),
                    "all_passed": ts.all_passed,
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
            "faq_score": round(self.faq_score, 4),
        }
