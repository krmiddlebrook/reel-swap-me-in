import json
import unittest

from app.higgsfield import (HiggsfieldError, HiggsfieldFatal,
                            classify_tool_error, find_media_url,
                            parse_credentials, unframe)


class TestParseCredentials(unittest.TestCase):
    def test_picks_higgsfield_entry(self):
        raw = json.dumps({"mcpOAuth": {
            "other|x": {"accessToken": "nope"},
            "higgsfield|abc123": {"accessToken": "tok", "serverUrl": "https://mcp.higgsfield.ai/mcp",
                                  "expiresAt": 1781229174486},
        }})
        entry = parse_credentials(raw)
        self.assertEqual(entry["accessToken"], "tok")

    def test_missing_entry_is_fatal(self):
        with self.assertRaises(HiggsfieldFatal):
            parse_credentials(json.dumps({"mcpOAuth": {}}))

    def test_garbage_is_fatal(self):
        with self.assertRaises(HiggsfieldFatal):
            parse_credentials("not json")


class TestUnframe(unittest.TestCase):
    def test_sse_framed(self):
        raw = 'event: message\ndata: {"a": 1}\n\n'
        self.assertEqual(unframe(raw), {"a": 1})

    def test_plain_json(self):
        self.assertEqual(unframe('{"a": 1}'), {"a": 1})

    def test_multiple_data_lines_takes_last(self):
        raw = 'data: {"a": 1}\n\ndata: {"a": 2}\n\n'
        self.assertEqual(unframe(raw), {"a": 2})

    def test_empty_raises(self):
        with self.assertRaises(HiggsfieldError):
            unframe("")


class TestFindMediaUrl(unittest.TestCase):
    def test_finds_nested_video_url(self):
        payload = {"job": {"results": [
            {"kind": "thumb", "url": "https://cdn.x/t.jpg"},
            {"kind": "video", "url": "https://cdn.x/out.mp4?sig=1"},
        ]}}
        self.assertEqual(find_media_url(payload, (".mp4",)),
                         "https://cdn.x/out.mp4?sig=1")

    def test_finds_image_url(self):
        payload = {"results": {"raw": {"url": "https://cdn.x/sheet.png"}}}
        self.assertEqual(find_media_url(payload, (".png", ".jpg", ".webp")),
                         "https://cdn.x/sheet.png")

    def test_none_when_absent(self):
        self.assertIsNone(find_media_url({"status": "queued"}, (".mp4",)))


class TestClassifyToolError(unittest.TestCase):
    def test_credit_errors_are_fatal(self):
        for text in ["Insufficient credits", "not enough CREDITS left",
                     "balance too low"]:
            self.assertTrue(classify_tool_error(text), text)

    def test_auth_errors_are_fatal(self):
        for text in ["Unauthorized", "invalid token", "authentication failed"]:
            self.assertTrue(classify_tool_error(text), text)

    def test_other_errors_fall_back(self):
        for text in ["Invalid params: unknown field", "model not found", ""]:
            self.assertFalse(classify_tool_error(text), text)


if __name__ == "__main__":
    unittest.main()
