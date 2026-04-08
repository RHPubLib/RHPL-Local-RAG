#!/usr/bin/env python3
"""
Wipe the existing Open WebUI knowledge base and re-upload all
Docling-converted markdown files.

Requires ENABLE_API_KEY=true in Open WebUI.
Connects via the nginx container on the Docker network (docker exec nginx curl).

SETUP: Update the configuration block below before running.
       Generate your API key in Open WebUI → Admin → Settings → Account → API Keys.
       Never commit a real API key to this file.
"""

import os
import sys
import json
import time
import subprocess
import requests
from pathlib import Path

# ── Configure these values for your environment ───────────────────────────────
OWUI_BASE = "http://open-webui:8080"          # Open WebUI address inside Docker network
API_KEY   = "YOUR_OPEN_WEBUI_API_KEY"         # Replace with your Open WebUI API key
KB_NAME   = "Your Library Policies"           # Name to create/replace in Open WebUI
KB_DESC   = "Staff policies and procedures"   # Description shown in Open WebUI

# Directories containing Docling-converted Markdown files to upload
DOCLING_OUTPUT = Path("/path/to/your/kb-converted")
INPUT_DIRS = [
    Path("/path/to/your/kb-converted/Personnel Policies"),
    Path("/path/to/your/kb-converted/Public Service Policies"),
]

# Additional directories uploaded directly (not mirrored from kb-sources)
EXTRA_KB_DIRS = [
    Path("/path/to/your/kb-converted/Staff Knowledge"),
]

# Model ID to update in Open WebUI after KB recreation
MODEL_ID = "your-policies-model-id"
# ─────────────────────────────────────────────────────────────────────────────

LOG_FILE = Path("/tmp/owui-upload.log")


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(msg + "\n")


def api(method, path, **kwargs):
    """Make an API call via docker exec nginx curl."""
    url = OWUI_BASE + path
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {API_KEY}"

    if method == "GET":
        cmd = [
            "docker", "exec", "nginx", "curl", "-s", "-X", "GET",
            "-H", f"Authorization: Bearer {API_KEY}",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(result.stdout)

    elif method == "POST" and "json" in kwargs:
        payload = json.dumps(kwargs["json"])
        cmd = [
            "docker", "exec", "nginx", "curl", "-s", "-X", "POST",
            "-H", f"Authorization: Bearer {API_KEY}",
            "-H", "Content-Type: application/json",
            "-d", payload,
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(result.stdout)

    elif method == "DELETE":
        cmd = [
            "docker", "exec", "nginx", "curl", "-s", "-X", "DELETE",
            "-H", f"Authorization: Bearer {API_KEY}",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return json.loads(result.stdout)
        except Exception:
            return {"raw": result.stdout}

    raise ValueError(f"Unsupported method: {method}")


def upload_file(md_path: Path, index: int):
    """Upload a markdown file to Open WebUI files API. Returns file ID or None."""
    tmp_path = f"/tmp/owui_upload_{index:04d}.md"

    content = md_path.read_bytes()
    write_cmd = subprocess.run(
        ["docker", "exec", "-i", "nginx", "sh", "-c", f"cat > '{tmp_path}'"],
        input=content,
        capture_output=True,
    )
    if write_cmd.returncode != 0:
        log(f"  ERROR writing to nginx container: {write_cmd.stderr}")
        return None

    safe_name = md_path.name
    upload_cmd = subprocess.run(
        [
            "docker", "exec", "nginx", "curl", "-s", "-X", "POST",
            "-H", f"Authorization: Bearer {API_KEY}",
            "-F", f"file=@{tmp_path};filename={safe_name};type=text/markdown",
            f"{OWUI_BASE}/api/v1/files/",
        ],
        capture_output=True, text=True,
    )

    subprocess.run(["docker", "exec", "nginx", "rm", "-f", tmp_path])

    try:
        data = json.loads(upload_cmd.stdout)
        if "id" in data:
            return data["id"]
        else:
            log(f"  ERROR uploading: {upload_cmd.stdout[:300]}")
            return None
    except Exception as e:
        log(f"  ERROR parsing upload response: {e} — {upload_cmd.stdout[:200]}")
        return None


def add_file_to_kb(kb_id: str, file_id: str) -> bool:
    result = api("POST", f"/api/v1/knowledge/{kb_id}/file/add", json={"file_id": file_id})
    return "id" in result or result.get("status") == "success" or "file_id" in str(result)


def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log(f"\n{'='*60}")
    log(f"Open WebUI KB reload started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"{'='*60}")

    # --- Step 1: Find all converted MD files ---
    md_files = []
    for input_dir in INPUT_DIRS:
        if not input_dir.exists():
            log(f"WARNING: input dir not found: {input_dir}")
            continue
        for md_path in sorted(input_dir.rglob("*.md")):
            if md_path.name in ("conversion.log", "upload.log"):
                continue
            if md_path.stat().st_size < 50:
                log(f"SKIP (empty): {md_path.name}")
                continue
            md_files.append(md_path)

    for extra_dir in EXTRA_KB_DIRS:
        if not extra_dir.exists():
            continue
        for md_path in sorted(extra_dir.rglob("*.md")):
            if md_path.stat().st_size < 50:
                log(f"SKIP (empty): {md_path.name}")
                continue
            md_files.append(md_path)

    log(f"Found {len(md_files)} converted markdown files to upload")

    # --- Step 2: Delete existing KB(s) by name and recreate ---
    # Note: We delete and recreate rather than update in place because Open WebUI's
    # vector store does not support reliable partial updates. Deleting clears the
    # embeddings completely before re-uploading.
    log(f"\n--- Finding existing knowledge base: {KB_NAME} ---")

    kbs_resp = api("GET", "/api/v1/knowledge/")
    if isinstance(kbs_resp, list):
        kbs = kbs_resp
    elif isinstance(kbs_resp, dict):
        kbs = kbs_resp.get("items", [])
    else:
        kbs = []

    matching = [kb for kb in kbs if kb.get("name") == KB_NAME]
    old_kb_ids = [kb.get("id") for kb in matching]
    for kb in matching:
        api("DELETE", f"/api/v1/knowledge/{kb.get('id')}/delete")
        log(f"Deleted existing KB: {kb.get('id')}")

    log(f"\n--- Creating knowledge base: {KB_NAME} ---")
    kb_data = api("POST", "/api/v1/knowledge/create", json={
        "name": KB_NAME,
        "description": KB_DESC,
    })
    if "id" not in kb_data:
        log(f"ERROR creating knowledge base: {kb_data}")
        sys.exit(1)
    kb_id = kb_data["id"]
    log(f"Created KB: {kb_id}")

    # --- Step 3: Update the model's KB reference in Open WebUI SQLite ---
    old_kb_ids_str = json.dumps(old_kb_ids)
    update_cmd = subprocess.run(
        ["docker", "exec", "open-webui", "python3", "-c", f"""
import sqlite3, json, uuid, time
conn = sqlite3.connect('/app/backend/data/webui.db')
cur = conn.cursor()

cur.execute('SELECT meta FROM model WHERE id=?', ('{MODEL_ID}',))
row = cur.fetchone()
if row:
    meta = json.loads(row[0])
    meta['knowledge'] = [{{'id': '{kb_id}', 'name': '{KB_NAME}', 'type': 'collection'}}]
    cur.execute('UPDATE model SET meta=? WHERE id=?', (json.dumps(meta), '{MODEL_ID}'))
    conn.commit()
    print('Model knowledge reference updated to {kb_id}')
else:
    print('Model not found — update knowledge reference manually in Open WebUI')

old_kb_ids = {old_kb_ids_str}
now = int(time.time())
copied = 0
seen = set()
for old_id in old_kb_ids:
    cur.execute('SELECT principal_type, principal_id, permission FROM access_grant WHERE resource_type="knowledge" AND resource_id=?', (old_id,))
    for principal_type, principal_id, permission in cur.fetchall():
        key = (principal_type, principal_id, permission)
        if key not in seen:
            seen.add(key)
            cur.execute('INSERT INTO access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at) VALUES (?,?,?,?,?,?,?)',
                (str(uuid.uuid4()), 'knowledge', '{kb_id}', principal_type, principal_id, permission, now))
            copied += 1

if ('user', '*', 'read') not in seen:
    cur.execute('INSERT INTO access_grant (id, resource_type, resource_id, principal_type, principal_id, permission, created_at) VALUES (?,?,?,?,?,?,?)',
        (str(uuid.uuid4()), 'knowledge', '{kb_id}', 'user', '*', 'read', now))
    copied += 1

conn.commit()
conn.close()
print(f'Access grants copied/created: {{copied}}')
"""],
        capture_output=True, text=True,
    )
    log(update_cmd.stdout.strip() or update_cmd.stderr.strip())

    # --- Step 4: Upload all MD files and add to KB ---
    log(f"\n--- Uploading {len(md_files)} files to Open WebUI ---")
    success = 0
    failed = []

    for i, md_path in enumerate(md_files, 1):
        rel = md_path.relative_to(DOCLING_OUTPUT) if DOCLING_OUTPUT in md_path.parents else md_path.name
        log(f"[{i:3}/{len(md_files)}] Uploading: {rel}")

        file_id = upload_file(md_path, i)
        if not file_id:
            failed.append(str(rel))
            continue

        ok = add_file_to_kb(kb_id, file_id)
        if ok:
            log(f"         OK → KB")
            success += 1
        else:
            log(f"         WARNING: uploaded but failed to add to KB (file_id={file_id})")
            failed.append(str(rel))

    log(f"\n{'='*60}")
    log(f"Upload complete: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"  Success: {success}")
    log(f"  Failed:  {len(failed)}")
    if failed:
        log(f"\nFailed files:")
        for f in failed:
            log(f"  - {f}")
    log(f"{'='*60}\n")


if __name__ == "__main__":
    main()
