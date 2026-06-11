#!/usr/bin/env python3
"""Headless mode: python3 replicate.py <instagram-reel-url>"""
import sys
import uuid

from app import pipeline


def main():
    restore = False if "--no-restore" in sys.argv[1:] else "auto"
    args = [a for a in sys.argv[1:] if a != "--no-restore"]
    if len(args) not in (1, 2, 3):
        print("usage: python3 replicate.py <instagram-reel-url> "
              "[clip-start-seconds] [clip-length-seconds] [--no-restore]")
        return 2
    start = float(args[1]) if len(args) >= 2 else 0.0
    length = float(args[2]) if len(args) == 3 else None
    job_id = uuid.uuid4().hex[:12]
    try:
        out = pipeline.run_job(
            job_id, args[0],
            lambda step, detail: print("[%s] %s" % (step, detail)),
            start=start, length=length, restore=restore)
    except pipeline.PipelineError as exc:
        print("error: %s" % exc)
        return 1
    print("done: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
