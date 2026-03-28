import pytest
from governiq.webhook.response_type_detector import ResponseType, detect_response_type


class TestDetectResponseType:
    def test_plain_text(self):
        messages = [{"val": "How can I help you?"}]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.TEXT
        assert payload is None

    def test_buttons_template(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "quick_replies",
                "elements": [
                    {"title": "Option A"},
                    {"title": "Option B"},
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.BUTTONS
        assert payload is not None
        assert len(payload["elements"]) == 2

    def test_inline_form(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "form",
                "formDef": {
                    "name": "RegistrationForm",
                    "components": [
                        {"key": "field1", "displayName": "Field One"},
                        {"key": "field2", "displayName": "Field Two"},
                    ]
                }
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.INLINE_FORM
        assert payload is not None
        assert "formDef" in payload

    def test_carousel(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "carousel",
                "elements": [
                    {"title": "Option A", "subtitle": "Details A"},
                    {"title": "Option B", "subtitle": "Details B"},
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.CAROUSEL
        assert len(payload["elements"]) == 2

    def test_external_url(self):
        messages = [{
            "type": "template",
            "payload": {
                "template_type": "button",
                "elements": [
                    {"type": "web_url", "url": "https://form.example.com/register", "openInTab": True}
                ]
            }
        }]
        rtype, payload = detect_response_type(messages)
        assert rtype == ResponseType.EXTERNAL_URL
        assert "https://" in payload["url"]

    def test_mixed_text_and_template_returns_template_type(self):
        messages = [
            {"val": "Please fill out this form:"},
            {
                "type": "template",
                "payload": {
                    "template_type": "form",
                    "formDef": {"name": "F", "components": []}
                }
            }
        ]
        rtype, _ = detect_response_type(messages)
        assert rtype == ResponseType.INLINE_FORM

    def test_unknown_template_falls_back_to_text(self):
        messages = [{"type": "template", "payload": {"template_type": "unknown_future_type"}}]
        rtype, _ = detect_response_type(messages)
        assert rtype == ResponseType.TEXT

    def test_empty_messages(self):
        rtype, payload = detect_response_type([])
        assert rtype == ResponseType.TEXT
        assert payload is None
