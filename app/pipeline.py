"""Reel-replication pipeline: download → prepare → swap → save."""
import glob
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from app import photos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
YTDLP = os.path.join(BIN_DIR, "yt-dlp")
FFMPEG = os.path.join(BIN_DIR, "ffmpeg")
WORK_DIR = os.path.join(ROOT, "work")
OUTPUT_DIR = os.path.join(ROOT, "output")


def user_photo():
    """Path of the stored user photo (me.jpg/jpeg/png), or None."""
    return photos.main_photo()

MIN_SECONDS = 5.0   # Higgsfield Recast accepts 5-15s clips
MAX_SECONDS = 15.0


class PipelineError(Exception):
    """An error whose message is safe to show to the user."""


_REEL_URL = re.compile(
    r"^https?://(www\.)?instagram\.com/(reel|reels|p|tv)/[A-Za-z0-9_-]+/?(\?.*)?$"
)


def detect_image_ext(data):
    """'.jpg' / '.png' from magic bytes, or None for anything else."""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return None


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


def clamp_length(length, duration_seconds):
    """Clamp a user-chosen clip length to Higgsfield's 5–15s window (and
    never longer than the video itself)."""
    try:
        length = float(length)
    except (TypeError, ValueError):
        length = MAX_SECONDS
    length = max(MIN_SECONDS, min(length, MAX_SECONDS))
    if duration_seconds is not None:
        length = min(length, duration_seconds)
    return length


def clamp_start(start, duration_seconds, length=MAX_SECONDS):
    """Clamp a user-chosen clip start so [start, start+length] fits."""
    try:
        start = float(start)
    except (TypeError, ValueError):
        return 0.0
    if start < 0:
        return 0.0
    if duration_seconds is not None:
        return max(0.0, min(start, duration_seconds - length))
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
    if not user_photo():
        raise PipelineError(
            "No photo found — add one in the page at http://localhost:8787 "
            "(or save it as assets/me.jpg).")


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


def prepare_clip(path, duration, job_dir, start=0.0, length=None):
    """Cut the chosen [start, start+length] window when needed; returns the
    path to use. Length is clamped to Higgsfield's 5–15s window."""
    plan_trim(duration)  # rejects videos under 5s
    length = clamp_length(length, duration)
    start = clamp_start(start, duration, length)
    if duration is not None and start <= 0 and length >= duration:
        return path  # the whole video already fits the window
    trimmed = os.path.join(job_dir, "reel-trimmed.mp4")
    # Re-encode rather than stream-copy: copy cuts on keyframes and can
    # overshoot the window, which Higgsfield rejects.
    cmd = [FFMPEG, "-y", "-ss", str(start), "-i", path, "-t", str(length),
           trimmed]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(trimmed):
        raise PipelineError("Couldn't cut the selected clip.")
    return trimmed


SHEET_META = os.path.join(ROOT, "assets", "character-sheet.json")


def _sheet_cache():
    """Return {"path", "ref_id"} when a sheet newer than the photo exists."""
    photo_mtime = os.path.getmtime(user_photo())
    path = None
    for cand in glob.glob(os.path.join(ROOT, "assets", "character-sheet.*")):
        if cand.endswith(".json"):
            continue
        if os.path.getmtime(cand) >= photo_mtime:
            path = cand
        else:
            os.remove(cand)  # photo changed — stale sheet
    if path is None:
        return None
    ref_id = None
    try:
        with open(SHEET_META) as fh:
            meta = json.load(fh)
        if meta.get("photo_mtime") == photo_mtime:
            ref_id = meta.get("ref_id")
    except (OSError, ValueError):
        pass
    return {"path": path, "ref_id": ref_id}


def ensure_character_sheet(progress):
    """Generate (once per photo) the character reference used for swaps.

    Deterministic Higgsfield call first; Claude agent only as fallback.
    Returns {"path": local image, "ref_id": Higgsfield job id or None}."""
    from app import claude_swap, higgsfield

    cached = _sheet_cache()
    if cached:
        return cached
    progress("sheet", "Creating your character sheet "
                      "(happens once per photo)…")
    photo = user_photo()
    photo_mtime = os.path.getmtime(photo)
    ref_id = None
    try:
        client = higgsfield.Client()
        photo_id = higgsfield.upload_file(client, photo)
        job_id = higgsfield.generate_sheet(client, photo_id)
        url = higgsfield.wait_for_job(
            client, job_id, higgsfield.IMAGE_EXTS,
            progress=lambda detail: progress("sheet", detail))
        ref_id = job_id
    except higgsfield.HiggsfieldFatal:
        raise
    except higgsfield.HiggsfieldError as exc:
        if shutil.which("claude") is None:
            raise PipelineError(
                "%s (Claude fallback unavailable — claude CLI not installed)"
                % exc)
        progress("sheet", "Direct Higgsfield call failed (%s) — using the "
                          "Claude agent instead…" % str(exc)[:80])
        url = claude_swap.create_character_sheet(
            photo, progress=lambda detail: progress("sheet", detail))
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
    sheet_path = os.path.join(ROOT, "assets", "character-sheet" + ext)
    try:
        urllib.request.urlretrieve(url, sheet_path)
    except Exception:
        raise PipelineError(
            "Character sheet was generated but downloading it failed. "
            "URL: %s" % url)
    with open(SHEET_META, "w") as fh:
        json.dump({"ref_id": ref_id, "photo_mtime": photo_mtime}, fh)
    return {"path": sheet_path, "ref_id": ref_id}


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


def restore_faces(raw_path, job_id, progress):
    """Local FaceFusion pass that puts the user's real face back onto the
    swapped video. The swap already cost credits, so ANY failure here keeps
    the raw video and surfaces a warning instead of failing the job (the
    "warning" step is stored separately by the server and shown next to
    the finished video)."""
    from app import face_restore

    restored = os.path.join(OUTPUT_DIR, "%s-restored.mp4" % job_id)
    try:
        sources = face_restore.source_photos(user_photo())
        return face_restore.restore(
            raw_path, restored, sources,
            progress=lambda detail: progress("restoring", detail))
    except Exception as exc:
        progress("warning",
                 "Face restore failed (%s) — kept the unrestored video."
                 % str(exc)[:160])
        return raw_path


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


def finish_job(job_id, path, duration, start, progress, length=None,
               engine="kling", restore="auto"):
    """Phase 2: cut the chosen window, ensure the character sheet, run the
    swap, save the result. Deterministic Higgsfield calls first; the Claude
    agent runs only when the default (kling) path hits a schema/protocol
    error — engine experiments fail visibly instead of switching engines."""
    from app import claude_swap, higgsfield

    job_dir = os.path.join(WORK_DIR, job_id)
    progress("preparing", "Cutting your clip…")
    clip = prepare_clip(path, duration, job_dir, start=start, length=length)

    sheet = ensure_character_sheet(progress)

    try:
        client = higgsfield.Client()
        credits = higgsfield.balance(client)
        if credits is not None and credits <= 0:
            raise higgsfield.HiggsfieldFatal(
                "You're out of Higgsfield credits — top up at higgsfield.ai.")
        progress("swapping", "Uploading your clip to Higgsfield…")
        video_id = higgsfield.upload_file(client, clip)
        image_ref = sheet["ref_id"]
        if not image_ref:
            progress("swapping", "Uploading your character sheet…")
            image_ref = higgsfield.upload_file(client, sheet["path"])
        clip_seconds = clamp_length(length, duration)
        gen_id = higgsfield.submit_swap(client, engine, image_ref, video_id,
                                        duration_seconds=clip_seconds)
        progress("swapping",
                 "Swap submitted on %s — rendering on Higgsfield "
                 "(this can take several minutes)…" % engine)
        video_url = higgsfield.wait_for_job(
            client, gen_id, higgsfield.VIDEO_EXTS,
            progress=lambda detail: progress("swapping", detail))
    except higgsfield.HiggsfieldFatal:
        raise
    except higgsfield.HiggsfieldError as exc:
        if engine != "kling":
            raise PipelineError(
                "Seedance run failed: %s" % str(exc)[:200])
        if shutil.which("claude") is None:
            raise PipelineError(
                "%s (Claude fallback unavailable — claude CLI not installed)"
                % exc)
        progress("swapping",
                 "Direct Higgsfield call failed (%s) — falling back to the "
                 "Claude agent…" % str(exc)[:80])
        video_url = claude_swap.swap(
            clip, sheet["path"],
            progress=lambda detail: progress("swapping", detail))

    progress("saving", "Downloading your generated video…")
    out_path = save_result(video_url, job_id)

    from app import face_restore
    if restore == "auto":
        restore = face_restore.available()
    if restore:
        out_path = restore_faces(out_path, job_id, progress)
    return out_path


def run_job(job_id, url, progress, start=0.0, length=None, engine="kling",
            restore="auto"):
    """Full pipeline in one shot (CLI mode — no interactive selection).

    Returns the path of the final video under output/."""
    info = start_job(job_id, url, progress)
    return finish_job(job_id, info["path"], info["duration"], start,
                      progress, length=length, engine=engine,
                      restore=restore)
