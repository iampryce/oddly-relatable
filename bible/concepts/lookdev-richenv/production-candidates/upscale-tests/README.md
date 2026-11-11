# AP-63 to AP-66: upscaling investigation and correction plan (assessment only)

Owner decisions applied (2026-11-11): **Image 4** (character) conditionally approved as a **working high-resolution source, not a final master**; **Image 5** (room) approved as an **alternative empty plate**, not a resolution upgrade; the canon stays authoritative. Both candidates are preserved untouched (hashes `ca0148b0…` and `ac83bf7f…` re-verified at the end of this work). Everything here is new files only. No generation, installs, paid calls, renderer changes, deletions or commits.

Scripts: `bible/concepts/src/upscale-tests.cjs`, `upscale-compare.cjs`. Raw numbers: `upscale-test-results.json`. Sheets: `compare-head-closeup.png`, `compare-hands.png`, `compare-plate-closeup.png`. Enlarged copies: `char04_2x_*.png` (2048×3072), `room05_2x_*.png` (1882×3344).

## 1. Local upscaling tools found (nothing installed)
| Item | Finding |
|---|---|
| AI upscalers (Real-ESRGAN, Upscayl, waifu2x, SRMD, Video2X, GIMP, Photoshop, Topaz, ImageMagick) | **None installed** |
| Python 3.14 | Present; **only `pip`** installed (no numpy, torch, opencv, onnxruntime, PIL) |
| Model weights (`.onnx`, `.pth`, `.param`) | None usable. The only `.pth` files are path stubs in the separate `youtube-automation` virtual environments (not touched) |
| Node | `sharp` 0.35.5 / libvips 8.18.7 (installed for the renderer): resampling only |
| FFmpeg 9.0.2 | `scale`, `zscale`, `hqx`, `xbr`, `epx`, `super2xsai`, `nlmeans`, `unsharp`; **no `dnn_processing`/libtorch/TensorFlow/OpenVINO** (so no AI super-resolution) |
| Hardware | i7-6600U (2 cores), 7.9 GB RAM, **Intel HD Graphics 520, 1 GB shared, Vulkan 1.3.215 present** (no CUDA). The VPS was not touched |
| Verdict | **No AI upscaling is possible locally today.** Only classical resampling. A portable Vulkan binary (e.g. Real-ESRGAN-ncnn-vulkan) would need a download, which counts as an install and needs your approval; it has no CPU fallback, and an Intel HD 520 with 1 GB shared would run it slowly with small tiles (not benchmarked) |

## 2. Upscaling tests (copies of both candidates)
**Method.** Ground truth: halve each candidate, enlarge back ×2 with each method, compare to the original. Then real ×2 enlargements and a tiling seam test. *Caveat: the sources are themselves soft AI output, so this measures how well each method reconstructs, not how much new detail it can invent (classical methods invent none).*

| Method (×2) | Character PSNR / edge error | Plate PSNR / edge error | Verdict |
|---|---|---|---|
| nearest | 30.4 / 39.0 | 29.0 / 20.8 | blocky |
| bilinear | 29.7 / 28.2 | 28.3 / 16.8 | soft |
| bicubic (sharp's lanczos3/mitchell/cubic/mks all collapse to this when enlarging) | 30.0 / 26.2 | 28.5 / 15.9 | baseline |
| **nohalo** | **34.0 / 25.2** | **30.8 / 16.9** | **best classical** (slow: 0.8 s character, 2.8 s plate) |
| lbb | 33.7 / 26.8 | 30.7 / 17.2 | close second |
| bicubic + unsharp | 29.8 / 29.0 | 28.3 / 16.5 | worse (halos) |
| bicubic + shock filter (my edge sharpener) | 27.8 / 43.0 | no effect | **rejected: damages edges** |

- **What it means at viewing size:** a ×2 nohalo copy of candidate 04 is hard to tell apart from the native image on a 1080×1920 screen (`compare-head-closeup.png`); the plate gains nothing visible (`compare-plate-closeup.png`). **Resampling cannot add real detail.**
- **Real gain already banked:** candidate 04 at native size is far crisper than the current sheet poses on screen (see the first panel versus the second in `compare-head-closeup.png`): about 2.2× the pixels per head. For close-ups it needs no upscaling to beat the sheet; at the renderer's 2.3× zoom it is stretched about 1.2× instead of about 2.6×.
- **Plate:** 941×1672 gives about 1.15× at full frame and about 2.4× at close-up zoom: soft rug and wood texture but acceptable for a flat-character comedy; true close-ups of the room need more native detail.
- **Tiling/seams (plate, 2×3 tiles, 64 px overlap, feather blend):** **seam error 0** with a deterministic local filter. This proves the tiling mechanics only. **An AI upscaler per tile can differ in texture, tone and invented detail across tile borders**, so plan for: overlap of at least 64 to 128 px, feathered blends, one fixed seed/model, a global colour match, and review of the rug pattern, the books (repeating) and the window glass where seams show first.

## 3. Higher-native-resolution generation: research only (no calls, nothing paid)
- **Codex/ChatGPT built-in image tool:** capped near 1024×1536 / 941×1672 in this account (measured, 4 outputs). The 2048 request was ignored.
- **OpenAI `gpt-image-2` API (released 2026-04-21 per third-party docs):** reported to accept sizes up to 3840×2160, roughly $0.40 per 4K high-quality image (aggregator figure). **Paid, not authorised; verify on the official OpenAI page first.**
- **Google Gemini 3 Pro Image / Nano Banana 2:** sources conflict on native 4K versus upscaled; **unverified, needs official docs**. Other vendors (Wan 2.7 Image Pro, Seedream 4, Kling O3) claim 4K; one source warns that "4K" is often "1K plus an upscaler".
- **Risk of any new generation:** it is a fresh sampling, so it can drift from the canon again (hands, skin). Reference-conditioned regeneration at 4K must be re-checked against the canon exactly as the last two were.
- These are web-search summaries (secondary sources), not verified facts.

## 4. Non-destructive correction plan (not yet executed; needs your go-ahead)
**Rules:** the candidate is never edited. Every step writes a new file in a new `corrected/` folder, with a before/after hash register and a pixel-diff proving only masked regions changed.

**Measured colours (mean of interior pixels):**
| Region | Canon | Candidate 04 | Sheet pose 01 |
|---|---|---|---|
| Skin | (252,222,180) | (253,232,205) | (252,228,198) |
| Sweater | (188,76,21) | (212,94,23) | n/m |
| Shoe | (132,86,59) | (157,93,57) | n/m |

1. **Masks:** colour-class masks for skin, sweater, shoes, eye whites, outline and background (colour distance + connected components, soft 1 to 2 px edges), saved as PNGs and reviewed visually.
2. **Skin tone:** per-channel gain on the **skin mask only**, about (1.00, 0.957, 0.878) so the mean lands on the canon's (252,222,180); eye whites, outlines, sweater and background untouched. Check ΔE against the canon and the preserved edges.
3. **Sweater and shoes (needs your decision):** the candidate sweater is about 12% brighter and the shoes paler/redder than the canon's painted-light values. You listed only skin and hands, so I will not change them unless you ask.
4. **Hands, the one design correction.** Important finding in `compare-hands.png`: the **canon's hand is a small rounded black mitt with two or three rounded finger bumps** (seen in the canon and in sheet pose 02). The **sheet's own neutral pose 01 already has the same curled-hook hands as candidate 04**, so the sheet drifted too; candidate 04 inherited it. Options:
   - **A. Transplant** the canon/pose 02 mitt: it exists only at about 40 px, so it would look soft next to a 1024-px-class figure. Not recommended.
   - **B. Hand-trace a vector mitt** from the canon's geometry, rasterised at native resolution with the candidate's outline weight, placed on the wrists. It is drawn, not generated, but it is a redraw, so **needs your explicit approval**. *Recommended.*
   - **C. A new reference-conditioned Codex image of hands only:** needs approval and carries drift risk. Not recommended.
   **Question for you:** is the target hand the canon's mitt with finger bumps (as in the phone-holding hand), or a plain rounded mitt with no fingers?
5. **QA:** diff against the candidate (only skin and hand regions may change), side-by-side with the canon at 1080×1920 viewing size and at close-up, outline and head/body proportion overlay, and the same-universe checklist.

## 5. Recommended next step (for your approval)
1. Execute the correction plan (items 1, 2 and 4B) to produce `corrected/character-master_v1.png` (new files only), and re-cut the neutral pose with the existing extractor.
2. Resolution: **do not spend on a new generation yet.** Use candidate 04 at native size (it already beats the sheet by about 2.2×) and the plate at ×1 to ×1.15. Approve one controlled test of a **portable Real-ESRGAN-ncnn-vulkan** binary (download with checksum into a quarantined work folder, copies only) to see whether AI upscaling of the **plate** helps without altering the canon; keep the flat character on classical nohalo or the native image.
3. If that fails, decide whether a paid higher-resolution route is worth it (needs a separate approval and official-docs verification first).
