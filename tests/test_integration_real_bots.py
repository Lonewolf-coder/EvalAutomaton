"""Integration tests — parse all 9 real Kore.ai bot exports.

These tests verify the Phase 1 parser fixes work against the actual bot exports,
not just the synthetic sample fixture. They assert on real structural properties
discovered during the Phase 1 deep-dive analysis.
"""

import pathlib

import pytest

from governiq.cbm.parser import (
    parse_bot_export_file,
    parse_bot_export_zip,
)

BOT_EXPORTS = pathlib.Path("tests/bot_exports")
MEDICAL_V1 = BOT_EXPORTS / "Medi_Assistant v.1" / "appDefinition.json"
MEDICAL_V2 = BOT_EXPORTS / "Medi_Assistant_Ai V.2" / "appDefinition.json"
TRAVEL_ZIPS = sorted(BOT_EXPORTS.glob("*.zip"))  # 7 Travel ZIPs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_node_types(cbm) -> set[str]:
    return {n.node_type for d in cbm.dialogs for n in d.nodes}


def _all_service_methods(cbm) -> set[str]:
    return {
        n.service_method.upper()
        for d in cbm.dialogs
        for n in d.nodes
        if n.is_service_node and n.service_method
    }


# ---------------------------------------------------------------------------
# Core parsing — all bots must parse without error
# ---------------------------------------------------------------------------

class TestRealBotParsing:

    def test_all_travel_zips_parse(self):
        """All 7 Travel ZIPs parse without error and have plausible structure."""
        assert len(TRAVEL_ZIPS) == 7, f"Expected 7 Travel ZIPs, found {len(TRAVEL_ZIPS)}"
        for z in TRAVEL_ZIPS:
            cbm = parse_bot_export_zip(z)
            assert cbm.bot_name != "", f"{z.name}: bot_name is empty"
            assert len(cbm.dialogs) >= 10, f"{z.name}: only {len(cbm.dialogs)} dialogs"
            assert cbm.dialog_gpt_enabled is True, f"{z.name}: dialog_gpt not enabled"

    def test_medical_v1_structure(self):
        cbm = parse_bot_export_file(MEDICAL_V1)
        assert cbm.bot_name == "Medi_Assistant"
        assert len(cbm.dialogs) == 12
        assert len(cbm.faqs) == 5
        assert cbm.dialog_gpt_enabled is True
        # Agent nodes with real system context
        agent_nodes = [n for d in cbm.dialogs for n in d.nodes if n.is_agent_node]
        assert len(agent_nodes) >= 1
        assert any(n.ai_assist_context for n in agent_nodes), "Expected at least 1 aiassist with context"

    def test_medical_v1_faq_answer_is_string(self):
        cbm = parse_bot_export_file(MEDICAL_V1)
        for faq in cbm.faqs:
            assert isinstance(faq.answer, str), f"FAQ answer should be str, got {type(faq.answer)}"
            assert len(faq.answer) > 0, f"FAQ '{faq.question}' has empty answer"

    def test_medical_v2_structure(self):
        cbm = parse_bot_export_file(MEDICAL_V2)
        # This bot's localeData name is "app6" (internal placeholder, not "Medi_Assistant")
        assert cbm.bot_name != "", "bot_name should not be empty"
        assert len(cbm.dialogs) == 12
        assert cbm.dialog_gpt_enabled is True
        entity_nodes = [n for d in cbm.dialogs for n in d.nodes if n.is_entity_node]
        assert len(entity_nodes) == 20

    def test_travel_ai_agent_11_structure(self):
        """Travel AI Agent (11) — 13 dialogs, 5 FAQs, has Book a Flight with aiassist."""
        cbm = parse_bot_export_zip(BOT_EXPORTS / "Travel AI Agent (11).zip")
        assert cbm.bot_name == "Travel AI Agent"
        assert len(cbm.dialogs) == 13
        assert len(cbm.faqs) == 5
        # Book a Flight dialog must exist and have an aiassist node
        book = cbm.find_dialog("Book a Flight", policy="contains")
        assert book is not None, "Should find 'Book a Flight' dialog"
        assert book.has_agent_node(), "Book a Flight must have aiassist node"

    def test_travel_ai_agent32_structure(self):
        """Travel AI Agent32 — 10 dialogs, 0 FAQs, has both generativeai and searchai."""
        cbm = parse_bot_export_zip(BOT_EXPORTS / "Travel AI Agent32.zip")
        assert cbm.bot_name == "Travel AI Agent"
        assert len(cbm.dialogs) == 10
        assert len(cbm.faqs) == 0
        types = _all_node_types(cbm)
        assert "generativeai" in types
        assert "searchai" in types
        # aiassist nodes with context (TRAP 12: systemContext camelCase)
        agent_nodes = [n for d in cbm.dialogs for n in d.nodes if n.is_agent_node]
        assert len(agent_nodes) >= 1
        assert any(n.ai_assist_context for n in agent_nodes), "Expected aiassist with systemContext"

    def test_travel_va_new_structure(self):
        """Travel VA New — 16 dialogs, most feature-rich bot: form, generativeai, agentTransfer."""
        cbm = parse_bot_export_zip(BOT_EXPORTS / "Travel VA New.zip")
        assert cbm.bot_name == "Travel VA New"
        assert len(cbm.dialogs) == 16
        assert len(cbm.faqs) == 5
        types = _all_node_types(cbm)
        assert "form" in types, "Expected form node"
        assert "generativeai" in types, "Expected generativeai node"
        assert "agentTransfer" in types, "Expected agentTransfer node"

    def test_travel_va_new_basic_identical_to_travel_va_new(self):
        """Travel VA New basic.zip is identical in structure to Travel VA New.zip."""
        cbm_a = parse_bot_export_zip(BOT_EXPORTS / "Travel VA New.zip")
        cbm_b = parse_bot_export_zip(BOT_EXPORTS / "Travel VA New basic.zip")
        assert cbm_a.bot_name == cbm_b.bot_name
        assert len(cbm_a.dialogs) == len(cbm_b.dialogs)
        assert len(cbm_a.faqs) == len(cbm_b.faqs)

    def test_travel_ai_agent_n_basic_identical_to_travel_ai_agent(self):
        """Travel Ai Agent N Basic.zip is identical to Travel Ai Agent.zip."""
        cbm_a = parse_bot_export_zip(BOT_EXPORTS / "Travel Ai Agent.zip")
        cbm_b = parse_bot_export_zip(BOT_EXPORTS / "Travel Ai Agent N Basic.zip")
        assert cbm_a.bot_name == cbm_b.bot_name
        assert len(cbm_a.dialogs) == len(cbm_b.dialogs)


# ---------------------------------------------------------------------------
# Cross-bot structural facts (confirmed in Phase 1 analysis)
# ---------------------------------------------------------------------------

class TestCrossBotStructuralFacts:

    def _get_all_cbms(self):
        """Parse all 9 real bots. Expensive; only call once per test."""
        cbms = []
        cbms.append(parse_bot_export_file(MEDICAL_V1))
        cbms.append(parse_bot_export_file(MEDICAL_V2))
        for z in TRAVEL_ZIPS:
            cbms.append(parse_bot_export_zip(z))
        return cbms

    def test_no_confirmation_nodes_in_any_bot(self):
        """CONFIRMED in Phase 1: no bot uses the 'confirmation' node type."""
        for cbm in self._get_all_cbms():
            types = _all_node_types(cbm)
            assert "confirmation" not in types, (
                f"{cbm.bot_name}: unexpected 'confirmation' node — update field_map.py!"
            )

    def test_all_channels_empty(self):
        """CONFIRMED in Phase 1: channels are always configured in the platform, never exported."""
        for cbm in self._get_all_cbms():
            assert len(cbm.channels) == 0, (
                f"{cbm.bot_name}: channels is not empty — update field guide!"
            )

    def test_dialog_gpt_enabled_all_bots(self):
        """All 9 real bots have DialogGPT enabled."""
        for cbm in self._get_all_cbms():
            assert cbm.dialog_gpt_enabled is True, (
                f"{cbm.bot_name}: dialog_gpt_enabled is {cbm.dialog_gpt_enabled}"
            )

    def test_faqs_answer_is_string_all_bots(self):
        """TRAP 9: FAQ answer should be extracted as a plain string, not left as a list."""
        for cbm in self._get_all_cbms():
            for faq in cbm.faqs:
                assert isinstance(faq.answer, str), (
                    f"{cbm.bot_name}: FAQ answer is {type(faq.answer).__name__}, not str"
                )
                assert len(faq.answer) > 0, (
                    f"{cbm.bot_name}: FAQ '{faq.question}' has empty answer text"
                )

    def test_service_method_is_valid_http_verb(self):
        """All service nodes have a valid HTTP method (lowercase, as stored in JSON)."""
        valid = {"get", "post", "put", "patch", "delete"}
        for cbm in self._get_all_cbms():
            for d in cbm.dialogs:
                for n in d.nodes:
                    if n.is_service_node and n.service_method is not None:
                        assert n.service_method.lower() in valid, (
                            f"{cbm.bot_name}/{d.name}/{n.name}: "
                            f"unexpected service_method '{n.service_method}'"
                        )

    def test_bot_names_not_empty_all_bots(self):
        """TRAP 4: bot name parsed from localeData.en.name, not the old botInfo key."""
        for cbm in self._get_all_cbms():
            assert cbm.bot_name != "", f"bot_name is empty — TRAP 4 regression?"

    def test_dialog_names_not_empty_all_bots(self):
        """TRAP 5: dialog names parsed from localeData.en.name, not dialog['name']."""
        for cbm in self._get_all_cbms():
            for d in cbm.dialogs:
                assert d.name != "", (
                    f"{cbm.bot_name}: dialog with _id={d.dialog_id} has empty name — TRAP 5 regression?"
                )

    def test_node_names_resolved_via_component_lookup(self):
        """TRAP 6+7: node names come from dialogComponents, not the stub."""
        for cbm in self._get_all_cbms():
            # Message, entity, and service nodes should always have non-empty names
            for d in cbm.dialogs:
                for n in d.nodes:
                    if n.node_type in ("message", "entity", "service", "aiassist"):
                        assert n.name != "", (
                            f"{cbm.bot_name}/{d.name}: {n.node_type} node has empty name — "
                            "componentId resolution may be broken (TRAP 6/7)"
                        )
