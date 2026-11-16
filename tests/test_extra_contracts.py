"""Additional purely offline contract and safety checks."""

import asyncio
import unittest
from collections import deque

from karaca_connect_client import (
    KaracaApiError,
    KaracaAuthError,
    KaracaClient,
    KaracaConnectionError,
    KaracaDeviceNotFound,
)


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        return self.body


class Session:
    def __init__(self, *responses):
        self.responses = deque(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.popleft()


def signed_in(token='token-1'):
    return Response(200, {'data': {'jwToken': token}})


class ClientExtraTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_rejection_is_not_reported_as_connection_failure(self):
        client = KaracaClient(Session(Response(200, {'succeeded': False, 'messages': ['invalid']})), email='u', password='p')
        with self.assertRaises(KaracaAuthError):
            await client.login()

    async def test_bad_json_type_does_not_pass_as_valid_device_data(self):
        client = KaracaClient(Session(signed_in(), Response(200, ['not-object'])), email='u', password='p')
        with self.assertRaises(KaracaConnectionError):
            await client.get_devices()

    async def test_invalid_first_device_id_is_not_selected(self):
        client = KaracaClient(Session(signed_in(), Response(200, {'data': [{'name': 'Unnamed'}]})), email='u', password='p')
        with self.assertRaises(KaracaDeviceNotFound):
            await client.resolve_device_id()

    async def test_multiple_devices_without_selection_is_rejected(self):
        session = Session(
            signed_in(),
            Response(200, {"data": [{"id": "dev-a"}, {"id": "dev-b"}]}),
        )
        client = KaracaClient(session, email="u", password="p")
        with self.assertRaises(KaracaDeviceNotFound):
            await client.resolve_device_id()
        self.assertIsNone(client.device_id)
        self.assertTrue(all(call[0] != "PUT" for call in session.calls))

    async def test_explicit_selection_does_not_guess_or_fetch_device_list(self):
        client = KaracaClient(Session(), email="u", password="p", device_id="dev-b")
        self.assertEqual(await client.resolve_device_id(), "dev-b")

    async def test_duplicate_device_id_and_invalid_first_device_is_not_used(self):
        session = Session(
            signed_in(),
            Response(200, {"data": [{"label": "unknown"}, {"id": "valid"}]}),
        )
        client = KaracaClient(session, email="u", password="p")
        with self.assertRaises(KaracaDeviceNotFound):
            await client.resolve_device_id()

    async def test_raw_password_not_present_in_client_repr(self):
        client = KaracaClient(Session(), email='private@example.invalid', password='opaque-super-secret')
        self.assertNotIn('opaque-super-secret', repr(client))
        self.assertNotIn('private@example.invalid', repr(client))

    async def test_failed_command_cannot_be_retried_with_different_payload_implicitly(self):
        session = Session(signed_in(), Response(400, {'succeeded': False, 'raw': 'upstream-private'}))
        client = KaracaClient(session, email='u', password='p', device_id='dev-1')
        with self.assertRaises(KaracaApiError) as error:
            await client.set_mode(6, True)
        self.assertNotIn('upstream-private', str(error.exception))
        self.assertEqual(len(session.calls), 2)

    async def test_explicit_device_ids_are_kept_as_strings(self):
        client = KaracaClient(Session(), email='u', password='p', device_id=123)
        self.assertEqual(await client.resolve_device_id(), '123')

    async def test_two_clients_do_not_share_tokens(self):
        one = Session(signed_in('first-token'), Response(200, {'data': []}))
        two = Session(signed_in('second-token'), Response(200, {'data': []}))
        client_one = KaracaClient(one, email='one', password='one')
        client_two = KaracaClient(two, email='two', password='two')
        await asyncio.gather(client_one.get_devices(), client_two.get_devices())
        self.assertEqual(one.calls[1][2]['headers']['Authorization'], 'Bearer first-token')
        self.assertEqual(two.calls[1][2]['headers']['Authorization'], 'Bearer second-token')


if __name__ == '__main__':
    unittest.main()
