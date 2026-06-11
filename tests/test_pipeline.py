import json
import unittest

from app.claude_swap import describe_tool_event, parse_agent_output
from app.pipeline import PipelineError, plan_trim, validate_reel_url


class TestValidateReelUrl(unittest.TestCase):
    def test_accepts_reel_url(self):
        self.assertEqual(
            validate_reel_url("https://www.instagram.com/reel/Cabc123_X-/"),
            "https://www.instagram.com/reel/Cabc123_X-/",
        )

    def test_accepts_reels_p_tv_and_strips_query(self):
        self.assertEqual(
            validate_reel_url("https://instagram.com/p/Cabc123/?igsh=xyz"),
            "https://instagram.com/p/Cabc123/",
        )
        validate_reel_url("https://www.instagram.com/reels/Cabc123/")
        validate_reel_url("https://www.instagram.com/tv/Cabc123/")

    def test_rejects_non_instagram(self):
        for bad in ["", "not a url", "https://youtube.com/watch?v=x",
                    "https://instagram.com/someuser/"]:
            with self.assertRaises(PipelineError):
                validate_reel_url(bad)


class TestPlanTrim(unittest.TestCase):
    def test_too_short_raises(self):
        with self.assertRaises(PipelineError):
            plan_trim(3.2)

    def test_in_range_no_trim(self):
        self.assertIsNone(plan_trim(5.0))
        self.assertIsNone(plan_trim(12.0))
        self.assertIsNone(plan_trim(15.0))

    def test_too_long_trims_to_15(self):
        self.assertEqual(plan_trim(42.0), 15.0)

    def test_unknown_duration_trims_defensively(self):
        self.assertEqual(plan_trim(None), 15.0)


class TestParseAgentOutput(unittest.TestCase):
    def _envelope(self, result_text, is_error=False):
        return json.dumps({"type": "result", "is_error": is_error,
                           "result": result_text})

    def test_success_json(self):
        out = self._envelope('{"videoUrl": "https://cdn.example/v.mp4"}')
        self.assertEqual(parse_agent_output(out), "https://cdn.example/v.mp4")

    def test_json_embedded_in_prose(self):
        out = self._envelope(
            'Done! Here is the result:\n{"videoUrl": "https://cdn.example/v.mp4"}')
        self.assertEqual(parse_agent_output(out), "https://cdn.example/v.mp4")

    def test_agent_reported_error(self):
        out = self._envelope('{"error": "Out of credits"}')
        with self.assertRaises(PipelineError) as ctx:
            parse_agent_output(out)
        self.assertIn("Out of credits", str(ctx.exception))

    def test_envelope_error(self):
        out = self._envelope("MCP server not authorized", is_error=True)
        with self.assertRaises(PipelineError):
            parse_agent_output(out)

    def test_garbage_raises(self):
        with self.assertRaises(PipelineError):
            parse_agent_output("not json at all")


class TestDescribeToolEvent(unittest.TestCase):
    def test_upload_tools(self):
        self.assertIn("Uploading", describe_tool_event("mcp__higgsfield__upload_file"))

    def test_bash_is_upload_command(self):
        self.assertIn("Uploading", describe_tool_event("Bash"))

    def test_model_catalog(self):
        self.assertIn("model", describe_tool_event("mcp__higgsfield__list_models"))

    def test_generation_submit(self):
        self.assertIn("submitted", describe_tool_event("mcp__higgsfield__create_generation"))

    def test_polling(self):
        self.assertIn("Rendering", describe_tool_event("mcp__higgsfield__get_generation_status"))
        self.assertIn("Rendering", describe_tool_event("mcp__higgsfield__wait_for_job"))

    def test_unknown_returns_none(self):
        self.assertIsNone(describe_tool_event("TodoWrite"))
        self.assertIsNone(describe_tool_event(""))


if __name__ == "__main__":
    unittest.main()
