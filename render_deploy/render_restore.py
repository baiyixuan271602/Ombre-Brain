#!/usr/bin/env python3
"""Boot-time restore: pull the buckets snapshot from GitHub into OMBRE_BUCKETS_DIR.
Retries 3 times; on total failure sets a flag so the backup loop will not
overwrite the remote copy during this container lifetime."""
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
BUCKETS = Path(os.environ.get("OMBRE_BUCKETS_DIR", "/app/buckets"))
FLAG = Path("/app/.restore_failed")


def log(m):
    print("[restore]", m, flush=True)


def md_count(root: Path) -> int:
    if not root.exists():
        return 0
    try:
        return sum(1 for p in root.rglob("*.md"))
    except Exception:
        return 0


def gh_get():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}",
        headers={"Authorization": f"Bearer {GH_TOKEN}", "User-Agent": "ombre-restore"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    if not GH_TOKEN or not GH_REPO:
        log("no GH_TOKEN/GH_BACKUP_REPO configured, skip")
        return
    have = md_count(BUCKETS)
    if have > 0:
        log(f"local buckets already have {have} md files, skip")
        return
    for attempt in range(1, 4):
        try:
            j = gh_get()
            payload = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
            tar_b64 = payload.get("tar_b64", "")
            if not tar_b64:
                log("backup has no tar content")
                return
            BUCKETS.mkdir(parents=True, exist_ok=True)
            data = base64.b64decode(tar_b64)
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                members = []
                for m in tf.getmembers():
                    name = m.name
                    if name.startswith("/") or ".." in name.split("/"):
                        continue
                    members.append(m)
                try:
                    tf.extractall(path=str(BUCKETS), members=members, filter="fully_trusted")
                except TypeError:
                    tf.extractall(path=str(BUCKETS), members=members)
            log(f"restored OK (files={payload.get('files_count','?')}, saved_at={payload.get('saved_at','?')})")
            if FLAG.exists():
                FLAG.unlink()
            return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log("no backup yet (404) - fresh start")
                return
            log(f"attempt {attempt}: HTTP {e.code}")
        except Exception as e:
            log(f"attempt {attempt}: {e}")
        if attempt < 3:
            time.sleep(5)
    FLAG.write_text("restore failed" + chr(10), encoding="utf-8")
    log("RESTORE FAILED after 3 attempts - flag set (backup loop will not overwrite remote)")


if __name__ == "__main__":
    main()
