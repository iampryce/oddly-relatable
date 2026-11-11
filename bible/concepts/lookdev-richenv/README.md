# Canonical look and approved technical tests

> 🔒 **The visual identity shown in `lookdev-scene-01.png` is PERMANENTLY LOCKED by the owner (2026-11-11).** See [CANONICAL_REFERENCE.md](CANONICAL_REFERENCE.md) for the integrity rules and hash, and `bible/VISUAL_IDENTITY.md` for the specification. **Do not redesign, replace or reinterpret it, and do not propose alternative visual styles.**

## Files
| File | What | Role |
|---|---|---|
| **`lookdev-scene-01.png`** | The approved scene: master character in the illustrated living room (941×1672) | **CANONICAL REFERENCE (read-only)** |
| `lookdev-character-test-02.png` | Technical test: the master character in six poses/expressions on a plain grey background (1199×1312) | Approved technical test |
| `lookdev-room-empty-03.png` | Technical test: the same room with the character removed (941×1672) | Approved technical test |
| `consistency-check-canon-vs-cell2.png` | Side-by-side of the canon and the closest test cell, made by Claude Code for review | Evidence |
| `prompt-01.txt`, `prompt-02-…txt`, `prompt-03-…txt` | The exact prompts | Provenance |
| `codex-final-message-0N.md` | Codex's final messages, verbatim | Provenance |

## Provenance
| | Image 1 (canon) | Image 2 (characters) | Image 3 (empty room) |
|---|---|---|---|
| Delegating / executing agent | Claude Code / Codex (`codex-cli 0.167.0`, ChatGPT login) | same | same |
| Tool | Codex built-in image generation (model not exposed) | same | same |
| Reference attached | **None** | The canonical image (a copy) via `-i` | The canonical image (a copy) via `-i` |
| Calls / images | 1 call, 1 image | **1 call, 1 image** (verified: one new output folder) | **1 call, 1 image** (verified) |
| Duration / exit | about 3 min 40 s, exit 0 | about 1 min 15 s, exit 0 | about 1 min 45 s, exit 0 |
| Original (preserved, untouched) | `…\generated_images\01a1c962-e4f0-7c01-9f1c-6c207965f6a2\exec-20dd7c60-….png` | `…\generated_images\01a1ca3b-5abc-7331-91ae-a4ddd41391a5\exec-099a529b-af2c-4b19-8c58-37f02c20edf8.png` | `…\generated_images\01a1ca3c-fc7a-7142-a67d-4c539e13c549\exec-3ea2b990-239d-44c6-83cb-b5d6baf3265a.png` |
| Repo copy vs original | byte-identical | byte-identical (SHA-256 prefix `36e8cef3…`) | byte-identical (SHA-256 prefix `48ed1ca3…`) |
| Cost | ChatGPT image allowance; no API | same | same |

All scratch work was done in `…\scratchpad\codex-lookdev` (outside the repository). Remaining quota is unknown; **no further images are authorised without the owner's approval.**

## Test 2 result: character consistency [OBSERVED, by eye and by side-by-side]
**Verdict: strongly on-model, not pixel-identical.**
- **Preserved well in all six cells:** the cream bald round head with small ears; large white oval eyes with dark pupils; thick brows; small mouth; rust ribbed-hem turtleneck; thin black limbs; small black hands; brown shoes; bold black outline; flat style with no shading; overall proportions. The worried-phone cell matches the canon very closely.
- **The six poses/expressions all read clearly:** neutral, worried with phone, shocked and frozen, laughing, pleading, deadpan with raised brow.
- **Small drifts to watch:** outlines are slightly thinner and cleaner than in the canon; the skin reads slightly lighter and more peach than the canon's cream; **hand style varies** (the shocked cell has spread-finger hands, the others rounded mitts); the sweater hem and torso width vary a little between cells.
- **Conclusion for production:** reference-conditioned generation **can** keep this character recognisably consistent, so AI-generated pose sheets are viable. A **review step per generated asset** against the canon (hands, skin tone, outline weight) is still needed, and any drift is fixed by regenerating, not by redesigning.

## Test 3 result: the same room without the character [OBSERVED + MEASURED]
**Verdict: near-identical.** The layout, perspective, furniture, objects, window, lighting, rug, foreground table and plant all match. The character and the small alert lines are gone; the bookshelf, rug and floor continue naturally, with no marks left.
Measured mean absolute pixel difference per channel (0 to 255) against the canon: window and curtain 7.1, armchair 6.0, credenza and record player 7.1, framed pictures 4.3, ceiling 2.8, foreground table and plant 5.3 (all small, re-rendering noise), versus **41.0** in the area the character occupied (expected).
**Implication:** an **empty plate of the canonical room** can be produced reliably, so a character cut-out can be composited into it for animation.

## Remaining limits and open questions
- Each image is a **single flat picture**: depth layers (back/mid/front) are not separated yet.
- Resolution is 941×1672, below the 1080×1920 master (upscaling or larger generation needed).
- Character cut-outs from the plain-grey sheet need a background-removal step (no generation needed).
- Whether a **new angle** of the same room, or **other rooms** in the same style, stay consistent is **untested**.
- The commercial-use terms for ChatGPT-generated images have **not** been verified.
- Whether new, distinct characters can be generated in the same universe is **untested** (and needs the owner's approval to generate).
