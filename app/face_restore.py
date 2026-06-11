"""Local face-restore post-pass: re-imposes the user's real face onto the
swapped video with FaceFusion (face swap + enhance). The swap engines get
body, motion, and scene right but drift on facial identity; this pass fixes
that for free, locally.

Optional — runs only when ./setup.sh --face-restore has vendored the
tooling (standalone Python + FaceFusion) under vendor/.
"""
import glob
import os
import platform
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT, "bin")
VENDOR_DIR = os.path.join(ROOT, "vendor")
FF_DIR = os.path.join(VENDOR_DIR, "facefusion")
FF_SCRIPT = os.path.join(FF_DIR, "facefusion.py")
FF_PYTHON = os.path.join(VENDOR_DIR, "ff-venv", "bin", "python")
FACES_DIR = os.path.join(ROOT, "assets", "faces")
MAX_EXTRA_PHOTOS = 9
TIMEOUT_SECONDS = 2 * 60 * 60


class FaceRestoreError(Exception):
    """An error whose message is safe to show to the user."""


def available():
    """True when the vendored FaceFusion stack is installed."""
    return os.path.exists(FF_SCRIPT) and os.path.exists(FF_PYTHON)


def extra_photos():
    """Extra face photos under assets/faces/, in stable order."""
    paths = []
    for ext in ("jpg", "jpeg", "png"):
        paths.extend(glob.glob(os.path.join(FACES_DIR, "*." + ext)))
    return sorted(paths)


def source_photos(primary):
    """All face photos, primary first. FaceFusion averages the identity
    embeddings across sources, so extra photos improve likeness."""
    return [primary] + [p for p in extra_photos() if p != primary]


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
    for provider in providers():
        if progress:
            progress("Restoring your face onto the video — local and free, "
                     "takes ~1 min per second of video%s…"
                     % (" (first run also downloads models)"
                        if provider == providers()[0] else ", retrying on CPU"))
        try:
            proc = subprocess.run(
                build_command(photos, video_path, output_path, provider),
                cwd=FF_DIR, env=env, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise FaceRestoreError("face restore timed out")
        except OSError as exc:
            raise FaceRestoreError("couldn't launch face restore: %s" % exc)
        if proc.returncode == 0 and os.path.exists(output_path):
            return output_path
        last_error = ((proc.stderr or "") + (proc.stdout or "")).strip()
        last_error = last_error.replace("\r", "\n").splitlines()[-1:]
        last_error = last_error[0][-160:] if last_error else ""
    raise FaceRestoreError(
        "face restore failed%s" % ((": %s" % last_error) if last_error
                                   else ""))
