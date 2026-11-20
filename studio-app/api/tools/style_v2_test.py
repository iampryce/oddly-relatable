"""House style v2: the owner-approved one-character test (2026-11-20). Run inside the API image with this branch's code.

Draws ONE test character (Leo's v2 description, never an existing character) in house style v2: a neutral pose and five
expressions, plus one v2 set as a wide and a close plate. Then it builds the acting rig from the new art, voices two
lines with Piper (free), runs Rhubarb lip sync and renders a short clip with the existing acting renderer.

Nothing is written to the database and nothing in the running studio changes: the OpenAI key is only READ through the
studio's own secret() (Settings > Credentials), and all output goes to --out.

Spend control: every image call is counted and estimated from the response's usage (gpt-image-2, 1024x1536: $0.165 per
high-quality image plus input image/text tokens). A call is refused when spent + a worst case of $0.25 would exceed
--budget, and never more than --max-images calls are made.

    python tools/style_v2_test.py --out /out [--budget 4.0] [--max-images 16]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORST_CALL = 0.25
EXPRESSIONS = ["deadpan", "annoyed", "shocked", "laughing", "worried"]
CHARACTER = SimpleNamespace(key="v2-test", name="V2 Test",
                            visual_description="a flat dark-brown short side-parted hair cap shape; plain white torso; no garment.",
                            skin_tone="")
SET_DESCRIPTION = ("a quiet modern apartment living room at night: a plain sofa against the back wall, one floor lamp lit "
                   "warm beside it, a large window on the left with cool blue city night outside; wide clear wooden floor "
                   "in the foreground")
CLOSE_NOTE = ("THE SAME ROOM as the attached image, same lighting, palette and style, but a TIGHTER view: the camera is closer "
              "to the open floor area, framing roughly the middle third of the room at a standing adult's chest height, so "
              "a character standing there would fill most of the frame. Keep the lower third open floor.")
LINES = [("I left one coffee in the fridge. One.", "deadpan", "medium"),
         ("So. Who drank it?", "annoyed", "close")]


class BudgetStop(RuntimeError):
    pass


class Spend:
    def __init__(self, budget: float, max_calls: int):
        self.budget, self.max_calls, self.calls, self.spent, self.log = budget, max_calls, 0, 0.0, []

    def guard(self, what: str):
        if self.calls >= self.max_calls:
            raise BudgetStop(f"image limit reached ({self.max_calls}) before {what}")
        if self.spent + WORST_CALL > self.budget:
            raise BudgetStop(f"budget ${self.budget:.2f} would be exceeded before {what} (spent about ${self.spent:.2f})")

    def record(self, what: str, usage: dict | None, seconds: float):
        u = usage or {}
        d = u.get("input_tokens_details") or {}
        cost = 0.165 + d.get("image_tokens", 0) * 10e-6 + d.get("text_tokens", 0) * 5e-6 if u else WORST_CALL
        self.calls += 1
        self.spent += cost
        self.log.append({"image": what, "estimated_usd": round(cost, 4), "usage": u, "seconds": round(seconds, 1)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=4.0)
    ap.add_argument("--max-images", type=int, default=16)
    a = ap.parse_args()
    out = Path(a.out)
    for d in ("raw", "poses", "sets", "rig", "clip"):
        (out / d).mkdir(parents=True, exist_ok=True)

    import httpx
    from oddstudio import engine, house_style, providers, sets
    from oddstudio.analysis import lipsync
    from oddstudio.config import REPO_ROOT, get_settings
    from oddstudio.db import new_session
    from oddstudio.settings_store import get_section
    from oddstudio.tasks import pose_prompt_v2

    with new_session() as db:                     # read only
        image_cfg = get_section(db, "image")
    cfg = {"provider": "openai", "model": image_cfg.get("model", ""), "size": "1024x1536", "fallback": "none"}
    spend = Spend(a.budget, a.max_images)
    report = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": cfg["model"] or "gpt-image-2 (default)",
              "size": cfg["size"], "character": vars(CHARACTER), "images": [], "checks": {}, "errors": []}

    real_post = providers.httpx.post
    current = {"what": ""}

    def counted_post(url, *args, **kw):
        if "/v1/images/" not in str(url):
            return real_post(url, *args, **kw)
        spend.guard(current["what"])
        t0 = time.time()
        r = real_post(url, *args, **kw)
        usage = None
        try:
            usage = r.json().get("usage")
        except Exception:
            pass
        spend.record(current["what"], usage, time.time() - t0)
        return r
    providers.httpx.post = counted_post

    def generate(what: str, prompt: str, dest: Path, reference=None, use_reference=False, background="mid-grey (#808080)") -> Path:
        current["what"] = what
        c = {**cfg, "use_reference": use_reference, "background": background}
        providers.image_generate(c, prompt, dest, reference)
        return dest

    def pose(expression: str, ref: Path | None) -> dict:
        raw = out / "raw" / f"{expression}.png"
        prompt = pose_prompt_v2(CHARACTER, expression, ref is not None, False)
        generate(f"pose:{expression}", prompt, raw, ref, use_reference=ref is not None)
        cut = out / "poses" / f"{expression}.png"
        shutil.copyfile(raw, cut)
        cleaned = engine.make_cutout(cut)
        info = engine.analyse_pose(cut)
        return {"expression": expression, "file": str(cut), "cutout_changed": cleaned, **info,
                "checks": {"figure_height_ok(>=1300)": info["figure_height"] >= 1300}}

    try:
        # 1. neutral (text only: no style image exists for v2 yet), one retry if it fails the size check
        neutral = None
        for attempt in (1, 2):
            p = pose("neutral", None)
            report["images"].append(p)
            if p["checks"]["figure_height_ok(>=1300)"]:
                neutral = p
                break
        if neutral is None:
            raise RuntimeError("the neutral pose failed the size check twice")

        # 2. rig from the neutral: proportions and line weight measured by the same extractor production uses
        anim = REPO_ROOT / "production" / "animation"
        rig_dir = out / "rig"
        r = subprocess.run([sys.executable, str(anim / "rig_extract.py"), neutral["file"], str(rig_dir)], capture_output=True, text=True, timeout=600)
        report["checks"]["rig_extract_neutral"] = {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-600:]}
        if r.returncode == 0:
            body = json.loads((rig_dir / "rig.json").read_text())["body"]
            ratio = (body["neck"][1] - body["top"]) / body["height"]
            report["checks"]["head_ratio"] = {"value": round(ratio, 3), "target": "0.26-0.32", "ok": 0.26 <= ratio <= 0.32}
            report["checks"]["line_width_px"] = {"value": body["line_width"], "per_figure_height": round(body["line_width"] / body["height"], 4)}

        # 3. expressions anchored on the new neutral
        for exp in EXPRESSIONS:
            try:
                p = pose(exp, Path(neutral["file"]))
            except BudgetStop:
                raise
            except Exception as e:
                report["errors"].append(f"{exp}: {type(e).__name__}: {str(e)[:300]}")
                continue
            report["images"].append(p)
            if r.returncode == 0:
                rr = subprocess.run([sys.executable, str(anim / "rig_extract.py"), p["file"], str(rig_dir), "--head-only", exp],
                                    capture_output=True, text=True, timeout=600)
                p["checks"]["rig_head_ok"] = rr.returncode == 0
                if rr.returncode:
                    p["rig_error"] = (rr.stdout + rr.stderr)[-300:]
        hs = [p for p in report["images"] if p.get("figure_height")]
        heights = [p["figure_height"] for p in hs]
        report["checks"]["figure_height_spread"] = {"min": min(heights), "max": max(heights)}
        engine.compose_sheet([(p["expression"], Path(p["file"])) for p in hs if p["checks"]["figure_height_ok(>=1300)"]],
                             out / "sheet.png", "House style v2 test: expression sheet")

        # 4. the v2 set: a wide plate (text only) and a close plate drawn from it
        wide = generate("set:wide", f"{house_style.SET_STYLE_V2}\nSetting: {SET_DESCRIPTION}", out / "sets" / "wide.png", background=None)
        close = generate("set:close", f"{house_style.SET_STYLE_V2}\nSetting: {SET_DESCRIPTION}\n{CLOSE_NOTE}", out / "sets" / "close.png",
                         reference=wide, use_reference=True, background=None)
        from PIL import Image
        for name, f in (("wide", wide), ("close", close)):
            with Image.open(f) as im:
                report["checks"][f"set_{name}_size"] = list(im.size)

        # 5. a short acted clip: Piper voice (free), Rhubarb lip sync, the existing acting renderer, in the v2 set
        if r.returncode == 0:
            s = get_settings()
            vs = providers.piper_voices()
            with Image.open(wide) as im:
                w, h = im.size
            blk = sets.proposed_blocking(w, h)
            faces = set(json.loads((rig_dir / "rig.json").read_text())["faces"])
            lines, clips, t = [], [], 0.5
            for i, (text, exp, shot) in enumerate(LINES):
                wav = providers.speak({"provider": "piper"}, text, str(vs[0]) if vs else "", out / "clip" / f"line{i + 1}")
                secs = providers.audio_seconds(wav)
                cues = lipsync(wav, text)["cues"]
                lines.append({"speaker": "tester", "text": text, "start": round(t, 2), "end": round(t + secs + 0.35, 2), "shot": shot,
                              "expression": exp if exp in faces else "neutral", "cues": cues})
                clips.append((wav, t))
                t = lines[-1]["end"] + 0.12
            spec = {"width": 1080, "height": 1920, "fps": 30, "duration": round(t + 0.6, 2), "captions": False, "bubbles": True,
                    "hook": "POV: someone drank your coffee",
                    "font": str(REPO_ROOT / "skills/directing-stickman-videos/assets/fonts/NotoSans.ttf"),
                    "set": {"plate": str(wide), "width": w, "height": h, **blk},
                    "cast": {"tester": {"rig": str(rig_dir), "height": 530, "lips": False, "start": "on"}},
                    "lines": lines, "end_card": None}
            (out / "clip" / "acting.json").write_text(json.dumps(spec, indent=1))
            silent = out / "clip" / "silent.mp4"
            t0 = time.time()
            rr = subprocess.run([s.node_bin, str(anim / "render-acting.mjs"), str(out / "clip" / "acting.json"), str(silent)],
                                capture_output=True, text=True, cwd=str(REPO_ROOT), env=engine.env_for_node(), timeout=900)
            report["checks"]["render"] = {"ok": rr.returncode == 0 and silent.exists(), "seconds": round(time.time() - t0, 1),
                                          "output": (rr.stdout + rr.stderr)[-400:]}
            if silent.exists():
                ff = s.ffmpeg or "ffmpeg"
                cmd = [ff, "-v", "error", "-y", "-i", str(silent)]
                for wav, _ in clips:
                    cmd += ["-i", str(wav)]
                delays = ";".join(f"[{k + 1}]adelay={int(st * 1000)}|{int(st * 1000)}[a{k}]" for k, (_, st) in enumerate(clips))
                mix = "".join(f"[a{k}]" for k in range(len(clips)))
                cmd += ["-filter_complex", f"{delays};{mix}amix=inputs={len(clips)}:normalize=0[m]", "-map", "0:v", "-map", "[m]",
                        "-c:v", "copy", "-c:a", "aac", str(out / "clip" / "clip.mp4")]
                subprocess.run(cmd, check=True, timeout=300)
                for k, ln in enumerate(lines):
                    mid = (ln["start"] + ln["end"]) / 2
                    subprocess.run([ff, "-v", "error", "-y", "-ss", f"{mid:.2f}", "-i", str(silent), "-frames:v", "1",
                                    str(out / "clip" / f"frame-{k + 1}-{ln['shot']}.png")], check=True, timeout=120)
    except BudgetStop as e:
        report["errors"].append(f"stopped: {e}")
    except httpx.HTTPError as e:
        report["errors"].append(f"network: {type(e).__name__}")
    except Exception as e:
        report["errors"].append(f"{type(e).__name__}: {str(e)[:500]}")
    finally:
        providers.httpx.post = real_post
        report["spend"] = {"image_calls": spend.calls, "estimated_usd": round(spend.spent, 3), "budget_usd": a.budget,
                           "calls": spend.log}
        report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (out / "report.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({"image_calls": spend.calls, "estimated_usd": round(spend.spent, 3), "errors": report["errors"]}))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
