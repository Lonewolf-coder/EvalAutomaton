"""CBM Evaluator — Structural evaluation of bot exports against manifest requirements.

Runs against the static bot export. Produces deterministic, reproducible results.
Can be re-run at any time against the same export and will produce identical output.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.manifest import (
    ComplianceCheck,
    ComplianceRequiredState,
    DialogNamePolicy,
    EnginePattern,
    Manifest,
    RequiredNode,
    TaskDefinition,
)
from ..core.scoring import (
    CheckResult,
    CheckStatus,
    ComplianceResult,
    EvidenceCard,
    EvidenceCardColor,
    TaskScore,
)
from .field_map import NODE_TYPE_AGENT, NODE_TYPE_ENTITY, NODE_TYPE_SERVICE
from .parser import CBMDialog, CBMFAQ, CBMObject


# ---------------------------------------------------------------------------
# Dialog matching
# ---------------------------------------------------------------------------

def _match_dialog(cbm: CBMObject, task: TaskDefinition) -> tuple[CBMDialog | None, str]:
    """Find the dialog matching the task's dialog_name and policy.

    Returns (matched_dialog, match_info_message).
    """
    policy = task.dialog_name_policy.value
    dialog = cbm.find_dialog(task.dialog_name, policy=policy)

    if dialog:
        return dialog, f"Dialog '{dialog.name}' matched using '{policy}' policy."

    # Fuzzy fallback for informational purposes
    fuzzy_dialog, score = cbm.find_dialog_fuzzy(task.dialog_name)
    if fuzzy_dialog and score > 0.3:
        return None, (
            f"Dialog '{task.dialog_name}' not matched in CBM — "
            f"closest match is '{fuzzy_dialog.name}' (similarity: {score:.0%}). "
            f"May be named differently."
        )
    return None, f"Dialog '{task.dialog_name}' not found in CBM."


# ---------------------------------------------------------------------------
# Node type checks
# ---------------------------------------------------------------------------

def _check_required_nodes(
    dialog: CBMDialog, task: TaskDefinition
) -> list[CheckResult]:
    """Check all required nodes declared in the manifest for this task."""
    results = []
    for req_node in task.required_nodes:
        matching = dialog.get_nodes_by_type(req_node.node_type)

        if req_node.service_method and matching:
            matching = [
                n for n in matching
                if n.service_method and n.service_method.upper() == req_node.service_method.upper()
            ]

        if matching:
            node_names = ", ".join(n.name for n in matching)
            results.append(CheckResult(
                check_id=f"cbm.{task.task_id}.node.{req_node.node_type}",
                task_id=task.task_id,
                pipeline="cbm",
                label=req_node.label,
                status=CheckStatus.PASS,
                details=f"Found: {node_names}",
                score=1.0,
            ))
        elif req_node.required:
            results.append(CheckResult(
                check_id=f"cbm.{task.task_id}.node.{req_node.node_type}",
                task_id=task.task_id,
                pipeline="cbm",
                label=req_node.label,
                status=CheckStatus.FAIL,
                details=f"Required node type '{req_node.node_type}' not found in dialog.",
                score=0.0,
            ))
        else:
            results.append(CheckResult(
                check_id=f"cbm.{task.task_id}.node.{req_node.node_type}",
                task_id=task.task_id,
                pipeline="cbm",
                label=req_node.label,
                status=CheckStatus.WARNING,
                details=f"Optional node type '{req_node.node_type}' not found.",
                score=0.5,
            ))
    return results


def _check_required_entities(
    dialog: CBMDialog, task: TaskDefinition
) -> list[CheckResult]:
    """Check that all required entities from manifest exist in dialog."""
    results = []
    entity_nodes = dialog.get_entity_nodes()
    entity_names = {n.name.lower() for n in entity_nodes}

    for entity_def in task.required_entities:
        found = entity_def.entity_key.lower() in entity_names
        if found:
            # Check validation rules if required
            matching_node = next(
                (n for n in entity_nodes if n.name.lower() == entity_def.entity_key.lower()),
                None,
            )
            has_validation = bool(matching_node and matching_node.validation_rules)

            if entity_def.validation_required and not has_validation:
                results.append(CheckResult(
                    check_id=f"cbm.{task.task_id}.entity.{entity_def.entity_key}.validation",
                    task_id=task.task_id,
                    pipeline="cbm",
                    label=f"Entity '{entity_def.entity_key}' validation rules",
                    status=CheckStatus.WARNING,
                    details="Entity found but no validation rules configured.",
                    score=0.5,
                ))
            else:
                results.append(CheckResult(
                    check_id=f"cbm.{task.task_id}.entity.{entity_def.entity_key}",
                    task_id=task.task_id,
                    pipeline="cbm",
                    label=f"Entity '{entity_def.entity_key}' present",
                    status=CheckStatus.PASS,
                    details=f"Entity node found in dialog.",
                    score=1.0,
                ))
        else:
            results.append(CheckResult(
                check_id=f"cbm.{task.task_id}.entity.{entity_def.entity_key}",
                task_id=task.task_id,
                pipeline="cbm",
                label=f"Entity '{entity_def.entity_key}' present",
                status=CheckStatus.FAIL,
                details=f"Required entity '{entity_def.entity_key}' not found in dialog nodes.",
                score=0.0,
            ))
    return results


# ---------------------------------------------------------------------------
# Per-task CBM evaluation
# ---------------------------------------------------------------------------

def evaluate_task_cbm(
    cbm: CBMObject, task: TaskDefinition
) -> TaskScore:
    """Run CBM structural evaluation for a single task.

    Returns a TaskScore with all CBM checks completed and evidence cards
    generated for the evaluator reference panel.
    """
    task_score = TaskScore(task_id=task.task_id, task_name=task.task_name)

    # Step 1: Dialog matching
    dialog, match_info = _match_dialog(cbm, task)

    if not dialog:
        # Dialog not found — informational, does not auto-fail
        task_score.cbm_checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.dialog_match",
            task_id=task.task_id,
            pipeline="cbm",
            label=f"Dialog '{task.dialog_name}' found in CBM",
            status=CheckStatus.INFO,
            details=match_info,
            score=0.0,
        ))
        task_score.evidence_cards.append(EvidenceCard(
            card_id=f"cbm.{task.task_id}.dialog_not_found",
            task_id=task.task_id,
            title="Dialog Not Matched",
            content=match_info,
            color=EvidenceCardColor.AMBER,
            pipeline="cbm",
        ))
        return task_score

    # Dialog found
    task_score.cbm_checks.append(CheckResult(
        check_id=f"cbm.{task.task_id}.dialog_match",
        task_id=task.task_id,
        pipeline="cbm",
        label=f"Dialog '{task.dialog_name}' found in CBM",
        status=CheckStatus.PASS,
        details=match_info,
        score=1.0,
    ))

    # Step 2: Required node checks
    task_score.cbm_checks.extend(_check_required_nodes(dialog, task))

    # Step 3: Required entity checks
    task_score.cbm_checks.extend(_check_required_entities(dialog, task))

    # Step 4: Pattern-specific checks
    task_score.cbm_checks.extend(_pattern_specific_checks(dialog, task))

    # Step 5: Generate CBM Evaluator Reference Panel evidence card
    task_score.evidence_cards.append(_build_reference_panel_card(dialog, task))

    return task_score


def _pattern_specific_checks(
    dialog: CBMDialog, task: TaskDefinition
) -> list[CheckResult]:
    """Run checks specific to the task's engine pattern."""
    checks: list[CheckResult] = []

    if task.pattern in (EnginePattern.CREATE, EnginePattern.CREATE_WITH_AMENDMENT):
        # Must have POST service node
        post_nodes = [
            n for n in dialog.get_service_nodes()
            if n.service_method and n.service_method.upper() == "POST"
        ]
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.post_service",
            task_id=task.task_id,
            pipeline="cbm",
            label="POST service node present",
            status=CheckStatus.PASS if post_nodes else CheckStatus.FAIL,
            details=f"Found {len(post_nodes)} POST service node(s)." if post_nodes
                    else "No POST service node found in dialog.",
            score=1.0 if post_nodes else 0.0,
        ))

        # Must have Agent Node for CREATE_WITH_AMENDMENT
        if task.pattern == EnginePattern.CREATE_WITH_AMENDMENT:
            checks.append(CheckResult(
                check_id=f"cbm.{task.task_id}.agent_node",
                task_id=task.task_id,
                pipeline="cbm",
                label="Agent Node (aiassist) present",
                status=CheckStatus.PASS if dialog.has_agent_node() else CheckStatus.FAIL,
                details="Agent Node found." if dialog.has_agent_node()
                        else "Agent Node (type 'aiassist') not found — required for amendment.",
                score=1.0 if dialog.has_agent_node() else 0.0,
            ))

        # Prompt node for booking summary
        prompt_nodes = dialog.get_nodes_by_type("prompt")
        message_nodes = dialog.get_nodes_by_type("message")
        has_summary = bool(prompt_nodes or message_nodes)
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.summary_display",
            task_id=task.task_id,
            pipeline="cbm",
            label="Summary/confirmation display node present",
            status=CheckStatus.PASS if has_summary else CheckStatus.WARNING,
            details=f"Found {len(prompt_nodes)} prompt and {len(message_nodes)} message node(s)."
                    if has_summary else "No prompt or message node for summary display.",
            score=1.0 if has_summary else 0.5,
        ))

    elif task.pattern == EnginePattern.RETRIEVE:
        # Must have GET service node
        get_nodes = [
            n for n in dialog.get_service_nodes()
            if n.service_method and n.service_method.upper() == "GET"
        ]
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.get_service",
            task_id=task.task_id,
            pipeline="cbm",
            label="GET service node present",
            status=CheckStatus.PASS if get_nodes else CheckStatus.FAIL,
            details=f"Found {len(get_nodes)} GET service node(s)." if get_nodes
                    else "No GET service node found.",
            score=1.0 if get_nodes else 0.0,
        ))

        # Not-found message node
        _check_not_found_handling(checks, dialog, task)

    elif task.pattern == EnginePattern.MODIFY:
        # Must have GET + PUT/PATCH service nodes
        get_nodes = [
            n for n in dialog.get_service_nodes()
            if n.service_method and n.service_method.upper() == "GET"
        ]
        put_nodes = [
            n for n in dialog.get_service_nodes()
            if n.service_method and n.service_method.upper() in ("PUT", "PATCH")
        ]
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.get_service",
            task_id=task.task_id,
            pipeline="cbm",
            label="GET service node present (retrieve before modify)",
            status=CheckStatus.PASS if get_nodes else CheckStatus.FAIL,
            details=f"Found {len(get_nodes)} GET node(s)." if get_nodes
                    else "No GET service node found.",
            score=1.0 if get_nodes else 0.0,
        ))
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.put_service",
            task_id=task.task_id,
            pipeline="cbm",
            label="PUT/PATCH service node present",
            status=CheckStatus.PASS if put_nodes else CheckStatus.FAIL,
            details=f"Found {len(put_nodes)} PUT/PATCH node(s)." if put_nodes
                    else "No PUT or PATCH service node found.",
            score=1.0 if put_nodes else 0.0,
        ))

    elif task.pattern == EnginePattern.DELETE:
        # Must have DELETE service node
        delete_nodes = [
            n for n in dialog.get_service_nodes()
            if n.service_method and n.service_method.upper() == "DELETE"
        ]
        checks.append(CheckResult(
            check_id=f"cbm.{task.task_id}.delete_service",
            task_id=task.task_id,
            pipeline="cbm",
            label="DELETE service node present",
            status=CheckStatus.PASS if delete_nodes else CheckStatus.FAIL,
            details=f"Found {len(delete_nodes)} DELETE node(s)." if delete_nodes
                    else "No DELETE service node found.",
            score=1.0 if delete_nodes else 0.0,
        ))

    return checks


def _check_not_found_handling(
    checks: list[CheckResult], dialog: CBMDialog, task: TaskDefinition
) -> None:
    """Check for not-found / error message handling nodes."""
    message_nodes = dialog.get_nodes_by_type("message")
    # Heuristic: look for message nodes with error/not-found keywords
    error_keywords = {"not found", "no record", "error", "invalid", "does not exist", "couldn't find"}
    has_error_msg = any(
        any(kw in n.message_text.lower() for kw in error_keywords)
        for n in message_nodes
    )
    checks.append(CheckResult(
        check_id=f"cbm.{task.task_id}.not_found_handling",
        task_id=task.task_id,
        pipeline="cbm",
        label="Not-found/error message node present",
        status=CheckStatus.PASS if has_error_msg else CheckStatus.WARNING,
        details="Error handling message node found." if has_error_msg
                else "No obvious error handling message detected (may use dynamic messages).",
        score=1.0 if has_error_msg else 0.5,
    ))


# ---------------------------------------------------------------------------
# Evidence card builders
# ---------------------------------------------------------------------------

def _build_reference_panel_card(dialog: CBMDialog, task: TaskDefinition) -> EvidenceCard:
    """Build the CBM Evaluator Reference Panel card for a task.

    Always visible alongside webhook results — not on demand.
    Shows user-labeled node names and content text inside each node.
    """
    lines = [f"**Dialog: {dialog.name}**", ""]
    lines.append("**Node Sequence:**")

    for i, node in enumerate(dialog.nodes, 1):
        type_label = node.node_type.upper()
        label = node.user_label
        extra = ""

        if node.is_entity_node:
            extra = f" (type: {node.entity_type or 'unknown'})"
            if node.validation_rules:
                extra += " [has validation rules]"
        elif node.is_service_node:
            extra = f" (method: {node.service_method or 'unknown'})"
        elif node.is_agent_node:
            extra = " (Agent Node - aiassist)"

        lines.append(f"  {i}. [{type_label}] {label}{extra}")

        # Show content text if available
        content_text = node.content_summary
        if content_text:
            display = content_text[:120]
            if len(content_text) > 120:
                display += "..."
            lines.append(f"       └─ {display}")

    content = "\n".join(lines)
    return EvidenceCard(
        card_id=f"cbm.{task.task_id}.reference_panel",
        task_id=task.task_id,
        title=f"CBM Reference Panel — {task.task_name}",
        content=content,
        color=EvidenceCardColor.GREY,
        pipeline="cbm",
        details={
            "dialog_name": dialog.name,
            "node_count": len(dialog.nodes),
            "node_types": [n.node_type for n in dialog.nodes],
            "node_labels": [n.user_label for n in dialog.nodes],
        },
    )


# ---------------------------------------------------------------------------
# Compliance checks
# ---------------------------------------------------------------------------

def evaluate_compliance(
    cbm: CBMObject, checks: list[ComplianceCheck]
) -> list[ComplianceResult]:
    """Run all compliance checks against the CBM object."""
    results = []
    for check in checks:
        actual = _resolve_cbm_field(cbm, check.cbm_field)
        status = _evaluate_compliance_check(actual, check)
        results.append(ComplianceResult(
            check_id=check.check_id,
            label=check.label,
            status=status,
            cbm_field=check.cbm_field,
            actual_value=actual,
            required_state=check.required_state.value,
            critical=check.critical,
            tooltip=check.tooltip,
        ))
    return results


def _resolve_cbm_field(cbm: CBMObject, field_path: str) -> Any:
    """Resolve a dot-path field against the CBM object."""
    # Common known fields
    field_map = {
        "dialogGPTSettings[0].dialogGPTLLMConfig.enable": cbm.dialog_gpt_enabled,
        "dialog_gpt_enabled": cbm.dialog_gpt_enabled,
        "default_language": cbm.default_language,
        "channels": cbm.channels,
    }
    if field_path in field_map:
        return field_map[field_path]

    # Fall back to raw export traversal
    parts = field_path.split(".")
    current: Any = cbm.raw_export
    for part in parts:
        if isinstance(current, dict):
            # Handle array notation
            arr_match = re.match(r'^(\w+)\[(\d+)\]$', part)
            if arr_match:
                key, idx = arr_match.group(1), int(arr_match.group(2))
                current = current.get(key)
                if isinstance(current, list) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                current = current.get(part)
        else:
            return None
    return current


def _evaluate_compliance_check(actual: Any, check: ComplianceCheck) -> CheckStatus:
    """Evaluate a single compliance check."""
    if actual is None:
        return CheckStatus.FAIL

    if check.required_state == ComplianceRequiredState.ENABLED:
        if isinstance(actual, bool):
            return CheckStatus.PASS if actual else CheckStatus.FAIL
        if isinstance(actual, str):
            return CheckStatus.PASS if actual.lower() in ("true", "enabled") else CheckStatus.FAIL

    elif check.required_state == ComplianceRequiredState.DISABLED:
        if isinstance(actual, bool):
            return CheckStatus.PASS if not actual else CheckStatus.FAIL
        if isinstance(actual, str):
            return CheckStatus.PASS if actual.lower() in ("false", "disabled") else CheckStatus.FAIL

    elif check.required_state == ComplianceRequiredState.PRESENT:
        return CheckStatus.PASS

    return CheckStatus.FAIL


# ---------------------------------------------------------------------------
# FAQ structural checks
# ---------------------------------------------------------------------------

def evaluate_faqs_structural(
    cbm: CBMObject, manifest: Manifest
) -> tuple[list[CheckResult], list[EvidenceCard]]:
    """Evaluate FAQ structure from CBM against manifest requirements."""
    checks: list[CheckResult] = []
    cards: list[EvidenceCard] = []
    faq_config = manifest.faq_config

    if not faq_config.required_faqs:
        return checks, cards

    cbm_faqs = cbm.faqs

    # Evidence card: show all FAQs found in CBM
    faq_lines = ["**All FAQs in CBM:**", ""]
    for i, faq in enumerate(cbm_faqs, 1):
        faq_lines.append(f"  {i}. Q: {faq.question}")
        faq_lines.append(f"     A: {faq.answer[:100]}{'...' if len(faq.answer) > 100 else ''}")
        faq_lines.append(f"     Alternates: {len(faq.alternate_questions)}")
        faq_lines.append("")

    cards.append(EvidenceCard(
        card_id="cbm.faq.all_faqs",
        task_id="faq",
        title="CBM FAQ Reference Panel",
        content="\n".join(faq_lines),
        color=EvidenceCardColor.GREY,
        pipeline="cbm",
    ))

    # Check each required FAQ exists in CBM (simple keyword matching for Phase 1)
    for req_faq in faq_config.required_faqs:
        matched = _find_matching_faq(req_faq.primary_question, cbm_faqs)
        if matched:
            # Check alternate question count
            if len(matched.alternate_questions) >= faq_config.min_alternate_questions:
                checks.append(CheckResult(
                    check_id=f"cbm.faq.{_safe_id(req_faq.primary_question)}",
                    task_id="faq",
                    pipeline="cbm",
                    label=f"FAQ: {req_faq.primary_question[:50]}",
                    status=CheckStatus.PASS,
                    details=(
                        f"Found matching FAQ with {len(matched.alternate_questions)} "
                        f"alternate questions."
                    ),
                    score=1.0,
                ))
            else:
                checks.append(CheckResult(
                    check_id=f"cbm.faq.{_safe_id(req_faq.primary_question)}",
                    task_id="faq",
                    pipeline="cbm",
                    label=f"FAQ: {req_faq.primary_question[:50]}",
                    status=CheckStatus.WARNING,
                    details=(
                        f"FAQ found but only {len(matched.alternate_questions)} alternates "
                        f"(minimum: {faq_config.min_alternate_questions})."
                    ),
                    score=0.7,
                ))
        else:
            checks.append(CheckResult(
                check_id=f"cbm.faq.{_safe_id(req_faq.primary_question)}",
                task_id="faq",
                pipeline="cbm",
                label=f"FAQ: {req_faq.primary_question[:50]}",
                status=CheckStatus.FAIL,
                details="Required FAQ not found in CBM.",
                score=0.0,
            ))

    return checks, cards


def _find_matching_faq(question: str, cbm_faqs: list[CBMFAQ]) -> CBMFAQ | None:
    """Find a CBM FAQ matching the required question (keyword overlap)."""
    q_tokens = set(re.split(r'\W+', question.lower()))
    best_match = None
    best_score = 0.0

    for faq in cbm_faqs:
        faq_tokens = set(re.split(r'\W+', faq.question.lower()))
        if not q_tokens or not faq_tokens:
            continue
        overlap = len(q_tokens & faq_tokens)
        score = overlap / max(len(q_tokens), len(faq_tokens))
        if score > best_score:
            best_score = score
            best_match = faq

    # Threshold for Phase 1 keyword matching (semantic matching in Phase 3)
    if best_score >= 0.5:
        return best_match
    return None


def _safe_id(text: str) -> str:
    """Convert text to a safe ID string."""
    return re.sub(r'\W+', '_', text.lower())[:40]
