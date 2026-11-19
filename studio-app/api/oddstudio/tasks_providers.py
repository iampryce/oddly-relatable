"""Provider test jobs: the Settings page's "Test" button queues `provider_test`, and the WORKER runs it with exactly the
provider and settings production would use. A passing test therefore proves the worker can really use that provider
(credentials, installed binaries, network), not just that a field is filled in.

payload: {"target": "<stage>:<provider>"} where stage is text | image | voice | storage | youtube | comfyui.
Image and voice tests store their output as a "provider-test" asset so the owner can look at or listen to it.
Costs: text a few tokens; image one small generation (about $0.01-0.04 on OpenAI); voice one short sentence.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from . import providers
from .config import get_settings
from .secrets_store import secret
from .settings_store import get_section
from .tasks import Ctx, store_asset, task

TARGETS = {
    "text": ("codex-cli", "openai", "anthropic"),
    "image": ("codex-cli", "openai"),
    "voice": ("piper", "openai", "elevenlabs", "kokoro"),
    "storage": ("s3", "local"),
    "youtube": ("youtube",),
    "comfyui": ("comfyui",),
    "transcription": ("openai", "local-whisper"),
    "vision": ("openai", "anthropic"),
    "lipsync": ("rhubarb",),
    "sound": ("elevenlabs",),
    "motion": ("procedural-rig",),
}


def _speech_sample(ctx, job) -> Path:
    """A real spoken sample of TEST_LINE (Piper on the worker) for transcription and lip-sync tests."""
    vs = providers.piper_voices()
    voice = str(vs[0]) if vs else providers.resolve_piper_voice(get_section(ctx.db, "voice").get("default_voice") or "")
    return providers.speak({"provider": "piper"}, TEST_LINE, voice, ctx.folder("provider-tests") / f"sample-{job.id}")


def _test_figures(path: Path) -> Path:
    """Two simple stick figures, the right one raising an arm (a known answer for the vision test)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (768, 512), (250, 246, 238))
    d = ImageDraw.Draw(im)
    for cx, wave in ((250, False), (520, True)):
        d.ellipse((cx - 55, 70, cx + 55, 180), outline=(0, 0, 0), width=8, fill=(255, 220, 190))
        d.line((cx, 180, cx, 330), fill=(0, 0, 0), width=8)
        d.line((cx, 330, cx - 55, 450), fill=(0, 0, 0), width=8); d.line((cx, 330, cx + 55, 450), fill=(0, 0, 0), width=8)
        d.line((cx, 220, cx - 75, 300), fill=(0, 0, 0), width=8)
        d.line((cx, 220, cx + 80, 120) if wave else (cx, 220, cx + 75, 300), fill=(0, 0, 0), width=8)
    im.save(path)
    return path
TEST_LINE = "Okay. The party is in the other room, and nobody is allowed to know."


@task
def provider_test(ctx: Ctx) -> dict:
    db, job = ctx.db, ctx.job
    target = (job.payload or {}).get("target", "")
    stage, _, name = target.partition(":")
    if name not in TARGETS.get(stage, ()):
        raise ValueError(f"unknown provider test {target!r}")
    t0 = time.time()
    out = {"target": target}
    if stage == "text":
        cfg = {**get_section(db, "text"), "provider": name, "fallback": "none"}
        if cfg.get("provider") != get_section(db, "text").get("provider"):
            cfg["model"] = ""   # the saved model belongs to the selected provider, not this one
        ans = providers.text_provider(cfg).complete_json(
            "You answer with one JSON object only.",
            'Reply with {"ok": true, "joke": "<one short family-friendly joke about group chats>"}')
        out["answer"] = ans
        ctx.log(f"{name} answered: {str(ans)[:200]}")
    elif stage == "image":
        cfg = {**get_section(db, "image"), "provider": name, "fallback": "none", "size": "1024x1024"}
        if name != get_section(db, "image").get("provider"):
            cfg["model"] = ""
        f = providers.image_generate(cfg, "A simple flat cartoon stickman waving, round head, thin black limbs, plain "
                                          "transparent background.", ctx.folder("provider-tests") / f"image-{job.id}.png")
        a = store_asset(db, ep_id=None, src=f, key=f"provider-tests/image-{name}-job{job.id}.png", kind="provider-test",
                        label=f"Image test ({name})", content_type="image/png", job_id=job.id)
        out.update(asset_id=a.id, bytes=f.stat().st_size)
    elif stage == "voice":
        cfg = {**get_section(db, "voice"), "provider": name, "fallback": "none"}
        voice = ""
        if name == "piper":
            vs = providers.piper_voices()
            voice = providers.resolve_piper_voice(cfg.get("default_voice") or (str(vs[0]) if vs else ""))
        elif name == "openai":
            voice = "alloy"
        elif name == "kokoro":
            voice = "am_michael"
        elif name == "elevenlabs":
            voice = cfg.get("default_voice") if cfg.get("provider") == "elevenlabs" else ""
            if not voice:
                # any voice of the account proves the key works end to end
                r = httpx.get("https://api.elevenlabs.io/v1/voices", timeout=30, headers={"xi-api-key": secret("elevenlabs_api_key")})
                if r.status_code >= 400:
                    raise providers.http_error("elevenlabs", r)
                vs = r.json().get("voices", [])
                if not vs:
                    raise RuntimeError("elevenlabs: the account has no voices")
                voice = vs[0]["voice_id"]
        f = providers.speak(cfg, TEST_LINE, voice, ctx.folder("provider-tests") / f"voice-{job.id}")
        ct = "audio/mpeg" if f.suffix == ".mp3" else "audio/wav"
        a = store_asset(db, ep_id=None, src=f, key=f"provider-tests/voice-{name}-job{job.id}{f.suffix}", kind="provider-test",
                        label=f"Voice test ({name})", content_type=ct, job_id=job.id)
        out.update(asset_id=a.id, seconds=round(providers.audio_seconds(f), 2), voice=voice.split("/")[-1])
    elif stage == "storage":
        from .storage import S3Storage, storage_config
        cfg = storage_config()
        if name == "s3":
            if not cfg["bucket"]:
                raise providers.ProviderNotConfigured("S3: set the bucket (and region) under Settings > Media storage")
            out.update(S3Storage({**cfg, "backend": "s3"}).check())
        else:
            from .storage import LocalStorage
            st, k = LocalStorage(), "_connection-test/local.txt"
            p = ctx.folder("provider-tests") / "local.txt"
            p.write_text("ok")
            st.put_file(k, p)
            out.update(ok=st.local_path(k).read_text() == "ok")
    elif stage == "youtube":
        from .youtube import access_token
        r = httpx.get("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", timeout=30,
                      headers={"Authorization": f"Bearer {access_token()}"})
        if r.status_code >= 400:
            raise providers.http_error("youtube", r)
        items = r.json().get("items", [])
        if not items:
            raise RuntimeError("youtube: signed in, but this Google account has no YouTube channel")
        out.update(channel=items[0]["snippet"]["title"], channel_id=items[0]["id"])
    elif stage == "comfyui":
        url = get_section(db, "comfyui").get("url", "").rstrip("/")
        if not url:
            raise providers.ProviderNotConfigured("ComfyUI: set the server URL under Settings > AI video")
        tok = secret("comfyui_token")
        r = httpx.get(url + "/system_stats", timeout=30, headers={"Authorization": f"Bearer {tok}"} if tok else {})
        if r.status_code >= 400:
            raise providers.http_error("comfyui", r)
        dev = r.json().get("devices", [])
        out.update(devices=[d.get("name") for d in dev], vram_gb=[round(d.get("vram_total", 0) / 2**30, 1) for d in dev])
    elif stage == "transcription":
        from .analysis import transcribe
        sample = _speech_sample(ctx, job)
        cfg = {**get_section(db, "transcription"), "provider": name, "fallback": "none"}
        if name != get_section(db, "transcription").get("provider"):
            cfg["model"] = ""
        tr = transcribe(cfg, sample)
        said = {w.strip(".,!?").lower() for w in TEST_LINE.split()}
        heard = {w.strip(" .,!?").lower() for w in tr["text"].split()}
        match = len(said & heard) / len(said)
        if match < 0.6:
            raise RuntimeError(f"{name}: transcript did not match the spoken test line ({match:.0%} of words): {tr['text'][:200]!r}")
        out.update(transcript=tr["text"][:300], words_matched=f"{match:.0%}", word_timestamps=len(tr["words"]),
                   segments=len(tr["segments"]), model=tr["model"])
    elif stage == "vision":
        from .analysis import analyse_images
        img = _test_figures(ctx.folder("provider-tests") / f"figures-{job.id}.png")
        cfg = {**get_section(db, "vision"), "provider": name, "fallback": "none"}
        if name != get_section(db, "vision").get("provider"):
            cfg["model"] = ""
        ans = analyse_images(cfg, [img], 'How many stick figures are in this image, and which one (left or right) is '
                                         'raising an arm? Reply {"figures": <number>, "raising": "left"|"right"|"none"}')
        if int(ans.get("figures", 0)) != 2:
            raise RuntimeError(f"{name}: expected 2 figures, the model said {ans}")
        out.update(answer=ans)
    elif stage == "lipsync":
        from .analysis import lipsync
        sample = _speech_sample(ctx, job)
        cues = lipsync(sample, TEST_LINE)["cues"]
        shapes = sorted({c["value"] for c in cues} - {"X"})
        if len(shapes) < 3:
            raise RuntimeError(f"rhubarb produced too few mouth shapes: {shapes}")
        out.update(cues=len(cues), mouth_shapes="".join(shapes), sample_seconds=round(providers.audio_seconds(sample), 2))
    elif stage == "sound":
        from .analysis import sound_effect
        f = sound_effect({**get_section(db, "sound"), "provider": name}, "a cartoon slide whistle going up", 2.0,
                         ctx.folder("provider-tests") / f"sfx-{job.id}")
        a = store_asset(db, ep_id=None, src=f, key=f"provider-tests/sfx-{name}-job{job.id}{f.suffix}", kind="provider-test",
                        label=f"Sound effect test ({name})", content_type="audio/mpeg", job_id=job.id)
        out.update(asset_id=a.id, seconds=round(providers.audio_seconds(f), 2))
    elif stage == "motion":
        # the studio rig animator: rig Character 01 from his approved art, perform one spoken line with a gesture
        import json as _json
        import subprocess as _sp
        from . import acting, engine
        from .config import REPO_ROOT, get_settings
        from .tasks import prepare_characters
        chars = prepare_characters(ctx)
        c = chars["character-01"]
        rig = acting.rig_for(ctx, c)
        sample = _speech_sample(ctx, job)
        secs = providers.audio_seconds(sample)
        cues = acting.cues_for(sample, TEST_LINE)
        st = _json.loads((acting.ANIM / "sets" / "living-room-empty-03.json").read_text())
        st["plate"] = str(REPO_ROOT / st["plate"])
        folder = ctx.folder("provider-tests", f"motion-{job.id}")
        spec = {"width": 540, "height": 960, "fps": 24, "duration": round(secs + 1.4, 2), "captions": False, "set": st,
                "cast": {"character-01": {"rig": str(rig), "height": 560, "lips": False, "start": "on"}},
                "lines": [{"speaker": "character-01", "text": TEST_LINE, "start": 0.5, "end": round(0.5 + secs + 0.3, 2),
                           "expression": "neutral", "gesture": "open_palms", "cues": cues}]}
        (folder / "acting.json").write_text(_json.dumps(spec))
        silent = folder / "clip.mp4"
        s = get_settings()
        env = engine.env_for_node()
        if s.ffmpeg:
            env["FFMPEG"] = s.ffmpeg
        r = _sp.run([s.node_bin, str(acting.ANIM / "render-acting.mjs"), str(folder / "acting.json"), str(silent)], capture_output=True,
                    text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env, timeout=900, stdin=_sp.DEVNULL)
        if r.returncode != 0 or not silent.exists():
            raise RuntimeError("acting renderer failed: " + (r.stderr or r.stdout)[-500:])
        clip = folder / "clip-audio.mp4"
        _sp.run([s.ffmpeg or "ffmpeg", "-v", "error", "-y", "-i", str(silent), "-itsoffset", "0.5", "-i", str(sample), "-map", "0:v",
                 "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-t", str(spec["duration"]), str(clip)], check=True, timeout=300, stdin=_sp.DEVNULL)
        a = store_asset(db, ep_id=None, src=clip, key=f"provider-tests/motion-rig-job{job.id}.mp4", kind="provider-test",
                        label="Motion test (studio rig animator)", content_type="video/mp4", job_id=job.id)
        rep = _json.loads(r.stdout.strip().splitlines()[-1])
        out.update(asset_id=a.id, seconds=spec["duration"], render_seconds=rep.get("render_seconds"), cues=len(cues))
    out["seconds_taken"] = round(time.time() - t0, 2)
    ctx.log(f"test passed in {out['seconds_taken']} s")
    db.commit()
    return out
