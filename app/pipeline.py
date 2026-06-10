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
