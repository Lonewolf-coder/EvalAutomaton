import pytest
from governiq.webhook.semantic_field_mapper import SemanticFieldMapper, MappingResult


class TestButtonMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_exact_match(self):
        buttons = [
            {"title": "Option A"},
            {"title": "Option B"},
            {"title": "Option C"},
        ]
        result = self.mapper.map_buttons(buttons, target_value="Option B")
        assert result.matched_label == "Option B"
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_contains_match(self):
        buttons = [
            {"title": "Select Option Alpha"},
            {"title": "Select Option Beta"},
        ]
        result = self.mapper.map_buttons(buttons, target_value="Alpha")
        assert result.matched_label == "Select Option Alpha"
        assert result.strategy == "contains"

    def test_no_match_returns_first_as_fallback(self):
        buttons = [{"title": "Option A"}, {"title": "Option B"}]
        result = self.mapper.map_buttons(buttons, target_value="Completely Unrelated Xyz")
        assert result.matched_label is not None
        assert result.confidence < 0.5

    def test_empty_buttons_raises(self):
        with pytest.raises(ValueError, match="No buttons"):
            self.mapper.map_buttons([], target_value="Anything")


class TestFormMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_label_hint_match(self):
        form_components = [
            {"key": "comp1", "displayName": "First Name"},
            {"key": "comp2", "displayName": "Date of Birth"},
        ]
        entity_map = {
            "firstName": {
                "value": "Jordan",
                "label_hints": ["First Name", "Name"],
            },
            "dateOfBirth": {
                "value": "01-01-1990",
                "label_hints": ["Date of Birth", "Birthday"],
            },
        }
        result = self.mapper.map_form(form_components, entity_map)
        assert result["comp1"] == "Jordan"
        assert result["comp2"] == "01-01-1990"

    def test_unmapped_component_returns_none(self):
        form_components = [{"key": "comp_unknown", "displayName": "Unknown Field"}]
        entity_map = {
            "firstName": {"value": "Jordan", "label_hints": ["First Name"]},
        }
        result = self.mapper.map_form(form_components, entity_map)
        assert result.get("comp_unknown") is None


class TestCarouselMapping:
    def setup_method(self):
        self.mapper = SemanticFieldMapper()

    def test_semantic_match(self):
        cards = [
            {"title": "Option A — Category 1"},
            {"title": "Option B — Category 2"},
            {"title": "Option C — Category 3"},
        ]
        # "Category 2" should semantically match "Option B — Category 2"
        result = self.mapper.map_carousel(cards, target_value="Category 2", strategy="semantic")
        assert result.matched_label == "Option B — Category 2"
        assert result.strategy == "semantic"

    def test_exact_carousel_match(self):
        cards = [{"title": "Option A"}, {"title": "Option B"}]
        result = self.mapper.map_carousel(cards, target_value="Option A", strategy="exact")
        assert result.matched_label == "Option A"
        assert result.confidence == 1.0

    def test_empty_carousel_raises(self):
        with pytest.raises(ValueError, match="No carousel cards"):
            self.mapper.map_carousel([], target_value="anything", strategy="exact")
