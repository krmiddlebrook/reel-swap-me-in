#!/usr/bin/env python3
"""Headless mode: python3 replicate.py <instagram-reel-url>"""
import sys
import uuid

from app import pipeline


def main():
    if len(sys.argv) != 2:
        print("usage: python3 replicate.py <instagram-reel-url>")
        return 2
    job_id = uuid.uuid4().hex[:12]
    try:
        out = pipeline.run_job(
            job_id, sys.argv[1],
            lambda step, detail: print("[%s] %s" % (step, detail)))
    except pipeline.PipelineError as exc:
        print("error: %s" % exc)
        return 1
    print("done: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
