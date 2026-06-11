import json
import unittest

from app.higgsfield import (HiggsfieldError, HiggsfieldFatal,
                            classify_tool_error, extract_result_url,
                            find_media_url, parse_credentials, unframe)

# Real (shortened) shape of job_status for a completed motion_control job:
# everything sits under a "generation" envelope, and the INPUT clip url lives
# under generation.params.medias — it must never win over generation.results.
REAL_JOB_PAYLOAD = {"generation": {
    "id": "615674fd-f249-438e-9028-ca839653a5a7",
    "type": "image",
    "status": "completed",
    "model": "kling3_0_motion_control",
    "params": {
        "medias": [
            {"data": {"url": "https://media.x/inputs/dc956cd3.mp4",
                      "type": "video_input"}, "role": "video"},
            {"data": {"url": "https://media.x/inputs/sheet_resize.jpg",
                      "type": "media_input"}, "role": "image"},
        ],
    },
    "results": {"rawUrl": "https://media.x/generations/615674fd.mp4"},
}}


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


class TestExtractResultUrl(unittest.TestCase):
    def test_prefers_results_over_input_params(self):
        self.assertEqual(extract_result_url(REAL_JOB_PAYLOAD, (".mp4",)),
                         "https://media.x/generations/615674fd.mp4")

    def test_unwrapped_shape_also_works(self):
        # show_generations items have the same fields without the envelope
        self.assertEqual(
            extract_result_url(REAL_JOB_PAYLOAD["generation"], (".mp4",)),
            "https://media.x/generations/615674fd.mp4")

    def test_never_returns_param_input_even_without_results(self):
        gen = dict(REAL_JOB_PAYLOAD["generation"], results={})
        self.assertIsNone(extract_result_url({"generation": gen}, (".mp4",)))

    def test_falls_back_to_non_param_subtrees(self):
        payload = {"params": {"url": "https://media.x/in.mp4"},
                   "output": {"video": "https://media.x/out.mp4"}}
        self.assertEqual(extract_result_url(payload, (".mp4",)),
                         "https://media.x/out.mp4")


class _StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def call(self, tool, args, timeout=90):
        self.calls.append((tool, args))
        return self.responses.pop(0)


class TestGenerateVideoPresetDecline(unittest.TestCase):
    def test_declines_preset_recommendation_and_retries(self):
        from app.higgsfield import _generate_video
        notice = ({"notice": {"type": "preset_recommendation", "data": {
            "retry_literal_with": {"declined_preset_id": "preset-123"}}}}, "")
        success = ({"job_id": "a" * 36}, "submitted")
        stub = _StubClient([notice, success])
        structured, _ = _generate_video(stub, {"model": "m", "prompt": "p"})
        self.assertEqual(structured, {"job_id": "a" * 36})
        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(stub.calls[1][1]["params"]["declined_preset_id"],
                         "preset-123")

    def test_no_notice_means_single_call(self):
        from app.higgsfield import _generate_video
        stub = _StubClient([({"job_id": "b" * 36}, "ok")])
        _generate_video(stub, {"model": "m", "prompt": "p"})
        self.assertEqual(len(stub.calls), 1)


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
