"""Run the character swap via headless Claude Code + the Higgsfield MCP server.

Prereq (one-time): `claude mcp add --transport http --scope user higgsfield
https://mcp.higgsfield.ai/mcp`, then OAuth via `/mcp` inside `claude`.
Headless `claude -p` reuses the stored token.
"""
import json
import subprocess

from app.pipeline import PipelineError

SWAP_TIMEOUT_SECONDS = 30 * 60  # video generation can take many minutes

PROMPT = """You are connected to the Higgsfield MCP server (tools prefixed mcp__higgsfield__).

Goal: create a character-swapped version of a video.
- Source video (local file): {video}
- Reference image of the replacement person (local file): {photo}

Steps:
1. Look at the Higgsfield tools you have available.
2. Upload the source video and the reference image using the appropriate Higgsfield upload tool(s).
3. Find the character-swap model in the model catalog. It is the one that replaces the person in an existing video with a character from a reference image while keeping the original motion — called Recast, or WAN 2.2 Animate in "replace" mode.
4. Submit the generation with the uploaded video as the source/motion input and the uploaded image as the character reference. Use sensible defaults for other parameters.
5. Wait and poll until the generation completes. It can take several minutes — keep polling.
6. Reply with ONLY one JSON object as the final line, no markdown fences:
   - success: {{"videoUrl": "<direct URL of the generated video file>"}}
   - failure: {{"error": "<one short sentence saying what failed>"}}

Rules:
- Use only Higgsfield MCP tools.
- If a tool fails for auth or credit reasons, stop and report it via the error JSON.
- Generate only the requested character swap, nothing else."""


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


def parse_agent_output(stdout):
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
    if payload and payload.get("videoUrl"):
        return payload["videoUrl"]
    if payload and payload.get("error"):
        raise PipelineError("Higgsfield step failed: %s" % payload["error"])
    raise PipelineError(
        "The agent finished without producing a video URL. Raw reply: %s"
        % str(envelope.get("result"))[:300])


def swap(video_path, photo_path):
    """Returns the URL of the generated (character-swapped) video."""
    cmd = [
        "claude", "-p", PROMPT.format(video=video_path, photo=photo_path),
        "--output-format", "json",
        "--allowedTools", "mcp__higgsfield,mcp__higgsfield__*",
        "--max-turns", "80",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SWAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise PipelineError("Generation timed out after 30 minutes — try again.")
    except FileNotFoundError:
        raise PipelineError("The 'claude' CLI was not found on PATH.")
    if proc.returncode != 0 and not proc.stdout.strip():
        raise PipelineError(
            "Claude exited with an error: %s" % (proc.stderr or "")[:300])
    return parse_agent_output(proc.stdout)
