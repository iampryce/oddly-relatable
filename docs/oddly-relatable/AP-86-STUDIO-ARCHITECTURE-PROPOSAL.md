# AP-86: next-generation production architecture

**Status (2026-11-16): PROPOSAL APPROVED (O1 to O4); S1, S2 and S3 AUTHORISED AND IMPLEMENTED; O5 TO O13 OPEN; S4 TO S7 NOT AUTHORISED.**
- **Approved by the owner on 2026-11-15:**
  - **O1:** this proposal and the milestone ID AP-86;
  - **O2:** the phase order and the S1 scope (data-model work only, local, $0, no artwork); every later phase needs its own approval;
  - **O3:** named marks and actions in set coordinates are the default placement model, and explicit placement overrides;
  - **O4:** depth-derived layering is the default, and explicit `z` overrides.
- **Still OPEN:** O5 to O13 (§13). Nothing in this document chooses set dimensions, layer, pose or prop standards, a first real set, an artwork route or budget, a facing strategy, framing formats, a movement method or an audio approach.
- **S1 (data models and validation) is implemented:** see §11.1.
- **S2 (sets and depth) was approved by the owner on 2026-11-16** (local, $0, synthetic fixtures only, no artwork, no GPU or paid services) **and is implemented:** see §11.2.
- **S3 (staging and props) was approved by the owner on 2026-11-16** (local, $0, synthetic fixtures only, no artwork, no GPU, image generation or paid services, no renderer changes) **and is implemented:** see §11.3. S4 to S7 have not started; each needs its own approval.
- **S4 approval request prepared (2026-11-16):** `AP-86-S4-APPROVAL-REQUEST.md`. S4 is **not authorised** until the owner approves it.
- No Character 02 is created or designed. AP-85 decisions M3 to M8 stay open and are not decided here.
- No GPU, external service, spending, model download or image generation. AP-84B3, its locks and its D1-7 gate are untouched; D1-7 stays NOT AUTHORISED.
- **The visual identity (AP-51 to AP-57, `bible/VISUAL_IDENTITY.md`) is not changed.** Everything here is engineering that serves it: flat, bold-outlined characters in rich, layered, warmly lit three-quarter environments.

**Builds on:**
- AP-79 (the layered story/scene/cast/camera/timeline/format architecture);
- AP-80R (the owner's long-term requirements);
- AP-82 (the end-to-end engine) and AP-83/84B (the studio, generation quarantine, reference packs, promotion design);
- AP-85 Track A (accepted 2026-11-15 at `305a504`);
- the bible's reuse ideas: `WORLD_BIBLE.md` §2, `MULTI_PLATFORM_ARCHITECTURE.md` §2 to §5, `VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` §2 to §5, and `ANIMATION_DIRECTION.md` §2 and §5.

---

## 1. Current architecture and existing capabilities (inspected 2026-11-15)

### 1.1 What exists and works

| Area | What exists | Where |
|---|---|---|
| Story layer | `oddly-relatable/story@1`: title, hook, end card, ordered scenes; each scene names a format, an environment ID and a cast. AP-78 conversation files are converted automatically | `production/lib/story.mjs` |
| Scene formats | Strategy registry. **text-chat** (Short 001) and **face-to-face** (AP-85) are implemented; phone-call, split-screen and solo are declared and fail clearly | `production/lib/formats/` |
| Characters | Per-character pose registry: file, SHA-256 (verified on load), feet anchor, figure height, approval class, optional `facing` and `facingVariants`; synthetic registries refused in production | `production/characters/character-01.json`, `lib/character.mjs`, `lib/cast.mjs` |
| Cast | Members by character ID, each with its own placement (feet x/y, figure height), z order, facing and speech style; independent pose timelines | `lib/cast.mjs`, `lib/conversation.mjs` |
| Environments | ID → file + SHA-256 registry; the plate is cover-fitted to the frame | `production/environments/environments.json`, `lib/story.mjs` |
| Camera | Wide / medium N× / close / hold; push-in, pull-back, shake, drift (text-chat); composed shots with focus, edge protection, clear-subject rule and explicit singles (face-to-face) | `lib/camera.mjs`, `lib/formats/face-to-face.mjs` |
| Timeline | Pose segments with cut / pop / crossfade transitions; frame-exact keyframes | `lib/timeline.mjs` |
| UI graphics | Chat bubbles, typing indicator, header, hook, end card; speaker-side bubbles | `lib/graphics.mjs`, `lib/layout.mjs` |
| Audio | One audio bed (optional voice and music files with SHA-256 and licence) plus the renderer's built-in SFX | `lib/audio.mjs`, `lib/wav.mjs` |
| Production run | story → project → audio → storyboard → MP4 (unmodified renderer) → QA → manifest; deterministic, overwrite-protected | `lib/produce.mjs`, `lib/qa.mjs` |
| Tests | 83 production tests (Track A A-1 to A-10, Short 001 byte and pixel baselines), 64 studio tests, 135 renderer tests | `production/tests/`, `studio/tests/`, renderer `tests/` |
| Studio | Local dashboard, job runner, SQLite audit trail; generation jobs with quarantine and human review; asset intelligence (story requirements, reference packs, candidate validation); registry promotion as new versions, never auto-current | `studio/lib/` |
| Governance | Canonical references with hashes; approval classes; AP-84B3 lock and ledger for any GPU experiment | `studio/config/`, `DECISIONS.md` |

### 1.2 What the renderer gives us (verified in `autopilot-core.mjs`; it stays unmodified, D22)
- Image, text and line layers, painted in array order, with `from`/`to` visibility windows.
- Keyframes on `x`, `y`, `w`, `angle` and `alpha`, eased between keys. The engine emits a key on every frame where needed, so motion is exact.
- Any even output size up to 3840 and 12 to 60 fps; the design plane is 1280 wide.
- **Hard limits:** no mirroring (no negative or scale keys outside style B3); rotation about the layer's top-left corner only (pivots rejected); images only (no video); one audio file; captions at a fixed bottom position; no grading, tint or blur (these are pre-rendered overlay images).
- The bible's spike already proved layered plates, three-depth parallax, baked shadows, foreground occlusion and tint overlays with this renderer (`VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` §2).

### 1.3 The current asset inventory
- **Character 01:** six standing poses (neutral, worried-phone, shocked, laughing, pleading, deadpan) extracted from the approved consistency sheet. Each is about 270×570 px. None is sitting, leaning, walking or holding a separate prop, and none declares a facing. The higher-resolution master v3 (1024×1536) is a single neutral pose.
- **Environments:** one approved empty living-room plate (941×1672), flattened. It has no separate depth layers, no prop cut-outs and no floor model. One alternative plate (candidate 05) exists.
- **Props:** none as separate assets. Everything visible is painted into the plate.
- **Placeholder:** the labelled synthetic placeholder lives only in test fixtures and is refused in production.

---

## 2. Architectural gaps and technical constraints

### 2.1 Gaps (each checked against the code)

| # | Gap | Today | Consequence |
|---|---|---|---|
| G1 | **No spatial model of an environment** | A plate is one image, cover-fitted. No floor line, horizon, depth scale, marks or surfaces | Every placement is hand-typed coordinates (`feetX`, `feetY`, `figureHeight`); nothing knows where a stool or counter is |
| G2 | **No depth-layered sets** | One flattened plate per environment | No foreground occlusion (a counter in front of legs), no parallax, no set dressing without redrawing |
| G3 | **No props** | No prop registry, IDs, anchors or states | A glass, phone, door or stool cannot be placed, held, moved or occluded |
| G4 | **No actions** | A pose is just an image; poses carry only a feet anchor and a name | "Sit on the stool" cannot be expressed; the author must pick an image and position it so it looks seated |
| G5 | **Poses lack semantics** | No tags (stance, action, expression), no contact anchors (seat, hands) | Poses cannot be chosen by meaning, aligned to furniture, or matched across characters |
| G6 | **Layering is manual** | Explicit `z` per member (AP-85) | Depth-correct ordering against furniture and other characters must be worked out by hand for every scene |
| G7 | **Camera bound by a just-fitting plate** | The background only just covers the frame | Pans and true singles are impossible without hiding people (AP-85 needed `single`); no parallax |
| G8 | **One aspect ratio per authoring** | A scene is composed for one output size | 9:16 and 16:9 from one scene (the approved author-once direction) is not supported |
| G9 | **No movement** | Members stand on fixed spots; transitions are cut, pop or crossfade only | No entrances, exits, walking or repositioning between beats |
| G10 | **Scene description is per-format and placement-heavy** | Lines, poses and shots are explicit | Stories describe *artwork placement*, not *what happens* |
| G11 | **Single-track audio assembly** | One bed of optional clips | Per-character voice stems, ambience and music need an external mix (the renderer takes one file) |
| G12 | **Asset production has no specification for the new kinds** | Reference packs and validation cover character poses and environment plates | No specification for layered sets, props, seated or contact poses, or anchor annotation |

### 2.2 Constraints the design must respect
- The visual identity is locked (AP-51 to AP-57). No new characters, locations or concepts are generated without owner approval (AP-57).
- The renderer stays unchanged unless a specific limitation is justified (D22). None of the proposals below needs a renderer change.
- Short 001 must stay byte-identical (A-10 baseline), and AP-85 Track A behaviour must be preserved, including composed framing, explicit singles and speaker-side bubbles.
- Artwork is never mirrored. Another facing needs artwork drawn that way (M7, open).
- Deterministic, local, $0 rendering. AI generation is optional and behind approval gates, quarantine and review.
- **Low-resolution sources:** the existing poses soften above about 1.5× zoom (AP-73).

---

## 3. Proposed component architecture

```
                        AUTHORED DATA (reusable)                              AUTHORED DATA (per story)
  ┌───────────────┐ ┌──────────────────┐ ┌──────────────┐ ┌──────────────┐   ┌──────────────────────────┐
  │ Character     │ │ Set (environment)│ │ Prop         │ │ Action       │   │ Story → scenes → beats   │
  │ registries    │ │ registries       │ │ registry     │ │ library      │   │ (who, where, does what,  │
  │ poses + tags  │ │ plates, layers,  │ │ art, states, │ │ stand, sit,  │   │  says what, how shot)    │
  │ + anchors     │ │ floor model,     │ │ anchors,     │ │ lean, hold,  │   └────────────┬─────────────┘
  │ + facings     │ │ marks, surfaces, │ │ affordances  │ │ walk, point… │                │
  └──────┬────────┘ │ occluders        │ └──────┬───────┘ └──────┬───────┘                │
         │          └────────┬─────────┘        │                │                        │
         └───────────────────┴─────────┬────────┴────────────────┘                        │
                                       ▼                                                  ▼
                          ┌─────────────────────────────────────────────────────────────────────┐
                          │ STAGING RESOLVER (new): marks + actions + anchors + floor model     │
                          │ → staged scene: every member/prop's world position, scale, pose,    │
                          │   depth and occlusion order per beat (explicit placements still win)│
                          └──────────────────────────────────┬──────────────────────────────────┘
                                                             ▼
                          ┌─────────────────────────────────────────────────────────────────────┐
                          │ FORMAT STRATEGIES (existing): text-chat, face-to-face, later        │
                          │ phone-call, split-screen, solo → lines, bubbles, shots              │
                          └──────────────────────────────────┬──────────────────────────────────┘
                                                             ▼
                          ┌─────────────────────────────────────────────────────────────────────┐
                          │ CAMERA + TIMELINE (existing, extended): composed shots per framing  │
                          │ profile (9:16, 16:9), pans within the superframe, parallax, moves,  │
                          │ pose transitions, movement paths → per-frame keys                   │
                          └──────────────────────────────────┬──────────────────────────────────┘
                                                             ▼
                 renderer project.json (UNMODIFIED renderer) → MP4 → external audio mix and caption
                 burn-in (later) → QA → export presets → human publication gate
```

**Principles, mapped to the brief:**
1. **No characters, places or stories in engine logic.** The engine knows *kinds*: a seat, a surface, a mark, an occluder, a hand anchor. Everything specific is data.
2. **Reusable assets are separate from scene instructions.** Registries describe what exists; stories reference IDs and actions.
3. **Each system can be extended on its own.** A new set, prop, action or pose is a data addition with validation. No other system changes.
4. **Determinism:** the resolver is pure (same inputs, same staged scene). Every asset is hash-verified, and every output is reproducible.
5. **Author once, render many:** stories are written in set coordinates. Framing profiles produce each aspect ratio.
6. **Explicit always wins.** An explicit placement, z or pose in a story overrides the resolver, so every current story and test means exactly what it means today.

---

## 4. Data models and registry examples

All registries keep their current approval, hash and promotion rules. New fields are **optional and additive**; current files stay valid.

### 4.1 Character registry v2 (additive to `production/characters/<id>.json`)

```jsonc
{
  "character": "character-01",
  "schemaVersion": 2,
  "poses": {
    "02": {                                   // existing fields unchanged: file, sha256, feet, figureHeight, approval…
      "name": "worried-phone",
      "tags": {"stance": "stand", "action": ["hold-phone", "talk"], "expression": "worried"},
      "facing": "front",                      // optional; undeclared poses can only be used "native"
      "anchors": {                            // image pixels, like "feet"
        "feet": {"x": 102, "y": 560},
        "handRight": {"x": 206, "y": 300}     // e.g. where a held prop attaches
      },
      "holds": "builtin:phone"                // the phone is painted into this pose (not a separate prop)
    },
    "sit-01": {                               // FUTURE pose (does not exist; needs approved artwork)
      "tags": {"stance": "sit", "expression": "neutral"},
      "anchors": {"seat": {"x": 140, "y": 330}, "feet": {"x": 150, "y": 560}, "handLeft": {"x": 60, "y": 300}}
    }
  },
  "proportions": {"figureHeightRef": 549, "headFraction": 0.30},   // for cross-character scale checks
  "canonicalReferences": "studio/config/canonical-references.json#character-01"
}
```

- **Tags** let an action ask for "a sitting pose with a worried expression", while a story can still name a pose ID.
- **Anchors** are contact points (feet, seat, hands, elbow) in image pixels. They are measured when a pose is approved, by the existing measurement in asset-intel for feet, or annotated by hand and reviewed.
- **Expressions:** today expressions are baked into whole-body poses. The model allows a future split (head layer + body) only if owner-approved art supports it. It is not assumed.

### 4.2 Set registry (environment v2): `production/environments/<set-id>.json`

```jsonc
{
  "set": "bar-01",                              // FUTURE example: no bar artwork exists
  "schemaVersion": 2,
  "kind": "interior/bar",
  "plates": {
    "counter-wide": {                           // one camera angle of the set
      "superframe": {"width": 3840, "height": 3840},   // square master, both 9:16 and 16:9 are windows (bible §4.2)
      "layers": [                               // back to front; each file hash-verified
        {"id": "back",  "file": "…/bar-01_counter-wide_back.png",  "sha256": "…", "parallax": 0.90},
        {"id": "mid",   "file": "…/bar-01_counter-wide_mid.png",   "sha256": "…", "parallax": 0.97},
        {"id": "counter-front", "file": "…/counter-front.png", "sha256": "…", "parallax": 1.0,
         "occluder": {"baselineY": 0.74}},       // drawn over anything standing behind this floor line
        {"id": "fore",  "file": "…/bar-01_counter-wide_fore.png",  "sha256": "…", "parallax": 1.30}
      ],
      "floor": {                                // perspective model for scale by depth (three-quarter view)
        "horizonY": 0.38,                       // plate fraction
        "refFeetY": 0.86, "refFigureHeight": 0.42   // a figure with feet at 0.86 is 0.42 of plate height
      },
      "marks": {                                // named spots, plate coordinates 0–1
        "stool-1":   {"kind": "seat", "point": {"x": 0.36, "y": 0.70}, "floor": {"x": 0.36, "y": 0.86}, "faces": "right"},
        "counter-2": {"kind": "stand", "point": {"x": 0.66, "y": 0.86}, "faces": "left"},
        "door":      {"kind": "entry", "point": {"x": 0.08, "y": 0.84}}
      },
      "surfaces": {
        "counter-top": {"kind": "surface", "line": {"x0": 0.20, "x1": 0.85, "y": 0.64}, "floorY": 0.80}
      },
      "actionSafe": {"x": 0.22, "y": 0.22, "w": 0.56, "h": 0.56},
      "lighting": {"key": "upper-left", "warmth": "warm"}    // used to pick baked shadows
    }
  },
  "variants": {"night": {"overlay": "…/night-tint.png"}}   // tints and dressing, not new plates
}
```

- The current `environments.json` entries stay valid: a flat plate is a set with one layer and no floor model. Explicit placement keeps working.
- Plate coordinates (0–1) are independent of the aspect ratio; a framing profile chooses the window.

### 4.3 Prop registry (new): `production/props/<prop-id>.json`

```jsonc
{
  "prop": "bar-stool-01",                       // FUTURE example
  "states": {"default": {"file": "…/bar-stool-01.png", "sha256": "…", "facing": "front",
                         "anchors": {"floor": {"x": 120, "y": 600}, "seat": {"x": 120, "y": 250}}}},
  "height": 0.22,                               // world size relative to the floor model's reference figure
  "affordances": ["seat"],
  "split": {"front": "…/bar-stool-01_front-legs.png"}   // optional part drawn OVER a seated character
}
```

Kinds of prop:
- set dressing (static, may be painted into the plate instead);
- interactive furniture (seat, surface, door with states `closed`/`open`);
- hand props (glass, phone, folder) with a `grip` anchor.

### 4.4 Action library (new, data): `production/actions/actions.json`

```jsonc
{
  "stand-at": {"needs": {"mark": "stand"}, "pose": {"stance": "stand"}, "align": {"feet": "mark.point"}},
  "sit-on":   {"needs": {"mark": "seat"},  "pose": {"stance": "sit"},
               "align": {"seat": "mark.point"}, "scaleFrom": "mark.floor",
               "layer": {"between": ["prop.back", "prop.split.front"]}},
  "lean-on":  {"needs": {"surface": true}, "pose": {"stance": "lean"}, "align": {"handLeft|elbow": "surface.line"}},
  "hold":     {"needs": {"prop": "grip"},  "pose": {"hasAnchor": "handRight"}, "attach": {"prop.grip": "pose.handRight"}},
  "walk-to":  {"needs": {"mark": "any"},   "pose": {"cycle": "walk"}, "path": "floor", "speed": 0.25}
}
```

An action is environment-independent. It states what it needs (a seat, a surface, a grip), which kind of pose (by tags), which anchors to align, and how to layer. **The engine resolves actions; it never knows "bar" or "office".**

### 4.5 Story/scene v2 (`oddly-relatable/story@2`, additive)

```jsonc
{
  "id": "bar-talk", "format": "face-to-face", "set": "bar-01", "plate": "counter-wide",
  "cast": [
    {"id": "a", "character": "character-01", "speech": {"style": "him"}},
    {"id": "b", "character": "<approved cast member>", "speech": {"style": "<its style>"}}
  ],
  "props": [{"id": "glass-a", "prop": "glass-01", "on": "counter-top", "at": 0.35}],
  "blocking": [                                     // what happens, not where images go
    {"who": "a", "do": "sit-on", "mark": "stool-1"},
    {"who": "b", "do": "stand-at", "mark": "counter-2"}
  ],
  "lines": [
    {"speaker": "a", "text": "…", "expression": "worried", "shot": {"camera": "Wide"}},
    {"speaker": "b", "text": "…", "shot": {"camera": "Medium 1.3×", "focus": "b"}},
    {"speaker": "a", "text": "…", "do": {"who": "a", "do": "hold", "prop": "glass-a"},
     "shot": {"camera": "Close", "focus": "a"}}
  ]
}
```

`story@1` scenes with explicit `placement`, `z` and `pose` remain valid and compile exactly as today.

---

## 5. How the parts connect

1. **The story** names a set and plate, the cast (by character ID), props (by prop ID, placed on marks or surfaces), blocking (actions) and lines (dialogue, expression, shot).
2. **The staging resolver** turns this into a staged scene, one entry per beat. For each member it works out:
   - **position:** the anchor of the chosen pose aligned to the mark or prop point;
   - **scale:** from the floor model at the member's floor contact, so a figure further back is smaller, consistent with the three-quarter perspective;
   - **pose:** chosen by action tags plus expression, filtered by the requested facing. Missing art is an error, never a mirror;
   - **depth:** from the floor y, which gives the draw order. Occluder layers and split props are inserted at their baselines. An explicit `z` overrides.
   - **held props:** attached by anchor, following the hand across pose changes. A hand anchor that is absent in the next pose is an error.
3. **The format strategy** (face-to-face, text-chat, …) adds the dialogue, bubbles and shots using today's code. Its input is the staged scene instead of hand-typed placements.
4. **Camera and timeline** compose each shot with the accepted Track A rules (focus, edge protection, clear subject, explicit single), now inside the superframe and per framing profile. They emit per-frame keys, applying the parallax factor per layer.
5. **Render, audio and QA** are unchanged. New QA checks: every contact anchor lands within tolerance of its target, and no member floats (feet off the floor line).

**Validation at every join, with errors and no silent defaults (the AP-85 rule):**
- an action that needs a seat but is given a stand mark;
- a pose without the anchor an action needs;
- a prop whose state is missing;
- a mark outside the plate;
- a facing that is not drawn.

---

## 6. Worked example: two characters at a bar

**Intent:** member A sits on a stool at the counter; member B stands at the counter beside them; they talk. A shot/reverse-shot covers the line, with A's reaction close-up.

**Assets this needs** (none exists today; each needs approved artwork, see §12):
- **Set `bar-01`, plate `counter-wide`:**
  - a back layer (back wall, shelves, warm lamps);
  - a mid layer (the far side of the counter);
  - a **counter-front occluder** layer;
  - a soft foreground layer (for example bar taps at the edge);
  - a floor model, marks `stool-1` and `counter-2`, and the surface `counter-top`.
- **Prop `bar-stool-01`:** stool art with `floor` and `seat` anchors, plus an optional `front` split (the front legs and seat rim drawn over A's legs).
- **Prop `glass-01`:** a glass with a `base` anchor (standing on the counter) and a `grip` anchor (held).
- **Character 01:** a sitting pose (`stance: sit`) with `seat`, `feet` and `handRight` anchors, and a standing pose facing the other member. Both facings need drawn art (M7).
- **Member B:** an approved character (Track B, M3 to M8) or, for engine tests, the labelled synthetic placeholder with equivalent anchors.

**Resolution, step by step:**
1. **`sit-on stool-1`.** The stool's `floor` anchor is placed at the mark's floor point, and the floor model gives the stool's scale at that depth. A's sitting pose is chosen by `stance: sit` plus the line's expression. A's `seat` anchor is aligned to the stool's `seat` anchor, and A's figure height comes from the same floor depth, so A and the stool share one scale. Layering is stool back, then A, then stool front split. The counter-front occluder is drawn **behind** A, because A sits in front of the counter.
2. **`stand-at counter-2`.** B's `feet` anchor is aligned to the mark, and B's scale comes from the floor model at that floor y. B's depth is compared with the counter occluder's baseline:
   - **in front of the counter:** B is drawn over it;
   - **behind the counter (a bartender):** the counter front hides B's lower body.
3. **Prop `glass-a` on the counter-top.** It sits on the surface line at 35% along, with its scale from the surface's floor depth.
4. **Line 3, `hold glass-a`:** the glass's `grip` is attached to A's `handRight` in A's current pose. If that pose has no `handRight` anchor, the build stops with an error.
5. **Shots:**
   - **Wide:** shows the full set window for the framing profile.
   - **Medium on B:** composed with the Track A rules. Because the superframe is larger than the frame, the camera can pan until A is fully out of frame, so a true single needs no hiding. `single: true` stays available, unchanged.
   - **Close on A:** the head and the glass hand are kept in frame.
   - **Each layer pans with its parallax factor:** the taps slide faster, the shelves slower.
6. **Bubbles:** as accepted in Track A, on the side where the speaker stands, styled from the speaker.
7. **9:16 and 16:9:** the same staged scene goes through both framing profiles. All marks lie inside the plate's action-safe square, so both windows contain the whole exchange (`MULTI_PLATFORM_ARCHITECTURE.md` §4.2).

## 7. Worked example: a character sitting at a desk in an office

**Intent:** Character 01 sits at a desk, types, then turns to face camera in shock.

**Assets** (none exist today):
- **Set `office-01`, plate `desk-a`:** a back layer (office wall, window, plants), a **desk-front occluder** (the desk's front panel and drawer unit, baseline at the desk's floor line), a desk-top layer (monitor and keyboard painted in, or as props), and the marks `desk-chair` (seat) and `walk-in` (entry).
- **Prop `office-chair-01`:** back and seat art with a `seat` anchor. The chair back is drawn *behind* the character and the seat rim *in front*, as a split.
- **Character 01:** a sitting/typing pose (`stance: sit`, `action: type`) with `seat` and both hand anchors, and a sitting/shocked pose (same seat anchor, facing front).

**Resolution, step by step:**
1. **`sit-on desk-chair`:**
   - the seat anchor is aligned and the scale comes from the chair's floor depth;
   - layering is chair back → Character 01 → chair seat rim → desk-front occluder;
   - the desk front hides the legs naturally, so a sitting pose only needs to be correct above the desk line. This cuts the art needed.
2. **Typing:** the `type` action checks that both hand anchors fall within tolerance of the `keyboard` surface line. A misplaced pose fails the build, so it never ships with floating hands.
3. **Shock beat:** a pose swap to sitting/shocked. The seat anchor is the same, so the body stays seated with no jump, and the existing cut, pop and crossfade transitions apply.
4. **Camera:** close on Character 01; the desk-front occluder stays in front as the camera pushes in. Face-to-face push-ins are added in phase S4. Today they are refused, not approximated.

---

## 8. Camera and animation workflow

**Keep what is accepted (Track A):**
- wide / medium N× / close / hold;
- composed medium and close shots (centre the focus within the background, nobody cut by the frame edge, clear subject);
- explicit `single`;
- speaker-side bubbles;
- text-chat's existing camera notes, with Short 001 byte-identical.

**Add, in order (each behind tests and its own approval):**
1. **Superframe framing.** Plates larger than the frame let the composer pan to true singles and reverse shots. The Track A rules are unchanged; they simply have more room. Today's just-fitting plates behave exactly as now.
2. **Framing profiles.**
   - **P-916** and **P-169** windows come from one staged scene. Each profile has an action-safe area, UI-safe margins and a caption zone (`MULTI_PLATFORM_ARCHITECTURE.md` §5).
   - Per-shot overrides apply only when a staging cannot satisfy both profiles.
   - Captions are burned in after rendering, per platform (bible option (a)), because the renderer's caption position is fixed.
3. **Parallax.** Each layer's key is computed with its own factor about the camera centre. This was proven in the bible spike, and depth gives the factors.
4. **Camera moves in face-to-face:** push-in, pull-back and pan between composed framings, as per-frame keys (smooth, no stutter). Every frame must still satisfy the framing rules, or the build fails.
5. **Continuity across cuts:**
   - shot/reverse-shot keeps screen sides. A stays left of B in every shot unless blocking moves them, because positions never change between cuts;
   - checks catch a member who changes side or scale between consecutive shots without blocking that explains it;
   - eyelines need facing art (M7).
6. **Character movement:**
   - **default:** pose swaps on the beat (the bible's principle: spend on faces and timing);
   - **movement:** position tweens along the floor model, with scale following depth, for slides, entrances and exits;
   - **walking:** a walk cycle of 2 to 4 approved poses stepped along the path;
   - **a limb rig** (thin limbs rotating about joints placed at the top-left corner) is an *option to test*, not a plan (`VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` §5);
   - **AI video clips** stay out of renderer shots and are spliced in by FFmpeg only if the premium-motion decisions (D10) allow.
7. **Pose interpolation:** stays cut, pop or crossfade between drawn poses. In-between images are not invented; a new in-between is new artwork and needs approval.

---

## 9. Proposed module and directory structure

```
production/
  characters/<character-id>.json        (v2 fields optional: tags, anchors, facing, proportions)
  environments/environments.json        (unchanged; flat plates keep working)
  environments/<set-id>.json            NEW  set registries: plates, layers, floor, marks, surfaces, occluders
  props/<prop-id>.json                  NEW  prop registries: states, anchors, affordances, splits
  actions/actions.json                  NEW  action library (data)
  framing/profiles.json                 NEW  P-916, P-169 windows, safe areas, caption zones
  stories/*.story.json                  (story@1 unchanged; story@2 adds set/plate/props/blocking)
  lib/
    story.mjs, scene.mjs, cast.mjs, character.mjs   (extended additively; v1 paths unchanged)
    sets.mjs          NEW  load/validate sets; plate → world mapping; floor model (scale by depth)
    props.mjs         NEW  load/validate props; states; anchors
    actions.mjs       NEW  validate actions; pose selection by tags/facing; anchor alignment rules
    staging.mjs       NEW  the resolver: story beats → staged scene (pure, deterministic)
    depth.mjs         NEW  draw order from depth + occluders + splits (explicit z wins)
    framing.mjs       NEW  framing profiles; superframe windows; per-profile composition (wraps Track A rules)
    camera.mjs, timeline.mjs                         (extended: parallax, moves in face-to-face, paths)
    formats/*.mjs                                    (consume the staged scene; text-chat untouched)
  tests/
    sets.test.mjs, props.test.mjs, actions.test.mjs, staging.test.mjs, depth.test.mjs, framing.test.mjs
    fixtures/  synthetic labelled sets/props/poses (like the AP-85 placeholder; test-only, never promotable)
studio/
  lib/asset-intel.mjs   extended: requirements for sets, plates, props, actions, anchors
  lib/generation.mjs    extended asset types (set-layer, prop) behind the same quarantine/review
  lib/promotion.mjs     unchanged rules (new version, never auto-current), new registry kinds
```

The renderer (`skills/directing-stickman-videos`) is not touched.

---

## 10. Migration and backward compatibility

1. **Additive schemas.** `story@1`, the current character registry, `environments.json` and every field AP-85 added keep their meaning. New behaviour appears only when a story uses new fields (`set`, `blocking`, `props`).
2. **Explicit beats implicit.** Hand-typed placement, z and pose always override the resolver, so every existing story and test compiles exactly as today.
3. **Regression gates in every phase:**
   - Short 001 project, assets and renderer frames stay byte-identical (the A-10 baseline);
   - Track A A-1 to A-10 pass;
   - the AP-85 review frames (A1, A3a, A3b, A5, A6) stay identical, measured with `production/evidence/ap85/review/fingerprint-frames.mjs`.
4. **Versioned registries.** A `schemaVersion` field is added; loaders accept v1 and v2. Promotion keeps creating new versions that are never auto-current.
5. **No artwork migration.** Approved files are never edited. New anchors and tags are metadata, added through the promotion and approval path.
6. **Synthetic fixtures first.** Every engine phase is built and tested on labelled synthetic sets, props and poses, refused in production like the AP-85 placeholder. Real artwork arrives only through approved production routes.

---

## 11. Phased implementation roadmap

Each phase needs its own owner approval, has its own regression gate, and stops at the gate. Phases S1 to S5 are engine work: local, $0, no artwork.

| Phase | Scope | Exit criteria | Cost |
|---|---|---|---|
| **S0** ✅ | Approve this proposal, the milestone ID and the decisions in §13 | **Done 2026-11-15:** O1 to O4 approved; O5 to O13 open | $0 |
| **S1 Data model** ✅ implemented | Schemas and validation for character v2 fields, sets, props, actions, story@2; loaders accept v1 and v2; errors for every invalid reference | Schema tests; Short 001 and Track A unchanged | $0 |
| **S2 Sets and depth** ✅ implemented (approved 2026-11-16) | Plate → world mapping, floor model (scale by depth), marks, surfaces, layered plates, occluders, depth ordering, parallax; synthetic labelled test set | Depth and scale tests; occlusion pixel tests (like A-4); regression gate | $0 |
| **S3 Staging and props** ✅ implemented (approved 2026-11-16) | Staging resolver; props with states and anchors; actions stand-at, sit-on, lean-on, hold; anchor-alignment QA | Bar and desk examples (§6, §7) built entirely from synthetic fixtures; anchor tolerance tests | $0 |
| **S4 Framing and camera** | Superframe composition, framing profiles 9:16/16:9 from one scene, face-to-face camera moves, continuity checks | Same staged scene → two profiles passing all framing rules; Track A rules preserved | $0 |
| **S5 Movement** | Paths on the floor model, entrances and exits, walk-cycle stepping, door states; optional limb-rig spike | Movement tests (no foot slip beyond tolerance); regression gate | $0 |
| **S6 First real set (art)** | One approved set and plate kit, plus Character 01's sitting and contact poses, via an approved production route | Owner visual approval of the assets; one produced test scene | **Depends on route (§12)** |
| **S7 Pipeline** | External audio mix (stems → one master), post-render caption burn-in per profile, export presets | Produced test episode passes QA in both profiles | $0 (local tools) |
| **Track B (AP-85)** | Character 02 identity work, as already planned | M3 to M8 decided by the owner | As decided there |

### 11.1 S1 implementation (2026-11-15)

S1 adds data models and validation only. It renders, stages, layers and moves nothing.

| Model | Module | What is validated |
|---|---|---|
| Shared rules | `production/lib/schema.mjs` | Identifiers, anchor and tag names, plate fractions, image-pixel points, repository-relative asset paths and SHA-256 values, unknown fields, supported schema versions |
| Character registry v2 | `production/lib/character.mjs` | Version-aware loading (v1 unchanged). v2 adds optional pose `tags` and `anchors` and registry `proportions`; v2 fields in a v1 file are refused; `anchors.feet` must equal `feet`; `verifyRegistryAssets` checks files, hashes and that anchors lie inside the image |
| Environments and sets | `production/lib/sets.mjs` | The v1 `environments.json` loader (same data, now validated). Set v2: plates; back-to-front layers with optional parallax and occluder baseline; optional floor model; marks (`stand`, `seat`, `entry`); surfaces; action-safe area; marks and surfaces share one namespace per plate; synthetic sets refused in production |
| Props | `production/lib/props.mjs` | States with assets and anchors; a required `defaultState`; affordances (`seat`, `grip`, `rest`), each needing its anchor in every state; optional front and back splits; synthetic props refused in production |
| Actions | `production/lib/actions.mjs` | At most one target (`mark` kind, `surface` or prop affordance); every `align`, `attach` and `scaleFrom` reference must agree with that target; pose selectors by tags and anchors |
| Story@2 | `production/lib/story-v2.mjs`, `story.mjs` | Scene `set`/`plate` (never together with `environment`), `props` (exactly one of `on`, `mark` or `placement`), `blocking` (one entry per member). Cross-references are checked against the set, prop and action registries |

**O3 and O4 in the data model:**
- `placementMode` returns `explicit` (an explicit placement always wins, even over blocking), then `blocking`, then `unplaced`.
- `layeringMode` returns `explicit-z`, otherwise `depth` in story@2.
- story@1 keeps its existing rules: explicit or default placement, and `z` defaulting to 0.

**Compile gate:** a story@2 scene that relies on a set, props, blocking, an unplaced member or depth-derived layering is refused, naming the phase it needs (S2 or S3). Everything else compiles exactly as story@1; Short 001 written as story@2 produces a byte-identical project.

**Not created:** no production set, prop or action-library data, because their standards are O5 to O7. Tests use labelled synthetic fixtures (`production/tests/fixtures/ap86-synthetic.mjs`), written only to temporary folders and refused by every production path.

**Tests:**
- `production/tests/ap86-s1-data-model.test.mjs`: 8/8;
- production suite 91/91 with FFmpeg (77 pass and 14 skipped without it);
- Short 001 and AP-85 Track A unchanged (byte and frame baselines);
- eight deliberate rule breaks were each caught.

### 11.2 S2 implementation (approved 2026-11-16)

Implemented at commit `bd32bde8ea03bc25eb3203bec53c01eb82ad53d6`.

| Capability | Where | Behaviour |
|---|---|---|
| Plate → world mapping | `sets.mjs` `plateWorldRect`, `plateToWorld`, `worldToPlate`, `resolvePlate` | The plate (its `superframe`, or the backdrop image's size) is cover-fitted to the design plane, centred. Plate fractions map to world units and back; marks and surfaces are mapped too, for S3 |
| Layered plates | `sets.mjs`, `formats/face-to-face.mjs` | Layers are drawn back to front. A layer is either full-plate (its image must have the plate's shape) or a cut-out with a plate `rect` (`x`, `y`, `w`; its height follows the image). Files are hash-verified. `assetRoot: "registry"` resolves files from the registry's folder (fixtures); the default is the repository |
| Layer-order rules | `sets.mjs` `validateSet` | The first layer is the full-plate backdrop. Backdrop layers come before occluder layers. Occluder baselines never move back up the plate |
| Floor model | `sets.mjs` `floorHeightAt` | Height = `refFigureHeight × (feetY − horizonY) / (refFeetY − horizonY)`. Feet on or above the horizon are an error |
| Explicit placement | `depth.mjs` `placementKind`, `worldPlacement` | World units (`feetX`, `feetY`, `figureHeight`) as before, or plate coordinates (`plateX`, `plateY`, optional `plateHeight`). The height comes from the floor model unless `plateHeight` is given (explicit wins). Mixing the two kinds is an error |
| Depth order (O4) | `depth.mjs` `layeringKey`, `drawOrder` | A member's depth is its feet line: a plate fraction in a set, or a frame fraction without a set. An explicit `z` is a depth on the same scale and wins. Occluders are drawn between members by baseline. Ties: an occluder comes before a member exactly on its baseline, and equal depths keep declaration order. Shadows are drawn with their member |
| Parallax | `depth.mjs` `parallaxCamera` | A layer with factor p zooms `1 + (zoom − 1) × p` and offsets × p about the shot's pivot. Members use factor 1. Wide shots are unchanged for every factor |
| Compile gate | `story-v2.mjs` | Sets compile in face-to-face scenes. Props, blocking and unplaced members still need S3 |
| Provenance | `produce.mjs` | Set registries are listed in the production manifest when a scene uses one; layer files appear under artwork |

story@1 takes exactly its old path. story@2 uses depth layering, and with explicit `z` it orders exactly as story@1.

**Tests:**
- `production/tests/ap86-s2-sets-depth.test.mjs`: 8/8, including rendered-pixel checks that a counter occluder hides a member behind its baseline but not one in front, that a foreground occluder hides everyone, that explicit `z` lifts a member over the counter, and that parallax changes only the zoomed shot;
- nine deliberate rule breaks were each caught;
- production 99/99 with FFmpeg (83 pass, 16 skipped without it); studio 64/64; renderer 134/135 (the pre-existing Jensen baseline failure, identical to the pre-S2 run);
- Short 001 byte and pixel baselines pass; AP-85 Track A 15/15; the AP-85 review scenes are byte-identical.

**Limitations and deferred work:**
- Sets render in face-to-face scenes only; text-chat is unchanged.
- Plates are centred; framing windows and profiles on the plate are S4.
- Parallax only shows in zoomed shots until camera moves exist (S4). A layer that carries the floor should keep factor 1, or feet appear to slide against it in zoomed shots. Which layers carry the floor is part of the open set standard (O5).
- Occlusion is by draw order with cut-out layers; there are no per-pixel depth masks.
- Each member keeps one depth for the whole scene; movement is S5.
- The backdrop-coverage check under parallax is defensive, and no test triggered it.
- The manifest's set-registry entry is untested end to end: no real set exists, and production refuses synthetic sets.

### 11.3 S3 implementation (approved 2026-11-16)

Implemented at commit `226ea7a1432dcacff9b094a4995cc0c8d28d998a`.

| Capability | Where | Behaviour |
|---|---|---|
| Staging resolver | `staging.mjs` `resolveStaging` | Turns explicit placements and blocking into world placements, contacts and a draw order. Deterministic; every missing mark, surface, prop, state, anchor, floor line or size is an error. Explicit placement wins (O3; the overridden action is reported) and explicit `z` wins (O4) |
| Placing actions | `staging.mjs` | The first `align` entry puts that pose anchor exactly on its target: a mark point or floor, a point along a surface (blocking `at`), or a prop anchor. The size comes from the floor model at `scaleFrom`, or at the prop's floor line for prop targets. A member's depth is the nearer of its feet and that floor line; a member whose feet do not reach it (sitting) gets no feet shadow |
| Poses | `staging.mjs` `poseMatches` | Lines still name poses (no guessing). Every pose a member uses under an action must match the action's pose selector (tags) and have the anchors it needs |
| Anchor-alignment QA | `staging.mjs` `ALIGN_TOLERANCE` = 1 design unit | Every align entry, for every pose used, must land within the tolerance (on a surface line: the height exactly, and the anchor within the line), or the build fails with the distance |
| Props | `staging.mjs`, `props.mjs` | Registered states with hash-verified files and in-bounds anchors. Front and back splits must match the state image's size and are drawn as extra layers. Placed on a mark (`floor` anchor), on a surface at `at` (`base` anchor) or explicitly (`floor`, else `base`). `height` is plate fraction at the floor model's reference line, scaled by depth |
| Held props | `staging.mjs`, `formats/face-to-face.mjs` | `hold` attaches the prop's `grip` to the hand anchor in each pose segment; each segment is its own layer, visible only for that pose and only while the holder is on camera |
| Draw order | `staging.mjs` | Occluders, members and free props by depth. A prop sat on is drawn just before its sitter, with its front split just after; held props come just after their holder |
| Rules | `story-v2.mjs`, `actions.mjs` | One placing action per member, plus any number of attaching actions (`hold`). A held prop has no placement of its own and no `z`. Surface placement and props on surfaces need `at`. Mark and surface placing actions must declare `scaleFrom`. An action either places or attaches |
| Examples | `production/tests/fixtures/ap86-s3-examples.mjs` | §6 bar: sit on a stool prop, hold a glass, lean on the counter, a glass on the counter. §7 office: sit at a desk mark behind the desk front, a mug on the desk, a visitor at a stand mark. Synthetic and labelled; temporary folders only |

**Tests:**
- `production/tests/ap86-s3-staging.test.mjs`: 7/7. Positions are worked out independently from the fixture numbers and compared with the render plan's layer keys; rendered pixels show the stool rim over the sitter, the glass in the hand and the desk front over the sitter;
- ten deliberate rule breaks were each caught;
- production 106/106 with FFmpeg (89 pass, 17 skipped without it); studio 64/64 (of 10 studio runs on the S3 tree, 8 were fully clean and 2 each had one intermittent environmental failure in a different test: a random test port landing on Windows-reserved port 5357, and a 1.5 s wall-clock assertion; S3 changes no studio code, the timed request measures about 20 ms with and without S3, and the pre-S3 commit passed 6 of 6 runs); renderer 134/135 (the pre-existing Jensen baseline failure, identical to the pre-S3 run);
- Short 001 byte and pixel baselines pass; AP-85 Track A 15/15; the AP-85 review scenes are byte-identical.
- The S1 and S2 tests were updated where they encoded rules S3 changes: holds and held props, props and blocking now compiling, and the unplaced-member message.

**Limitations and deferred work:**
- Blocking applies to the whole scene: no timing, entrances or movement (S5).
- Poses are named by the lines; the resolver checks them but never chooses them.
- One `hold` attaches one prop anchor to one pose anchor. Held props do not follow pop-transition scaling.
- The face-crop check still assumes a standing figure, so for seated poses its face box is conservative.
- Occlusion is by draw order with cut-outs, as in S2.
- **Shadow defect found during S3: corrected and accepted under AP-85.** S3 found a pre-existing defect (not caused by S3): shadow layers split for `single` shots had no visibility window, so off-camera members' shadows showed and shadows were duplicated. It was corrected under an owner-approved AP-85 corrective task at commit `59e6f3ef2b224ebefd64e5588cd47018b0f30633`, which shows each shadow only while its member is on camera, and the owner accepted the corrected A4 evidence on 2026-11-16 (evidence: `production/evidence/ap85/shadow-correction/`; AP-85 plan §5.5). Only AP-85 A4's shadow pixels changed; S3's prop layers already set their windows and were not affected.

**Ordering:** S1 → S2 → S3 is the critical path. S4 can follow S2. S5 follows S3. S6 can be prepared in parallel as decisions only, but no art is produced until approved. Track B stays independent; when Character 02 exists, it is simply another registry the system already supports.

---

## 12. Dependencies, risks and cost implications

### 12.1 Dependencies
- **Artwork for every new capability that is visible on screen.** Sitting, leaning, walking and contact poses, other facings, layered sets and props all need new approved art. The engine can be built and proven without it, using synthetic fixtures.
- **Owner decisions:** the decisions in §13; AP-85 M3 to M8 for any second character; D14/D18 (master format) for framing profiles; D10 for premium motion.
- **Local tools only:** Node, the existing canvas library, FFmpeg. Nothing new is needed for S1 to S5. S7 needs an FFmpeg-based mix and caption burn-in, also local.

### 12.2 Risks

| Risk | Mitigation |
|---|---|
| Flat cut-outs look pasted on in a rich plate (the bible's central risk) | Floor-model scale, baked contact shadows matched to the plate's light, occluders, warm overlay; owner visual review per set |
| Perspective mismatch between three-quarter plates and front-drawn characters, especially seated poses | Sitting poses drawn for the set's perspective class; occluders hide the hardest parts (legs behind desks and counters); anchor-tolerance QA |
| Facing multiplies the art (every pose × facings) | M7 decides; stage to minimise facings; facings only for the poses a set needs |
| Low-resolution poses soften in close shots | Higher-resolution pose standard for new art (the canvas size is already set at 1024×1536); softness warnings stay |
| Splitting flat AI plates into layers costs a lot of manual masking | Specify layered plates up front (§4.2), with the plate kit produced in layers rather than cut out afterwards |
| Consistency of new plates and angles generated by AI is unproven | Gated experiments only (AP-84B3-style locks and budgets); a hand-drawn route remains an option |
| The resolver hides authoring mistakes | Explicit errors for every unmet need; staging report in `layout-report.json`; contact sheets for review |
| Scope creep into a general animation suite | Phases with exit criteria; pose swaps remain the default motion |
| Render time grows with layers and per-frame keys | About 0.4 s per frame at 1080p with 5–6 layers (bible spike); shot caching; measure per phase |
| Regressions in accepted work | Byte and pixel gates for Short 001 and Track A in every phase |

### 12.3 Cost
- **S1 to S5 and S7:** $0. Local engineering with synthetic fixtures; no services, GPU or downloads.
- **S6 (real art):** depends on the route the owner chooses:
  - hand-drawn or commissioned art (cost per asset, outside this repository);
  - Codex image generation under AP-57 (one call per image, approval needed);
  - a GPU route (the AP-84B3 experiment is the existing gated model: a $5.00 cap, one $10 deposit, D1-7 not authorised).

  **No route is chosen or authorised here.**
- **Asset count for one set** (estimate, not a measurement):
  - **set:** 3–4 plate layers × 2–3 angles;
  - **props:** 5–10;
  - **Character 01:** 4–8 new poses (sitting, contact, two facings).

  A second set reuses all the poses and actions; only plate layers and props are new. That reuse is what author-once/render-many buys.

---

## 13. Owner decisions required before implementation

| # | Decision | Notes |
|---|---|---|
| O1 | Approve this proposal and the milestone ID AP-86 | **APPROVED 2026-11-15** |
| O2 | Approve phase order and the scope of S1 (data model only, $0, no artwork) | **APPROVED 2026-11-15.** Each later phase is approved separately |
| O3 | Placement model: named marks and actions in set coordinates as the default, with explicit placement as the override | **APPROVED 2026-11-15** |
| O4 | Depth-derived layering as the default, with explicit `z` as the override | **APPROVED 2026-11-15** |
| O5 | Set standard: square superframe master size, layer split (back, mid, occluders, fore), floor model, marks | Bible proposals: 3840 square master, three depth layers; to confirm |
| O6 | Pose standard for new art: canvas size, required anchors (feet, seat, hands), tags, minimum action set per recurring character | The canvas is already approved at 1024×1536 for new character poses (2026-11-13) |
| O7 | Prop standard: anchors, states, splits; which props are separate and which are painted into plates | |
| O8 | First real set for S6 (for example living room, office or bar) and which Character 01 poses to commission first | Content choice; no artwork until approved |
| O9 | Production route and budget for new art (S6) | Overlaps AP-85 M5; not decided here |
| O10 | Facing approach (draw per facing, or stage to avoid) | This is AP-85 **M7**; still open |
| O11 | Master and derived formats for framing profiles | Relates to open D14 and D18 |
| O12 | Movement method: walk cycles from drawn poses; whether to run a limb-rig spike | Pose swaps remain the default either way |
| O13 | Audio: external stem mixing and post-render caption burn-in (S7) | Outside the renderer; no renderer change |

**Explicitly not decided here:**
- AP-85 M3 to M8 (Character 02's role, design brief, production route, Track B thresholds, facing, review protocol);
- any image generation or GPU use;
- AP-84B3 D1-7;
- any renderer change;
- any change to the locked visual identity.
