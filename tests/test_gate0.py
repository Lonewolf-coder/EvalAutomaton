import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from governiq.core.gate0 import Gate0Checker, Gate0Result, Gate0CheckStatus


class TestGate0Result:
    def test_result_is_pass_only_when_all_pass(self):
        result = Gate0Result(checks={
            "webhook_reachability": Gate0CheckStatus.PASS,
            "bot_credentials": Gate0CheckStatus.PASS,
            "bot_published": Gate0CheckStatus.PASS,
            "web_channel": Gate0CheckStatus.WARN,
            "backend_api": Gate0CheckStatus.PASS,
            "webhook_version": Gate0CheckStatus.PASS,
        })
        assert result.can_proceed is True  # WARN does not block

    def test_any_fail_blocks(self):
        result = Gate0Result(checks={
            "webhook_reachability": Gate0CheckStatus.PASS,
            "bot_credentials": Gate0CheckStatus.FAIL,
            "bot_published": Gate0CheckStatus.PASS,
            "web_channel": Gate0CheckStatus.PASS,
            "backend_api": Gate0CheckStatus.PASS,
            "webhook_version": Gate0CheckStatus.PASS,
        })
        assert result.can_proceed is False

    def test_web_channel_available_true_when_pass(self):
        result = Gate0Result(checks={"web_channel": Gate0CheckStatus.PASS})
        assert result.web_channel_available is True

    def test_web_channel_available_false_when_warn(self):
        result = Gate0Result(checks={"web_channel": Gate0CheckStatus.WARN})
        assert result.web_channel_available is False


class TestGate0CheckerStaticMethods:
    def test_v2_check_pass_on_v2_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/v2/bot123")
        assert status == Gate0CheckStatus.PASS

    def test_v2_check_fail_on_v1_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/v1/bot123")
        assert status == Gate0CheckStatus.FAIL
        assert "V2" in msg

    def test_v2_check_warn_on_ambiguous_url(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        status, msg = checker._check_webhook_version("https://bots.kore.ai/chatbot/bot123")
        assert status == Gate0CheckStatus.WARN

    def test_web_channel_warn_when_absent(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"channelInfos": [{"type": "webhook"}]}
        status, msg = checker._check_web_channel(bot_response)
        assert status == Gate0CheckStatus.WARN

    def test_web_channel_pass_when_present(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"channelInfos": [{"type": "webhook"}, {"type": "websdkapp"}]}
        status, msg = checker._check_web_channel(bot_response)
        assert status == Gate0CheckStatus.PASS

    def test_publish_status_fail_when_not_published(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"publishStatus": "inProgress"}
        status, msg = checker._check_publish_status(bot_response)
        assert status == Gate0CheckStatus.FAIL
        assert "published" in msg.lower()

    def test_publish_status_pass(self):
        checker = Gate0Checker.__new__(Gate0Checker)
        bot_response = {"publishStatus": "published"}
        status, msg = checker._check_publish_status(bot_response)
        assert status == Gate0CheckStatus.PASS


class TestGate0CheckerRun:
    @pytest.mark.asyncio
    async def test_run_short_circuits_on_v1_url(self):
        """V1 URL fails version check — run() returns early without network calls."""
        checker = Gate0Checker(
            webhook_url="https://bots.kore.ai/chatbot/v1/botabc",
            bot_id="st-abc",
            backend_api_url="",
        )
        result = await checker.run()
        assert result.can_proceed is False
        assert result.checks["webhook_version"] == Gate0CheckStatus.FAIL
        # No backend/webhook checks should have run
        assert "backend_api" not in result.checks

    @pytest.mark.asyncio
    async def test_run_skips_bot_details_when_no_client(self):
        """Without kore_api_client, bot checks are SKIP."""
        checker = Gate0Checker(
            webhook_url="https://bots.kore.ai/chatbot/v2/botabc",
            bot_id="st-abc",
            backend_api_url="",
        )
        # Patch the network calls to avoid real HTTP
        with patch.object(checker, "_check_webhook_reachability", new=AsyncMock(
            return_value=(Gate0CheckStatus.PASS, "reachable")
        )):
            result = await checker.run()
        assert result.checks.get("bot_credentials") == Gate0CheckStatus.SKIP
        assert result.checks.get("bot_published") == Gate0CheckStatus.SKIP
        assert result.checks.get("web_channel") == Gate0CheckStatus.SKIP
        assert result.can_proceed is True  # SKIP does not block
