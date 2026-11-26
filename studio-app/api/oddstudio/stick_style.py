"""The studio's stick man master prompt (owner, 2026-11-25): the style block every new character master is drawn
with. Settings > Studio style keeps an editable copy; this text is only the default. The per-character lines (name, one
accessory, expression) are added after it by stick_pipeline.master_prompt."""

STICK_MAN_MASTER_PROMPT = """Create an original, expressive 2D stick man character for an animation series.

The character must be a TRUE STICK MAN.

**Character design:**
- A simple circular white head.
- Two large expressive white eyes with black pupils.
- Simple black eyebrows and a small expressive mouth.
- Absolutely no nose.
- A thin black line for the neck and torso.
- Thin black line arms and legs.
- Simple curved line hands, with no realistic fingers.
- Simple line feet.
- No solid human torso, no muscles and no realistic anatomy.

**Visual style:**
- Bold, thick, smooth black outlines.
- Clean, polished 2D cartoon illustration.
- Expressive facial animation.
- Minimalist stick-figure anatomy.
- Smooth, consistent line thickness.
- Subtle shading only where appropriate.

**Pose:** Standing upright, full body visible, facing the viewer at a slight three-quarter angle, arms relaxed.

**Background:** Plain white background.

**Important:** The character must remain recognisably a stick man. Its body, arms and legs must be constructed
from simple lines. Do not turn it into a normal cartoon human, mascot, person with a shirt, or character with a
solid body.

High-quality professional 2D animation character design. No text, no watermark."""
