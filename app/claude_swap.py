"""Run the character swap via headless Claude Code + the Higgsfield MCP server.

Prereq (one-time): `claude mcp add --transport http --scope user higgsfield
https://mcp.higgsfield.ai/mcp`, then OAuth via `/mcp` inside `claude`.
Headless `claude -p` reuses the stored token.
"""
import json
import subprocess
import tempfile
import threading

from app.pipeline import PipelineError

SWAP_TIMEOUT_SECONDS = 30 * 60  # video generation can take many minutes

# Higgsfield uploads work via pre-signed URLs the agent must curl file bytes
# to, so the inner run needs curl permission and sandbox network access to
# Higgsfield hosts (the default sandbox allowlist blocks them).
_INLINE_SETTINGS = json.dumps({
    "sandbox": {"network": {"allowedDomains": ["higgsfield.ai", "*.higgsfield.ai"]}},
})

_ALLOWED_TOOLS = ",".join([
    "mcp__higgsfield",
    "mcp__higgsfield__*",
    "Bash(curl:*)",
    "Bash(curl *)",
])

_UPLOAD_RULES = """- If an upload tool hands you a pre-signed URL to push file bytes to, run that upload yourself with a Bash curl command (for example `curl -sf -X PUT --data-binary @"<file>" "<url>"` — follow whatever method and headers the tool specifies). curl to higgsfield.ai hosts is pre-approved.
- Use Higgsfield MCP tools, plus Bash curl commands only for uploading the local files named above to Higgsfield URLs.
- If a tool fails for auth or credit reasons, stop and report it via the error JSON."""

PROMPT = """You are connected to the Higgsfield MCP server (tools prefixed mcp__higgsfield__).

Goal: create a character-swapped version of a video.
- Source video (local file): {video}
- Character sheet of the replacement person (local image file): {photo}

Steps:
1. Look at the Higgsfield tools you have available.
2. Upload the source video and the character sheet image using the appropriate Higgsfield upload tool(s).
3. Find the character-swap model in the model catalog: Higgsfield Recast / WAN 2.2 Animate. It MUST run in "replace" mode — the mode that swaps the person in the source video with the character from the reference image while keeping the source video's motion, framing, and pacing. Do NOT use "animate" mode (that mode animates a still photo, which is wrong here). If the tool exposes a mode/task/type parameter, set it to replace.
4. Submit the generation with the uploaded video as the source/motion input, the uploaded character sheet as the character reference, and mode set to replace. Parameter guidance (replace mode works image→video, so respect these):
   - If the tool accepts an optional text prompt, keep it short and describe ONLY the replacement person's appearance as seen in the character sheet (e.g. hair, build, clothing). Never describe the scene, background, lighting, camera, or actions — those must come from the source video unchanged.
   - If a resolution or quality option exists, prefer ~720p output (replace mode's sweet spot); otherwise keep the tool's defaults.
   - Do not enable any background-replacement, restyle, or voice options.
5. Wait and poll until the generation completes. It can take several minutes — keep polling.
6. Reply with ONLY one JSON object as the final line, no markdown fences:
   - success: {{"videoUrl": "<direct URL of the generated video file>"}}
   - failure: {{"error": "<one short sentence saying what failed>"}}

Rules:
{rules}
- Generate only the requested character swap, nothing else."""

SHEET_PROMPT = """You are connected to the Higgsfield MCP server (tools prefixed mcp__higgsfield__).

Goal: create a character reference sheet from a photo of a person.
- Source photo (local file): {photo}

Steps:
1. Look at the Higgsfield tools you have available.
2. Upload the photo using the appropriate Higgsfield upload tool.
3. Use a Higgsfield image-generation model that accepts an identity/character reference image (for example Soul or Nano Banana) to generate ONE character reference image of the same person, built for video character-swap models (WAN Animate replace / Recast). Requirements, in priority order:
   - exactly one person, a single full-body figure — NOT a collage or multi-view sheet (swap models latch onto one face and can project extra elements into the output)
   - face clearly visible, front-facing, neutral expression, no extreme angle, nothing covering the face
   - identity must faithfully match the source photo (same face, hair, build)
   - standing naturally, arms relaxed at the sides, hands empty — no props, phones, bags, or accessories being held
   - soft even studio lighting, neutral color temperature, no harsh shadows
   - soft light-gray studio background (not pure white), uncluttered
   - vertical 9:16 portrait framing (matches reel videos), sharp focus, photorealistic
   - no text, labels, watermarks, or borders.
4. Wait and poll until the generation completes.
5. Reply with ONLY one JSON object as the final line, no markdown fences:
   - success: {{"imageUrl": "<direct URL of the generated image file>"}}
   - failure: {{"error": "<one short sentence saying what failed>"}}

Rules:
{rules}
- Generate only the requested character sheet, nothing else."""


def describe_tool_event(tool_name):
    """Map an agent tool call to a user-facing status line (or None)."""
    name = (tool_name or "").lower()
    if not name:
        return None
    if "upload" in name or name == "bash":
        return "Uploading your clip and photo to Higgsfield…"
    if "model" in name:
        return "Choosing the character-swap model…"
    if any(key in name for key in ("status", "wait", "poll", "history")):
        return "Rendering on Higgsfield…"
    if any(key in name for key in ("create", "generate", "submit")):
        return "Generation submitted to Higgsfield — rendering…"
    return None


def _extract_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return None


def parse_agent_output(stdout, key="videoUrl"):
    envelope = _extract_json(stdout or "")
    if envelope is None:
        raise PipelineError(
            "Claude returned unparseable output — try again, and check "
            "'claude mcp list' shows higgsfield as connected.")
    if envelope.get("is_error"):
        raise PipelineError(
            "Claude run failed: %s — if this mentions auth, redo the /mcp "
            "login in claude." % str(envelope.get("result"))[:300])
    payload = _extract_json(envelope.get("result") or "")
    if payload and payload.get(key):
        return payload[key]
    if payload and payload.get("error"):
        raise PipelineError("Higgsfield step failed: %s" % payload["error"])
    raise PipelineError(
        "The agent finished without producing a result URL. Raw reply: %s"
        % str(envelope.get("result"))[:300])


def swap(video_path, sheet_path, progress=None):
    """Returns the URL of the generated (character-swapped) video.

    Streams the agent's tool calls so `progress(detail)` can narrate
    upload → submit → render in the UI as they happen.
    """
    prompt = PROMPT.format(video=video_path, photo=sheet_path,
                           rules=_UPLOAD_RULES)
    return parse_agent_output(_run_agent(prompt, progress), key="videoUrl")


def create_character_sheet(photo_path, progress=None):
    """Returns the URL of a generated multi-view character sheet image."""
    prompt = SHEET_PROMPT.format(photo=photo_path, rules=_UPLOAD_RULES)
    return parse_agent_output(_run_agent(prompt, progress), key="imageUrl")


def _run_agent(prompt, progress=None):
    """Run headless claude -p, streaming tool events to `progress`.

    Returns the raw final result-envelope line for parse_agent_output."""
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--allowedTools", _ALLOWED_TOOLS,
        "--max-turns", "80",
        "--settings", _INLINE_SETTINGS,
    ]
    stderr_file = tempfile.TemporaryFile(mode="w+")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=stderr_file, text=True)
    except FileNotFoundError:
        raise PipelineError("The 'claude' CLI was not found on PATH.")

    timed_out = []

    def _kill():
        timed_out.append(True)
        proc.kill()

    watchdog = threading.Timer(SWAP_TIMEOUT_SECONDS, _kill)
    watchdog.start()
    result_line = None
    last_detail = None
    try:
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "assistant":
                for block in (event.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        detail = describe_tool_event(block.get("name"))
                        if detail and detail != last_detail and progress:
                            last_detail = detail
                            progress(detail)
            elif event.get("type") == "result":
                result_line = line
        proc.wait()
    finally:
        watchdog.cancel()

    if timed_out:
        raise PipelineError("Generation timed out after 30 minutes — try again.")
    if result_line is None:
        stderr_file.seek(0)
        raise PipelineError(
            "Claude exited with an error: %s" % stderr_file.read()[:300])
    return result_line
