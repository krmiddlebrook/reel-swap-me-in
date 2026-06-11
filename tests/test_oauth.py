import base64
import hashlib
import json
import os
import tempfile
import time
import unittest

from app.oauth import (load_credentials, make_pkce, save_credentials,
                       token_state)


class TestMakePkce(unittest.TestCase):
    def test_challenge_is_s256_of_verifier(self):
        verifier, challenge = make_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_no_padding_and_fresh_each_call(self):
        v1, c1 = make_pkce()
        v2, c2 = make_pkce()
        self.assertNotEqual(v1, v2)
        for token in (v1, c1, v2, c2):
            self.assertNotIn("=", token)
            self.assertGreaterEqual(len(token), 40)


class TestTokenState(unittest.TestCase):
    NOW = 1_000_000.0

    def test_absent_without_access_token(self):
        self.assertEqual(token_state({}, now=self.NOW), "absent")

    def test_valid_when_not_near_expiry(self):
        creds = {"access_token": "t", "expires_at": self.NOW + 3600}
        self.assertEqual(token_state(creds, now=self.NOW), "valid")

    def test_refreshable_when_expired_with_refresh_token(self):
        creds = {"access_token": "t", "expires_at": self.NOW - 1,
                 "refresh_token": "r"}
        self.assertEqual(token_state(creds, now=self.NOW), "refreshable")

    def test_absent_when_expired_without_refresh_token(self):
        creds = {"access_token": "t", "expires_at": self.NOW - 1}
        self.assertEqual(token_state(creds, now=self.NOW), "absent")


class TestCredentialStore(unittest.TestCase):
    def test_round_trip_with_0600_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "creds.json")
            save_credentials({"client_id": "abc", "access_token": "t"},
                             path=path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(load_credentials(path=path)["client_id"], "abc")

    def test_missing_or_garbage_loads_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            self.assertEqual(load_credentials(path=missing), {})
            garbage = os.path.join(tmp, "bad.json")
            open(garbage, "w").write("not json")
            self.assertEqual(load_credentials(path=garbage), {})


if __name__ == "__main__":
    unittest.main()
