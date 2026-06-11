"""Reel-replication pipeline: download → prepare → swap → save."""
import os
import re
import subprocess
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
YTDLP = os.path.join(BIN_DIR, "yt-dlp")
FFMPEG = os.path.join(BIN_DIR, "ffmpeg")
USER_PHOTO = os.path.join(ROOT, "assets", "me.jpg")
WORK_DIR = os.path.join(ROOT, "work")
OUTPUT_DIR = os.path.join(ROOT, "output")

MIN_SECONDS = 5.0   # Higgsfield Recast accepts 5-15s clips
MAX_SECONDS = 15.0


class PipelineError(Exception):
    """An error whose message is safe to show to the user."""


_REEL_URL = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|reels|p|tv)/[A-Za-z0-9_-]+/?(\?.*)?$"
)


def validate_reel_url(url):
    url = (url or "").strip()
    if not _REEL_URL.match(url):
        raise PipelineError("That doesn't look like an Instagram reel URL.")
    return url.split("?")[0]


def plan_trim(duration_seconds):
    """Return the length to trim to, or None when no trim is needed."""
    if duration_seconds is None:
        return MAX_SECONDS
    if duration_seconds < MIN_SECONDS:
        raise PipelineError(
            "Reel too short — Higgsfield needs at least 5 seconds.")
    if duration_seconds > MAX_SECONDS:
        return MAX_SECONDS
    return None


def clamp_start(start, duration_seconds):
    """Clamp a user-chosen clip start so [start, start+15s] fits the video."""
    try:
        start = float(start)
    except (TypeError, ValueError):
        return 0.0
    if start < 0:
        return 0.0
    if duration_seconds is not None:
        return max(0.0, min(start, duration_seconds - MAX_SECONDS))
    return start


def _require_setup():
    missing = []
    if not os.path.exists(YTDLP):
        missing.append("bin/yt-dlp")
    if not os.path.exists(FFMPEG):
        missing.append("bin/ffmpeg")
    if missing:
        raise PipelineError(
            "Missing %s — run ./setup.sh first." % " and ".join(missing))
    if not os.path.exists(USER_PHOTO):
        raise PipelineError(
            "No photo found — save a clear front-facing photo of yourself "
            "as assets/me.jpg.")


def download_reel(url, job_dir):
    """Download the reel; returns (mp4_path, duration_seconds_or_None)."""
    os.makedirs(job_dir, exist_ok=True)
    out_path = os.path.join(job_dir, "reel.mp4")
    cmd = [
        YTDLP, "--no-playlist", "-f", "mp4/best",
        "--no-simulate", "--print", "%(duration)s",
        "-o", out_path, url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise PipelineError(
            "Couldn't download this reel — make sure the URL is right and "
            "the reel is public.")
    duration = None
    try:
        duration = float(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        pass
    return out_path, duration


def prepare_clip(path, duration, job_dir, start=0.0):
    """Trim to Higgsfield's window when needed; returns the path to use.

    `start` (seconds) picks which window of a long reel to keep."""
    trim_to = plan_trim(duration)
    start = clamp_start(start, duration)
    if trim_to is None:
        return path
    trimmed = os.path.join(job_dir, "reel-trimmed.mp4")
    # Re-encode rather than stream-copy: copy cuts on keyframes and can
    # overshoot past 15s, which Higgsfield rejects.
    cmd = [FFMPEG, "-y", "-ss", str(start), "-i", path, "-t", str(trim_to),
           trimmed]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(trimmed):
        raise PipelineError("Couldn't trim the reel to 15 seconds.")
    return trimmed


def save_result(video_url, job_id):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "%s.mp4" % job_id)
    try:
        urllib.request.urlretrieve(video_url, out)
    except Exception:
        raise PipelineError(
            "Generation succeeded but downloading the result failed. "
            "URL: %s" % video_url)
    return out


def start_job(job_id, url, progress):
    """Phase 1: download the reel and decide whether the user must pick a
    15s window. Returns {path, duration, needs_selection}."""
    _require_setup()
    url = validate_reel_url(url)
    job_dir = os.path.join(WORK_DIR, job_id)

    progress("downloading", "Downloading the reel…")
    path, duration = download_reel(url, job_dir)
    needs_selection = duration is not None and duration > MAX_SECONDS
    return {"path": path, "duration": duration,
            "needs_selection": needs_selection}


def finish_job(job_id, path, duration, start, progress):
    """Phase 2: trim from `start`, run the swap, save the result."""
    from app import claude_swap  # late import: keeps pure functions test-light

    job_dir = os.path.join(WORK_DIR, job_id)
    progress("preparing", "Preparing your 15-second clip…")
    clip = prepare_clip(path, duration, job_dir, start=start)

    progress("swapping",
             "Claude + Higgsfield are re-casting you into the reel "
             "(this can take several minutes)…")
    video_url = claude_swap.swap(
        clip, USER_PHOTO,
        progress=lambda detail: progress("swapping", detail))

    progress("saving", "Downloading your generated video…")
    return save_result(video_url, job_id)


def run_job(job_id, url, progress, start=0.0):
    """Full pipeline in one shot (CLI mode — no interactive selection).

    Returns the path of the final video under output/."""
    info = start_job(job_id, url, progress)
    return finish_job(job_id, info["path"], info["duration"], start, progress)
