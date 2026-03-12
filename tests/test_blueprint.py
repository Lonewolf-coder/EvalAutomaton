"""Tests for the CBM Blueprint module."""

import json
from pathlib import Path

import pytest

from governiq.cbm.blueprint import (
    CBMBlueprint,
    generate_blueprint,
    blueprint_to_dict,
    save_blueprint,
)
from governiq.cbm.parser import parse_bot_export

SAMPLE_EXPORT = Path(__file__).parent / "sample_bot_export.json"


@pytest.fixture
def cbm():
    with SAMPLE_EXPORT.open() as f:
        data = json.load(f)
    return parse_bot_export(data)


@pytest.fixture
def blueprint(cbm):
    return generate_blueprint(cbm)


class TestBlueprintGeneration:

    def test_generate_returns_cbm_blueprint(self, blueprint):
        assert isinstance(blueprint, CBMBlueprint)

    def test_bot_overview_metadata(self, blueprint):
        ov = blueprint.bot_overview
        assert ov.bot_name == "Medical Appointment Bot"
        assert ov.total_dialogs == 4
        assert ov.total_faqs == 4
        assert ov.dialog_gpt_enabled is True

    def test_bot_overview_node_type_counts(self, blueprint):
        counts = blueprint.bot_overview.node_type_counts
        assert "entity" in counts
        assert counts["entity"] >= 6
        assert "message" in counts
        assert "service" in counts
        assert "aiassist" in counts

    def test_dialogs_all_present(self, blueprint):
        assert len(blueprint.dialogs) == 4
        names = {d.dialog_name for d in blueprint.dialogs}
        assert "Welcome" in names
        assert "Book Appointment" in names
        assert "Get Appointment Details" in names
        assert "Modify Appointment Details" in names

    def test_booking_dialog_blueprint(self, blueprint):
        book = next(d for d in blueprint.dialogs if "Book" in d.dialog_name)
        assert book.has_agent_node is True
        assert book.has_service_node is True
        assert book.node_count == 9
        methods_upper = [m.upper() for m in book.service_methods]
        assert "POST" in methods_upper

    def test_modify_dialog_has_all_service_methods(self, blueprint):
        mod = next(d for d in blueprint.dialogs if "Modify" in d.dialog_name)
        methods_upper = {m.upper() for m in mod.service_methods}
        assert "GET" in methods_upper
        assert "PUT" in methods_upper
        assert "DELETE" in methods_upper

    def test_node_blueprints_have_correct_types(self, blueprint):
        book = next(d for d in blueprint.dialogs if "Book" in d.dialog_name)
        types = [n.node_type for n in book.nodes]
        assert "aiassist" in types
        assert "service" in types
        assert "entity" in types

    def test_service_host_masked(self, blueprint):
        """Service URL in NodeBlueprint shows only host, not full path."""
        for d in blueprint.dialogs:
            for n in d.nodes:
                if n.node_type == "service" and n.service_host:
                    # Should be host only (no slashes in path)
                    assert "/" not in n.service_host, (
                        f"service_host should be host only, got: {n.service_host}"
                    )

    def test_faq_topics_present(self, blueprint):
        assert blueprint.faq_count == 4
        assert len(blueprint.faq_topics) == 4
        assert blueprint.faq_topics[0].startswith("What are your working hours")

    def test_total_nodes_count(self, blueprint):
        # 1 + 9 + 4 + 8 = 22 nodes across 4 dialogs
        assert blueprint.bot_overview.total_nodes == 22

    def test_node_types_appearance_order(self, blueprint):
        """node_types list preserves first-appearance order, no duplicates."""
        for d in blueprint.dialogs:
            assert len(d.node_types) == len(set(d.node_types)), (
                f"{d.dialog_name}: node_types has duplicates"
            )

    def test_generated_at_is_iso_string(self, blueprint):
        from datetime import datetime
        # Should parse without error
        datetime.fromisoformat(blueprint.generated_at)


class TestBlueprintSerialization:

    def test_blueprint_to_dict_is_serializable(self, blueprint):
        bp_dict = blueprint_to_dict(blueprint)
        # Must not raise
        serialized = json.dumps(bp_dict)
        assert len(serialized) > 100

    def test_blueprint_to_dict_structure(self, blueprint):
        bp_dict = blueprint_to_dict(blueprint)
        assert "bot_overview" in bp_dict
        assert "dialogs" in bp_dict
        assert "faq_count" in bp_dict
        assert "faq_topics" in bp_dict
        assert "generated_at" in bp_dict

    def test_save_blueprint_creates_file(self, blueprint, tmp_path):
        out_path = save_blueprint(blueprint, "test-session-001", data_dir=str(tmp_path))
        assert out_path.exists()
        with out_path.open() as f:
            loaded = json.load(f)
        assert loaded["bot_overview"]["bot_name"] == "Medical Appointment Bot"

    def test_save_blueprint_creates_directory(self, blueprint, tmp_path):
        deep_dir = tmp_path / "nested" / "dir"
        save_blueprint(blueprint, "session-x", data_dir=str(deep_dir))
        assert (deep_dir / "blueprints" / "session-x.json").exists()
