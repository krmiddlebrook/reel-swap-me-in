import unittest

from app.server import origin_allowed


class TestOriginAllowed(unittest.TestCase):
    def test_absent_origin_allowed(self):
        # Same-origin fetches and curl send no Origin header.
        self.assertTrue(origin_allowed(None))
        self.assertTrue(origin_allowed(""))

    def test_local_origins_allowed(self):
        self.assertTrue(origin_allowed("http://localhost:8787"))
        self.assertTrue(origin_allowed("http://127.0.0.1:8787"))

    def test_foreign_origins_rejected(self):
        for bad in ["https://evil.example", "http://localhost:8000",
                    "http://localhost:87870", "https://localhost:8787",
                    "http://127.0.0.1:8787.evil.example", "null"]:
            self.assertFalse(origin_allowed(bad), bad)


if __name__ == "__main__":
    unittest.main()
