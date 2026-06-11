"""Local face-restore post-pass: re-imposes the user's real face onto the
swapped video with FaceFusion (face swap + enhance). The swap engines get
body, motion, and scene right but drift on facial identity; this pass fixes
that for free, locally.

Optional — runs only when ./setup.sh --face-restore has vendored the
tooling (standalone Python + FaceFusion) under vendor/.
"""
import json
import os
import platform
import subprocess
import threading

from app import photos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
VENDOR_DIR = os.path.join(ROOT, "vendor")
FF_DIR = os.path.join(VENDOR_DIR, "facefusion")
FF_SCRIPT = os.path.join(FF_DIR, "facefusion.py")
FF_PYTHON = os.path.join(VENDOR_DIR, "ff-venv", "bin", "python")
TIMEOUT_SECONDS = 2 * 60 * 60

SETTINGS_PATH = os.path.join(ROOT, "assets", "face-restore-settings.json")

SWAPPER_MODELS = ("hyperswap_1a_256", "hyperswap_1b_256",
                  "hyperswap_1c_256", "inswapper_128_fp16",
                  "inswapper_128", "ghost_2_256", "simswap_256")
ENHANCER_MODELS = ("gfpgan_1.4", "codeformer", "restoreformer_plus_plus",
                   "gpen_bfr_512")
PIXEL_BOOSTS = ("256x256", "512x512", "768x768", "1024x1024")

DEFAULT_SETTINGS = {
    "enhancer_blend": 80,
    "pixel_boost": "512x512",
    "swapper_model": "hyperswap_1a_256",
    "enhancer_model": "gfpgan_1.4",
}

_SETTING_CHOICES = {
    "pixel_boost": PIXEL_BOOSTS,
    "swapper_model": SWAPPER_MODELS,
    "enhancer_model": ENHANCER_MODELS,
}


def validate_settings(data):
    """Known keys with valid values; raises ValueError naming the first
    bad one. Unknown keys are ignored (forward compatibility)."""
    if not isinstance(data, dict):
        raise ValueError("settings must be a JSON object")
    clean = {}
    for key, value in data.items():
        if key == "enhancer_blend":
            if isinstance(value, bool) or not isinstance(value, int) \
                    or not 0 <= value <= 100:
                raise ValueError("enhancer_blend must be an integer 0-100")
            clean[key] = value
        elif key in _SETTING_CHOICES:
            if value not in _SETTING_CHOICES[key]:
                raise ValueError("%s must be one of: %s"
                                 % (key, ", ".join(_SETTING_CHOICES[key])))
            clean[key] = value
    return clean


def load_settings():
    """Saved settings merged over defaults. Never raises — a corrupt or
    missing file silently yields the defaults."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH) as fh:
            settings.update(validate_settings(json.load(fh)))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(data):
    """Validate, merge over current settings, persist; returns the result."""
    clean = validate_settings(data)
    settings = load_settings()
    settings.update(clean)
    with open(SETTINGS_PATH, "w") as fh:
        json.dump(settings, fh, indent=2)
    return settings


# One restore at a time: concurrent multi-GB ONNX inference thrashes the
# machine, and parallel CoreML model compilation is flaky.
_RUN_LOCK = threading.Lock()


class FaceRestoreError(Exception):
    """An error whose message is safe to show to the user."""


def available():
    """True when the vendored FaceFusion stack is installed."""
    return os.path.exists(FF_SCRIPT) and os.path.exists(FF_PYTHON)


def source_photos(primary):
    """All face photos, primary first. FaceFusion averages the identity
    embeddings across sources, so extra photos improve likeness."""
    return [primary] + [p for p in photos.extra_photos() if p != primary]


def providers():
    """Execution providers to try, fastest first."""
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return ["coreml", "cpu"]
    return ["cpu"]


def build_command(sources, target, output, provider):
    cmd = [FF_PYTHON, FF_SCRIPT, "headless-run", "-s"]
    cmd += list(sources)
    cmd += [
        "-t", target, "-o", output,
        "--processors", "face_swapper", "face_enhancer",
        "--face-swapper-pixel-boost", "512x512",
        "--face-enhancer-model", "gfpgan_1.4",
        "--face-enhancer-blend", "80",
        "--face-selector-mode", "one",
        "--face-selector-order", "large-small",
        "--output-audio-encoder", "aac",
        "--execution-providers", provider,
    ]
    return cmd


def restore(video_path, output_path, photos, progress=None):
    """Run the FaceFusion pass; returns output_path.

    Tries CoreML first on Apple Silicon and falls back to CPU — the CoreML
    provider can fail in restricted environments (it compiles models into
    the system temp dir)."""
    if not available():
        raise FaceRestoreError(
            "Face restore isn't installed — run ./setup.sh --face-restore.")
    if not photos:
        raise FaceRestoreError("No face photo found.")
    env = dict(os.environ)
    env["PATH"] = BIN_DIR + os.pathsep + env.get("PATH", "")  # vendored ffmpeg
    last_error = ""
    with _RUN_LOCK:
        for provider in providers():
            if progress:
                progress("Restoring your face onto the video — local and "
                         "free, takes ~1 min per second of video%s…"
                         % (" (first run also downloads models)"
                            if provider == providers()[0]
                            else ", retrying on CPU"))
            try:
                proc = subprocess.run(
                    build_command(photos, video_path, output_path, provider),
                    cwd=FF_DIR, env=env, capture_output=True, text=True,
                    timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # No CPU retry after a timeout: an even slower provider
                # won't beat a 2-hour deadline.
                raise FaceRestoreError("face restore timed out")
            except OSError as exc:
                raise FaceRestoreError(
                    "couldn't launch face restore: %s" % exc)
            if proc.returncode == 0 and os.path.exists(output_path):
                return output_path
            last_error = _last_line(proc.stderr) or _last_line(proc.stdout)
    raise FaceRestoreError(
        "face restore failed%s" % ((": %s" % last_error) if last_error
                                   else ""))


def _last_line(text):
    """Last non-empty line of subprocess output, trimmed for display."""
    lines = [ln.strip() for ln in (text or "").replace("\r", "\n").splitlines()
             if ln.strip()]
    return lines[-1][-160:] if lines else ""
