import pytest
from pydantic import ValidationError
from governiq.core.manifest import FAQTask, UIPolicy, Manifest, TaskDefinition, EnginePattern


class TestUIPolicy:
    def test_default_is_prefer_webhook(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
        )
        assert td.ui_policy == UIPolicy.PREFER_WEBHOOK

    def test_web_driver_value(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
            ui_policy="web_driver",
        )
        assert td.ui_policy == UIPolicy.WEB_DRIVER

    def test_invalid_value_rejected(self):
        with pytest.raises(ValidationError):
            TaskDefinition(
                task_id="t1",
                task_name="Task 1",
                pattern=EnginePattern.CREATE,
                dialog_name="Book",
                ui_policy="allow_playwright",  # undefined — must be rejected
            )


class TestFAQTask:
    def test_valid_faq_task(self):
        task = FAQTask(
            task_id="FAQ-HOURS",
            question="What are your opening hours?",
            expected_answer="Open 9 AM to 5 PM Monday to Saturday.",
            similarity_threshold=0.80,
        )
        assert task.task_id == "FAQ-HOURS"
        assert task.similarity_threshold == 0.80

    def test_similarity_threshold_required(self):
        with pytest.raises(ValidationError):
            FAQTask(
                task_id="FAQ-HOURS",
                question="What are your opening hours?",
                expected_answer="Open 9 AM to 5 PM.",
                # missing similarity_threshold
            )

    def test_threshold_bounds(self):
        with pytest.raises(ValidationError):
            FAQTask(
                task_id="FAQ-X",
                question="q",
                expected_answer="a",
                similarity_threshold=1.5,  # > 1.0 — invalid
            )

    def test_alternative_questions_optional(self):
        task = FAQTask(
            task_id="FAQ-X",
            question="q",
            expected_answer="a",
            similarity_threshold=0.75,
        )
        assert task.alternative_questions == []


class TestRichUIFields:
    def test_expected_response_type_defaults_none(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
        )
        assert td.expected_response_type is None

    def test_expected_response_type_accepts_valid_string(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
            expected_response_type="buttons",
        )
        assert td.expected_response_type == "buttons"

    def test_rich_ui_action_defaults_empty_dict(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
        )
        assert td.rich_ui_action == {}

    def test_rich_ui_action_accepts_config(self):
        td = TaskDefinition(
            task_id="t1",
            task_name="Task 1",
            pattern=EnginePattern.CREATE,
            dialog_name="Book",
            expected_response_type="buttons",
            rich_ui_action={"entity_key": "appointmentType", "strategy": "semantic"},
        )
        assert td.rich_ui_action["entity_key"] == "appointmentType"


class TestManifestFAQTasks:
    def test_manifest_accepts_faq_tasks(self):
        import json
        from pathlib import Path
        path = Path("manifests/medical_appointment_basic.json")
        data = json.loads(path.read_text())
        data["faq_tasks"] = [
            {
                "task_id": "FAQ-HOURS",
                "question": "What are your opening hours?",
                "expected_answer": "9 AM to 5 PM, Monday to Saturday.",
                "similarity_threshold": 0.80,
            }
        ]
        m = Manifest(**data)
        assert len(m.faq_tasks) == 1
        assert m.faq_tasks[0].task_id == "FAQ-HOURS"

    def test_faq_tasks_defaults_to_empty(self):
        import json
        from pathlib import Path
        data = json.loads(Path("manifests/medical_appointment_basic.json").read_text())
        m = Manifest(**data)
        assert m.faq_tasks == []
