"""Test basic safety preconditions without contacting a real Karaca account."""

import unittest

from karaca_connect_client import KaracaClient


class ClientSafetyTests(unittest.TestCase):
    def test_empty_credentials_rejected(self):
        with self.assertRaises(ValueError):
            KaracaClient(object(), email="", password="something")

    def test_nonpositive_timeout_rejected(self):
        for seconds in (0, -1, -10):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                KaracaClient(object(), email="test", password="secret", timeout_seconds=seconds)

    def test_no_public_password_or_token_properties(self):
        c = KaracaClient(object(), email="test", password="not-real")
        self.assertFalse(hasattr(c, "password"))
        self.assertFalse(hasattr(c, "token"))
