# Visual Direction — Simple 2D Characters in Rich Illustrated Environments

> ## 📜 HISTORICAL EXPLORATION, NOT CURRENT DIRECTION
> The visual identity is now **permanently locked** (AP-51 to AP-57) to the canonical image. This document records the earlier exploration (Inkblock, 2.5D Modern Pop, the hybrid, "Stickstage") and **technical evidence about the renderer**. Its options, recommendations and decisions V1 to V5 are **resolved or superseded**; **do not use it to propose alternative visual styles.** The renderer findings (layers, parallax, shadows, limits) remain valid. Current specification: [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md).

**Status:** investigation report and proof-of-concept proposal for owner approval. **Not an approved identity.** The owner's message calls this the *preferred direction for exploration*, which I have recorded as exactly that.
**Date:** 2026-11-11 · **Author:** Claude Code · Supersedes nothing yet; it refines the Inkblock vs 2.5D comparison in [VISUAL_DIRECTION_COMPARISON.md](VISUAL_DIRECTION_COMPARISON.md).

> **Direction change received after this report was drafted (2026-11-11):** the owner does **not** want Femi or African-specific stories; the channel must be for **the world at large**, and a **different character** is wanted. This report has been adjusted: the images now use a **neutral placeholder figure** (the retired Femi boards are archived in `concepts/_archive-retired-femi/`) (the technical findings do not depend on who the character is), and the proof of concept now needs a **new original character that the owner supplies or chooses**. See `DECISIONS.md` AP-16 to AP-18.

**Evidence labels:** **[VERIFIED]** I ran it or read it in code · **[OBSERVED]** I looked at actual images or frames · **[REASONED]** inferred from code or experience, not tested · **[UNTESTED]** unknown · **[ASSUMED]** a recommendation or estimate.

---

## 0. The reference picture (received and inspected)

**Received 2026-11-11 as an image in chat:** a phone screenshot of one frame of a short vertical video (710×1536 px), including the TikTok app's interface overlays. A private copy is kept **outside the repository** at `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\references\tiktok-reference-1.jpg`, because it is someone else's artwork and is not for redistribution in our repo.

**What I actually see [OBSERVED]:**
- **Format:** vertical 9:16 portrait.
- **Character:** a round pale head with wavy brown hair; large white eyes with dark pupils, tilted worried brows, a small mouth; a tapered white shirt body with a yellow tie; **thin black arms and legs** with simple black hands and one visible shoe. He sits on a sofa with one leg crossed over, an orange phone held to his ear.
- **Environment:** a richly illustrated living room: blue-grey wall, a cream sofa with orange, mustard and blue cushions, wooden furniture, lamps with warm shades, many framed wall decorations, a patterned rug and table. The sofa is seen at three-quarter angle; warm soft light; a painterly texture.
- **Depth layers:** a cropped table and ottoman in the foreground, the sofa and character in the middle, the decorated wall behind.
- **Text:** a white rounded label with bold black title at the top, and bold white captions with a black outline and one highlighted word, lower-centre.
- **The app labels the clip "Contains AI-generated media."** That suggests AI generation was involved, but I cannot tell the method.
- The example's subject is religious symbolism. That is irrelevant to us and would break our rule against religion as a punchline.

**How it matches your description:** thin black limbs ✔, large expressive eyes and brows ✔, a detailed illustrated room ✔, perspective ✔, warm light ✔, foreground / middle / background layering ✔.

**What one frame cannot show:** animation and motion, camera moves, how the character is layered, any cast shadow (I see no obvious one), audio, pacing, or how it was produced.

**A useful lesson for our proof of concept [OBSERVED, interpretation REASONED]:** the character looks integrated mainly because he **physically interacts with the set** (he sits *in front of* the sofa cushions, his legs overlap the furniture), his **palette is tiny and echoes the room** (cream, gold, black), and his **bold black linework contrasts strongly** with the muted background. That matters more than shadows. It means our proof of concept should include a shot where the character sits on or leans against furniture, which needs the sofa split into a back layer and a front layer, so the sprite sits *between* them. The renderer's layer ordering supports that.

**It is a vertical-first reference, and the owner has since approved vertical as the primary format** (YouTube, TikTok and Facebook; 16:9 secondary; see `MULTI_PLATFORM_ARCHITECTURE.md`). The renderer supports native portrait, but portrait scenes must be **composed**, not cropped from landscape. This changes the proof of concept (§8).

## 0b. Look-development result (2026-11-11): the visual idea switched

The owner said they still saw the "Femi sketch" and wanted the idea switched to something like the reference. They were right: the grey placeholder in the vector boards still had Femi's body shape and poses. So the vector boards were moved to `concepts/technical-tests/` as **technical evidence only**, and one new image was generated with Codex (**1 of the up to 4 images** proposed in V6; **no reference image attached**): [lookdev-scene-01.png](concepts/lookdev-richenv/lookdev-scene-01.png). Provenance, the exact prompt and the preserved original are in `bible/concepts/lookdev-richenv/`.

**What it shows [OBSERVED]:** a vertical 9:16 mid-century living room with strong perspective, layered depth, warm light and cropped foreground objects, plus a **flat 2D character with thin black limbs, very large expressive eyes and brows** and a simple orange turtleneck, reading a phone. No text, logos or watermarks.

**Why it is closer to the owner's look:** the richness comes from the environment (a painted, detailed set), while the character stays simple and flat, which is exactly the contrast the owner described. Vector drawing could not reach this level.

**Original, not a copy:** different head, clothing, palette, room, pose and composition from the reference, and no religious or decorative iconography. Whether it is different *enough* is for the owner and ChatGPT to judge.

**The new limits it exposes [OBSERVED / REASONED]:**
- It is **one flattened picture**. To animate it with the renderer we need an **empty plate of the same room** (and ideally depth layers) and the **character as a separate cut-out**.
- **Resolution** is 941×1672, below the 1080×1920 master.
- **Consistency is the decisive unknown:** can Codex redraw *this same character* in other poses and expressions, and the *same room* from another angle or without him? The remaining proposed images should test exactly this: (2) the character in several poses and expressions on a plain background, using this image as the reference; (3) the same room with no character.
- The character is drawn by the AI, so it **may drift**; if so, a vector character redrawn to match this design is the fallback (the earlier recommendation).
- Commercial-use terms for the image output are unverified.

## 1. Repository inspection (task 1)

| Reference | How inspected | What it shows |
|---|---|---|
| **A2 Modern Pop**, 2A and 2B demos | Six frames each from the MP4s, viewed as thumbnails **[OBSERVED]** | A flat figure (white head, thin black limbs) in a dimensional world; 2A is a bright studio with perspective floor, 2B is painterly and cinematic. No visible character shading. |
| **A4 Cozy Storytelling**, cafe demo | Six frames from `style-4-cozy-cafe.mp4` **[OBSERVED]** + `cozy-storytelling.md` read **[VERIFIED]** | **Closest match to your description:** a simple stick figure (white head, dark thin limbs) in a richly illustrated street café with soft light, depth haze, close-up inserts and a **foreground leaf pass**. |
| **B2 Colorful Hand-Drawn**, sleep demo | Six frames **[OBSERVED]** | Made by the *renderer*: flat, poster-like illustrated shots, a small character, **no perspective depth, parallax or lighting.** |
| Not inspected | GIF previews, `examples.md`, the outside X walkthrough, any TikTok source | n/a |

**Conclusion:** the repository *describes* this look (A4 rules) and *produced* it with AI video generators (Director mode, outside our control), but its **renderer pipeline (Autopilot) has never produced it.** What we want is therefore a new composition workflow, not an existing one. The A4 reference confirms the style is feasible; it does not give us a pipeline.

## 2. Renderer capability vs the new direction (task 2), tested

I ran a **technical spike** through the **unmodified** renderer. It used a local three-layer room, a flat stand-in figure (the neutral placeholder) with shadows, and a tint overlay. No AI generation and no Codex were used. Result: a 6-second 1920×1080, 30 fps MP4 (180 frames, H.264 + AAC, decodes cleanly) rendered in **77 s (≈0.43 s per frame)**. Frames: [spike-layered-depth-frames.png](concepts/technical-tests/spike-layered-depth-frames.png). Spike builder: `bible/concepts/src/spike-build-layered-depth.cjs`. Spike output (outside the repo): `C:\Users\PC\Desktop\Works\stickman-video-director\studio-work\spike-layered-depth\output\preview.mp4`.

| Need | Supported by the unmodified renderer? | Evidence |
|---|---|---|
| Full-frame illustrated plates | ✅ Yes | Spike **[VERIFIED]** |
| Three-layer parallax (back / mid / front, different scale rates) | ✅ Yes | Spike **[OBSERVED]**; the soft foreground plant moves faster than the wall |
| Transparent character sprite over a plate | ✅ Yes | Spike **[OBSERVED]** |
| Grounding shadows | ✅ as **pre-baked PNG layers** (no live shadows, skew or perspective) | Spike **[OBSERVED]** |
| Camera push-in, snap zoom, shake | ✅ via keyframes on every layer | Spike **[OBSERVED]** |
| Smooth camera motion | ⚠ **Needs one key per frame.** Interpolation eases to a stop at every key (smoothstep per segment), so sparse keys stutter. A generator emitting per-frame keys gives exact motion. | Code read **[VERIFIED]**; per-frame keys used in the spike |
| Pose and expression swaps, reaction cuts | ✅ via separate image layers with `from`/`to`, or shots | Spike **[OBSERVED]** (three pose swaps across cuts) |
| Mood tint (Doom Tint) | ✅ as an overlay layer with an `alpha` fade | Spike **[OBSERVED]** |
| Desaturation / colour grading | ❌ not built in | Code **[VERIFIED]**; pre-bake a desaturated plate and crossfade |
| Mirrored sprites | ❌ no negative scale (`w` must be positive; scale keys are rejected outside style B3) | Code **[VERIFIED]**; export pre-flipped PNGs |
| Rotation about a joint | ⚠ rotates about the layer's **top-left corner** only; no pivot setting | Code **[VERIFIED]**; limb rigs are possible if each limb PNG has its joint at the corner **[REASONED, UNTESTED]** |
| AI video clips inside a shot | ❌ images only | Code **[VERIFIED]** |
| Several audio stems | ❌ one audio file | Code **[VERIFIED]**; mix externally |
| Render time | ≈0.4 s/frame at 1080p with 5–6 full-frame layers. A 2:45 episode ≈ 4,950 frames ≈ **35 min worst case** (shots are cached, so revisions are faster) | Spike **[VERIFIED]**; extrapolation **[ASSUMED]** |
| Sharpness at deep zoom | Sprite (3 px per unit) stayed crisp to 2.55× zoom; the 1920 px plate went slightly soft, which reads like depth of field. **Higher-resolution sources (sprites ≈6 px per unit, plates 3840 px) are advisable for hero close-ups.** | Spike **[OBSERVED]** at full size |
| Foot slip from parallax | None visible in the frames I viewed with coefficients 0.85 / 0.95 / 1.0 / 1.35. **Not measured numerically.** | **[OBSERVED]** |

**Answer to task 6:** the current renderer **can support this approach without modification.** What it lacks is *authoring convenience*, so **minimal external tooling** (§6) is needed around it, not inside it.

## 3. Can Codex create consistent characters and reusable backgrounds? (task 3)

I was told **not to generate images in this investigation**, so this section uses the single plate test already done earlier today and the CLI facts.

| Question | What is known | Rating |
|---|---|---|
| Does it follow a reference image? | One test: yes for layout, palette and props (`-i` attaches the reference). **[OBSERVED]** | ✅ for backgrounds |
| Is the model/version known? | No; the tool exposes no model choice. **[VERIFIED]** | ⚠ unknown |
| Seeds / repeatable results? | None exposed. **[VERIFIED]** | ❌ no determinism |
| Output size | 1672×941 in the test. **[OBSERVED]** | ⚠ below master; upscale or re-ask |
| Speed | ≈78 s per image. **[OBSERVED]** | ✅ |
| Quota | Unknown and treated as limited. | ⚠ |
| Consistency of the **same room from another angle** | Not tested. **[UNTESTED]** | ❓ |
| Consistency of a **character across poses** | Not tested. **[UNTESTED]**; generally the weakest point of image models | ❌ risk |
| Transparent backgrounds, separate layers | Not tested. **[UNTESTED]** | ❓ |
| Style control (flat vs painterly) | Not tested beyond one style request. | ❓ |

**Recommendation [ASSUMED]:**
- **Characters: keep them as local vector puppets,** not Codex. Thin-limb, flat, rule-based characters are exactly what vectors do perfectly, and they stay identical forever. Codex-generated characters would drift and cost quota every time.
- **Backgrounds: use Codex for plates and props,** with a **locked "style block"** (palette, light direction, perspective, "no people") plus the previous accepted plate attached as a reference each time.
- **Room kits:** generate one master wide plate, get approval, then derive other angles from it, always with the master attached. Judge consistency by eye against a checklist (layout, colours, light direction, props).
- **Depth layers from a flat AI plate (three options, none yet proven):** (a) ask for foreground props separately on a plain background; (b) cut foreground objects out locally with hand-made polygon masks; (c) rebuild the room in Blender. I would try (b) first.
- **Style match:** a locally applied "flatten" pass (posterise, soften, line accent) may make an AI plate sit better with flat characters. **[UNTESTED]**

## 4. Compositing characters into detailed environments (task 4)

| Technique | How | Status |
|---|---|---|
| **Scale by depth** | Sprite height ∝ distance from the horizon to its feet; the generator computes it from a "floor map" per plate | **[REASONED]**; the spike used a fixed scale |
| **Grounding** | Contact shadow plus a cast shadow in the key-light direction, baked as a PNG per pose per plate | **[OBSERVED]** in the spike |
| **Colour integration** | A warm tint matched to the plate's light | **[OBSERVED]** |
| **Occlusion** | Order the layers so an occluding object (sofa arm, desk edge) is drawn *over* the sprite; needs a cut-out layer | **[REASONED]**; the spike layers were ordered back, mid, sprite, front |
| **Style unification** | A final overlay layer (soft grade, faint grain) over everything; optional plate flattening | **[UNTESTED]** |
| **Reality check** | The flat placeholder figure on the **procedural** room felt like one world; on the **Codex** plate it looked pasted on, because the plate was soft and painterly while the figure was hard-outlined | **[OBSERVED]** both |

So the richer the plate, the more care the character needs. This is the central risk of the whole direction and the thing the proof of concept should settle.

## 5. Camera, depth, shadows and animation (task 5)

- **Camera:** push-ins, pull-backs, snap zooms, shakes and pans all work **[OBSERVED]**; a camera-move generator should emit per-frame keys from one instruction like "push to 1.6× on the character's face over 0.8 s".
- **Depth layers:** three layers worked. Parallax coefficients 0.85 (back), 0.95 (mid), 1.0 (character), 1.35 (foreground) looked natural with no visible foot slip **[OBSERVED]**. A foreground layer should be soft (depth of field) and dark-ish so it frames rather than distracts.
- **Shadows:** pre-baked per pose per light direction. Mirrored poses need mirrored shadows, so the exporter must flip shadow and sprite together.
- **Character animation:** pose and expression swaps carry most of the acting **[OBSERVED]**. Because the new direction uses **thin limbs**, a **limb rig** (arms and legs as separate sprites rotating about a joint at the layer corner) becomes practical and would add walking and gesturing without AI video **[REASONED, UNTESTED]**; I recommend testing it in the proof of concept.
- **Premium motion (AI video):** still reserved for physical gags; it cannot be placed inside a renderer shot, so it would be spliced in by FFmpeg between renders.

## 6. Minimal external tooling needed [ASSUMED]

All of it sits **outside** the renderer, which stays unchanged:

| Tool | Purpose | Size |
|---|---|---|
| Asset exporter | Vector puppets to transparent PNGs (poses, expressions, flipped copies, shadows) | Small; a prototype already exists (`--export-spike`) |
| Project builder with a camera/parallax generator | Writes `project.json` with per-frame keys from shot instructions | Small; prototype exists (`spike-build-layered-depth.cjs`) |
| Plate post-processor | Resize, flatten, mask foreground cut-outs | Small, uses the installed `sharp` |
| Overlay baker | Tints, vignettes, desaturated plate variants | Small |
| Audio mixer | FFmpeg mix of stems to one master | Small |
| Caption timing | Whisper needs Python packages that are not installed (approval needed) | Later |

No new dependency is needed for the first four.

## 7. Proposed original visual identity (task 7) [PROPOSED]

Working name: **"Stickstage"** (a stage set with stickman actors). It borrows only *general* traits from your description and none of any creator's artwork.

**Characters** (a thin-limb *placeholder figure*, drawn only to show the construction, is in [C-thinlimb-character-sheet.png](concepts/technical-tests/C-thinlimb-character-sheet.png) and [C-thinlimb-scene.png](concepts/technical-tests/C-thinlimb-scene.png); crude, locally drawn, **not a proposed character**):
- **Thin ink limbs** (about 4.5 px at 1080p), small round hands, simple capsule shoes.
- **Large expressive eyes and brows**: pill eyes with highlights, thick brows; our signature **brow lift-off** stays for peak shock.
- **Distinct head shapes, skin tones, hair and accessories** per character (to be designed for the new character), so no two are interchangeable and none looks like a generic white-headed stick figure. Skin tones and looks should reflect a **global audience**, not one region.
- **Simple garment blocks** in each character's signature colour; no complex clothing.
- **Flat shading** (no form shading), with grounding by shadow and tint.

**Environments:**
- Rich 2D illustrated rooms with **true perspective**, warm key light from a consistent direction per set, soft shadows, subtle textures.
- **Three layers per plate** (back, mid, front) plus a soft foreground element for depth.
- **Reusable kits:** about 3 camera angles per set, plus day/night via tint overlays.
- **Everyday settings that read anywhere in the world** (home, office, café, street, shop). No region-specific setting, and real-world places are not named. (The West African world in `WORLD_BIBLE.md` is superseded.)

**Colour and readability rules:** characters are the darkest-lined and most saturated things in frame; environments sit in warm mid-tones; no pure black; the brand pair (Tangerine and Teal) stays on characters, props and thumbnails.

**Originality safeguards (checked against the actual screenshot):** we take only the *general* traits: simple thin-limbed characters in detailed, layered rooms, a broad technique used by many creators. We will **not** reuse: that composition (a seated phone call on a cream sofa), its blue-grey and cream palette, religious or decorative iconography, its character construction (cream round head, wavy brown hair, white shirt with yellow tie, black mitt hands), or its title-label and caption styling. Our character is distinguished by head shape, skin tone, glasses/hair/costume and a Tangerine and Teal palette, and our rooms and subjects are our own. **Open point:** the owner and ChatGPT should still judge by eye whether the finished look is different *enough*, since I can only compare against one frame.

## 8. Recommended proof of concept (task 8) [PROPOSED]

**Goal:** judge whether *one original character in one living room* reaches the quality you want, using only the existing renderer and Codex, before investing in the full cast.

**Scope:** **one new original character (supplied or chosen by the owner; Femi is retired)** with thin limbs, one living room, 12–15 seconds, silent or built-in sound effects only. **Vertical 9:16 first (1080×1920), then a 16:9 reframe of the same scene graph** to test the reuse approach in `MULTI_PLATFORM_ARCHITECTURE.md` §4 (a square superframe plate with the action staged in the central safe square). No full cast, no pilot content.

| Step | Work | Agent / tool | Cost |
|---|---|---|---|
| P0 | You provide the screenshot, **supply or choose the new character** (a description or reference), and approve this scope | Owner | n/a |
| P1 | Design the new character's static look (thin limbs, big eyes and brows) for your approval; then export 3–4 poses × 4 expressions, shadows, flipped copies | Claude Code, local vectors | $0 |
| P2 | Three plate candidates for the **same** shot: **(a)** improved procedural vector room; **(b)** Codex plate set, **at most 4 images** (master wide, a close angle, one foreground prop, one alternative lighting); **(c)** plate (b) flattened locally to match the character | Claude Code + **Codex** (b only) + local | Uses ChatGPT image allowance for (b) |
| P3 | Compose a 12–15 s test: wide push-in, parallax, three reaction cuts, snap zoom, tint, one limb-rig gesture | Claude Code, **unmodified renderer** | $0 |
| P4 | Compare (a), (b), (c) side by side; owner reviews picture and style match | Owner | n/a |

**Acceptance criteria [ASSUMED]:** the character stays on-model in every shot; no visible foot slip; shadows read as grounded; style match judged "one world" by you; render under about 10 minutes; plate kit reusable from a second angle; no paid API; no renderer change.

**Risks:** AI plate style clash (the likely outcome of (b) without (c)); multi-angle consistency; quota; per-frame key files are larger but still small.

**Approvals I need from you:** the screenshot; the POC scope; permission for **up to 4 Codex image generations** in P2(b). Nothing is generated until you say so.

## 9. Updated decisions

| ID | Decision | Recommendation |
|---|---|---|
| **V1** | Direction: now also **"Stickstage" (thin-limb characters, rich layered environments)** in addition to A, B, C | Explore Stickstage through the POC before locking |
| **V2** | Character flatness | Flat, grounded by shadow and tint; test limb rigs |
| **V3** | Environment route | Decide after POC step P2 compares procedural / Codex / flattened Codex |
| **V4** | **The new character** (replaces Femi) | You supply a description or reference, or choose from options I propose; I then draw it for approval |
| **V6** | **Approve the POC scope and up to 4 Codex images** | Approve |
| **V7** | **Provide the TikTok screenshot** so originality can be checked | Needed before locking any identity |
