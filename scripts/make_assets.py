# scripts/make_assets.py
"""Build logo.png, logo_white.png and a multi-size icon.ico from assets/logo_source.webp.

Needs Pillow:  pip install Pillow
"""
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "logo_source.webp"

img = Image.open(SRC).convert("RGB")
# crop to the artwork (everything that is not near-white) with padding, then make it square
bg = Image.new("RGB", img.size, (255, 255, 255))
diff = ImageChops.difference(img, bg).convert("L").point(lambda v: 255 if v > 18 else 0)
box = diff.getbbox()
pad = int(max(box[2] - box[0], box[3] - box[1]) * 0.08)
box = (max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, img.width), min(box[3] + pad, img.height))
art = img.crop(box)
side = max(art.size)
square = Image.new("RGB", (side, side), (255, 255, 255))
square.paste(art, ((side - art.width) // 2, (side - art.height) // 2))
square = square.resize((512, 512), Image.LANCZOS)
square.save(ROOT / "assets" / "logo.png")

# white-on-transparent version for the dark UI: alpha = darkness of the artwork
gray = square.convert("L")
alpha = gray.point(lambda v: max(0, min(255, int((255 - v) * 1.15))))
white = Image.new("RGBA", square.size, (255, 255, 255, 0))
white.putalpha(alpha)
white.save(ROOT / "assets" / "logo_white.png")

square.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("assets written")
