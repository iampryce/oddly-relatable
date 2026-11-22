"""Download the pinned model weights listed in models.lock and check each SHA-256 (standard library only).

models.lock: a JSON list of {"url": "<https URL at a pinned revision>", "path": "<relative path>", "sha256": "<hex>",
"licence": "<name>"}. A file already present with the right checksum is kept. An empty list, a placeholder, a
non-https URL, a path outside the models folder or a checksum mismatch is an error (nothing is guessed).
Usage: python fetch_models.py models.lock /models
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from urllib import request as urlreq


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(entries, root: Path) -> list[tuple[str, Path, str]]:
    if not isinstance(entries, list) or not entries:
        raise SystemExit("models.lock is empty: pin the weights (URL at a fixed revision, SHA-256, licence) first")
    out = []
    for e in entries:
        url, rel, sha = e.get("url", ""), e.get("path", ""), e.get("sha256", "")
        if not url.startswith("https://") or "PIN-ME" in json.dumps(e) or len(sha) != 64 or not e.get("licence"):
            raise SystemExit(f"models.lock entry not pinned: {rel or url}")
        dst = (root / rel).resolve()
        if root.resolve() not in dst.parents:
            raise SystemExit(f"models.lock path outside the models folder: {rel}")
        out.append((url, dst, sha))
    return out


def main(lock: str, root: str) -> None:
    items = check(json.loads(Path(lock).read_text()), Path(root))
    for url, dst, sha in items:
        if dst.is_file() and sha256_file(dst) == sha:
            print(f"ok (cached) {dst.name}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        with urlreq.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 22):
                f.write(chunk)
        got = sha256_file(tmp)
        if got != sha:
            tmp.unlink(missing_ok=True)
            raise SystemExit(f"checksum mismatch for {dst.name}: expected {sha[:12]}…, got {got[:12]}…")
        tmp.rename(dst)
        print(f"ok {dst.name}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
