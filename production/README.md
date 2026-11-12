# Oddly Relatable production toolkit (AP-78, AP-79)

Turns a story, written as structured data, into a project for the existing renderer (`skills/directing-stickman-videos/`), which is **not modified**. The toolkit only produces the renderer's normal `project.json` input and uses its public functions read-only.

**No new dependencies.** It reuses the renderer's installed `@napi-rs/canvas` and bundled fonts (Noto Sans, Caveat). Requires Node ≥ 20 and, for preview and render, the `FFMPEG` and `FFPROBE` environment variables (as the renderer does).

## Commands

```bash
# Compile a story (or an AP-78 conversation episode) into a renderer project
node production/cli.mjs build production/stories/short-001-v2.story.json studio-work/short-001-v2-ap79

# Inspect: renderer-exact stills at every beat and camera move, as one labelled sheet (no encode)
node production/cli.mjs storyboard studio-work/short-001-v2-ap79/project.json

# Optional MP4 preview through the unmodified renderer CLI (max 60 s)
node production/cli.mjs video studio-work/short-001-v2-ap79/project.json --seconds 60 --replace

# Tests
node --test production/tests/*.test.mjs
```

`build` fails if a check fails: a bubble outside the platform safe zone, the hook over the header, or the camera cropping a face. `--allow-issues` writes the project anyway and lists the issues in `layout-report.json`. Softness warnings (a pose enlarged above 1.7× on screen) are reported but do not fail the build.

## Architecture (AP-79): one responsibility per layer

| Layer | Data | Module |
|---|---|---|
| Story | `stories/*.story.json`: title, format, hook, end card, ordered scenes | `lib/story.mjs` (validation, AP-78 episode adapter, environment resolution) |
| Scene format | each scene names a format; one strategy per format | `lib/formats/` (`text-chat` implemented; `phone-call`, `split-screen`, `face-to-face`, `solo` declared, not implemented) |
| Environment | `environments/environments.json` (ID → file, SHA-256) | `lib/story.mjs` |
| Character / cast | `characters/<character-id>.json` pose registries; a scene's `cast` lists members by character ID with placement, height, `z` and `facing` | `lib/cast.mjs`, `lib/character.mjs` |
| Dialogue / audio | scene `speakers` and `events` (messages, typing, pauses, pose changes, built-in SFX cues) | `lib/conversation.mjs` |
| Camera | per-beat `camera` notes taken from the script | `lib/camera.mjs` |
| Animation timeline | pose segments per cast member, transitions | `lib/timeline.mjs` |
| UI graphics and layout | bubbles, typing indicator, header, hook, end card; chat stack | `lib/graphics.mjs`, `lib/layout.mjs` |
| Render / post | renderer project (one shot per scene), silent track, reports, provenance, storyboard | `lib/scene.mjs`, `lib/preview.mjs`, `lib/wav.mjs` |

Stories never contain image paths for characters. They name a character ID, and the registry resolves the pose files, verifying each file's SHA-256.

**Renderer contract used (verified in `autopilot-core.mjs` and `autopilot-render.mjs`):**
- Style B1, contiguous shots.
- `image` layers with `from`/`to` visibility windows and `keys` (`t`, `x`, `y`, `w`, `alpha`), painted in array order.
- At least one single-line caption.
- An audio track whose length sets the duration.
- Built-in SFX `tap`, `paper`, `pop`, `chime`, `jingle` (gain ≤ 0.3).

## Camera (outside the renderer)

- **How it moves:**
  - Zoom about a pivot that stays fixed on screen. The pivot is the focus cast member's head top, so the face grows downward and never rises into the chat zone; feet crop in medium shots.
  - The camera transforms world layers only (environment, characters, shadows). Screen-space UI (bubbles, header, hook, end card) is never moved or scaled.
- **Frame-exact keys:** keys are sampled on the frame grid wherever the camera or a transition changes, and compressed on holds. The renderer never interpolates between moving keys.
- **Limits:**
  - Zoom is limited to 1×–1.5× (the approved limit for sheet poses).
  - Shake and drift offsets are clamped so the background always covers the frame.
  - A per-frame check fails the build if a face is cropped.

| Script note | Mapping |
|---|---|
| `Wide` | zoom 1.0, cut at the beat start |
| `Medium N×` (or `Medium`) | zoom N (default 1.3), cut |
| `Close` | zoom = 1.5 (cap), cut |
| `Hard cut, …` | explicit cut. Framing changes at a beat start are cuts anyway |
| `Slow push-in to N×` | eased zoom over the whole beat. `Push-in` without "slow" runs over min(1 s, beat) |
| `Pull back to wide` | eased zoom to 1.0 over min(1.2 s, beat) |
| `Hold`, `Still` | no change |
| `small shake`, `shake` / `drift` | decaying shake / slow drift over the beat |

Unknown wording is rejected, not guessed.

## Pose transitions

`transition` on an event applies to the pose change it makes:
- `cut` (default): the AP-78 behaviour.
- `pop`: a 0.2 s scale bounce anchored at the feet; the size returns exactly to 1.
- `crossfade`: a 0.16 s dissolve-over. The incoming pose fades in on top while the outgoing pose stays opaque, so the room never shows through.

Transitions only move, scale or fade existing artwork; no in-between drawings are created.

## Story format (`oddly-relatable/story@1`)

```jsonc
{
  "schema": "oddly-relatable/story@1", "id": "my-story", "title": "My Story",
  "format": {"width": 1080, "height": 1920, "fps": 30},
  "hook": {"text": "Four words. No warning.", "start": 0, "duration": 3},
  "endCard": {"duration": 3, "lines": [{"text": "My Story", "size": 92}], "caption": "Oddly Relatable"},
  "scenes": [{
    "id": "scene-1", "format": "text-chat", "environment": "living-room-empty-03",
    "cast": [{"id": "him", "character": "character-01", "placement": {"feetX": 640, "feetY": 2070, "figureHeight": 880}, "z": 0, "facing": "native"}],
    "reactionCast": "him", "camera": {"focus": "him", "maxZoom": 1.5},
    "header": {"label": "Wife", "icon": "heart"},
    "speakers": {"her": {"side": "left", "style": "her"}, "him": {"side": "right", "style": "him"}},
    "events": [
      {"type": "message", "speaker": "her", "text": "We need to talk.", "duration": 3, "pose": "02", "sfx": "chime", "camera": "Wide, still"},
      {"type": "typing", "speaker": "her", "duration": 3, "visible": 2.4, "camera": "Hold"},
      {"type": "message", "speaker": "him", "text": "Define March.", "duration": 2, "poses": {"him": "03"}, "transition": "pop", "camera": "Medium 1.3×"}
    ]
  }]
}
```

- **Multi-character:** `pose` targets `reactionCast`; `poses: {castId: poseId}` sets several members at once.
- **Multi-scene:** stories with several scenes become several contiguous renderer shots. The hook overlays the first shot and the end card extends the last.
- **AP-78 files still work:** `oddly-relatable/conversation-episode@1` is converted to a one-scene story.
- **Units:** renderer design units (the frame is 1280 wide; 1080×1920 output is 1280×2275.6).

## Fixtures and evidence

- **`stories/short-001-v2.story.json`:** Short 001. Its dialogue is identical to `fixtures/short-001-v2.conversation.json`, and its camera notes are verbatim from `bible/episodes/short-001-we-need-to-talk/SCRIPT_V2.md` (tests enforce both). Character 01 only; pose changes stay hard cuts, because the script specifies none.
- **`fixtures/synthetic-two-member-cast.story.json`:** **technical test only.** Two independently placed instances of Character 01 exercise the cast model, z-order, every transition and every camera feature. It is not a second character.
- **Evidence:** `evidence/ap78/` and `evidence/ap79/` hold storyboards, previews, layout reports, the AP-78 vs AP-79 comparison and a render summary with a PSNR regression check. All technical evidence only, not production approval.

## Limitations

- **Formats:** only `text-chat` is implemented. The other formats are declared strategies that fail clearly.
- **Facing:** only `native` is supported. The B1 renderer cannot mirror images, so mirrored artwork would need separate approval.
- **Close-up softness:** sheet poses are about 550 px tall, so at 1.5× zoom they are enlarged about 2× on screen (reported as softness warnings).
- **Crossfade ghosting:** a short dissolve between two different drawings briefly shows both.
- **Not built:** lip-sync, voices and music. SFX are the renderer's built-in synthesized sounds.
- **One caption required:** the renderer requires at least one caption, so the end card carries one by default.
