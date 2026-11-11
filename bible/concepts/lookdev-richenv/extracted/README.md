# AP-58: six poses of Canonical Character 01, extracted (transparent PNG)

Source: `../lookdev-character-test-02.png` (SHA-256 `36e8cef3f3149786eb82cf00aa03df9c29d1a5f8ffad9efbbfbacd5928f3c137`, **unchanged, read-only use**). Script: `bible/concepts/src/extract-poses.cjs` (installed `sharp`, no new dependencies). **No generation, no redrawing**: pixels are only made transparent or cropped.

| File | Size | Feet anchor (x,y in file) |
|---|---|---|
| `canonical-character-01_01-neutral.png` | 272×572 | 135, 561 |
| `canonical-character-01_02-worried-phone.png` | 270×571 | 102, 560 |
| `canonical-character-01_03-shocked-frozen.png` | 274×596 | 139, 585 |
| `canonical-character-01_04-laughing.png` | 299×580 | 175, 569 |
| `canonical-character-01_05-pleading.png` | 273×569 | 130, 558 |
| `canonical-character-01_06-deadpan-arms-crossed.png` | 271×591 | 134, 580 |

`manifest.json` holds hashes, boxes and anchors. `contact-sheet-extracted-poses.png` shows all six over a checkerboard, warm brown and dark teal: clean on all three.

## Method
Flat grey background (209,209,209) removed by border flood-fill; enclosed pockets (≥120 px) and small enclosed grey slivers (≤800 px, ring test so eye whites are kept) made transparent; a 4 px edge band converts the source's bright anti-aliasing "ringing" to transparent and dark blends to partial-alpha outline; connected components assigned to the 3×2 grid; 10 px padding.

## Defect history (kept for evidence in `_v1…_v4-*-defect/`)
v1 white halo (ringing) · v2 holes in eye whites (global threshold) · v3 grey slivers between arm and torso · v4 marks inside the eyes (sliver rule too broad). The final version was checked at zoom: eye whites intact, no halo, enclosed gaps transparent.

## Known limits
Poses are separate drawings, not rigs: minor drift between them (hand style, shocked pose sweater slightly more saturated). Sheet resolution is low (about 270 px wide) and softens when zoomed.
