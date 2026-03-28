from unittest.mock import patch, MagicMock
from governiq.webhook.model_cache import get_shared_model, reset_model_cache


class TestModelCache:
    def setup_method(self):
        reset_model_cache()  # ensure clean state between tests

    def teardown_method(self):
        reset_model_cache()  # clear any mock instances so other test modules get the real model

    def test_returns_same_instance_on_second_call(self):
        with patch("governiq.webhook.model_cache.SentenceTransformer") as mock_cls:
            mock_cls.return_value = MagicMock()
            m1 = get_shared_model()
            m2 = get_shared_model()
        assert m1 is m2
        assert mock_cls.call_count == 1  # loaded only once

    def test_uses_correct_model_name(self):
        with patch("governiq.webhook.model_cache.SentenceTransformer") as mock_cls:
            mock_cls.return_value = MagicMock()
            get_shared_model()
        mock_cls.assert_called_once_with("paraphrase-multilingual-mpnet-base-v2")
