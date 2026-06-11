import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

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


def _can_bind():
    import socket
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.close()
        return True
    except OSError:
        return False


@unittest.skipUnless(_can_bind(), "sandbox blocks socket binding")
class Test404LogMessage(unittest.TestCase):
    """send_error passes an int as args[0]; log_message must not crash."""

    def setUp(self):
        # Bind to port 0 so the OS assigns a free ephemeral port.
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self._port = self._srv.server_address[1]
        t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        t.start()

    def tearDown(self):
        self._srv.shutdown()

    def test_photo_404_returns_http_response_not_dropped_connection(self):
        """GET /api/photos/nope.jpg must return HTTP 404, not a dropped conn.

        Before the fix, log_message did `"/api/jobs/" not in args[0]` where
        args[0] is an int (the status code passed by send_error → log_error),
        raising TypeError and dropping the connection without sending any
        response.  urllib raises HTTPError(404) on a proper 404; it raises
        URLError / RemoteDisconnected when the connection is dropped."""
        url = "http://127.0.0.1:%d/api/photos/nope.jpg" % self._port
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
