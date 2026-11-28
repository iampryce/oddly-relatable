#!/usr/bin/env python3
"""16:9 contact sheet:  python3 sheet169.py stills/x sheet.jpg [cols] [width]"""
import sys, glob, os
from PIL import Image, ImageDraw
d, out = sys.argv[1], sys.argv[2]; C = int(sys.argv[3]) if len(sys.argv) > 3 else 4; w = int(sys.argv[4]) if len(sys.argv) > 4 else 480; h = w * 9 // 16
fs = sorted(glob.glob(d + "/f*.jpg")); ims = [Image.open(f).resize((w, h)) for f in fs]
sh = Image.new("RGB", (w * min(C, len(ims)), (h + 22) * ((len(ims) + C - 1) // C)), "white"); dr = ImageDraw.Draw(sh)
for i, (im, f) in enumerate(zip(ims, fs)):
    x, y = (i % C) * w, (i // C) * (h + 22); sh.paste(im, (x, y + 22)); dr.text((x + 6, y + 5), os.path.basename(f), fill="black")
sh.save(out, quality=90); print(out, len(ims))
