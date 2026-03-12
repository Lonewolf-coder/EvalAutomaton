"""CBM Blueprint — Structured bot overview for the evaluator's Blueprint Panel.

Generates a serializable summary of the parsed CBM object. Purely informational;
no scoring logic. Saved to ./data/blueprints/{session_id}.json by the engine.

Reuses CBMNode.content_summary and CBMDialog.connection_graph from parser.py
to avoid duplicating field-path logic.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .parser import CBMDialog, CBMNode, CBMObject


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class NodeBlueprint:
    node_id: str
    node_type: str
    name: str
    content_summary: str
    service_method: str | None
    service_host: str | None          # host only — path masked for security
    entity_type: str | None
    ai_assist_context: str | None     # truncated to 200 chars
    logic_branches: int               # number of conditional transitions


@dataclass
class DialogBlueprint:
    dialog_id: str
    dialog_name: str
    short_desc: str
    node_count: int
    node_types: list[str]             # unique types in appearance order
    nodes: list[NodeBlueprint]
    has_agent_node: bool
    has_service_node: bool
    service_methods: list[str]        # e.g. ["get", "post"]
    connection_edges: list[list]      # [[from_id, to_id, condition_label], ...]


@dataclass
class BotOverviewBlueprint:
    bot_name: str
    bot_version: str
    languages: list[str]
    dialog_gpt_enabled: bool | None
    dialog_gpt_model: str
    llm_features: list[str]           # enabled feature names
    total_dialogs: int
    total_nodes: int
    total_faqs: int
    node_type_counts: dict[str, int]  # {"aiassist": 3, "service": 7, ...}
    custom_dashboard_count: int
    channels_configured: list[str]   # always empty in known exports


@dataclass
class CBMBlueprint:
    bot_overview: BotOverviewBlueprint
    dialogs: list[DialogBlueprint]
    faq_count: int
    faq_topics: list[str]             # first question per FAQ, truncated to 80 chars
    generated_at: str                 # ISO-8601 UTC


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------

def _mask_url(service_url: str | None) -> str | None:
    """Return only the hostname (strip path, query, credentials)."""
    if not service_url:
        return None
    try:
        return urlparse(service_url).hostname or service_url
    except Exception:
        return service_url


def _truncate(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text[:limit] + "..." if len(text) > limit else text


def _build_node_blueprint(node: CBMNode) -> NodeBlueprint:
    logic_branches = len(node.logic_conditions) if node.logic_conditions else 0
    return NodeBlueprint(
        node_id=node.node_id,
        node_type=node.node_type,
        name=node.name,
        content_summary=node.content_summary,
        service_method=node.service_method,
        service_host=_mask_url(node.service_url),
        entity_type=node.entity_type,
        ai_assist_context=_truncate(node.ai_assist_context, 200),
        logic_branches=logic_branches,
    )


def _build_dialog_blueprint(dialog: CBMDialog) -> DialogBlueprint:
    seen_types: list[str] = []
    for n in dialog.nodes:
        if n.node_type not in seen_types:
            seen_types.append(n.node_type)

    service_methods = list({
        n.service_method
        for n in dialog.nodes
        if n.is_service_node and n.service_method
    })

    return DialogBlueprint(
        dialog_id=dialog.dialog_id,
        dialog_name=dialog.name,
        short_desc=dialog.short_desc,
        node_count=len(dialog.nodes),
        node_types=seen_types,
        nodes=[_build_node_blueprint(n) for n in dialog.nodes],
        has_agent_node=dialog.has_agent_node(),
        has_service_node=any(n.is_service_node for n in dialog.nodes),
        service_methods=service_methods,
        connection_edges=[list(edge) for edge in dialog.connection_graph],
    )


def _build_overview(cbm: CBMObject) -> BotOverviewBlueprint:
    all_nodes = [n for d in cbm.dialogs for n in d.nodes]
    node_type_counts = dict(Counter(n.node_type for n in all_nodes))

    enabled_features = [
        f.get("name", "")
        for f in cbm.llm_features
        if isinstance(f, dict) and f.get("enable")
    ]

    return BotOverviewBlueprint(
        bot_name=cbm.bot_name,
        bot_version=cbm.bot_version,
        languages=cbm.languages,
        dialog_gpt_enabled=cbm.dialog_gpt_enabled,
        dialog_gpt_model=cbm.dialog_gpt_model,
        llm_features=enabled_features,
        total_dialogs=len(cbm.dialogs),
        total_nodes=len(all_nodes),
        total_faqs=len(cbm.faqs),
        node_type_counts=node_type_counts,
        custom_dashboard_count=len(cbm.custom_dashboards),
        channels_configured=[c.get("type", "") for c in cbm.channels if isinstance(c, dict)],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_blueprint(cbm: CBMObject) -> CBMBlueprint:
    """Generate a complete CBMBlueprint from a parsed CBM object."""
    overview = _build_overview(cbm)
    dialogs = [_build_dialog_blueprint(d) for d in cbm.dialogs]
    faq_topics = [
        (faq.question[:80] + "..." if len(faq.question) > 80 else faq.question)
        for faq in cbm.faqs
    ]
    return CBMBlueprint(
        bot_overview=overview,
        dialogs=dialogs,
        faq_count=len(cbm.faqs),
        faq_topics=faq_topics,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def blueprint_to_dict(bp: CBMBlueprint) -> dict[str, Any]:
    """Serialize a CBMBlueprint to a JSON-serializable dict."""
    return asdict(bp)


def save_blueprint(
    bp: CBMBlueprint,
    session_id: str,
    data_dir: str = "./data",
) -> Path:
    """Save blueprint JSON to {data_dir}/blueprints/{session_id}.json.

    Creates the directory if it does not exist.
    Returns the path to the saved file.
    """
    out_dir = Path(data_dir) / "blueprints"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session_id}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(blueprint_to_dict(bp), f, indent=2)
    return out_path
