"""Entirely offline simulations of the cloud API."""

import unittest
import asyncio
from aiohttp import ClientConnectionError
from collections import deque

from karaca_connect_client import (
    KaracaApiError,
    KaracaAuthError,
    KaracaClient,
    KaracaConnectionError,
    KaracaDeviceNotFound,
    KaracaRateLimitError,
    KaracaServiceError,
)


class FakeResponse:
    def __init__(self, status, data):
        self.status = status
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self, **kwargs):
        return self.data


class FakeSession:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.popleft()


def ok_login(token="private-test-token"):
    return FakeResponse(200, {"succeeded": True, "data": {"jwToken": token}})


class KaracaClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_login_and_detail(self):
        session = FakeSession(ok_login(), FakeResponse(200, {"data": {"detail": {"mode": 6}, "meta": {"connected": True}}}))
        client = KaracaClient(session, email="test@example.invalid", password="test", device_id="dev123")
        self.assertEqual((await client.get_detail())["detail"]["mode"], 6)
        self.assertEqual(session.calls[-1][2]["headers"]["Authorization"], "Bearer private-test-token")

    async def test_device_selection(self):
        session = FakeSession(ok_login(), FakeResponse(200, {"data": [{"id": 234, "label": "Test"}]}))
        client = KaracaClient(session, email="t", password="t")
        self.assertEqual(await client.resolve_device_id(), "234")

    async def test_no_devices(self):
        session = FakeSession(ok_login(), FakeResponse(200, {"data": []}))
        client = KaracaClient(session, email="t", password="t")
        with self.assertRaises(KaracaDeviceNotFound):
            await client.resolve_device_id()

    async def test_login_failure_never_includes_response_body(self):
        session = FakeSession(FakeResponse(401, {"raw": "sensitive-upstream-response"}))
        client = KaracaClient(session, email="t", password="bad")
        with self.assertRaises(KaracaAuthError) as error:
            await client.login()
        self.assertNotIn("sensitive", str(error.exception))

    async def test_missing_token(self):
        client = KaracaClient(FakeSession(FakeResponse(200, {"data": {}})), email="t", password="t")
        with self.assertRaises(KaracaAuthError):
            await client.login()

    async def test_token_refresh_on_401(self):
        session = FakeSession(ok_login("old-token"), FakeResponse(401, {}), ok_login("new-token"), FakeResponse(200, {"data": {"detail": {"mode": 9}}}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        self.assertEqual((await client.get_detail())["detail"]["mode"], 9)
        self.assertEqual(session.calls[-1][2]["headers"]["Authorization"], "Bearer new-token")

    async def test_second_401_raises_without_infinite_retry(self):
        session = FakeSession(ok_login("old"), FakeResponse(401, {}), ok_login("new"), FakeResponse(401, {}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaAuthError):
            await client.get_detail()
        self.assertEqual(len(session.calls), 4)

    async def test_429_rate_limit(self):
        client = KaracaClient(FakeSession(ok_login(), FakeResponse(429, {})), email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaRateLimitError):
            await client.get_detail()

    async def test_503_service_unavailable(self):
        client = KaracaClient(FakeSession(ok_login(), FakeResponse(503, {})), email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaServiceError):
            await client.get_detail()

    async def test_malformed_data(self):
        client = KaracaClient(FakeSession(ok_login(), FakeResponse(200, {"data": None})), email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaConnectionError):
            await client.get_detail()

    async def test_mode_command(self):
        session = FakeSession(ok_login(), FakeResponse(200, {"succeeded": True}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        await client.set_mode(9)
        self.assertEqual(session.calls[-1][0], "PUT")
        self.assertEqual(session.calls[-1][2]["json"], {"active": True})

    async def test_settings_fallback(self):
        session = FakeSession(ok_login(), FakeResponse(400, {"succeeded": False}), FakeResponse(200, {"succeeded": True}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        await client.set_setting(3, False)
        self.assertEqual(session.calls[-1][2]["json"], {"active": False})

    async def test_api_error_does_not_leak_payload(self):
        client = KaracaClient(FakeSession(ok_login(), FakeResponse(400, {"raw": "secret-value", "succeeded": False})), email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaApiError) as error:
            await client.get_detail()
        self.assertNotIn("secret-value", str(error.exception))

    async def test_get_settings(self):
        client = KaracaClient(FakeSession(ok_login(), FakeResponse(200, {"data": {"notifications": [{"id": 3, "value": True}]}})), email="t", password="t", device_id="dev")
        self.assertEqual((await client.get_settings())[0]["id"], 3)

    async def test_service_error_with_html_response(self):
        session = FakeSession(ok_login(), FakeResponse(503, None))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaServiceError):
            await client.get_detail()

    async def test_rate_limit_with_non_json_response(self):
        session = FakeSession(ok_login(), FakeResponse(429, "Too Many Requests"))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaRateLimitError):
            await client.get_detail()

    async def test_service_error_during_login_is_not_auth_failure(self):
        session = FakeSession(FakeResponse(503, {"succeeded": False}))
        client = KaracaClient(session, email="t", password="t")
        with self.assertRaises(KaracaServiceError):
            await client.login()

    async def test_login_rate_limit_is_not_invalid_credentials(self):
        session = FakeSession(FakeResponse(429, {}))
        client = KaracaClient(session, email="t", password="t")
        with self.assertRaises(KaracaRateLimitError):
            await client.login()

    async def test_403_forbidden(self):
        session = FakeSession(ok_login(), FakeResponse(403, {"raw": "secret"}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaAuthError) as error:
            await client.get_detail()
        self.assertNotIn("secret", str(error.exception))

    async def test_network_error_is_sanitized(self):
        class OfflineSession:
            def request(self, *_args, **_kwargs):
                raise ClientConnectionError("upstream-user-secret")
        client = KaracaClient(OfflineSession(), email="t", password="t")
        with self.assertRaises(KaracaConnectionError) as error:
            await client.login()
        self.assertNotIn("upstream-user-secret", str(error.exception))

    async def test_login_is_shared_across_concurrent_requests(self):
        session = FakeSession(
            ok_login(),
            FakeResponse(200, {"data": []}),
            FakeResponse(200, {"data": []}),
        )
        client = KaracaClient(session, email="t", password="t")
        result = await asyncio.gather(client.get_devices(), client.get_devices())
        self.assertEqual(result, [[], []])
        self.assertEqual(sum(1 for call in session.calls if call[1].endswith("/api/auth/signin")), 1)

    async def test_malformed_device_list(self):
        session = FakeSession(ok_login(), FakeResponse(200, {"data": [1, 2]}))
        client = KaracaClient(session, email="t", password="t")
        with self.assertRaises(KaracaConnectionError):
            await client.get_devices()

    async def test_setting_fallback_does_not_trigger_for_rate_limit(self):
        session = FakeSession(ok_login(), FakeResponse(429, {}))
        client = KaracaClient(session, email="t", password="t", device_id="dev")
        with self.assertRaises(KaracaRateLimitError):
            await client.set_setting(3, False)
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
