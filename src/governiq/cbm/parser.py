"""CBM Parser — Parses Kore.ai bot exports into a structured CBM object.

Respects the three parser traps:
1. dialogGPTSettings is an ARRAY — access [0]
2. FAQ array is knowledgeTasks[0].faqs.faqs — NOT .faqs
3. Agent Node type is 'aiassist' — not 'agent'
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import field_map as fm


# ---------------------------------------------------------------------------
# Data structures the parser produces
# ---------------------------------------------------------------------------

@dataclass
class CBMNode:
    """A single node in a dialog flow."""
    node_id: str
    node_type: str
    name: str
    component: dict[str, Any] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_agent_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_AGENT

    @property
    def is_service_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_SERVICE

    @property
    def is_entity_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_ENTITY

    @property
    def is_message_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_MESSAGE

    @property
    def is_form_node(self) -> bool:
        return self.node_type == fm.NODE_TYPE_FORM

    @property
    def service_method(self) -> str | None:
        if self.is_service_node:
            return self.component.get("method") or self.raw.get("method")
        return None

    @property
    def entity_type(self) -> str | None:
        if self.is_entity_node:
            return self.component.get("entityType") or self.raw.get("entityType")
        return None

    @property
    def user_label(self) -> str:
        """The user-visible label for this node (what the bot builder named it).

        Tries multiple locations since Kore.ai stores display names inconsistently.
        """
        for key in ("title", "displayName", "label"):
            val = self.raw.get(key) or self.component.get(key)
            if val:
                return str(val)
        return self.name

    @property
    def message_text(self) -> str:
        """Extract message text from component, handling multiple formats."""
        comp = self.component
        # Try common Kore.ai message locations
        for path in ["message", "text", "prompt", "msg"]:
            if path in comp:
                val = comp[path]
                if isinstance(val, list):
                    return " ".join(str(v) for v in val)
                return str(val)
        return ""

    @property
    def content_summary(self) -> str:
        """Human-readable content summary showing what's inside the node."""
        if self.is_message_node:
            return self.message_text[:200] if self.message_text else ""
        if self.is_entity_node:
            prompt = ""
            for key in ("prompt", "question", "message"):
                val = self.component.get(key) or self.raw.get(key)
                if val:
                    prompt = str(val)[:150]
                    break
            entity_t = self.entity_type or "unknown"
            return f"[{entity_t}] {prompt}" if prompt else f"[{entity_t}]"
        if self.is_service_node:
            method = self.service_method or "unknown"
            url = self.component.get("url") or self.raw.get("url") or ""
            return f"{method} {url[:120]}" if url else method
        if self.node_type == "script":
            code = self.component.get("script") or self.raw.get("script") or ""
            if isinstance(code, str) and code.strip():
                lines = [l.strip() for l in code.strip().split("\n") if l.strip()]
                return lines[0][:150] if lines else ""
            return ""
        if self.is_agent_node:
            return "Agent Node (aiassist) — handles amendments"
        return ""

    @property
    def validation_rules(self) -> list[dict[str, Any]]:
        if self.is_entity_node:
            rules = self.component.get("validationRules") or self.raw.get("validationRules")
            return rules if isinstance(rules, list) else []
        return []


@dataclass
class CBMDialog:
    """A parsed dialog with its node sequence."""
    name: str
    dialog_id: str
    nodes: list[CBMNode] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def get_nodes_by_type(self, node_type: str) -> list[CBMNode]:
        return [n for n in self.nodes if n.node_type == node_type]

    def has_node_type(self, node_type: str) -> bool:
        return any(n.node_type == node_type for n in self.nodes)

    def get_entity_nodes(self) -> list[CBMNode]:
        return self.get_nodes_by_type(fm.NODE_TYPE_ENTITY)

    def get_service_nodes(self) -> list[CBMNode]:
        return self.get_nodes_by_type(fm.NODE_TYPE_SERVICE)

    def has_agent_node(self) -> bool:
        return self.has_node_type(fm.NODE_TYPE_AGENT)


@dataclass
class CBMFAQ:
    """A single FAQ entry from the knowledge task."""
    question: str
    answer: str
    alternate_questions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CBMObject:
    """The complete structured CBM object produced by the parser.

    This is the single output of the CBM pipeline. The evaluation engine
    and CBM Map renderer work from this object exclusively.
    """
    bot_name: str = ""
    bot_description: str = ""
    default_language: str = ""
    dialogs: list[CBMDialog] = field(default_factory=list)
    faqs: list[CBMFAQ] = field(default_factory=list)
    dialog_gpt_enabled: bool | None = None
    component_map: dict[str, Any] = field(default_factory=dict)
    channels: list[dict[str, Any]] = field(default_factory=list)
    raw_export: dict[str, Any] = field(default_factory=dict)

    def find_dialog(self, name: str, policy: str = "contains") -> CBMDialog | None:
        """Find a dialog by name using the specified matching policy."""
        name_lower = name.lower()
        for dialog in self.dialogs:
            dialog_lower = dialog.name.lower()
            if policy == "exact" and dialog_lower == name_lower:
                return dialog
            elif policy == "contains" and name_lower in dialog_lower:
                return dialog
            elif policy == "contains" and dialog_lower in name_lower:
                return dialog
        return None

    def find_dialog_fuzzy(self, name: str) -> tuple[CBMDialog | None, float]:
        """Fuzzy match a dialog name. Returns (dialog, similarity_score)."""
        if not self.dialogs:
            return None, 0.0

        name_lower = name.lower()
        best_match = None
        best_score = 0.0

        for dialog in self.dialogs:
            dialog_lower = dialog.name.lower()
            # Simple token overlap similarity
            name_tokens = set(re.split(r'\W+', name_lower))
            dialog_tokens = set(re.split(r'\W+', dialog_lower))
            if not name_tokens or not dialog_tokens:
                continue
            overlap = len(name_tokens & dialog_tokens)
            score = overlap / max(len(name_tokens), len(dialog_tokens))
            if score > best_score:
                best_score = score
                best_match = dialog

        return best_match, best_score


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """Resolve a dot/bracket path against a dict. Returns None if not found."""
    current = data
    # Split on dots but handle array indexing like [0]
    parts = re.split(r'\.', path)
    for part in parts:
        if current is None:
            return None
        # Handle array index: e.g. "dialogGPTSettings[0]"
        match = re.match(r'^(\w+)\[(\d+)\]$', part)
        if match:
            key, idx = match.group(1), int(match.group(2))
            current = current.get(key) if isinstance(current, dict) else None
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            current = current.get(part) if isinstance(current, dict) else None
    return current


def _parse_nodes(raw_nodes: list[dict[str, Any]]) -> list[CBMNode]:
    """Parse a list of raw node dicts into CBMNode objects."""
    nodes = []
    for raw in raw_nodes:
        node = CBMNode(
            node_id=raw.get("nodeId", raw.get("_id", "")),
            node_type=raw.get("type", "unknown"),
            name=raw.get("name", ""),
            component=raw.get("component", {}),
            transitions=raw.get("transitions", []),
            raw=raw,
        )
        nodes.append(node)
    return nodes


def _parse_dialogs(raw_dialogs: list[dict[str, Any]]) -> list[CBMDialog]:
    """Parse raw dialog array into CBMDialog objects."""
    dialogs = []
    for raw in raw_dialogs:
        raw_nodes = raw.get("nodes", [])
        dialog = CBMDialog(
            name=raw.get("name", ""),
            dialog_id=raw.get("_id", raw.get("dialogId", "")),
            nodes=_parse_nodes(raw_nodes),
            raw=raw,
        )
        dialogs.append(dialog)
    return dialogs


def _parse_faqs(raw_export: dict[str, Any]) -> list[CBMFAQ]:
    """Parse FAQs respecting TRAP 2: knowledgeTasks[0].faqs.faqs."""
    knowledge_tasks = raw_export.get("knowledgeTasks", [])
    if not knowledge_tasks:
        return []

    # TRAP 2: The FAQ array is at .faqs.faqs, NOT .faqs
    first_kt = knowledge_tasks[0]
    faqs_container = first_kt.get("faqs", {})
    faq_array = faqs_container.get("faqs", []) if isinstance(faqs_container, dict) else []

    parsed = []
    for raw in faq_array:
        faq = CBMFAQ(
            question=raw.get("question", ""),
            answer=raw.get("answer", ""),
            alternate_questions=raw.get("alternateQuestions", []),
            raw=raw,
        )
        parsed.append(faq)
    return parsed


def _parse_dialog_gpt(raw_export: dict[str, Any]) -> bool | None:
    """Parse DialogGPT setting respecting TRAP 1: dialogGPTSettings is an ARRAY."""
    settings = raw_export.get("dialogGPTSettings", [])
    if not isinstance(settings, list) or not settings:
        return None

    # TRAP 1: Access [0].dialogGPTLLMConfig.enable
    first = settings[0]
    llm_config = first.get("dialogGPTLLMConfig", {})
    enable = llm_config.get("enable")
    if isinstance(enable, bool):
        return enable
    if isinstance(enable, str):
        return enable.lower() == "true"
    return None


def parse_bot_export(export_data: dict[str, Any]) -> CBMObject:
    """Parse a Kore.ai bot export JSON into a structured CBM object.

    This is the main entry point for the CBM parser. It handles:
    - Dialog parsing with full node sequences
    - FAQ extraction (respecting the faqs.faqs trap)
    - DialogGPT settings (respecting the array trap)
    - Component map for dialog name resolution
    - Channel configuration

    Args:
        export_data: The raw bot export JSON (appDefinition.json content)

    Returns:
        CBMObject with all structural information extracted.
    """
    # Bot metadata
    bot_info = export_data.get("botInfo", {})
    bot_name = bot_info.get("name", "")
    bot_desc = bot_info.get("description", "")
    default_lang = bot_info.get("defaultLanguage", "en")

    # Dialogs
    raw_dialogs = export_data.get("dialogs", [])
    dialogs = _parse_dialogs(raw_dialogs)

    # FAQs (TRAP 2)
    faqs = _parse_faqs(export_data)

    # DialogGPT (TRAP 1)
    dialog_gpt_enabled = _parse_dialog_gpt(export_data)

    # Component map
    component_map = export_data.get("componentMap", {})

    # Channels
    channels = export_data.get("channels", [])

    return CBMObject(
        bot_name=bot_name,
        bot_description=bot_desc,
        default_language=default_lang,
        dialogs=dialogs,
        faqs=faqs,
        dialog_gpt_enabled=dialog_gpt_enabled,
        component_map=component_map,
        channels=channels if isinstance(channels, list) else [],
        raw_export=export_data,
    )


def parse_bot_export_file(file_path: str | Path) -> CBMObject:
    """Convenience: parse a bot export from a JSON file path."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_bot_export(data)
