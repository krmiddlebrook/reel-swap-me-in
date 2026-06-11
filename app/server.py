"""Tiny stdlib web server for the reel-replicate app. No dependencies."""
import json
import os
import re
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import face_restore, oauth, pipeline

PORT = 8787
PUBLIC_DIR = os.path.join(pipeline.ROOT, "public")

_jobs = {}            # job_id -> public state (returned by /api/jobs/<id>)
_job_files = {}       # job_id -> {path, duration} kept server-side only
_jobs_lock = threading.Lock()

_CLIP_PATH = re.compile(r"^/api/jobs/([0-9a-f]{12})/clip$")
_WORK_PATH = re.compile(r"^/work/([0-9a-f]{12})/reel\.mp4$")


def _status():
    """Setup state for the UI banner."""
    if oauth.connected():
        connected, source = True, "app"
    else:
        try:
            from app import higgsfield
            higgsfield._read_credentials()
            connected, source = True, "claude"
        except Exception:
            connected, source = False, None
    return {"connected": connected, "source": source,
            "photo": bool(pipeline.user_photo()),
            "faceRestore": face_restore.available(),
            "extraFaces": len(face_restore.extra_photos())}


def _set_job(job_id, **fields):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _progress(job_id):
    def progress(step, detail):
        if step == "warning":  # keep the job running; shown next to "done"
            _set_job(job_id, warning=detail)
        else:
            _set_job(job_id, status="running", step=step, detail=detail)
    return progress


def _run_start(job_id, url, engine, restore):
    try:
        info = pipeline.start_job(job_id, url, _progress(job_id))
        info["engine"] = engine
        info["restore"] = restore
        if info["needs_selection"]:
            with _jobs_lock:
                _job_files[job_id] = info
            _set_job(
                job_id, status="awaiting_selection", step="selecting",
                detail="This reel is %ds — pick the part to use (5–15s)."
                       % round(info["duration"]),
                reelUrl="/work/%s/reel.mp4" % job_id,
                duration=info["duration"])
            return
        _finish(job_id, info, 0.0)
    except pipeline.PipelineError as exc:
        _set_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # surface anything unexpected to the UI
        _set_job(job_id, status="error", error="Unexpected error: %s" % exc)


def _run_finish(job_id, info, start, length=None):
    try:
        _finish(job_id, info, start, length)
    except pipeline.PipelineError as exc:
        _set_job(job_id, status="error", error=str(exc))
    except Exception as exc:
        _set_job(job_id, status="error", error="Unexpected error: %s" % exc)


def _finish(job_id, info, start, length=None):
    out_path = pipeline.finish_job(
        job_id, info["path"], info["duration"], start, _progress(job_id),
        length=length, engine=info.get("engine") or "kling",
        restore=info.get("restore", False))
    _set_job(job_id, status="done", step="done",
             detail="Your reel is ready!",
             resultUrl="/output/%s" % os.path.basename(out_path))


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        """Serve a file with byte-range support (Safari needs 206 for video)."""
        try:
            size = os.path.getsize(path)
            fh = open(path, "rb")
        except OSError:
            self.send_error(404)
            return
        with fh:
            start, end, code = 0, size - 1, 200
            range_match = re.match(
                r"bytes=(\d*)-(\d*)$", (self.headers.get("Range") or "").strip())
            if range_match and (range_match.group(1) or range_match.group(2)):
                if range_match.group(1):
                    start = int(range_match.group(1))
                    if range_match.group(2):
                        end = min(int(range_match.group(2)), size - 1)
                else:  # suffix form: last N bytes
                    start = max(0, size - int(range_match.group(2)))
                if start >= size or start > end:
                    self.send_error(416)
                    return
                code = 206
            fh.seek(start)
            body = fh.read(end - start + 1)
        self.send_response(code)
        if code == 206:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        work_match = _WORK_PATH.match(self.path)
        if self.path in ("/", "/index.html"):
            self._file(os.path.join(PUBLIC_DIR, "index.html"),
                       "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(200, _status())
        elif self.path.startswith("/oauth/callback"):
            self._get_oauth_callback()
        elif self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            if job:
                self._json(200, job)
            else:
                self._json(404, {"error": "unknown job"})
        elif work_match:
            self._file(os.path.join(pipeline.WORK_DIR, work_match.group(1),
                                    "reel.mp4"), "video/mp4")
        elif self.path.startswith("/output/"):
            name = os.path.basename(self.path)  # no traversal
            self._file(os.path.join(pipeline.OUTPUT_DIR, name), "video/mp4")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/photo":
            self._post_photo()
            return
        if self.path == "/api/faces":
            self._post_face()
            return
        if self.path == "/api/faces/clear":
            self._post_faces_clear()
            return
        if self.path == "/api/auth/start":
            self._post_auth_start()
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "Invalid request body."})
            return

        clip_match = _CLIP_PATH.match(self.path)
        if clip_match:
            self._post_clip(clip_match.group(1), data)
        elif self.path == "/api/replicate":
            self._post_replicate(data)
        else:
            self.send_error(404)

    def _post_auth_start(self):
        try:
            self._json(200, {"authUrl": oauth.begin_login(PORT)})
        except pipeline.PipelineError as exc:
            self._json(502, {"error": str(exc)})

    def _get_oauth_callback(self):
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [""])[0]
        error = (query.get("error") or [""])[0]
        if error or not code:
            message = "Login failed: %s — close this tab and try again." \
                      % (error or "no code returned")
        else:
            try:
                oauth.handle_callback(code, state, PORT)
                message = ("Higgsfield connected ✓ — you can close this tab "
                           "and head back to Reel Swap Me In.")
            except pipeline.PipelineError as exc:
                message = "Login failed: %s" % exc
        body = ("<!doctype html><meta charset='utf-8'><body style=\""
                "font-family:sans-serif;background:#0e0d12;color:#f3f1ec;"
                "display:flex;align-items:center;justify-content:center;"
                "min-height:100vh;text-align:center\"><h3>%s</h3></body>"
                % message).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _post_photo(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 20 * 1024 * 1024:
            self._json(400, {"error": "Photo must be a file under 20 MB."})
            return
        data = self.rfile.read(length)
        ext = pipeline.detect_image_ext(data)
        if not ext:
            self._json(400, {"error": "Please upload a JPEG or PNG photo."})
            return
        assets = os.path.join(pipeline.ROOT, "assets")
        os.makedirs(assets, exist_ok=True)
        for old in ("me.jpg", "me.jpeg", "me.png"):
            old_path = os.path.join(assets, old)
            if os.path.exists(old_path):
                os.remove(old_path)
        with open(os.path.join(assets, "me" + ext), "wb") as fh:
            fh.write(data)
        self._json(200, {"ok": True})

    def _post_face(self):
        """Store one extra face photo (improves face-restore likeness)."""
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 20 * 1024 * 1024:
            self._json(400, {"error": "Photo must be a file under 20 MB."})
            return
        data = self.rfile.read(length)
        ext = pipeline.detect_image_ext(data)
        if not ext:
            self._json(400, {"error": "Please upload a JPEG or PNG photo."})
            return
        if len(face_restore.extra_photos()) >= face_restore.MAX_EXTRA_PHOTOS:
            self._json(400, {"error": "That's plenty — %d extra photos max."
                                      % face_restore.MAX_EXTRA_PHOTOS})
            return
        os.makedirs(face_restore.FACES_DIR, exist_ok=True)
        name = "face-%s%s" % (uuid.uuid4().hex[:8], ext)
        with open(os.path.join(face_restore.FACES_DIR, name), "wb") as fh:
            fh.write(data)
        self._json(200, {"ok": True,
                         "extraFaces": len(face_restore.extra_photos())})

    def _post_faces_clear(self):
        for path in face_restore.extra_photos():
            os.remove(path)
        self._json(200, {"ok": True, "extraFaces": 0})

    def _post_replicate(self, data):
        from app import higgsfield
        try:
            url = pipeline.validate_reel_url(data.get("reelUrl"))
        except pipeline.PipelineError as exc:
            self._json(400, {"error": str(exc)})
            return
        engine = data.get("engine") or "kling"
        if engine not in higgsfield.SWAP_ENGINES:
            self._json(400, {"error": "Unknown swap engine."})
            return
        restore = bool(data.get("restore")) and face_restore.available()
        job_id = uuid.uuid4().hex[:12]
        _set_job(job_id, status="running", step="starting", detail="Starting…")
        threading.Thread(target=_run_start,
                         args=(job_id, url, engine, restore),
                         daemon=True).start()
        self._json(202, {"jobId": job_id})

    def _post_clip(self, job_id, data):
        with _jobs_lock:
            job = dict(_jobs.get(job_id) or {})
            info = _job_files.get(job_id)
        if not job or info is None:
            self._json(404, {"error": "unknown job"})
            return
        if job.get("status") != "awaiting_selection":
            self._json(409, {"error": "This job isn't waiting on a clip choice."})
            return
        length = pipeline.clamp_length(data.get("length"), info["duration"])
        start = pipeline.clamp_start(data.get("start"), info["duration"], length)
        _set_job(job_id, status="running", step="preparing",
                 detail="Clipping %0.1fs from %0.1fs…" % (length, start),
                 reelUrl=None)
        threading.Thread(target=_run_finish,
                         args=(job_id, info, start, length),
                         daemon=True).start()
        self._json(202, {"jobId": job_id, "start": start, "length": length})

    def log_message(self, fmt, *args):  # keep the console quiet while polling
        if "/api/jobs/" not in (args[0] if args else ""):
            BaseHTTPRequestHandler.log_message(self, fmt, *args)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Reel Swap Me In → http://localhost:%d" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
