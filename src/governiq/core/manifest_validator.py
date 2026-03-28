"""Manifest Defect Detection — Rules MD-01 through MD-13.

These rules run at manifest save time (builder UI) and at evaluation start
time (pre-flight check). Errors block evaluation. Warnings are shown but
do not block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .manifest import (
    DialogNamePolicy,
    EnginePattern,
    Manifest,
    TaskDefinition,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ManifestDefect:
    rule_id: str
    severity: Severity
    message: str
    task_id: str | None = None
    field_path: str | None = None


@dataclass
class ValidationResult:
    valid: bool
    defects: list[ManifestDefect] = field(default_factory=list)

    @property
    def errors(self) -> list[ManifestDefect]:
        return [d for d in self.defects if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ManifestDefect]:
        return [d for d in self.defects if d.severity == Severity.WARNING]


def validate_manifest(manifest: Manifest) -> ValidationResult:
    """Run all MD rules against a manifest. Returns a ValidationResult."""
    defects: list[ManifestDefect] = []

    defects.extend(_md01_exact_dialog_name_warning(manifest))
    defects.extend(_md02_empty_value_pool(manifest))
    defects.extend(_md03_amendment_without_pattern(manifest))
    defects.extend(_md04_missing_cross_task_ref(manifest))
    defects.extend(_md05_cross_task_ref_invalid_source(manifest))
    defects.extend(_md06_state_assertion_without_endpoint(manifest))
    defects.extend(_md07_delete_without_expect_deletion(manifest))
    defects.extend(_md08_create_without_required_entities(manifest))
    defects.extend(_md09_faq_missing_alternates(manifest))
    defects.extend(_md10_duplicate_task_ids(manifest))
    defects.extend(_md11_scoring_weights_exceed_one(manifest))
    defects.extend(_md12_edge_case_missing_negative_tests(manifest))
    defects.extend(_md13_faq_task_empty_fields(manifest))

    has_errors = any(d.severity == Severity.ERROR for d in defects)
    return ValidationResult(valid=not has_errors, defects=defects)


# ---------------------------------------------------------------------------
# Individual MD rules
# ---------------------------------------------------------------------------

def _md01_exact_dialog_name_warning(manifest: Manifest) -> list[ManifestDefect]:
    """MD-01: Warn if dialogNamePolicy is 'exact' — candidates may name differently."""
    defects = []
    for task in manifest.tasks:
        if task.dialog_name_policy == DialogNamePolicy.EXACT:
            defects.append(ManifestDefect(
                rule_id="MD-01",
                severity=Severity.WARNING,
                message=(
                    f"Task '{task.task_id}' uses exact dialog name matching for "
                    f"'{task.dialog_name}'. Candidates may use different naming. "
                    f"Consider 'contains' policy to reduce false failures."
                ),
                task_id=task.task_id,
                field_path="dialog_name_policy",
            ))
    return defects


def _md02_empty_value_pool(manifest: Manifest) -> list[ManifestDefect]:
    """MD-02: Error if a CREATE-pattern entity has an empty value pool.

    RETRIEVE/MODIFY/DELETE tasks may have entities with empty value pools
    because they get their values from cross-task references — this is valid.
    """
    needs_pool = {EnginePattern.CREATE, EnginePattern.CREATE_WITH_AMENDMENT}
    defects = []
    for task in manifest.tasks:
        if task.pattern not in needs_pool:
            continue
        for entity in task.required_entities:
            if not entity.value_pool:
                defects.append(ManifestDefect(
                    rule_id="MD-02",
                    severity=Severity.ERROR,
                    message=(
                        f"Task '{task.task_id}' entity '{entity.entity_key}' has an "
                        f"empty value pool. Driver cannot inject test values."
                    ),
                    task_id=task.task_id,
                    field_path=f"required_entities.{entity.entity_key}.value_pool",
                ))
    return defects


def _md03_amendment_without_pattern(manifest: Manifest) -> list[ManifestDefect]:
    """MD-03: Error if amendment_config present but pattern is not CREATE_WITH_AMENDMENT."""
    defects = []
    for task in manifest.tasks:
        if task.amendment_config and task.pattern != EnginePattern.CREATE_WITH_AMENDMENT:
            defects.append(ManifestDefect(
                rule_id="MD-03",
                severity=Severity.ERROR,
                message=(
                    f"Task '{task.task_id}' has amendment_config but pattern is "
                    f"'{task.pattern.value}', not CREATE_WITH_AMENDMENT."
                ),
                task_id=task.task_id,
                field_path="amendment_config",
            ))
        if task.pattern == EnginePattern.CREATE_WITH_AMENDMENT and not task.amendment_config:
            defects.append(ManifestDefect(
                rule_id="MD-03",
                severity=Severity.ERROR,
                message=(
                    f"Task '{task.task_id}' uses CREATE_WITH_AMENDMENT pattern but "
                    f"has no amendment_config."
                ),
                task_id=task.task_id,
                field_path="amendment_config",
            ))
    return defects


def _md04_missing_cross_task_ref(manifest: Manifest) -> list[ManifestDefect]:
    """MD-04: Error if RETRIEVE/MODIFY/DELETE task has no cross_task_refs."""
    needs_ref = {EnginePattern.RETRIEVE, EnginePattern.MODIFY, EnginePattern.DELETE}
    defects = []
    for task in manifest.tasks:
        if task.pattern in needs_ref and not task.cross_task_refs:
            defects.append(ManifestDefect(
                rule_id="MD-04",
                severity=Severity.ERROR,
                message=(
                    f"Task '{task.task_id}' uses {task.pattern.value} pattern but "
                    f"declares no cross_task_refs. It cannot know which record to use."
                ),
                task_id=task.task_id,
                field_path="cross_task_refs",
            ))
    return defects


def _md05_cross_task_ref_invalid_source(manifest: Manifest) -> list[ManifestDefect]:
    """MD-05: Error if a cross_task_ref references a task_id that does not exist."""
    defects = []
    task_ids = {t.task_id for t in manifest.tasks}
    for task in manifest.tasks:
        for ref_key, ref in task.cross_task_refs.items():
            if ref.source_task_id not in task_ids:
                defects.append(ManifestDefect(
                    rule_id="MD-05",
                    severity=Severity.ERROR,
                    message=(
                        f"Task '{task.task_id}' cross_task_ref '{ref_key}' references "
                        f"source_task_id '{ref.source_task_id}' which does not exist."
                    ),
                    task_id=task.task_id,
                    field_path=f"cross_task_refs.{ref_key}.source_task_id",
                ))
    return defects


def _md06_state_assertion_without_endpoint(manifest: Manifest) -> list[ManifestDefect]:
    """MD-06: Warning if state_assertion is enabled but verify_endpoint is empty.

    This is a warning (not error) because verify_endpoint may be provided at
    evaluation time by the candidate's submission, not at manifest creation time.
    """
    defects = []
    for task in manifest.tasks:
        if task.state_assertion and task.state_assertion.enabled:
            if not task.state_assertion.verify_endpoint:
                defects.append(ManifestDefect(
                    rule_id="MD-06",
                    severity=Severity.WARNING,
                    message=(
                        f"Task '{task.task_id}' has state_assertion enabled but "
                        f"verify_endpoint is empty — must be provided at evaluation time."
                    ),
                    task_id=task.task_id,
                    field_path="state_assertion.verify_endpoint",
                ))
    return defects


def _md07_delete_without_expect_deletion(manifest: Manifest) -> list[ManifestDefect]:
    """MD-07: Warning if DELETE task state_assertion does not set expect_deletion."""
    defects = []
    for task in manifest.tasks:
        if task.pattern == EnginePattern.DELETE and task.state_assertion:
            if not task.state_assertion.expect_deletion:
                defects.append(ManifestDefect(
                    rule_id="MD-07",
                    severity=Severity.WARNING,
                    message=(
                        f"Task '{task.task_id}' uses DELETE pattern but "
                        f"state_assertion.expect_deletion is false."
                    ),
                    task_id=task.task_id,
                    field_path="state_assertion.expect_deletion",
                ))
    return defects


def _md08_create_without_required_entities(manifest: Manifest) -> list[ManifestDefect]:
    """MD-08: Error if CREATE/CREATE_WITH_AMENDMENT has no required_entities.

    Exception: Welcome/greeting tasks using CREATE pattern without entities
    are valid (they only check the greeting message, not entity collection).
    """
    create_patterns = {EnginePattern.CREATE, EnginePattern.CREATE_WITH_AMENDMENT}
    defects = []
    for task in manifest.tasks:
        if task.pattern in create_patterns and not task.required_entities:
            # Welcome/greeting tasks don't need entities
            if task.required_greeting_text or task.required_menu_items:
                continue
            defects.append(ManifestDefect(
                rule_id="MD-08",
                severity=Severity.ERROR,
                message=(
                    f"Task '{task.task_id}' uses {task.pattern.value} pattern but "
                    f"declares no required_entities."
                ),
                task_id=task.task_id,
                field_path="required_entities",
            ))
    return defects


def _md09_faq_missing_alternates(manifest: Manifest) -> list[ManifestDefect]:
    """MD-09: Warning if any FAQ has fewer alternates than min_alternate_questions."""
    defects = []
    faq_config = manifest.faq_config
    min_alts = faq_config.min_alternate_questions
    for i, faq in enumerate(faq_config.required_faqs):
        if len(faq.alternate_questions) < min_alts:
            defects.append(ManifestDefect(
                rule_id="MD-09",
                severity=Severity.WARNING,
                message=(
                    f"FAQ #{i + 1} ('{faq.primary_question[:50]}...') has "
                    f"{len(faq.alternate_questions)} alternates, minimum is {min_alts}."
                ),
                field_path=f"faq_config.required_faqs[{i}].alternate_questions",
            ))
    return defects


def _md10_duplicate_task_ids(manifest: Manifest) -> list[ManifestDefect]:
    """MD-10: Error if two tasks share the same task_id."""
    defects = []
    seen: dict[str, int] = {}
    for i, task in enumerate(manifest.tasks):
        if task.task_id in seen:
            defects.append(ManifestDefect(
                rule_id="MD-10",
                severity=Severity.ERROR,
                message=(
                    f"Duplicate task_id '{task.task_id}' at positions "
                    f"{seen[task.task_id]} and {i}."
                ),
                task_id=task.task_id,
            ))
        else:
            seen[task.task_id] = i
    return defects


def _md11_scoring_weights_exceed_one(manifest: Manifest) -> list[ManifestDefect]:
    """MD-11: Warning if scoring weights do not sum to 1.0."""
    defects = []
    sc = manifest.scoring_config
    total = (
        sc.cbm_structural_weight
        + sc.webhook_functional_weight
        + sc.compliance_weight
        + sc.faq_weight
    )
    if abs(total - 1.0) > 0.01:
        defects.append(ManifestDefect(
            rule_id="MD-11",
            severity=Severity.WARNING,
            message=(
                f"Scoring weights sum to {total:.2f}, not 1.0. "
                f"Results may not reflect intended weighting."
            ),
            field_path="scoring_config",
        ))
    return defects


def _md12_edge_case_missing_negative_tests(manifest: Manifest) -> list[ManifestDefect]:
    """MD-12: Error if EDGE_CASE task has no negative_tests."""
    defects = []
    for task in manifest.tasks:
        if task.pattern == EnginePattern.EDGE_CASE and not task.negative_tests:
            defects.append(ManifestDefect(
                rule_id="MD-12",
                severity=Severity.ERROR,
                message=(
                    f"Task '{task.task_id}' uses EDGE_CASE pattern but "
                    f"declares no negative_tests."
                ),
                task_id=task.task_id,
                field_path="negative_tests",
            ))
    return defects


def _md13_faq_task_empty_fields(manifest: Manifest) -> list[ManifestDefect]:
    """MD-13: FAQ task has empty question or expected_answer."""
    defects = []
    for faq in manifest.faq_tasks:
        if not faq.question.strip():
            defects.append(ManifestDefect(
                rule_id="MD-13",
                severity=Severity.ERROR,
                message=(
                    f"FAQ task '{faq.task_id}' has an empty question. "
                    "The question field is required for live FAQ evaluation."
                ),
                task_id=faq.task_id,
                field_path="question",
            ))
        if not faq.expected_answer.strip():
            defects.append(ManifestDefect(
                rule_id="MD-13",
                severity=Severity.ERROR,
                message=(
                    f"FAQ task '{faq.task_id}' has an empty expected_answer. "
                    "Provide the canonical answer so semantic similarity can be computed."
                ),
                task_id=faq.task_id,
                field_path="expected_answer",
            ))
    return defects
