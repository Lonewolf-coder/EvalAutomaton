"""Tests for the CBM Parser — validates correct handling of parser traps."""

import json
from pathlib import Path

import pytest

from governiq.cbm.parser import parse_bot_export, parse_bot_export_file
from governiq.cbm.field_map import NODE_TYPE_AGENT


SAMPLE_EXPORT = Path(__file__).parent / "sample_bot_export.json"


@pytest.fixture
def bot_export():
    with SAMPLE_EXPORT.open("r") as f:
        return json.load(f)


@pytest.fixture
def cbm(bot_export):
    return parse_bot_export(bot_export)


class TestCBMParser:
    """Test the CBM parser handles all three parser traps correctly."""

    def test_bot_metadata(self, cbm):
        assert cbm.bot_name == "Medical Appointment Bot"
        assert cbm.default_language == "en"

    def test_dialogs_parsed(self, cbm):
        assert len(cbm.dialogs) == 4
        names = [d.name for d in cbm.dialogs]
        assert "Welcome" in names
        assert "Book Appointment" in names
        assert "Get Appointment Details" in names
        assert "Modify Appointment Details" in names

    def test_trap1_dialog_gpt_is_array(self, cbm):
        """TRAP 1: dialogGPTSettings is an ARRAY, not an object."""
        assert cbm.dialog_gpt_enabled is True

    def test_trap2_faqs_faqs(self, cbm):
        """TRAP 2: FAQ array is at knowledgeTasks[0].faqs.faqs."""
        assert len(cbm.faqs) == 4
        assert cbm.faqs[0].question == "What are your working hours?"

    def test_trap3_agent_node_type(self, cbm):
        """TRAP 3: Agent Node type is 'aiassist', not 'agent'."""
        book_dialog = cbm.find_dialog("Book Appointment")
        assert book_dialog is not None
        assert book_dialog.has_agent_node()
        agent_nodes = book_dialog.get_nodes_by_type(NODE_TYPE_AGENT)
        assert len(agent_nodes) == 1
        assert agent_nodes[0].node_type == "aiassist"

    def test_dialog_find_contains(self, cbm):
        dialog = cbm.find_dialog("Book", policy="contains")
        assert dialog is not None
        assert "Book" in dialog.name

    def test_dialog_find_exact(self, cbm):
        dialog = cbm.find_dialog("Welcome", policy="exact")
        assert dialog is not None
        assert dialog.name == "Welcome"

    def test_service_nodes(self, cbm):
        book_dialog = cbm.find_dialog("Book Appointment")
        assert book_dialog is not None
        service_nodes = book_dialog.get_service_nodes()
        assert len(service_nodes) == 1
        assert service_nodes[0].service_method == "POST"

    def test_entity_nodes(self, cbm):
        book_dialog = cbm.find_dialog("Book Appointment")
        assert book_dialog is not None
        entity_nodes = book_dialog.get_entity_nodes()
        assert len(entity_nodes) == 6
        entity_names = {n.name for n in entity_nodes}
        assert "patientName" in entity_names
        assert "contactNumber" in entity_names

    def test_validation_rules(self, cbm):
        book_dialog = cbm.find_dialog("Book Appointment")
        contact_node = next(
            n for n in book_dialog.get_entity_nodes() if n.name == "contactNumber"
        )
        assert len(contact_node.validation_rules) == 1

    def test_faq_alternates(self, cbm):
        first_faq = cbm.faqs[0]
        assert len(first_faq.alternate_questions) >= 2

    def test_get_dialog_has_not_found_message(self, cbm):
        get_dialog = cbm.find_dialog("Get Appointment")
        assert get_dialog is not None
        message_nodes = get_dialog.get_nodes_by_type("message")
        not_found = [n for n in message_nodes if "no appointment was found" in n.message_text.lower()]
        assert len(not_found) == 1

    def test_modify_dialog_has_all_service_types(self, cbm):
        mod_dialog = cbm.find_dialog("Modify Appointment")
        assert mod_dialog is not None
        service_nodes = mod_dialog.get_service_nodes()
        methods = {n.service_method for n in service_nodes}
        assert "GET" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_component_map(self, cbm):
        assert len(cbm.component_map) == 4

    def test_parse_from_file(self):
        cbm = parse_bot_export_file(SAMPLE_EXPORT)
        assert cbm.bot_name == "Medical Appointment Bot"
        assert len(cbm.dialogs) == 4
