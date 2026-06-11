import unittest

from app.server import origin_allowed
from app import server


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


class TestPhotoRoutes(unittest.TestCase):
    def test_action_route_parses_name_and_action(self):
        match = server._PHOTO_ACTION.match("/api/photos/face-ab.jpg/promote")
        self.assertEqual(match.group(1), "face-ab.jpg")
        self.assertEqual(match.group(2), "promote")
        match = server._PHOTO_ACTION.match("/api/photos/me.jpg/delete")
        self.assertEqual(match.group(2), "delete")

    def test_action_route_rejects_garbage(self):
        for bad in ("/api/photos//promote", "/api/photos/a/b/promote",
                    "/api/photos/a.jpg/rename", "/api/photos/promote"):
            self.assertIsNone(server._PHOTO_ACTION.match(bad), bad)

    def test_file_route(self):
        match = server._PHOTO_FILE.match("/api/photos/me.jpg")
        self.assertEqual(match.group(1), "me.jpg")
        self.assertIsNone(server._PHOTO_FILE.match("/api/photos/"))
        self.assertIsNone(server._PHOTO_FILE.match("/api/photos/a/b"))

    def test_file_route_with_query_string_via_base_path(self):
        # do_GET must match routes against the query-stripped path: the
        # gallery requests /api/photos/<name>?t=<ts> as a cache-buster.
        raw = "/api/photos/me.jpg?t=123"
        self.assertIsNone(server._PHOTO_FILE.match(raw))  # regex alone fails
        base = raw.split("?", 1)[0]
        match = server._PHOTO_FILE.match(base)
        self.assertEqual(match.group(1), "me.jpg")

    def test_upload_role_parsing(self):
        self.assertEqual(server._upload_role("/api/photos"), "extra")
        self.assertEqual(server._upload_role("/api/photos?role=main"), "main")
        self.assertEqual(server._upload_role("/api/photos?role=extra"),
                         "extra")
        self.assertIsNone(server._upload_role("/api/photos?role=banana"))


if __name__ == "__main__":
    unittest.main()
