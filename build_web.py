#!/usr/bin/env python3
"""Optionally rebuild the shipped overview; running the dashboard needs no Node."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
# Kept for the standalone subscription-period regression check.
ENHANCED_TAIL = (WEB_DIR / "src" / "overview.js").read_text(encoding="utf-8")


def verify() -> None:
    manifest = json.loads((WEB_DIR / "build-manifest.json").read_text(encoding="utf-8"))
    for group in ("inputs", "outputs"):
        for name, expected in manifest[group].items():
            actual = hashlib.sha256((BASE_DIR / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Web build is stale: {name}; run npm ci and python3 build_web.py")
    def fingerprint(match):
        before, url, after = match.groups()
        version = hashlib.sha256((WEB_DIR / url.lstrip("/")).read_bytes()).hexdigest()[:12]
        return before + url + "?v=" + version + after
    template = (WEB_DIR / "src" / "index.html").read_text(encoding="utf-8")
    expected_html = re.sub(r'((?:src|href)=")(/assets/[^"?]+\.(?:js|css))(")', fingerprint, template)
    if (WEB_DIR / "index.html").read_text(encoding="utf-8") != expected_html:
        raise ValueError("Overview HTML or its asset fingerprints are stale; run python3 prepare_web.py or rebuild")
    print("Verified shipped overview source and assets")


def build() -> None:
    try:
        subprocess.run([os.environ.get("NODE_BINARY", "node"), "web/build.cjs"], cwd=BASE_DIR, check=True)
    except FileNotFoundError as error:
        raise SystemExit("Optional rebuild requires Node.js 22+ and npm ci. The shipped dashboard runs without Node.") from error
    verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the shipped source and assets without Node")
    options = parser.parse_args()
    verify() if options.check else build()
