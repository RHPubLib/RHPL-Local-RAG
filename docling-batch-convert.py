#!/usr/bin/env python3
"""
Batch convert all policy documents through Docling Serve.
Saves markdown output to the OUTPUT_BASE directory, mirroring the input folder structure.
Skips files already converted (resumable).

SETUP: Update INPUT_DIRS and OUTPUT_BASE below to match your folder paths.
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

DOCLING_URL = "http://localhost:5001/v1/convert/file"
OPTIONS = {
    "do_ocr": True,
    "pdf_backend": "dlparse_v4",
    "table_mode": "accurate",
    "ocr_engine": "tesseract",
    "ocr_lang": ["eng"],
}
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".xlsx"}

# ── Configure these paths for your environment ────────────────────────────────
INPUT_DIRS = [
    Path("/path/to/your/Personnel Policies"),
    Path("/path/to/your/Public Service Policies"),
]
OUTPUT_BASE = Path("/path/to/your/kb-converted")
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE = OUTPUT_BASE / "conversion.log"


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


def convert_file(input_path: Path, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(input_path, "rb") as f:
            response = requests.post(
                DOCLING_URL,
                files={"files": (input_path.name, f, "application/octet-stream")},
                data={"options": json.dumps(OPTIONS)},
                timeout=600,
            )

        if response.status_code != 200:
            log(f"  ERROR HTTP {response.status_code}: {response.text[:200]}")
            return False

        data = response.json()

        # Extract markdown from response: document.md_content
        markdown = None
        doc = data.get("document", {})
        if isinstance(doc, dict):
            markdown = doc.get("md_content") or doc.get("md") or doc.get("markdown")
        # Fallback: top-level keys
        if markdown is None:
            markdown = data.get("markdown") or data.get("md_content")

        if markdown is None:
            log(f"  ERROR: Could not find markdown in response. Keys: {list(data.keys())}")
            with open(output_path.with_suffix(".debug.json"), "w") as f:
                json.dump(data, f, indent=2)
            return False

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        return True

    except requests.exceptions.Timeout:
        log(f"  ERROR: Timed out after 600s")
        return False
    except Exception as e:
        log(f"  ERROR: {e}")
        return False


def main():
    OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
    log(f"\n{'='*60}")
    log(f"Docling batch conversion started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*60}")

    all_files = []
    for input_dir in INPUT_DIRS:
        for path in sorted(input_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                rel = path.relative_to(input_dir.parent)
                output_path = OUTPUT_BASE / rel.with_suffix(".md")
                all_files.append((path, output_path))

    total = len(all_files)
    log(f"Found {total} files to convert\n")

    success = 0
    skipped = 0
    failed = []

    for i, (input_path, output_path) in enumerate(all_files, 1):
        # Skip if already converted and non-empty
        if output_path.exists() and output_path.stat().st_size > 100:
            log(f"[{i:3}/{total}] SKIP (already done): {input_path.name}")
            skipped += 1
            continue

        log(f"[{i:3}/{total}] Converting: {input_path.name}")
        t0 = time.time()
        ok = convert_file(input_path, output_path)
        elapsed = time.time() - t0

        if ok:
            size = output_path.stat().st_size
            log(f"         OK ({elapsed:.1f}s, {size:,} bytes output)")
            success += 1
        else:
            log(f"         FAILED ({elapsed:.1f}s)")
            failed.append(str(input_path))

    log(f"\n{'='*60}")
    log(f"Conversion complete: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Success: {success}")
    log(f"  Skipped: {skipped}")
    log(f"  Failed:  {len(failed)}")
    if failed:
        log(f"\nFailed files:")
        for f in failed:
            log(f"  - {f}")
    log(f"{'='*60}\n")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
