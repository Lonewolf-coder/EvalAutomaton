# tests/test_message_normaliser.py
import pytest
from src.governiq.webhook.message_normaliser import extract_text, normalise_messages


def test_plain_string():
    assert extract_text("Hello world") == "Hello world"


def test_dict_with_val():
    assert extract_text({"val": "Hello"}) == "Hello"


def test_dict_with_text():
    assert extract_text({"text": "Hi there"}) == "Hi there"


def test_dict_with_payload_text():
    assert extract_text({"payload": {"text": "Payload text"}}) == "Payload text"


def test_template_message():
    result = extract_text({"type": "template", "payload": {"some": "data"}})
    assert result == "[template message]"


def test_unknown_dict_falls_back_to_str():
    result = extract_text({"unknown_key": "value"})
    assert isinstance(result, str)
    assert len(result) > 0


def test_normalise_messages_mixed():
    messages = [
        "Hello",
        {"val": "How can I help?"},
        {"type": "template", "payload": {}},
    ]
    texts, raws = normalise_messages(messages)
    assert texts == ["Hello", "How can I help?", "[template message]"]
    assert raws[0] == "Hello"
    assert raws[1] == {"val": "How can I help?"}
    assert raws[2] == {"type": "template", "payload": {}}


def test_normalise_messages_empty():
    texts, raws = normalise_messages([])
    assert texts == []
    assert raws == []
