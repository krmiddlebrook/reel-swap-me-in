"""Tiny stdlib web server for the reel-replicate app. No dependencies."""
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app import pipeline

PORT = 8787
PUBLIC_DIR = os.path.join(pipeline.ROOT, "public")

_jobs = {}
_jobs_lock = threading.Lock()


def _set_job(job_id, **fields):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(fields)


def _run(job_id, url):
    def progress(step, detail):
        _set_job(job_id, status="running", step=step, detail=detail)
    try:
        out_path = pipeline.run_job(job_id, url, progress)
        _set_job(job_id, status="done", step="done",
                 detail="Your reel is ready!",
                 resultUrl="/output/%s" % os.path.basename(out_path))
    except pipeline.PipelineError as exc:
        _set_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # surface anything unexpected to the UI
        _set_job(job_id, status="error", error="Unexpected error: %s" % exc)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._file(os.path.join(PUBLIC_DIR, "index.html"),
                       "text/html; charset=utf-8")
        elif self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            if job:
                self._json(200, job)
            else:
                self._json(404, {"error": "unknown job"})
        elif self.path.startswith("/output/"):
            name = os.path.basename(self.path)  # no traversal
            self._file(os.path.join(pipeline.OUTPUT_DIR, name), "video/mp4")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/replicate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            url = pipeline.validate_reel_url(data.get("reelUrl"))
        except pipeline.PipelineError as exc:
            self._json(400, {"error": str(exc)})
            return
        except ValueError:
            self._json(400, {"error": "Invalid request body."})
            return
        job_id = uuid.uuid4().hex[:12]
        _set_job(job_id, status="running", step="starting", detail="Starting…")
        threading.Thread(target=_run, args=(job_id, url), daemon=True).start()
        self._json(202, {"jobId": job_id})

    def log_message(self, fmt, *args):  # keep the console quiet while polling
        if "/api/jobs/" not in (args[0] if args else ""):
            BaseHTTPRequestHandler.log_message(self, fmt, *args)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Reel Replicate Me → http://localhost:%d" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
