"""Cinematic episodes: the ComfyUI graphs, prompt templates and GPU estimates (pure functions, no database, no network).

Stills on the rented GPU (free beyond GPU time):
  * Qwen-Image-Edit-2511 (Apache-2.0) with REFERENCES: up to three pictures (TextEncodeQwenImageEditPlus image1-3):
    the approved character masters of the shot first (identity is what must not drift), then the approved location
    picture when a slot is left. Same template wiring as reactions.edit_graph (AuraFlow shift 3.1, CFGNorm, 40 steps,
    CFG 4, euler/simple), but on an EMPTY 1280x720 latent: a new picture composed from the references.
  * Qwen-Image-2512 (Apache-2.0) text-to-image only for a shot with no reference at all (an empty landscape before any
    location picture exists). Never Qwen-Image 2.1 (qwen-research licence: non-commercial).
Motion: Wan 2.2 i2v 14B, high-noise fp8 for steps 0-2 and low-noise fp8 for steps 2-4, each with its lightx2v 4-step
LoRA (the reactions' proven settings: CFG 1, shift 5, euler/simple), 1280x720, 81 frames at 16 fps per piece (5.06 s).
A longer shot is a chain of pieces, each starting from the previous piece's last frame. With an approved END still the
first piece is WanFirstLastFrameToVideo (start + end); otherwise WanImageToVideo (start only).
Dialogue: talking_s2v.build_graph (Speech-to-Video settings "B") with a realistic prompt and negative.

First real GPU run still to tune: the Qwen-Image-2512 file name (Comfy-Org repackage), the minutes per piece on the
L40S (estimated from 3 min per piece on an A100), and whether 81-frame pieces hold faces as well as the 33-frame
reaction clips did.
"""
from __future__ import annotations

import math

from .cast_styles import INVENTED_PEOPLE_RULE

HF = "https://huggingface.co/Comfy-Org"
W, H = 1280, 720
FPS, PIECE = 16, 81                    # Wan 2.2 i2v: 81 frames at 16 fps per piece
I2V_STEPS, I2V_SPLIT, I2V_CFG, I2V_SHIFT = 4, 2, 1.0, 5.0
QWEN_STEPS, QWEN_CFG, QWEN_SHIFT = 40, 4.0, 3.1
MAX_REFS_QWEN = 3
# minutes on an L40S / RTX 6000 Ada (first-run estimates, to tune): Qwen still 1.5 (at most 2), i2v piece 4,
# start-up + model downloads 10 per session (the Qwen + Wan + S2V files together are about 60 GB)
STILL_MIN, STILL_MIN_MAX, PIECE_MIN, SETUP_MIN, MAX_MARGIN = 1.5, 2.0, 4.0, 12.0, 1.25

QWEN_IMAGE_2512 = {"folder": "diffusion_models", "filename": "qwen_image_2512_fp8_e4m3fn.safetensors", "type": "diffusion_model",
                   "base": "Qwen-Image",
                   "url": f"{HF}/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors"}

SIZES = ("extreme wide", "wide", "medium", "medium close", "close", "extreme close", "over the shoulder", "insert")
SIZE_ALIASES = {"ews": "extreme wide", "els": "extreme wide", "ws": "wide", "ls": "wide", "long": "wide",
                "establishing": "extreme wide", "ms": "medium", "mid": "medium", "mcu": "medium close", "cu": "close",
                "close up": "close", "close-up": "close", "closeup": "close", "ecu": "extreme close",
                "extreme close up": "extreme close", "extreme close-up": "extreme close", "ots": "over the shoulder",
                "over-the-shoulder": "over the shoulder", "two shot": "medium", "two-shot": "medium", "full": "wide"}
CAMERAS = {"static": "a locked-off static camera",
           "push in": "the camera slowly pushes in",
           "pull out": "the camera slowly pulls back",
           "pan left": "the camera pans slowly to the left",
           "pan right": "the camera pans slowly to the right",
           "tilt up": "the camera tilts slowly up",
           "tilt down": "the camera tilts slowly down",
           "tracking": "the camera tracks alongside the movement",
           "orbit": "the camera orbits slowly around the subject",
           "crane up": "the camera cranes up and away",
           "crane down": "the camera cranes down toward the subject",
           "handheld": "a subtle handheld camera"}
CAMERA_ALIASES = {"dolly in": "push in", "zoom in": "push in", "push": "push in", "dolly out": "pull out",
                  "zoom out": "pull out", "pull back": "pull out", "pan": "pan right", "tilt": "tilt up",
                  "track": "tracking", "tracking shot": "tracking", "arc": "orbit", "crane": "crane up",
                  "hand-held": "handheld", "locked": "static", "locked off": "static", "still": "static", "none": "static"}

LOOK = ("Photorealistic live-action film still, natural skin texture, realistic hands with five fingers, cinematic "
        "lighting, shallow depth of field, subtle film grain.")
STILL_NEG = ("cartoon, anime, illustration, 3D render, CGI, plastic skin, airbrushed, extra fingers, extra limbs, "
             "deformed hands, merged people, duplicated person, text, subtitles, watermark, logo, celebrity likeness")
MOTION_NEG = ("cartoon, anime, illustration, 3D render, CGI look, plastic skin, extra fingers, extra limbs, deformed hands, "
              "face morphing, identity change, changing costume, flicker, warping, smearing, jump cut, sudden camera jump, "
              "text, subtitles, watermark")
TALK_NEG = MOTION_NEG + ", exaggerated mouth, distorted teeth, frozen face, mouth moving out of sync"


def norm_size(s: str) -> str:
    k = str(s or "").strip().lower().replace("shot", "").strip()
    if k in SIZES:
        return k
    return SIZE_ALIASES.get(k, "medium")


def norm_camera(c: str) -> tuple[str, str]:
    """(camera move from CAMERAS, the original words when they were not a known move)."""
    k = str(c or "").strip().lower()
    if k in CAMERAS:
        return k, ""
    if k in CAMERA_ALIASES:
        return CAMERA_ALIASES[k], ""
    for name in CAMERAS:
        if name in k:
            return name, ""
    return "static", str(c or "").strip()[:120]


# ================================================================== prompts (templates; GPT or the owner may replace them)
def still_prompt(shot: dict, people: list[str], location: str | None, ref_people: list[str], has_location_ref: bool,
                 provider: str) -> str:
    """A shot still from the screenplay's shot. ref_people: the names whose masters are passed, in order (after the
    location picture for Nano, first for Qwen)."""
    parts = [f"A {shot.get('size') or 'medium'} shot, 16:9, from a live-action feature film."]
    n0 = 1
    if provider == "nano" and has_location_ref:
        parts.append(f"Image 1 is the location ({location}): keep its architecture, materials, colours and light.")
        n0 = 2
    for i, name in enumerate(ref_people):
        parts.append(f"The person in image {n0 + i} is {name}: keep exactly their face, hair, build and costume.")
    if provider == "qwen" and has_location_ref:
        parts.append(f"Image {n0 + len(ref_people)} is the location ({location}): keep its architecture, materials and light.")
    elif location and not has_location_ref:
        parts.append(f"Location: {location}.")
    extra = [p for p in people if p not in ref_people]
    if extra:
        parts.append("Also in the shot: " + ", ".join(extra) + ".")
    if shot.get("action"):
        parts.append(f"Action: {shot['action'].strip().rstrip('.')}.")
    ln = shot.get("line")
    if ln:
        parts.append(f"{ln['speaker']} is speaking, {ln.get('emotion') or 'focused'}; the face is clearly visible.")
    if shot.get("vfx"):
        parts.append(f"Visual effect: {shot['vfx'].strip().rstrip('.')}.")
    parts += [LOOK, INVENTED_PEOPLE_RULE, "No text, subtitles or watermark."]
    return " ".join(parts)


def motion_prompt(shot: dict) -> str:
    cam = CAMERAS.get(shot.get("camera") or "static", CAMERAS["static"])
    parts = [(shot.get("action") or "The people in the picture act the moment naturally").strip().rstrip(".") + "."]
    if shot.get("vfx"):
        parts.append(f"{shot['vfx'].strip().rstrip('.')}.")
    parts.append(f"{cam[0].upper() + cam[1:]}.")
    parts.append("Realistic human motion and real acting, the same faces and costumes throughout, cinematic lighting, "
                 "film look. " + INVENTED_PEOPLE_RULE)
    return " ".join(parts)


def talk_prompt(shot: dict, name: str) -> str:
    ln = shot.get("line") or {}
    emo = (ln.get("emotion") or "with quiet intensity").strip()
    cam = CAMERAS.get(shot.get("camera") or "static", CAMERAS["static"])
    return (f"{name} speaks the line, {emo}. Natural, realistic lip movement that follows the words, a real actor's "
            f"facial expression, small natural head movement and blinks; the others in the shot listen and react "
            f"subtly. {cam[0].upper() + cam[1:]}. Photorealistic live-action film, the same face and costume "
            f"throughout, cinematic lighting. " + INVENTED_PEOPLE_RULE)


# ================================================================== graphs
def qwen_still_graph(refs: list[str], prompt: str, seed: int, prefix: str, models: list[dict]) -> dict:
    """Qwen-Image-Edit-2511 composing a NEW 1280x720 picture from up to three reference pictures (uploaded names, in
    order: image1, image2, image3); Qwen-Image-2512 text-to-image when there is no reference."""
    if len(refs) > MAX_REFS_QWEN:
        raise ValueError(f"Qwen-Image-Edit takes at most {MAX_REFS_QWEN} reference pictures")
    q = {m["type"]: m["filename"] for m in models}
    unet = q["diffusion_model"] if refs else QWEN_IMAGE_2512["filename"]
    g = {"u": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
         "m": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["u", 0], "shift": QWEN_SHIFT}},
         "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": q["text_encoder"], "type": "qwen_image", "device": "default"}},
         "v": {"class_type": "VAELoader", "inputs": {"vae_name": q["vae"]}},
         "lat": {"class_type": "EmptySD3LatentImage", "inputs": {"width": W, "height": H, "batch_size": 1}}}
    if refs:
        g["cn"] = {"class_type": "CFGNorm", "inputs": {"model": ["m", 0], "strength": 1.0}}
        imgs = {}
        for i, name in enumerate(refs, 1):
            g[f"li{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g[f"sc{i}"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": [f"li{i}", 0]}}
            imgs[f"image{i}"] = [f"sc{i}", 0]
        g["pe"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["c", 0], "prompt": prompt, "vae": ["v", 0], **imgs}}
        g["ne"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["c", 0], "prompt": STILL_NEG, "vae": ["v", 0], **imgs}}
        g["pm"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                   "inputs": {"conditioning": ["pe", 0], "reference_latents_method": "index_timestep_zero"}}
        g["nm"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                   "inputs": {"conditioning": ["ne", 0], "reference_latents_method": "index_timestep_zero"}}
        model, pos, neg = ["cn", 0], ["pm", 0], ["nm", 0]
    else:
        g["pe"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": prompt}}
        g["ne"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": STILL_NEG}}
        model, pos, neg = ["m", 0], ["pe", 0], ["ne", 0]
    g["k"] = {"class_type": "KSampler", "inputs": {"model": model, "seed": seed, "steps": QWEN_STEPS, "cfg": QWEN_CFG,
                                                   "sampler_name": "euler", "scheduler": "simple", "positive": pos,
                                                   "negative": neg, "latent_image": ["lat", 0], "denoise": 1.0}}
    g["d"] = {"class_type": "VAEDecode", "inputs": {"samples": ["k", 0], "vae": ["v", 0]}}
    g["s"] = {"class_type": "SaveImage", "inputs": {"images": ["d", 0], "filename_prefix": prefix}}
    return g


def i2v_graph(start: str, end: str | None, prompt: str, seed: int, prefix: str, models: list[dict],
              length: int = PIECE) -> dict:
    """Wan 2.2 i2v 14B (high/low fp8 + lightx2v 4-step LoRAs) from the start picture; with `end` the first+last-frame
    node. 1280x720, `length` frames (4k+1) at 16 fps."""
    names = [m["filename"] for m in models]
    hi, lo, lhi, llo, te, vae = names
    common = {"steps": I2V_STEPS, "cfg": I2V_CFG, "sampler_name": "euler", "scheduler": "simple",
              "positive": ["w", 0], "negative": ["w", 1]}
    g = {"a": {"class_type": "LoadImage", "inputs": {"image": start}},
         "c": {"class_type": "CLIPLoader", "inputs": {"clip_name": te, "type": "wan", "device": "default"}},
         "v": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
         "uh": {"class_type": "UNETLoader", "inputs": {"unet_name": hi, "weight_dtype": "default"}},
         "ul": {"class_type": "UNETLoader", "inputs": {"unet_name": lo, "weight_dtype": "default"}},
         "lh": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["uh", 0], "lora_name": lhi, "strength_model": 1.0}},
         "ll": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["ul", 0], "lora_name": llo, "strength_model": 1.0}},
         "sh": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["lh", 0], "shift": I2V_SHIFT}},
         "sl": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["ll", 0], "shift": I2V_SHIFT}},
         "p": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": prompt}},
         "n": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["c", 0], "text": MOTION_NEG}}}
    base = {"positive": ["p", 0], "negative": ["n", 0], "vae": ["v", 0], "width": W, "height": H, "length": length, "batch_size": 1}
    if end:
        g["b"] = {"class_type": "LoadImage", "inputs": {"image": end}}
        g["w"] = {"class_type": "WanFirstLastFrameToVideo", "inputs": {**base, "start_image": ["a", 0], "end_image": ["b", 0]}}
    else:
        g["w"] = {"class_type": "WanImageToVideo", "inputs": {**base, "start_image": ["a", 0]}}
    g["k1"] = {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sh", 0], "add_noise": "enable", "noise_seed": seed,
               "latent_image": ["w", 2], "start_at_step": 0, "end_at_step": I2V_SPLIT, "return_with_leftover_noise": "enable"}}
    g["k2"] = {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["sl", 0], "add_noise": "disable", "noise_seed": 0,
               "latent_image": ["k1", 0], "start_at_step": I2V_SPLIT, "end_at_step": I2V_STEPS, "return_with_leftover_noise": "disable"}}
    g["d"] = {"class_type": "VAEDecode", "inputs": {"samples": ["k2", 0], "vae": ["v", 0]}}
    g["cv"] = {"class_type": "CreateVideo", "inputs": {"images": ["d", 0], "fps": FPS}}
    g["sv"] = {"class_type": "SaveVideo", "inputs": {"video": ["cv", 0], "filename_prefix": "video/" + prefix, "format": "auto", "codec": "auto"}}
    return g


# ================================================================== lengths and cost
def motion_pieces(seconds: float) -> list[int]:
    """81-frame pieces for a motion shot of `seconds` (at least one; each later piece repeats the joining frame)."""
    frames = max(1, math.ceil(round(float(seconds) * FPS, 6)))
    n = max(1, math.ceil((frames - 1) / (PIECE - 1)))
    return [PIECE] * n


def talk_frames(voice_seconds: float) -> int:
    """Frames of a dialogue shot: the approved line plus 0.5 s (the voice is padded by 1 s so the last piece never
    runs short, as on Episode 15)."""
    return max(17, math.ceil(round((float(voice_seconds) + 0.5) * FPS, 6)))


def task_minutes(task: dict) -> tuple[float, float]:
    """(typical, at most) GPU minutes of one task: still | motion | talk."""
    from .talking_s2v import shot_minutes
    k = task["kind"]
    if k == "still":
        return STILL_MIN, STILL_MIN_MAX
    if k == "motion":
        m = PIECE_MIN * len(task.get("pieces") or [PIECE])
        return m, m
    if k == "talk":
        m = shot_minutes(int(task["frames"]))
        return m, m
    raise ValueError(f"unknown task {k}")


def estimate(tasks: list[dict], prices: list[float], lifetime_min: int) -> dict:
    """GPU minutes and cost of one run of tasks (sessions as many as the maximum lifetime needs)."""
    if not tasks:
        return {"minutes": 0.0, "usd_typical": 0.0, "usd_max": 0.0, "sessions": 0, "too_long": False,
                "label": "nothing to make on the GPU"}
    typ = sum(task_minutes(t)[0] for t in tasks)
    mx = sum(task_minutes(t)[1] for t in tasks)
    usable = max(15.0, lifetime_min - SETUP_MIN - 5)
    sessions = max(1, math.ceil(mx / usable))
    minutes, minutes_max = round(typ + sessions * SETUP_MIN, 1), round(mx + sessions * SETUP_MIN, 1)
    p0 = prices[0] if prices else 0.0
    pmax = max(prices) if prices else 0.0
    ut, um = round(p0 * minutes / 60, 2), round(pmax * minutes_max * MAX_MARGIN / 60, 2)
    too_long = any(task_minutes(t)[1] > usable for t in tasks)
    return {"minutes": minutes, "minutes_max": minutes_max, "sessions": sessions, "usd_typical": ut, "usd_max": um,
            "too_long": too_long, "label": f"about {minutes:.0f} GPU min: about ${ut:.2f}, at most ${um:.2f}"}


def voice_audio_graph(delays: list[float], has_music: bool, total: float, music_volume: float) -> str:
    """FFmpeg filter_complex for the final mix: inputs 1..n are the approved line takes (each delayed to its shot's
    start), input n+1 the optional music (looped, cut to the length, lowered). Output label [aout]."""
    parts, labels = [], []
    for i, d in enumerate(delays, 1):
        ms = max(0, int(round(d * 1000)))
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]")
        labels.append(f"[v{i}]")
    if has_music:
        k = len(delays) + 1
        parts.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,aloop=loop=-1:size=2147483647,"
                     f"atrim=0:{total:.3f},volume={music_volume:.2f}[mus]")
        labels.append("[mus]")
    if not labels:
        return f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[aout]"
    if len(labels) == 1:
        parts.append(f"{labels[0]}apad,atrim=0:{total:.3f}[aout]")
    else:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,apad,atrim=0:{total:.3f}[aout]")
    return ";".join(parts)
