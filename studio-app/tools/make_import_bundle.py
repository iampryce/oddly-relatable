#!/usr/bin/env python3
"""Build local import bundles for the studio's "Import local generation" panel (asset_import.py), from the local art
stage folders an image route wrote (generated/, prompts/, references/, manifest/manifest.json).

Nothing is uploaded and nothing is generated: each bundle is a byte-identical copy of the chosen image plus a manifest
JSON in the studio's import schema (format oddstudio-import-1: generated / reviewed / approved / rejected kept as
separate fields). The owner uploads a bundle on the Characters page or in Settings > Sets; it enters the studio as a
candidate and the owner decides it there.

Which images to bundle, and the decisions to record (information only), come from a plan JSON:

    {"art_root": "/path/to/art-generation",          # where the stage folders are read from
     "record_root": "/path/as/recorded",             # optional: the path written into manifests (default art_root)
     "items": [{"id": "ralph-seated", "target": "character", "character": "ralph", "stage": "stage-01b",
                "image": "x.png", "kind": "pose", "expression": "neutral", "posture": "seated", "body_turn": "left",
                "prompt_file": "prompts/p.txt", "references": [{"role": "identity", "file": "references/r.png"}],
                "generated_at": "2026-11-24", "approved": {"by": "owner", "at": "2026-11-24", "note": "..."},
                "notes": ["..."]},
               {"id": "room-reverse", "target": "set", "label": "Room (reverse)", "reverse_of_item": "room-wide", ...}],
     "masks": [{"id": "ralph-mask", "parent_item": "ralph-seated", "shape": "ralph"}]}

Masks need --figmasks (a module with figure_mask(name) and SHAPES; it needs Pillow and numpy): each mask is rendered
FULL SIZE (uncropped, the parent's pixel grid) as an alpha PNG, with its own manifest: how it was made, the script and
its sha256, the parent's sha256 and the polygon spec.

    python make_import_bundle.py --plan plan.json --out bundles/ [--figmasks figmasks.py]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "oddstudio-import-1"
DIMENSIONS = ("posture", "body_turn", "view", "framing")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header (no image library needed)."""
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise SystemExit(f"{path}: not a PNG")
    return struct.unpack(">II", head[16:24])


def stage_manifest(art: Path, stage: str) -> dict:
    return json.loads((art / stage / "manifest" / "manifest.json").read_text(encoding="utf-8"))


def entry_for(man: dict, image: str) -> dict:
    for e in man.get("images", []):
        if e.get("name") == image:
            return e
    raise SystemExit(f"{image}: not listed in its stage manifest")


def session_of(original: str) -> str:
    """The image route's session id: the folder the original was saved in (…/generated_images/<session>/exec-….png)."""
    parts = Path(original).parts
    return parts[-2] if len(parts) >= 2 else ""


def recorded(path: Path, art: Path, record_root: str) -> str:
    return str(Path(record_root) / path.relative_to(art))


def build_item(it: dict, art: Path, record_root: str, out: Path, default_how: str = "") -> dict:
    stage = art / it["stage"]
    src = stage / "generated" / it["image"]
    man = stage_manifest(art, it["stage"])
    e = entry_for(man, it["image"])
    digest = sha256_of(src)
    prefix = e.get("sha256_prefix")
    if prefix and not digest.startswith(prefix):
        raise SystemExit(f"{src}: sha256 {digest[:16]} does not match the stage manifest's prefix {prefix}")
    w, h = png_size(src)
    codex = man.get("codex") or {}
    by = ", ".join(x for x in (codex.get("cli"), f"{codex['sign_in']} sign-in" if codex.get("sign_in") else "") if x)
    prompt_file = stage / it["prompt_file"]
    refs = []
    for r in it.get("references", []):
        f = stage / r["file"]
        refs.append({"role": r.get("role", ""), "file": r["file"], "source": recorded(f, art, record_root), "sha256": sha256_of(f)})
    at = e.get("generated_at") or it.get("generated_at") or ""
    if not at:
        raise SystemExit(f"{it['id']}: no generation date (stage manifest or plan generated_at)")
    m = {"format": FORMAT, "kind": it["kind"], "file_name": it["image"], "sha256": digest, "width": w, "height": h,
         "generated": {"at": at, "by": by or it.get("generator", ""),
                       "how": man.get("method") or it.get("how") or default_how,
                       "session_id": session_of(e.get("codex_original", "")),
                       "original_path": e.get("codex_original", ""),
                       "prompt": prompt_file.read_text(encoding="utf-8"),
                       "prompt_file": recorded(prompt_file, art, record_root),
                       "references": refs},
         "source_manifest": recorded(stage / "manifest" / "manifest.json", art, record_root),
         "notes": ([f"generation: {e['generation_status']}"] if e.get("generation_status") else [])
                  + ([f"authorisation: {man['authorisation']}"] if man.get("authorisation") else []) + list(it.get("notes", []))}
    if e.get("defects") or e.get("review_status"):
        m["reviewed"] = {"by": it.get("reviewed_by", "stage manifest review"), "at": it.get("reviewed_at", at[:10]),
                         "notes": ([f"stage manifest status at the time: {e['review_status']}"] if e.get("review_status") else [])
                         + [f"defect: {d}" for d in e.get("defects", [])]}
    for k in ("approved", "rejected"):
        if it.get(k):
            m[k] = it[k]
    for k in ("expression", "expressions", *DIMENSIONS, "label", "description", "plate_view"):
        if it.get(k) not in (None, "", []):
            m[k] = it[k]
    folder = out / it["id"]
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copy2(src, folder / it["image"])
    if sha256_of(folder / it["image"]) != digest:
        raise SystemExit(f"{it['id']}: the copy is not byte-identical")
    return {"manifest": m, "folder": folder}


def render_mask(spec: dict, parent: dict, figmasks: Path, out: Path) -> dict:
    """The figure-only mask of the parent image, full size (uncropped), with its own manifest."""
    mod_spec = importlib.util.spec_from_file_location("figmasks", figmasks)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)
    from PIL import Image
    shape = mod.SHAPES[spec["shape"]]
    pm = parent["manifest"]
    if sha256_of(Path(shape["src"])) != pm["sha256"]:
        raise SystemExit(f"{spec['id']}: the mask's source image is not the parent's file")
    full = {}
    orig = mod.Image.fromarray

    def capture(*a, **k):       # figure_mask crops its result; keep the full-size RGBA it builds first
        img = orig(*a, **k)
        if img.mode == "RGBA":
            full["img"] = img
        return img
    mod.Image.fromarray = capture
    try:
        cropped = mod.figure_mask(spec["shape"])
    finally:
        mod.Image.fromarray = orig
    img = full["img"]
    if img.size != (pm["width"], pm["height"]):
        raise SystemExit(f"{spec['id']}: the mask is {img.size}, the parent is {pm['width']}x{pm['height']}")
    if cropped.size != img.crop(img.getbbox()).size:
        raise SystemExit(f"{spec['id']}: the full-size mask does not match the cropped one")
    folder = out / spec["id"]
    folder.mkdir(parents=True, exist_ok=False)
    name = f"{Path(pm['file_name']).stem}-figure-mask.png"
    img.save(folder / name)
    w, h = img.size
    polygon_spec = {k: v for k, v in shape.items()}
    polygon_spec["src"] = pm["file_name"]
    m = {"format": FORMAT, "kind": "mask", "file_name": name, "sha256": sha256_of(folder / name), "width": w, "height": h,
         "generated": {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "by": f"{figmasks.name} figure_mask (Pillow {Image.__version__})",
                       "how": "rendered locally from hand-drawn polygons (no image model): full size, uncropped, RGBA "
                              "with the original pixels and the figure-only alpha"},
         "parent_sha256": pm["sha256"],
         "mask": {"method": "hand-drawn polygons and ellipses over the source image (a 20 px grid); inside them only the "
                            "plain grey background and the chair's wood colour are left out; shins and thighs cleaned "
                            "of the chair's rails",
                  "script": f"{figmasks.name} figure_mask", "script_sha256": sha256_of(figmasks),
                  "source_sha256": pm["sha256"], "spec": polygon_spec},
         "notes": [f"figure-only mask of {pm['file_name']}"] + list(spec.get("notes", []))}
    for k in ("expression", *DIMENSIONS):
        if pm.get(k):
            m[k] = pm[k]
    return {"manifest": m, "folder": folder}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--figmasks", type=Path)
    a = ap.parse_args(argv)
    plan = json.loads(a.plan.read_text(encoding="utf-8"))
    art = Path(plan["art_root"])
    record_root = plan.get("record_root") or str(art)
    a.out.mkdir(parents=True, exist_ok=True)
    built, index = {}, []
    for it in plan["items"]:
        built[it["id"]] = b = build_item(it, art, record_root, a.out, plan.get("default_how", ""))
        index.append({"id": it["id"], "target": it["target"], "character": it.get("character"), "kind": it["kind"]})
    for it in plan["items"]:      # a reverse plate names its wide plate by that file's sha256 (the studio links it)
        if it.get("reverse_of_item"):
            built[it["id"]]["manifest"]["reverse_of"] = built[it["reverse_of_item"]]["manifest"]["sha256"]
    for spec in plan.get("masks", []):
        if a.figmasks is None:
            raise SystemExit("masks in the plan: pass --figmasks")
        parent = built[spec["parent_item"]]
        built[spec["id"]] = render_mask(spec, parent, a.figmasks, a.out)
        index.append({"id": spec["id"], "target": "character", "character": spec.get("character"), "kind": "mask",
                      "parent": spec["parent_item"], "upload_after": spec["parent_item"]})
    for bid, b in built.items():
        (b["folder"] / "manifest.json").write_text(json.dumps(b["manifest"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        entry = next(x for x in index if x["id"] == bid)
        entry.update({"image": f"{bid}/{b['manifest']['file_name']}", "manifest": f"{bid}/manifest.json",
                      "sha256": b["manifest"]["sha256"]})
    (a.out / "index.json").write_text(json.dumps({"format": FORMAT, "bundles": index}, indent=1) + "\n", encoding="utf-8")
    for x in index:
        print(f"{x['id']}: {x['target']} {x.get('character') or ''} {x['kind']} -> {x['image']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
