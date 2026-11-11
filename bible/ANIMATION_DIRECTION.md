# Animation Direction — Hybrid Production

> ⚠️ **PARTLY SUPERSEDED (owner direction, 2026-11-11):** the channel is for the **world at large**: **no Nigerian/African-specific stories, settings, names or language, and Femi is retired.** The cast, names, locations, language notes and jokes in this document were drafted for a West African setting and are **paused pending a rewrite**. Treat them as archive and templates (roles, structure and technique may carry over), **not as approved content**. See `DECISIONS.md` (AP-16 to AP-18).

> ## 🔒 VISUAL IDENTITY PERMANENTLY LOCKED (owner decision, 2026-11-11; AP-51 to AP-57)
> The channel's identity is **simple, expressive 2D characters + richly illustrated, cinematic 2D environments**, exactly as shown in the canonical reference [`bible/concepts/lookdev-richenv/lookdev-scene-01.png`](concepts/lookdev-richenv/lookdev-scene-01.png) (SHA-256 `36b7c97e…ff016`, read-only). **Do not redesign, replace, reinterpret or propose alternative visual styles. Do not silently alter this decision.** Anything in this document that describes an earlier look (Inkblock, 2.5D Modern Pop, vector puppet kits, "Stickstage" exploration) is **superseded**. Specification and rules: [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md).

### What the locked identity means for this document
- **Superseded (look):** the Inkblock puppet-kit construction, indigo ink, floating brows, mood-tint look and 2.5D variants described below. **Still valid (technical):** the layer, keyframe, camera, parallax, shadow and sound mechanics; the renderer capabilities and limits; the hybrid principle (pose-based by default, selective premium motion).
- **Characters** must be produced **to match the canonical image**. The approved tests (2026-11-11) showed that **reference-conditioned generation keeps Canonical Character 01 strongly on-model** across six poses and expressions (minor drift in outline weight, skin tone and hand style is corrected by regenerating, never by redesigning). Cut-outs from such sheets can become the sprites the renderer composites. **D3 (vector puppet kits) is superseded;** any other method (for example redrawing) must match the canon and needs the owner's approval.
- **Environments** are richly illustrated 2D plates in the canonical style. The empty-room test showed the **same room can be recreated without the character, near-identically**, giving an animatable plate. **Depth-layer separation, higher resolution, new angles and other rooms are still to be tested.**
- **Image generation:** one Codex call per image, scratch folder, the canonical image (a copy) as reference; **no new concepts, alternative designs or alternative environments without approval.**
- **Next technical steps (each needs approval):** cut out the six poses from the sheet (no generation); composite them onto the empty plate; render a short vertical test through the unmodified renderer.

**Status:** the hybrid approach itself is **[APPROVED]**: pose-based and keyframed by default, selective full-motion AI video only where it materially improves comedy or storytelling, locally rendered, affordable. Everything else here is **[PROPOSED]**.
**Not in this phase:** no AI video integration, no image generation, no renderer change.

Renderer facts below are marked **(verified)**: read from `skills/directing-stickman-videos/scripts/` in Phase 0. They set the real limits of what the default method can do today.

---

## 1. Principle

> **Spend the budget on faces and timing. Spend money on motion only when a pose swap would look wrong.**

A funny frame held at the right moment beats a smooth movement at the wrong one. The channel's quality comes from expression design, cut timing and sound, not from continuous animation.

## 2. What the existing renderer can do (verified)

| Capability | Detail |
|---|---|
| Layers | `image` (PNG/JPEG only), `text`, `line`, `arrow`, `underline` |
| Keyframes | `x`, `y`, `w` (width), `angle` (radians), `alpha`, `progress`, smoothstep-interpolated |
| Visibility | Per-layer `from`/`to` times inside a shot |
| Shots | Back-to-back with no gaps or overlaps; shot cache means re-rendering changes is fast |
| Output sizes | Any even width/height from 256 up to 3840 and 12–60 fps; default design plane is 1280 wide and scaled |
| Native 16:9 and 9:16 | Supported, but portrait scenes must be recomposed by hand |
| Captions | One line at a time, burned in, plus SRT and VTT files. Custom caption font and size (20–64) supported. |
| Narration | **One** audio file per film, at its original speed |
| SFX | Built-in synthesised `tap`, `paper`, `pop`, `chime`, `jingle` only, **or** a pre-mixed audio file marked `contains_sfx: true` |
| Music | One looped track with gain 0–0.2 (not usable together with a pre-mixed master) |

### Limits that shape our workflow (verified)

1. **No rotation pivot for images** in the B1–B4 styles: `angle` rotates around the layer's top-left corner and `pivotX`/`pivotY` are rejected. Rotations (a head tilt, a door swing) must be baked into the art or built as sprite swaps. Workaround: design the pivot into the sprite (position the art so its top-left is at the hinge), or use swaps.
2. **Only one audio file.** Separate character voice stems, SFX and music must be **mixed outside the renderer** into one master, then passed as the narration file with `contains_sfx: true`.
3. **File-based SFX and ambience tracks exist only in style B4**, which brings a dark background, a fixed narrator identity requirement, a 3-second maximum shot length and other thriller-specific rules. Not suitable.
4. **No background colour or style of our own.** The four built-in styles hard-code their background (B1 near-white `#FDFDFC` with an optional grid, B2 warm paper `#f4f0e5`, B3 and B4 near-black). **Recommended workaround: use B1 with `"grid": false`** and full-frame background plates, so the renderer's own background never shows.
5. **No built-in tint, vignette or transitions** (the TV finish is B3-only). Tints (Doom Tint, Flashback) must be **pre-rendered overlay images** with transparency, used as `image` layers with `alpha` keyframes.
6. **Captions are single-line.** Long jokes need semantic splitting into several cues.
7. **Caption timing needs real word alignment.** The repo ships an optional Whisper helper; it needs Python packages that are not installed.

These constraints do **not** block the plan. They define the tooling that Phase 2 would need to supply **outside** the renderer (an audio mixer, an overlay set, a project-file generator). Any renderer change would need its own approval (see D22 in the decision list at the end of this file).

## 3. How characters are made [PROPOSED, D3]

**Recommendation: parametric vector puppet kits.** Each character is drawn once as vector shapes (SVG) with separate, named parts. A local script (to be written in a later phase) exports every needed combination as transparent PNGs.

Why:
- **Perfect consistency.** The same shape every time, so no AI drift.
- **Cheap variants.** New expression or outfit = swap a part and re-export.
- **Free to run locally.** Sharp (already installed and locked) can rasterise SVG.
- **Fits the renderer.** The renderer takes PNG image layers.

**AI image generation's role:** concept exploration and **background plates** only, always checked against the palette and outline rules. Not used for characters unless an approved reference sheet is the input and each output is reviewed.

Alternative (not recommended): AI-generated pose sheets per character. Risks: drift between poses, inconsistent faces, repeated cost to fix.

## 4. Puppet kit specification [PROPOSED]

Each recurring character needs:

| Asset | Count | Notes |
|---|---|---|
| Heads (angles) | Front, ¾ left, ¾ right, profile (4) | Include hair; neutral face removed so face parts are swapped |
| Eye sets | 10 states | See `VISUAL_IDENTITY.md` §3 |
| Brow sets | 8 states | Floating layer |
| Mouth sets | 12 expressions + 6 visemes | |
| Body poses | 12 core + 6 character-specific | see below |
| Hand shapes | 10 | |
| Outfits | 1 default + 1–2 extras | |
| Props | As needed | Phone, folder, cup, bag, flowers, etc. |

**12 core body poses** (every character): stand neutral; stand weight-shifted; walk A; walk B; sit; arms crossed; point; hands on hips; shrug; facepalm; slump; frozen vertical.
**Character-specific:** Femi pleading hands and charger-drawer dig; Amara's folder pose and eyebrow-judge lean; Tunde's advice pose and laughing fall; Dez's finger guns; Madam F's over-glasses stare; Zee's phone-filming pose.

**Per-character estimated assets:** about 4 heads × 10 eye × 8 brow × 18 mouth are not exported as every combination. The exporter **composites on demand** only the combinations a script requires. A typical 2:45 episode needs 60–120 composited frames in total for a cast of 3–4.

## 5. Default production method [APPROVED list; details PROPOSED]

| Technique | Implementation |
|---|---|
| **Reusable character poses** | PNG exports of each puppet pose, placed as `image` layers |
| **Facial expression swaps** | Swap face-part layers or use a pre-composited head; cut on the beat |
| **Hand and body pose changes** | Pose swap at the line or reaction, 2–4 frame holds |
| **Keyframed movement** | Slides, bounces, shakes via `x`/`y`/`angle` keys |
| **Camera zooms and pans** | **Group layers exist only in style B3 (verified), so there is no single "camera" object in B1.** A camera move is built by keyframing the `x`, `y` and `w` of the background plate and of every actor and prop layer by the same ratios. A small generator script (later phase) computes those keys from one "camera move" instruction. Plates are 3840×2160, so up to 2× zoom stays sharp. |
| **Entrances and exits** | Slide in/out from the sides; door open/close sprite swaps |
| **Reactions and comedic pauses** | Hold on a face; reaction cut-ins; Pepper cutaway |
| **Sound effects and visual emphasis** | Pre-mixed SFX; shock lines, sweat drops, stars as FX layers |

**Master format [D18]:** 1920×1080 at 30 fps for episodes (verified supported). Shorts are recomposed natively at 1080×1920.

### Camera rules
- Default: medium-wide, characters about half the frame height, floor line at 72%.
- Zoom in for tension (slow, 1.0 → 1.15 over 3–6 s). Snap zoom (0.15 s) for a punchline.
- Pan only to follow an entrance or to reveal a visual gag.
- Cuts, not fades, between scenes. Short whip-pan transition (0.2 s) optional for location changes.
- Do not move the camera during dialogue unless motivated.

### Shot grammar (budget-friendly)
1. **Establishing plate** (2–3 s, wide, no dialogue).
2. **Two-shot** (both characters, the default for conversation).
3. **Single** (close on the speaker).
4. **Reaction cut-in** (face only, 0.5–1.0 s).
5. **Insert** (a phone screen, a bill, a prop).
6. **Cutaway** (Pepper, clock, imagination frame).

### Dialogue lip-sync
- **Mouth-flap, not phoneme-perfect.** Alternate 2–3 mouth shapes timed to the audio's energy; use the six visemes only for key words.
- Mouth changes at about 6–8 Hz while speaking; hold closed on pauses.

## 6. Level-of-effort tiers for scenes [PROPOSED]

| Tier | Description | Share |
|---|---|---|
| **Tier 1: Static plus swaps** | Held pose, mouth flap, expression swaps, minor shakes | ~60% |
| **Tier 2: Keyframed action** | Slides, bounces, zooms, entrances, FX layers, scale cheats | ~30% |
| **Tier 3: Premium motion** | AI video clips for physical comedy or dramatic reactions | ≤10% |

## 7. Selective premium motion [APPROVED list of uses; rules PROPOSED, D10]

**Use premium motion for:**
- Dramatic reactions where subtle body motion sells the moment.
- Physical comedy: falls, chases, collisions, tumbling.
- Unusual movement a pose swap cannot suggest.
- Important visual punchlines (the payoff shot of an episode).
- Scenes where pose-based animation would look noticeably unnatural.

**Do not use it for:** ordinary dialogue, establishing shots, anything solvable with a pose swap and a good sound effect, or because a scene "feels plain".

### Decision gate (every candidate clip)

A clip is approved only if **all** are true:

1. A written sentence says what the clip adds that poses cannot ("his body folds in half and slides under the table").
2. A pose-based attempt (storyboard with swaps) has been considered and rejected.
3. The clip is **3–6 seconds** (shorter is better; the repo's documented Google Flow route is limited to about 8 s per clip).
4. It fits the **episode budget**: at most 10% of runtime and at most 3 clips per episode [D10].
5. A fallback exists: a pose-based version of the beat that can be used if the clip fails the consistency check.

## 8. Keeping AI clips on-model [PROPOSED]

The biggest risk is **character drift**. Rules:

1. **Source from the model sheet.** Start each clip from an approved pose export (image-to-video), the same art the pose pipeline uses, never a text-only description.
2. **Provide the first frame, and the last frame if the tool allows**, so the clip starts and ends on exact approved poses.
3. **Flat-style prompt block** (a frozen description of the Inkblock rules: flat colours, indigo outlines, floating brows, no shading, no texture, no camera shake). Reuse it verbatim every time. Never use words that suggest another creator's style.
4. **Keep clips short and simple:** one character action, locked camera, plain background or a plate.
5. **Backgrounds:** generate the character on a flat colour or green-screen-like plain field, then composite over our own plate so the set stays identical.
6. **Cut on neutral:** begin and end clips on poses that match the surrounding pose-based shots; hide the transition with a cut, a shake or an FX burst.
7. **No faces speaking** in premium clips: dialogue stays in the pose pipeline (mouth-flap) so voices and lip movement stay consistent. Premium clips are for bodies and reactions.
8. **No text, logos or UI in generated clips.** Add them in our compositing.
9. **Consistency check** before acceptance (all must pass):
   - [ ] Head shape matches the model sheet (silhouette overlay test).
   - [ ] Garment colour is within tolerance of the signature hex.
   - [ ] Outline weight and colour match.
   - [ ] Eyes and brows follow our style (pill eyes, floating brows).
   - [ ] Hands are lollipop hands (no extra fingers).
   - [ ] Number of limbs is correct throughout.
   - [ ] No shading, texture or style drift.
10. **Retry cap:** three attempts per clip; if none pass, use the pose-based fallback.
11. **Colour matching:** apply a standard grade to match the clip to the flat palette.
12. **Record everything:** prompt, source frame, provider, model, cost and outcome in a per-episode ledger.

**Compositing the clip:** the clip is rasterised to frames or used as video and inserted by FFmpeg as a pre-rendered segment between rendered pose scenes. **How** to integrate it with the renderer is a Phase 2+ engineering task; the renderer today accepts still images only (verified), so video segments would be joined outside it. No design is made for that now.

## 9. Per-episode production flow [PROPOSED]

1. Script locked (with beat sheet and balance log).
2. Storyboard: shot list with tier labels (1/2/3) and premium-clip candidates.
3. Asset check: needed poses, expressions, props, plates; list new ones.
4. Voice recording or generation (per character).
5. Dialogue edit and caption alignment.
6. Assembly: shots, keyframes, overlays.
7. Sound: SFX, music, mix to a single master.
8. Preview render (about 20 s), review.
9. Full render; check picture and sound; QA checklist.
10. Package: thumbnail, title, description; Shorts cut-downs.

## 10. Quality bar (picture) [PROPOSED]

- No shot holds without a visible change (expression, blink, tiny movement, caption change) for more than about 2.5 seconds. (The repo's own B-series gate uses this number, verified in its documents.)
- Characters never appear off-model.
- Backgrounds never fight characters (value check).
- Captions never cover faces or key props.
- Every joke has a visible reaction or a deliberate pause.

## 11. Decisions requiring approval (animation-specific)

| ID | Decision | Recommendation |
|---|---|---|
| D3 | Vector puppet kits as the character method | Approve |
| D10 | Premium-motion budget (≤10% of runtime, ≤3 clips per episode) | Approve limits now; choose provider later |
| D18 | Master resolution and frame rate | 1920×1080 at 30 fps |
| **D22** | **Renderer strategy.** The built-in styles lack: a custom background, image pivots, multiple audio stems and tints. Options: (a) keep the renderer unchanged and supply tooling outside it (B1 style with the grid off, pre-mixed audio, overlay PNGs); (b) later, extend it with a new style. | **(a) first.** Revisit (b) only if limits bite. Requires explicit approval before any renderer edit. |
