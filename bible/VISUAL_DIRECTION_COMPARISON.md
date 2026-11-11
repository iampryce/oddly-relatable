# Visual Direction Comparison — Inkblock vs 2.5D Modern Pop

> ⚠️ **PARTLY SUPERSEDED (owner direction, 2026-11-11):** the channel is for the **world at large**: **no Nigerian/African-specific stories, settings, names or language, and Femi is retired.** The cast, names, locations, language notes and jokes in this document were drafted for a West African setting and are **paused pending a rewrite**. Treat them as archive and templates (roles, structure and technique may carry over), **not as approved content**. See `DECISIONS.md` (AP-16 to AP-18).

> ## 📜 HISTORICAL EXPLORATION, NOT CURRENT DIRECTION
> The visual identity is now **permanently locked** (AP-51 to AP-57) to the canonical image. This document records the earlier exploration (Inkblock, 2.5D Modern Pop, the hybrid, "Stickstage") and **technical evidence about the renderer**. Its options, recommendations and decisions V1 to V5 are **resolved or superseded**; **do not use it to propose alternative visual styles.** The renderer findings (layers, parallax, shadows, limits) remain valid. Current specification: [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md).

**Status:** comparison for owner review. **No visual identity is approved.** Nothing here changes `VISUAL_IDENTITY.md`, which still describes Inkblock as a *proposal*. The Channel Bible cannot be finalised until you choose.
**Date:** 2026-11-11 · **Prepared by:** Claude Code (concept art drawn locally as vectors; see §8 for how it was made and its limits).

Boards (all in `bible/concepts/technical-tests/`):

| File | Shows |
|---|---|
| [COMPARE_A_vs_B.png](concepts/technical-tests/COMPARE_A_vs_B.png) | Side-by-side: the same neutral placeholder figure, same room, same three poses in both concepts |
| [A-inkblock-scene.png](concepts/technical-tests/A-inkblock-scene.png) · [A-inkblock-scene-doom-tint.png](concepts/technical-tests/A-inkblock-scene-doom-tint.png) | Concept A living room, with the signature "Doom Tint" |
| [B-modernpop25d-scene.png](concepts/technical-tests/B-modernpop25d-scene.png) | Concept B living room (true perspective) |
| [A-inkblock-character-sheet.png](concepts/technical-tests/A-inkblock-character-sheet.png) · [B-modernpop25d-character-sheet.png](concepts/technical-tests/B-modernpop25d-character-sheet.png) | The placeholder figure in three poses: *The Text*, *Frozen*, *Pleading* |
| [B-levels-flat-vs-lit.png](concepts/technical-tests/B-levels-flat-vs-lit.png) | The open question: how flat should the character be inside the 3D room? |

---

## 1. What I actually inspected

| Material | How | Result |
|---|---|---|
| `assets/readme/style-2a-demo.mp4` (Modern Studio Tech, 1920×1080, 10 s) | Extracted 6 evenly spaced frames with FFmpeg into a contact sheet and **looked at it** | Inspected |
| `assets/readme/style-2b-demo.mp4` (Cinematic Story, 1920×1080, 10 s) | Same | Inspected |
| `skills/.../references/style-catalog.md` §3 (Style 2 text) | Read | Inspected |
| README text for A2 | Read in Phase 0 | Inspected |
| `*.gif` previews, `examples.md` Style 2 examples, the linked X walkthrough, any outside channel | **Not inspected** | Not inspected |

**Limits of what I saw:** the frames were viewed as 640-pixel-wide thumbnails, six per clip. Subtle details (a faint rim light, small shading) could be missed. These demos are clips from AI video generators following the Director-mode prompts, not the output of this repository's renderer.

### What the Modern Pop reference does (observed)
- **2A:** a *completely flat* character (white round head, red beanie, yellow tee, thin black limbs) in a bright high-key "studio" with a perspective floor grid, big white blocks and a soft contact shadow under the feet. Depth comes from the environment; the character has no visible form shading.
- **2B:** the *same flat character* in dark, painterly, cinematic environments (mountain ridges, glowing paths, dusk light). Again the character appeared flat while the world carried the lighting and depth.
- **Lesson:** "flat figure in a dimensional world" works because of strong value contrast, perspective cues and grounding shadows, not because the figure is shaded.
- **Repository attribution:** the README names outside channels as inspiration for A3, A6 and B2–B4, but **not for A2**. I did not research any outside source for it.

## 2. The two concepts

To make the comparison fair, **the same neutral placeholder figure is used** in both. It is a **stand-in, not a character**, and it replaced the retired Femi design on 2026-11-11 (the old boards are archived in `concepts/_archive-retired-femi/`). It has a domino-shaped head, no glasses, neutral grey colouring, a slate garment, the same proportions (3.6 head-units tall, as `VISUAL_IDENTITY.md` specifies) and the same three poses.

| | **A · Inkblock** | **B · 2.5D Modern Pop** |
|---|---|---|
| Environment | Flat colour-block stage set, front-on, floor line at 72% | Real one-point perspective room: converging floor, walls, ceiling, boxes with lit/shaded faces |
| Depth cues | Overlap and scale only | Perspective, window light and light shaft, ambient-occlusion shadows, lamp glow, vignette |
| Character linework | 6 px outline, 8 px limbs | 4 px outline, 6 px limbs (cleaner, lighter) |
| Brows | Floating; "lift-off" on shock | Attached; simple raise |
| Character lighting | None; mood comes from full-frame tints (Doom Tint) | Scene tint + contact shadow + cast shadow (see §4) |
| Camera | Straight-on, pans and zooms | Straight-on plus parallax: layers scale at different rates |
| Look | Warm, graphic, playful | Clean, bright, modern, more "produced" |

**Honest caveat:** because the same figure is used in both, Concept B is really *"Inkblock character grammar in a 2.5D world"*, not a literal Modern Pop character (white head, thin black sticks, beanie). A literal Modern Pop-style character would be a different design, and I did not draw one. If you want that tested, say so.

## 3. Strengths and weaknesses

| | A · Inkblock | B · 2.5D Modern Pop |
|---|---|---|
| **Visual impact / "premium" feel** | Charming, but reads as a flat cartoon | Clearly richer; the room feels like a place |
| **Distinctiveness** | High: floating brows, head shapes, tints are ours | Medium: the *formula* (flat figure, dimensional world) is shared with the reference, even though the specifics differ |
| **Expression readability** | Excellent: brow lift-off is a strong gag | Good, slightly less exaggerated |
| **Reuse / cost** | Cheapest: a plate is one flat image; any angle is easy | Costlier: every camera angle needs its own perspective plate; reverse shots need new plates |
| **Character consistency** | Easy (vector puppet) | Same character art, but needs more poses (¾ views, depth scale), plus a shadow per pose |
| **Fit with the existing renderer** | Good | Workable but heavier (see §5) |
| **Comedy tools** | Doom Tint, freeze labels, scale cheats: all easy | Same, plus real light changes (window light dimming) and depth gags |
| **Risk of looking like the repository reference** | Low | Moderate: mitigated by §6 |
| **Cost per episode** | Low | Medium |

## 4. The open question: should characters stay completely flat?

I rendered the same pose, in the same room, three ways ([B-levels-flat-vs-lit.png](concepts/technical-tests/B-levels-flat-vs-lit.png)):

| Level | Treatment | What I saw |
|---|---|---|
| **1 · Fully flat** | Sprite as drawn, plus a contact shadow | Clean and consistent, but he looks slightly "pasted on" the room |
| **2 · Flat + scene light** | Same flat sprite, plus a warm colour tint matching the room and a cast shadow on the floor | Integrates clearly better; the character is still 100% flat artwork |
| **3 · One-tone cel shade** | Adds a shaded side and a highlight edge | Adds a stylised look but starts to fight the flat linework; **my cel pass is crude** (a straight block of shade), so this level is not fairly judged |

**Recommendation (yours to decide): keep the characters flat 2D (Level 2).** Reasons:
1. Flat sprites swap poses and expressions freely; shaded ones need separate versions for each light direction, mirrored pose and camera angle.
2. The contrast of a flat character in a deep world is the style's charm, as the reference itself shows.
3. Level 2's tint and shadow are pre-made and cheap, and fit the renderer's image layers.

Use Level 3 only if you explicitly want a different look, and then it should be redrawn properly by an artist, not by my quick pass.

## 5. Production implications for the existing renderer (verified from its code in Phase 0)

| Need in Concept B | What the renderer offers | Consequence |
|---|---|---|
| Depth scaling (a character walking toward camera) | `w` (width) and `x`/`y` keyframes | Possible; scale and move the sprite by hand or generated keys |
| Cast shadows that follow the floor | **No skew or perspective**, only images | Pre-render a shadow PNG per pose per plate lighting |
| Camera moves with parallax | Per-layer keyframes | Works: scale background, midground and foreground at different rates, via generated keys |
| Mood tints and light changes | **None built in** | Pre-rendered overlay PNGs with `alpha` keys |
| Image rotation about a hinge | Rotates around the layer's top-left only | Bake pivots into art or use pose swaps |
| 3D plates themselves | Still images only (PNG/JPEG) | Plates must be made elsewhere (§7) |

Everything is achievable **without changing the renderer**, but Concept B needs a bigger tooling layer around it (camera-move generator, shadow baker, tint overlays). Concept A needs a smaller one.

## 6. Originality safeguards for Concept B

The repository's Modern Pop uses a *white* round head, thin *black* stick limbs, a *red beanie*, a *yellow tee*, glass-UI studio sets and cinematic landscapes. Concept B shares only the general idea of a flat figure in a lit world, which is a common technique and not something we can or should claim. To stay clearly our own:
- Keep Inkblock's character grammar: skin-toned head shapes, glasses, garment colours, a cast of individuals.
- Use domestic and urban sets, never glass-UI "tech studios" or epic landscapes.
- Never use a beanie-and-yellow-tee mascot, white heads or all-black stick limbs.
- No reference images from other creators are used to generate anything.

## 7. How the 3D-looking environments could be made

| Route | Cost | Pros | Cons | Status |
|---|---|---|---|---|
| **1 · Procedural vectors** (what I used) | Free | Fully consistent, editable, no installs | Limited richness; every angle is more code | Demonstrated here |
| **2 · Blender** (free 3D app: model each room once, render plates from any angle with real lighting) | Free software, but **needs an install, which requires your approval** | Best consistency and camera freedom; parallax layers can be rendered separately | Learning curve and setup time | Not started |
| **3 · AI-generated plates** (via the existing Codex image tool, characters stay vectors) | Uses your ChatGPT image quota | Richest look fastest | Consistency across angles is unproven; quota limits | **One test requested; see §9** |
| **4 · Paid image/video APIs** | Paid | n/a | **Not approved** | Not used |

**Rough effort estimate (my assumption, not measured):** Concept B costs about 1.5–2.5× Concept A per set, because of perspective angles, shadows and tints. Characters cost about the same.

## 7b. Option C, a hybrid [PROPOSED, not drawn]
Use Concept B's dimensional plates only for **hero and establishing shots** and for story peaks, and Concept A-style flat plates for the many repeated dialogue shots. This keeps most of the savings and most of the look. It is an option, not a recommendation I'd push without seeing real shots.

## 8. How the concept art was made, and its limits

- Drawn as SVG by a local script and rasterised with `sharp`, which is **already installed and locked**. No new dependency, no network, no AI, no paid service.
- Source: `bible/concepts/src/generate-concepts.cjs` (throwaway concept code, not production tooling). SVGs are in `bible/concepts/svg/`.
- **It is concept art, not final artwork.** Faces and bodies are deliberately simple, the Level 3 shading is crude, and the perspective room is mathematically correct but simply furnished.
- I corrected two problems during the work: the first figure was about 4.7 heads tall instead of the specified 3.6, and the first cast shadow floated away from his feet.

## 9. Codex background-plate test (route 3, one image)

Delegated to the existing Codex CLI (ChatGPT login) as one scratch-only experiment: an **empty** living-room plate generated from a character-free layout reference. Full provenance, the preserved original's path and the files are in [codex-plate-test/](concepts/codex-plate-test/README.md). Result: [codex plate](concepts/codex-plate-test/codex-plate-B-livingroom.png) and [the flat placeholder figure composited on it](concepts/technical-tests/codex-plate-test/placeholder-flat-on-codex-plate.png).

| Finding | Detail |
|---|---|
| ✅ Followed the brief | No people, text or logos; same layout, palette and props; clean and usable |
| ✅ Far richer than my procedural room | Soft window light, believable materials and depth, in about 78 seconds |
| ⚠ **Style mismatch with a flat character** | The painted plate makes the hard-outlined flat placeholder figure look pasted on. The richer the environment, the harder this gets. |
| ⚠ Resolution | 1672×941, below the 1920×1080 master and the 3840×2160 oversize the camera plan assumes |
| ⚠ Baked light, one layer | No separate depth layers, so parallax needs extra work |
| ❓ Unproven | The same room from other angles or lighting; repeatability; quota; commercial-use terms for the output |

**What this means for the decisions:**
- **V2 and V3 are linked.** A rich plate (AI or Blender) pushes towards Level 3 character treatment or a *flattened, posterised plate*; a simple vector plate suits Level 2 flat characters. You cannot pick the plate route and the character treatment independently.
- AI plates look promising **only if they can be made to match the character style** (flatter shading, simpler textures) and stay consistent across angles. One image cannot show that. Testing it would use more of the ChatGPT image allowance (a further, separate request).

## 7b. Option C (hybrid)

## 10. Decisions needed from you

| ID | Decision | My recommendation |
|---|---|---|
| **V1** | Visual direction: **A · Inkblock**, **B · 2.5D Modern Pop**, or **C · hybrid** | **B or C** if you want the premium look and accept the cost; **A** if cost and distinctiveness matter most. I lean to **C**, but I'd want to see real pilot shots before locking it. |
| **V2** | Characters flat or shaded | **Flat, Level 2** |
| **V3** | Environment route: procedural vectors, Blender (needs install approval), or AI plates via Codex (one image tested, see §9) | Linked to V2. For flat characters, procedural vectors or a *flattened* Blender render fit best; AI plates need a style-matching and multi-angle test first. Blender is the most robust long-term route. |
| **V4** | ~~Is Femi's concept design acceptable?~~ **Withdrawn: Femi is retired.** The figure in the boards is now a neutral placeholder; the new character is decision V8 | n/a |
| **V5** | Do you want a literal Modern Pop-style character (white head, thin sticks) drawn as a third test? | Not recommended, because of the originality risk |

Once V1 is chosen I will update `VISUAL_IDENTITY.md`, `WORLD_BIBLE.md` and `ANIMATION_DIRECTION.md` to match, then ask you to approve the full Channel Bible.
