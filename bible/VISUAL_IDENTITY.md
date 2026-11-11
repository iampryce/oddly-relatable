# Visual Identity: PERMANENTLY LOCKED

> ## 🔒 Final, owner-approved, permanent (2026-11-11)
> **This visual direction is FINAL. Do not redesign it, replace it, reinterpret it or propose alternative visual styles.** It is recorded as decisions **AP-51 to AP-57** in `DECISIONS.md`. Documentation and creative proposals **must not silently alter it**; any change needs an explicit owner decision recorded there.
>
> **Canonical visual reference:** [`bible/concepts/lookdev-richenv/lookdev-scene-01.png`](concepts/lookdev-richenv/lookdev-scene-01.png), SHA-256 `36b7c97e8b9c31673d6b04dbc9c95b0a6b433dd14dee133fff9c87ad3ebff016`, read-only, preserved in three identical copies. Integrity rules: [CANONICAL_REFERENCE.md](concepts/lookdev-richenv/CANONICAL_REFERENCE.md).

**Superseded and archived (not current):** the Inkblock draft (`bible/_archive-superseded/VISUAL_IDENTITY_inkblock-draft.md`), the 2.5D Modern Pop concept, the "Stickstage" exploration, the vector puppet-kit look, the Femi boards (`concepts/_archive-retired-femi/`) and the grey placeholder boards (`concepts/technical-tests/`, technical evidence only).

---

## 1. The defining combination

**Simple, expressive 2D characters + richly illustrated, cinematic 2D environments.**

This pairing is the permanent identity of the channel. The characters stay simple and flat; the environments carry the richness. Everything below describes what is locked. Where this document says "as in the canonical image", **the image, not a written description, is the authority.**

## 2. What is locked: character design language
Simple, flat 2D cartoon characters with:
- **Clean, bold, consistent black outlines.**
- **Round, expressive faces.**
- **Large expressive eyes and eyebrows.**
- **Simple, thin limbs.**
- **Clear, readable body language.**
- **Natural, exaggerated expressions suitable for comedy.**
- **Carefully controlled character proportions.**
- **Clothing with simple, distinctive colours and designs.**

## 3. What is locked: environment design
- **Richly illustrated 2D environments**, with detailed furniture, decorations and background objects.
- **Strong three-quarter perspective.**
- **Warm cinematic lighting.**
- **Layered foreground, middle-ground and background elements**, with natural furniture overlap and environmental depth.
- **Detailed textures and believable interior spaces**; beautiful, carefully composed environments.
- **Consistent treatment everywhere:** living rooms, offices, restaurants, apartments, shops, streets, schools, public spaces. **Never photorealistic in one place and flat cartoon in another.** Keep the approved illustrated 2D look.

## 4. The master character (Canonical Character 01) 🔒
The character in the canonical image is the **first canonical character**. He is **unnamed** (naming is a separate decision). **Preserve, and do not change his appearance in any future generation:**

| Locked element | As shown in the canonical image [OBSERVED] |
|---|---|
| Head | **Cream-coloured, bald, round**, with small ears |
| Face proportions | Existing proportions; **large white oval eyes with dark pupils** under **thick expressive eyebrows**; a **small mouth** (the existing eyebrow and mouth design) |
| Limbs | **Thin black arms and legs** |
| Hands | Small rounded black hands |
| Clothing | **Rust-coloured, ribbed knit turtleneck** with a simple tapered torso |
| Shoes | Brown, rounded |
| Outline | **Bold, clean black outline**, flat colour, **no shading** on the character |
| Body | The existing body proportions and outline style |

**Expression range is allowed** (the approved consistency test shows neutral, worried, shocked, laughing, pleading and deadpan), but the *design* never changes. Reference sheet: [`lookdev-character-test-02.png`](concepts/lookdev-richenv/lookdev-character-test-02.png). Known minor drifts to correct by regenerating, never by redesigning: outline slightly thinner, skin slightly lighter, and hand style (use the rounded mitt hands).

## 5. All future characters: one visual universe 🔒
**Every additional character must belong to the same visual universe, like characters from the same animated television series, not unrelated characters from different animation styles. They must NOT all look identical.**

| Must be **shared** (same universe) | Must be **distinct** (per character) |
|---|---|
| The same 2D illustration technique | **Head shape or silhouette** |
| The same outline quality (bold, clean black) | **Hairstyle or head features** where appropriate |
| The same character construction principles (simple, flat, thin limbs, round expressive face) | **Facial characteristics** |
| The same facial expression language (large expressive eyes and brows, exaggerated comedic expressions) | **Clothing and colour identity** |
| The same level of polish | **Body proportions** where appropriate |
| The same relationship between simple characters and detailed environments | **Personality shown through posture and expressions** |

### Same-universe check (apply to every new character before approval)
1. Placed next to Canonical Character 01 on the same background, does it look like it is from the **same series**?
2. Is the **outline weight and quality** the same?
3. Are the **eyes, brows and mouth** drawn with the same expressive language?
4. Are the **limbs thin** and the body simple?
5. Can it be recognised from its **silhouette** and **colour identity** alone, and does it differ clearly from every other character?
6. Is it **flat, with no shading**, against a detailed environment?
7. Is it **original** (no resemblance to the owner's reference creator's characters or any existing character)?

New characters are **not** created without the owner's approval (no new designs are proposed here).

## 6. Environments for future stories 🔒
The setting changes with the story; **the visual treatment does not.** Every environment follows the canonical image's quality: a detailed, painterly-illustrated 2D interior or exterior with a strong three-quarter view, warm cinematic light, layered depth and natural overlap.

| Setting | Notes (treatment only; contents belong to each story) |
|---|---|
| Living rooms, apartments | As in the canonical image |
| Offices, schools, shops, restaurants | Same illustrated 2D treatment, same lighting quality |
| Streets, public spaces | Same illustrated 2D treatment; **not** photographic |
Stories are for **the world at large**: no region-specific settings, and no religious or political symbols.

## 7. What the canonical image also shows (composition, not a rule to change)
The vertical 9:16 frame leaves **calm space near the top** (for a title) and **near the bottom** (for captions), keeps the character at about **one third of the frame height**, and crops **foreground objects at the frame edges** for depth. These are observations that suit vertical-first distribution; they do not redefine the identity.

## 8. What is NOT part of the locked identity
Character **names and personalities**, the cast list, story content, **brand colours and logo**, title typography, music and audio, and the production method for creating assets. These remain separate decisions. (The earlier Tangerine and Teal brand pair was part of the superseded Inkblock draft and is **not** locked.)

## 9. Production implications (technical; do not alter the identity)
- **Verified by the approved tests (2026-11-11):** reference-conditioned generation keeps the master character **strongly on-model** across six poses and expressions, and can recreate **the same room with the character removed, near-identically** (details and measurements in `concepts/lookdev-richenv/README.md`). This makes **a character cut-out composited into an empty plate of the same room** a viable route for the existing renderer's layered approach.
- **Still open (technical, not visual):** separating depth layers; higher resolution; whether new angles and other rooms stay consistent; the exact asset pipeline and per-asset review against the canon. Any redrawing method must **match** the canon, not reinterpret it, and would need the owner's approval.
- **Image generation** is by **one Codex call per image**, in a scratch folder, with the canonical image (a copy) as reference; **no new concepts, alternative designs or alternative environments are generated without approval.**

## 10. Governance 🔒
- This document, `CANONICAL_REFERENCE.md` and decisions AP-51 to AP-57 are the **single source of truth** for the visual identity.
- **Do not silently alter** this direction in documentation, prompts or proposals. If a conflict is found elsewhere, this document wins and the other document is corrected.
- A change requires an **explicit owner decision**, recorded in `DECISIONS.md` with the date.
- Every new character, location or episode must feel like it belongs to this same animated universe.
