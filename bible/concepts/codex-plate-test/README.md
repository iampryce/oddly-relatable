# Codex background-plate test (experimental, not an approved asset)

**Date:** 2026-11-11 · **Status:** experiment for the V3 decision (environment production route). **Not authoritative; not approved for any episode.**

| Item | Value |
|---|---|
| Delegating agent | Claude Code |
| Executing agent | Codex (`codex-cli 0.167.0`, ChatGPT login) |
| Tool | Codex's built-in image generation. The model is not exposed and was not assumed. |
| Method | `codex exec --sandbox workspace-write -C <scratch dir> -i input-layout-reference-empty.png -o … --skip-git-repo-check -`, prompt on stdin |
| Run time | About 78 seconds, exit code 0, exactly one image requested and made |
| Scratch directory | `…\scratchpad\codex-work` (outside the repository) |
| **Original generated file (preserved, untouched)** | `C:\Users\PC\.codex\generated_images\01a1c903-1f99-76a2-99a3-7f36660d55be\exec-56ddb1ce-504b-4224-881e-bb68bdcdaffe.png` |
| Copy made by Codex in the scratch directory | `plate-B-livingroom.png` (byte-identical to the original, checked by SHA-256) |
| Copy placed here | `codex-plate-B-livingroom.png` (1672×941 PNG) |
| Cost | No API call. It used the ChatGPT image allowance, and the remaining quota is unknown. |

## Files
| File | What |
|---|---|
| `input-layout-reference-empty.png` | Character-free layout reference, drawn locally by Claude Code, given to Codex for composition only |
| `codex-plate-B-livingroom.png` | The plate Codex generated |
| `placeholder-flat-on-codex-plate.png` (moved to `../technical-tests/codex-plate-test/`) | The neutral placeholder figure (flat vector sprite, "Level 2") composited onto the plate locally by Claude Code, to judge integration. (An earlier version with the retired Femi is archived in `../_archive-retired-femi/codex-plate-test/`.) |
| `codex-final-message.md` | Codex's final message, verbatim |

## Prompt summary
Produce one 16:9 empty living-room plate, same layout and camera as the reference, clean bright modern 2.5D illustration, soft dimensional lighting, muted palette (cream, honey wood, teal and tangerine accents), not photorealistic, uncluttered centre-left floor, **no people, characters, animals, text, logos or watermarks, and do not imitate any specific artist, studio, channel or franchise**; generate exactly one image, no retries or variants.

## Findings
- **Followed the brief:** no people, text or logos appeared; layout, palette and props matched; the plate looks clean and usable as a background.
- **Much richer than the procedural vector room:** soft light patches from the window, believable materials and depth.
- **Resolution:** 1672×941, below the 1920×1080 episode master and well below the 3840×2160 oversize the camera-move plan wants. It would need upscaling or a re-generation at a larger size, which is not controllable as far as I can tell.
- **Style mismatch with the flat character:** the soft painted look makes the hard-outlined flat placeholder figure read as pasted on. A richer plate raises the bar for the character (more shading) or requires the plate to be flattened and posterised to match.
- **Baked lighting, single layer:** no separate foreground or depth layers, so parallax would need extra work (for example separate generations or manual cut-outs).
- **Unproven:** consistency of the same room from other angles or in other lighting; repeatability; how many images the quota allows.
- **Rights:** the commercial-use terms for ChatGPT-generated images have **not** been verified here; check them before any use in a published episode.
