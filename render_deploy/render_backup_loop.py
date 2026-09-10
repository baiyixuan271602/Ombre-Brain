#!/usr/bin/env python3
"""Periodic snapshot of the buckets directory to GitHub.
Guards (learned from production incidents):
  - skip while /app/.restore_failed exists (never overwrite a good remote)
  - never push when there are zero md files locally (avoid nuking remote with an
    uninitialized state)
"""
import base64
import io
import json
import os
import tarfile
import time
import urllib.request
import urllib.error
from pathlib import Path

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_REPO = os.environ.get("GH_BACKUP_REPO", "")
GH_PATH = os.environ.get("GH_BACKUP_PATH", "ombre_backup.json")
INTERVAL = int(os.environ.get("GH_BACKUP_INTERVAL", "180"))
BUCKETS = Path(os.environ.get("OMBRE_BUCKETS_DIR", "/app/buckets"))
FLAG = Path("/app/.restore_failed")
API = "https://api.github.com"
EXCLUDE_DIRS = {"_app", "_prev", "__pycache__"}


def log(m):
    print("[backup]", m, flush=True)


def md_count():
    if not BUCKETS.exists():
        return 0
    try:
        return sum(1 for p in BUCKETS.rglob("*.md"))
    except Exception:
        return 0


def should_exclude(rel: Path) -> bool:
    parts = rel.parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if any(p.startswith(".seed") for p in parts):
        return True
    name = rel.name
    if name.endswith(".pyc"):
        return True
    return False


def make_tar():
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(BUCKETS.rglob("*")):
            rel = p.relative_to(BUCKETS)
            if should_exclude(rel):
                continue
            if p.is_file():
                try:
                    tf.add(str(p), arcname=str(rel))
                    count += 1
                except Exception:
                    pass
    return buf.getvalue(), count


def remote_meta():
    try:
        req = urllib.request.Request(
            f"{API}/repos/{GH_REPO}/contents/{GH_PATH}",
            headers={"Authorization": f"Bearer {GH_TOKEN}", "User-Agent": "ombre-backup"})
        j = json.load(urllib.request.urlopen(req, timeout=60))
        payload = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
        return {"sha": j.get("sha"), "exists": True, "files": payload.get("files_count", 0)}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"exists": False}
        log(f"remote HTTP {e.code}")
        return None
    except Exception as e:
        log(f"remote error: {e}")
        return None


def push(sha, data_b64, files_count, md_total):
    payload = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files_count": files_count,
        "md_count": md_total,
        "tar_b64": data_b64,
    }
    body = {
        "message": f"auto backup ({md_total} md, {files_count} files)",
        "content": base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode(),
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        f"{API}/repos/{GH_REPO}/contents/{GH_PATH}",
        data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "User-Agent": "ombre-backup", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=120)


def tick():
    if FLAG.exists():
        return
    if not BUCKETS.exists():
        return
    local_md = md_count()
    if local_md == 0:
        return
    r = remote_meta()
    if r is None:
        return
    data, count = make_tar()
    push(r.get("sha"), base64.b64encode(data).decode(), count, local_md)
    log(f"pushed ({local_md} md, {count} files, {len(data)} bytes)")


def main():
    if not GH_TOKEN or not GH_REPO:
        log("no GH config; backup loop disabled")
        return
    log(f"backup loop started: {GH_REPO}/{GH_PATH} every {INTERVAL}s")
    while True:
        try:
            tick()
        except Exception as e:
            log(f"tick error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
