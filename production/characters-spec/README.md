# Characters drawn from a spec (prototype)

Owner decision 2026-11-20 ("B: drawn from spec"). Prototype only: nothing in the studio uses these yet. `style_version`
and framing are untouched.

A character is a small JSON file. `production/animation/spec_rig.mjs` draws it into the same rig folder that
`rig_extract.py` produces from approved art (`rig.json`, `head-<expression>.png`, `mouth-<expression>.png`,
`torso.png`, `shoe-l.png`, `shoe-r.png`). The acting renderer (`render-acting.mjs` with `animator.mjs`) animates it
unchanged. Limbs, black blob hands, overlay lip-sync mouths (Rhubarb A–H, X) and blinks are drawn live, as for the
extracted characters. No image model is involved. The same spec always draws the same character, and the source is drawn
at 1600 px figure height, so close-ups stay sharp.

```
node production/animation/spec_rig.mjs production/characters-spec/priya.json <out_dir>
```

## Spec format

All lengths are fractions, so a spec never contains pixels. Body lengths are fractions of the figure height (feet to the top of the head), and face lengths are fractions of the head. Every field is optional except `id`. A field that is left out takes the house default shown here.

```jsonc
{
  "id": "priya",                       // rig folder / cast key
  "name": "Priya",
  "about": "Early 30s, fast-talking office manager ...",   // for people; not drawn

  "proportions": {
    "head": 0.30,          // head height / figure height
    "head_aspect": 1.06,   // head height / head width (< 1 = wider head)
    "torso": 0.30,         // torso length / figure height
    "shoulder": 0.15,      // half shoulder width / figure height
    "hip": 0.105           // half hip width / figure height
  },
  "line":  {"weight": 0.0125},         // outline and limb weight / figure height
  "skin":  "#ffffff",
  "hair":  {"shape": "short_crop | high_bun | bald_tufts", "color": "#26181a"},
  "torso": {"garment": {"type": "none | polo | blazer | cardigan", "color": "#8e3b2f"}},

  "face": {                            // fractions of the head
    "eye_w": 0.095, "eye_h": 0.2,      // eye ellipse
    "spacing": 0.36,                   // eye centre distance / head width
    "eye_y": 0.53,                     // from the top of the head
    "brow_w": 0.21, "brow_y": 0.4, "brow_weight": 2.1,   // brow weight is a multiple of the line weight
    "mouth_w": 0.2, "mouth_y": 0.76
  },

  // per-character overrides of the house expressions (merged per part: brow, eyes, mouth)
  "expressions": {
    "annoyed": {"brow": {"angle": 18, "tilt": true}, "mouth": {"offset": 0.05}}
  }
}
```

### Expressions

There are six house expressions: `neutral`, `deadpan`, `annoyed`, `shocked`, `laughing` and `worried`. Each one is built from three parts, and a spec overrides only the values it names:

| Part | Values |
|---|---|
| `brow` | `angle` (degrees, + = inner ends down / cross), `raise` (fraction of the head, + = up), `tilt` (one brow up) |
| `eyes` | `open` (height scale), `size` (scale), `squint` (lid flattens the top, 0–1), `look` (sideways glance), `smile` (closed happy arcs) |
| `mouth` | `type` `line` / `o` / `d`, `curve` (+ smile, − frown), `width`, `height`, `offset` (sideways), `wobble` |

To add a new expression, give it a name under `expressions` with all three parts. The renderer can use any face name that the rig contains.

### Libraries

Hair shapes and garments are short drawing functions in `spec_rig.mjs` (`HAIR`, `GARMENT`). A new look, such as a cap,
glasses, a ponytail or a hoodie, is one new function. Every character can then use it by name.

## The three prototype characters

| | Dez | Priya | Gus |
|---|---|---|---|
| Who | Late 20s, dry and literal, the straight man | Early 30s, office manager, exasperated | Late 50s, caretaker, stubborn |
| Silhouette | Narrow, short crop | High bun, sharp blazer | Wide head, broad, bald with tufts |
| Signature | Deadpan half-lidded eyes | One-brow-up annoyed, side mouth | Heavy brows, big laugh |

## Preview (`preview/`)

- `closeups.png`: the 3 characters × 6 expressions at close-up zoom (1.1).
- `visemes.png`: overlay lip-sync mouths X, A–H and blink on four faces. Frown and smile shapes stay on the closed shapes.
- `spec-scene-10s.mp4` and `scene-stills.png`: a 10 s scene through the real `render-acting.mjs` with a POV banner,
  no bubbles or captions, Rhubarb cues and placeholder voices (macOS `say`), on the living-room plate. Shots are wide, medium and close.
- `compare.png`: the close-ups beside the owner's reference stills (slots until the stills are added).
