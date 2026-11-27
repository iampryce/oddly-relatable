"""The five cast style presets (owner request 2026-11-26: "options of style, like 3D, 2D stick man, up to 5 types").

Each episode picks ONE of them (episodes.style) and every character master of that episode is drawn in it, so the cast
matches. Settings > Cast styles keeps an editable copy of each text block and its optional style reference images; the
texts below are only the defaults. No brand or studio names appear in any prompt.

"stick" is the house style: its text block and reference default to Settings > Studio style (stick_style.py, the
owner's TRUE STICK MAN prompt) unless the owner writes a different block for the preset itself.
"""

STYLE_IDS = ("stick", "flat2d", "3d", "anime", "clay")

_POSE = ("**Pose:** Standing upright, neutral expression, full body visible from head to feet, facing the viewer at a "
         "slight three-quarter angle, arms relaxed.\n\n**Background:** Plain white background.\n\n"
         "One character only. An ORIGINAL character: do not copy any real person, actor or existing character. "
         "No text, no watermark, no logo.")

FLAT_2D = """Create an original 2D cartoon character for an animation series, in a flat 2D cartoon style.

**Character design:**
- A big rounded head.
- Large white eyes with black pupils.
- Clearly defined eyebrows and a small mouth.
- Absolutely no nose.
- Thin black stick arms and legs.
- Black hook-shaped hands, with no realistic fingers.
- Rounded shoes.
- Simple clothes in flat colours.

**Visual style:**
- Thick, bold, smooth black outlines.
- Clean, polished 2D cartoon illustration.
- Subtle cel shading only.

""" + _POSE

ANIMATED_3D = """Create an original stylised 3D animated character for an animated series.

**Character design:**
- Slightly exaggerated cartoon proportions: a larger head and large expressive eyes.
- Smooth, rounded, appealing shapes and a simple, readable silhouette.
- Simple clothes with clean materials.

**Visual style:**
- A polished, stylised 3D animated-film look, not photorealistic.
- Soft studio lighting with gentle shadows.
- Clean, smooth surfaces and soft colours.

""" + _POSE

ANIME = """Create an original character for an animated series in a clean 2D anime style.

**Character design:**
- Large expressive eyes with simple highlights.
- A small, simple nose and mouth.
- Hair drawn as clean solid shapes.
- Simple clothes in flat colours.

**Visual style:**
- Crisp, thin, even line art.
- Flat cel shading with one shadow tone.
- Clean, bright 2D anime illustration.

""" + _POSE

CLAY = """Create an original character that looks like a stop-motion claymation figure for an animated series.

**Character design:**
- A handmade modelling-clay figure with rounded, chunky forms.
- Simple glossy bead eyes and a simple sculpted mouth.
- Simple clothes sculpted from clay or felt.

**Visual style:**
- Matte clay surfaces with faint fingerprints and tool marks.
- Soft studio lighting with soft shadows, like a stop-motion set.
- Warm, slightly muted colours.

""" + _POSE

DEFAULT_STYLES: dict[str, dict] = {
    # style_prompt "" = use Settings > Studio style (the owner's TRUE STICK MAN prompt); references [] = use its reference
    "stick": {"label": "True stick man", "style_prompt": "", "references": [],
              "note": "The house style: the owner's TRUE STICK MAN prompt from Settings > Studio style."},
    "flat2d": {"label": "Flat 2D cartoon", "style_prompt": FLAT_2D, "references": [],
               "note": "Big rounded head, large white eyes, no nose, bold outlines, stick limbs, hook hands, cel shading."},
    "3d": {"label": "3D animated", "style_prompt": ANIMATED_3D, "references": [],
           "note": "A polished, stylised 3D animated-film look."},
    "anime": {"label": "Anime", "style_prompt": ANIME, "references": [],
              "note": "Clean 2D anime: thin line art, flat cel shading."},
    "clay": {"label": "Claymation", "style_prompt": CLAY, "references": [],
             "note": "Stop-motion clay figures."},
}
