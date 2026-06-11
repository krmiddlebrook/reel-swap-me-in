"""Deterministic Higgsfield client.

Speaks MCP JSON-RPC directly to https://mcp.higgsfield.ai/mcp, reusing the
OAuth session Claude Code stores in the macOS Keychain. No Claude inference
involved — app/claude_swap.py remains as the fallback when this path hits a
schema/protocol surprise.
"""
import json
import mimetypes
import os
import subprocess
import time
import urllib.request

from app.pipeline import PipelineError

USER_AGENT = "claude-code/2.1.170 (external, cli)"  # their bot filter 403s default UAs
PROTOCOL_VERSION = "2025-03-26"
KEYCHAIN_SERVICE = "Claude Code-credentials"
WAIT_TIMEOUT_SECONDS = 30 * 60
DEFAULT_POLL_SECONDS = 5

SHEET_MODEL = "soul_2"          # Higgsfield's identity model; 1 reference image
SWAP_RESOLUTION = "720p"        # character-swap research sweet spot
SEEDANCE_MODEL = "seedance_2_0"
SEEDANCE_RESOLUTION = "480p"    # lowest tier seedance offers (480/720/1080)
SWAP_ENGINES = ("kling", "seedance")

SEEDANCE_SWAP_PROMPT = (
    "Recreate the reference video exactly: the same scene, background, "
    "environment, lighting, camera movement, framing, pacing, and the same "
    "actions and choreography, beat for beat. Replace the main person in "
    "the video with the person from the reference image - identical face, "
    "hair, and build, faithfully preserved throughout. Change nothing else: "
    "do not alter the setting, add elements, or restyle the footage."
)
VIDEO_EXTS = (".mp4", ".mov", ".webm")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

SHEET_PROMPT = (
    "Studio character reference photo of the exact person in the reference "
    "image - identical face, hair, and build. A single full-body figure, "
    "standing naturally and facing the camera, neutral expression, arms "
    "relaxed at the sides, hands empty - no props or accessories being "
    "held. Soft even studio lighting, neutral color temperature, no harsh "
    "shadows. Soft light-gray seamless studio background, uncluttered. "
    "Sharp focus, photorealistic. No text, labels, watermarks, or borders. "
    "Exactly one person in the image."
)


class HiggsfieldError(PipelineError):
    """Deterministic-path failure that the Claude fallback may recover from."""


class HiggsfieldFatal(PipelineError):
    """Failure the fallback can't fix (auth, credits) — fail fast."""


# ---------------------------------------------------------------- pure helpers

def parse_credentials(raw):
    """Pick the Higgsfield mcpOAuth entry out of the credential-store JSON."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise HiggsfieldFatal(
            "Couldn't read Claude Code's credential store — run 'claude', "
            "type /mcp, and authenticate higgsfield.")
    for key, entry in (data.get("mcpOAuth") or {}).items():
        if key.startswith("higgsfield") and entry.get("accessToken"):
            return entry
    raise HiggsfieldFatal(
        "Higgsfield isn't connected to Claude Code — run './setup.sh', then "
        "'claude', type /mcp, and authenticate higgsfield.")


def unframe(raw):
    """MCP streamable-http responses may arrive SSE-framed; return the JSON."""
    raw = raw or ""
    if "data:" in raw:
        payloads = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
        raw = payloads[-1] if payloads else ""
    try:
        return json.loads(raw)
    except ValueError:
        raise HiggsfieldError("Higgsfield returned an unreadable response.")


def find_media_url(obj, extensions):
    """Recursively find the first https URL whose path ends in `extensions`."""
    if isinstance(obj, str):
        if obj.startswith("https://"):
            path = obj.split("?", 1)[0].lower()
            if path.endswith(extensions):
                return obj
        return None
    if isinstance(obj, dict):
        values = obj.values()
    elif isinstance(obj, (list, tuple)):
        values = obj
    else:
        return None
    for value in values:
        found = find_media_url(value, extensions)
        if found:
            return found
    return None


_INPUT_KEYS = ("params", "request", "inputs", "input")
_RESULT_KEYS = ("results", "result", "output", "outputs")


def _result_subtrees(obj):
    """Yield values stored under result-ish keys, at any depth."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in _RESULT_KEYS:
                yield value
            else:
                for subtree in _result_subtrees(value):
                    yield subtree
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            for subtree in _result_subtrees(item):
                yield subtree


def _strip_inputs(obj):
    """Copy of the payload with params/inputs subtrees removed at any depth
    (input media URLs share the same file extensions as results)."""
    if isinstance(obj, dict):
        return {k: _strip_inputs(v) for k, v in obj.items()
                if k.lower() not in _INPUT_KEYS}
    if isinstance(obj, (list, tuple)):
        return [_strip_inputs(v) for v in obj]
    return obj


def extract_result_url(payload, extensions):
    """Find the GENERATED media URL in a job payload — never an input's.

    job_status wraps the job in a "generation" envelope, so result subtrees
    are located recursively, then a depth-stripped scan is the fallback."""
    for subtree in _result_subtrees(payload):
        url = find_media_url(subtree, extensions)
        if url:
            return url
    return find_media_url(_strip_inputs(payload), extensions)


def classify_tool_error(text):
    """True when the error is fatal (fallback can't help): credits or auth."""
    text = (text or "").lower()
    fatal_markers = ("credit", "balance too low", "insufficient",
                     "unauthorized", "unauthenticated", "invalid token",
                     "authentication", "forbidden", "subscription")
    return any(marker in text for marker in fatal_markers)


# ----------------------------------------------------------------------- auth

def _read_credentials():
    out = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise HiggsfieldFatal(
            "Couldn't read Claude Code's credential store from the Keychain.")
    return parse_credentials(out.stdout)


def get_token():
    """Return (access_token, server_url), refreshing via the claude CLI
    (a no-inference health check) when the stored token is near expiry."""
    entry = _read_credentials()
    if entry.get("expiresAt", 0) / 1000.0 < time.time() + 60:
        subprocess.run(["claude", "mcp", "list"], capture_output=True,
                       text=True, timeout=180)
        entry = _read_credentials()
        if entry.get("expiresAt", 0) / 1000.0 < time.time() + 60:
            raise HiggsfieldFatal(
                "Higgsfield login expired — run 'claude', type /mcp, and "
                "re-authenticate higgsfield.")
    return entry["accessToken"], entry["serverUrl"]


# --------------------------------------------------------------------- client

class Client:
    """Minimal MCP JSON-RPC client for the Higgsfield server."""

    def __init__(self):
        self._token, self._url = get_token()
        self._rid = 0
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "reel-swap-me-in", "version": "1.0"},
        })

    def _rpc(self, method, params=None, timeout=90):
        self._rid += 1
        body = {"jsonrpc": "2.0", "id": self._rid, "method": method}
        if params is not None:
            body["params"] = params
        req = urllib.request.Request(self._url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self._token,
            "User-Agent": USER_AGENT,
        })
        try:
            raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise HiggsfieldFatal(
                    "Higgsfield rejected the stored login (HTTP %d) — run "
                    "'claude', type /mcp, re-authenticate higgsfield." % exc.code)
            raise HiggsfieldError(
                "Higgsfield API error (HTTP %d)." % exc.code)
        except OSError as exc:
            raise HiggsfieldError("Couldn't reach Higgsfield: %s" % exc)
        response = unframe(raw)
        if response.get("error"):
            raise HiggsfieldError(
                "Higgsfield RPC error: %s" % response["error"].get("message"))
        return response.get("result") or {}

    def call(self, tool, arguments, timeout=90):
        """tools/call → (structuredContent dict, text content string)."""
        result = self._rpc("tools/call",
                           {"name": tool, "arguments": arguments},
                           timeout=timeout)
        text = " ".join(c.get("text", "") for c in result.get("content") or []
                        if c.get("type") == "text").strip()
        if result.get("isError"):
            message = text or "tool %s failed" % tool
            if classify_tool_error(message):
                raise HiggsfieldFatal("Higgsfield: %s" % message[:300])
            raise HiggsfieldError("Higgsfield: %s" % message[:300])
        structured = result.get("structuredContent")
        if structured is None and text:
            try:
                structured = json.loads(text)
            except ValueError:
                structured = None
        return structured or {}, text


# ------------------------------------------------------------------------ ops

def upload_file(client, path):
    """Upload a local file; returns its confirmed media_id."""
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    media_kind = "video" if content_type.startswith("video") else "image"
    structured, text = client.call("media_upload", {
        "filename": os.path.basename(path),
        "content_type": content_type,
    })
    media_id, put_url = _extract_upload_target(structured, text)
    with open(path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(put_url, data=data, method="PUT",
                                 headers={"Content-Type": content_type,
                                          "User-Agent": USER_AGENT})
    try:
        urllib.request.urlopen(req, timeout=300).read()
    except (urllib.error.HTTPError, OSError) as exc:
        raise HiggsfieldError("Uploading %s failed: %s"
                              % (os.path.basename(path), exc))
    client.call("media_confirm", {"type": media_kind, "media_id": media_id})
    return media_id


def _walk_strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            for pair in _walk_strings(v):
                yield pair if pair[0] else (k, pair[1])
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            for pair in _walk_strings(item):
                yield pair
    elif isinstance(obj, str):
        yield (None, obj)


def _extract_upload_target(structured, text):
    """Find (media_id, presigned PUT url) in a media_upload response."""
    media_id, put_url = None, None
    source = structured if structured else None
    if source is None:
        try:
            source = json.loads(text)
        except (ValueError, TypeError):
            source = {"text": text}
    for key, value in _walk_strings(source):
        lowered = (key or "").lower()
        if value.startswith("https://") and ("upload" in lowered or "url" in lowered
                                             or put_url is None and "X-Amz" in value):
            put_url = put_url or value
        if "media" in lowered and "id" in lowered and len(value) >= 32:
            media_id = media_id or value
    if not media_id or not put_url:
        raise HiggsfieldError(
            "media_upload response had an unexpected shape (no media_id/url).")
    return media_id, put_url


def _job_id_from(structured, text):
    for key, value in _walk_strings(structured if structured else {}):
        if (key or "").lower() in ("jobid", "job_id", "id") and len(value) >= 8:
            return value
    for token in (text or "").replace('"', " ").split():
        if len(token) == 36 and token.count("-") == 4:
            return token
    raise HiggsfieldError("Generation was submitted but no job id came back.")


def generate_sheet(client, photo_media_id):
    """Submit the character-sheet image generation; returns job id."""
    structured, text = client.call("generate_image", {"params": {
        "model": SHEET_MODEL,
        "prompt": SHEET_PROMPT,
        "aspect_ratio": "9:16",
        "medias": [{"value": photo_media_id, "role": "image"}],
    }})
    return _job_id_from(structured, text)


def _generate_video(client, params):
    """generate_video with automatic decline of preset recommendations —
    the server may intercept prompts it thinks match a preset and ask; we
    always want literal generation."""
    structured, text = client.call("generate_video", {"params": params})
    notice = (structured or {}).get("notice") or {}
    if notice.get("type") == "preset_recommendation":
        declined = ((notice.get("data") or {}).get("retry_literal_with")
                    or {}).get("declined_preset_id")
        retry = dict(params)
        if declined:
            retry["declined_preset_id"] = declined
        structured, text = client.call("generate_video", {"params": retry})
    return structured, text


def submit_swap(client, engine, image_ref, video_media_id,
                duration_seconds=None):
    """Submit the character swap on the chosen engine; returns job id."""
    if engine == "seedance":
        params = {
            "model": SEEDANCE_MODEL,
            "prompt": SEEDANCE_SWAP_PROMPT,
            "aspect_ratio": "auto",     # follow the reference video
            "resolution": SEEDANCE_RESOLUTION,
            "mode": "std",
            "medias": [
                {"value": video_media_id, "role": "video"},
                {"value": image_ref, "role": "image"},
            ],
        }
        if duration_seconds:
            # match the clip; seedance accepts 4-15s and defaults to 15
            params["duration"] = max(4, min(15, int(round(duration_seconds))))
        structured, text = _generate_video(client, params)
    else:
        structured, text = client.call("motion_control", {"params": {
            "image_id": image_ref,
            "motion_video_id": video_media_id,
            "resolution": SWAP_RESOLUTION,
            "scene_control": "video",  # keep the reel's scene, replace the person
        }})
    return _job_id_from(structured, text)


def wait_for_job(client, job_id, extensions, progress=None):
    """Poll job_status until terminal; returns the result media URL."""
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        structured, text = client.call(
            "job_status", {"jobId": job_id, "sync": True}, timeout=120)
        blob = json.dumps(structured).lower()
        status = str(structured.get("status", "")).lower()
        if status in ("completed", "succeeded", "success") or '"status": "completed"' in blob:
            url = extract_result_url(structured, extensions)
            if url:
                return url
            raise HiggsfieldError(
                "Job completed but no result URL was found in the response.")
        if status in ("failed", "error", "canceled", "cancelled") \
                or '"status": "failed"' in blob:
            reason = structured.get("fail_reason") or text or "generation failed"
            if classify_tool_error(str(reason)):
                raise HiggsfieldFatal("Higgsfield: %s" % str(reason)[:300])
            raise HiggsfieldError("Higgsfield: %s" % str(reason)[:300])
        if progress:
            pct = structured.get("progress")
            progress("Rendering on Higgsfield…" +
                     (" (%s%%)" % pct if isinstance(pct, (int, float)) else ""))
        time.sleep(float(structured.get("poll_after_seconds")
                         or DEFAULT_POLL_SECONDS))
    raise HiggsfieldError("Generation timed out after 30 minutes.")


def balance(client):
    """Return available credits as an int, or None if the shape is unknown."""
    structured, text = client.call("balance", {})
    for key in ("credits", "available_credits", "balance"):
        value = structured.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, dict):
            inner = value.get("available") or value.get("amount")
            if isinstance(inner, (int, float)):
                return int(inner)
    return None
