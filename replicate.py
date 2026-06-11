#!/usr/bin/env python3
"""Headless mode: python3 replicate.py <instagram-reel-url>"""
import sys
import uuid

from app import pipeline


def main():
    if len(sys.argv) not in (2, 3, 4):
        print("usage: python3 replicate.py <instagram-reel-url> "
              "[clip-start-seconds] [clip-length-seconds]")
        return 2
    start = float(sys.argv[2]) if len(sys.argv) >= 3 else 0.0
    length = float(sys.argv[3]) if len(sys.argv) == 4 else None
    job_id = uuid.uuid4().hex[:12]
    try:
        out = pipeline.run_job(
            job_id, sys.argv[1],
            lambda step, detail: print("[%s] %s" % (step, detail)),
            start=start, length=length)
    except pipeline.PipelineError as exc:
        print("error: %s" % exc)
        return 1
    print("done: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
