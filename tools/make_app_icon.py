#!/usr/bin/env python3
"""Generate the Echolyra app icon (1024×1024) into the Xcode asset catalog.

Design: a gold 'E' (echo) whose three bars are crossed by cyan concentric echo arcs,
on a deep midnight gradient. Reproducible with Pillow + numpy.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "ios/Echolyra/Assets.xcassets/AppIcon.appiconset"
S = 1024
SS = 4                     # supersample factor
W = S * SS

BG_TOP = np.array([24, 38, 56], dtype=float)
BG_BOTTOM = np.array([7, 11, 18], dtype=float)
GOLD = (230, 181, 92)
GOLD_LIGHT = (250, 219, 155)
CYAN = (86, 212, 225)
TEAL = (46, 158, 176)


def gradient_background() -> Image.Image:
    y = np.linspace(0, 1, W)[:, None]
    base = BG_TOP[None, :] * (1 - y) + BG_BOTTOM[None, :] * y
    img = np.repeat(base[:, None, :], W, axis=1)
    # soft radial glow behind the mark
    yy, xx = np.mgrid[0:W, 0:W]
    cx, cy = W * 0.42, W * 0.46
    radial = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (W * 0.34) ** 2))
    glow = np.array([18, 74, 86], dtype=float)
    img = img + radial[..., None] * glow * 0.55
    # vignette
    dist = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - W / 2) / (W / 2)) ** 2)
    img *= np.clip(1.12 - 0.30 * dist ** 2, 0.55, 1.05)[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def layer() -> Image.Image:
    return Image.new("RGBA", (W, W), (0, 0, 0, 0))


def rounded_bar(size: tuple[int, int], radius: int, color: tuple) -> Image.Image:
    img = layer()
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, size[0], size[1]), radius=radius, fill=color + (255,))
    return img


def glow(img: Image.Image, radius: float, alpha: float) -> Image.Image:
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    a = blurred.split()[3].point(lambda v: int(v * alpha))
    blurred.putalpha(a)
    return blurred


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    canvas = gradient_background().convert("RGBA")

    # --- background echo arcs (cyan, concentric, opening right)
    arcs = layer()
    d = ImageDraw.Draw(arcs)
    cx, cy = int(W * 0.46), int(W * 0.52)
    for i, r in enumerate((int(W * 0.28), int(W * 0.38), int(W * 0.48))):
        width = int(W * (0.026 - i * 0.004))
        color = CYAN if i == 0 else TEAL
        d.arc((cx - r, cy - r, cx + r, cy + r), start=-62, end=62,
              fill=color + (int(255 - i * 45),), width=width)
    canvas.alpha_composite(glow(arcs, W * 0.026, 0.85))
    canvas.alpha_composite(arcs)

    # --- the 'E' mark: three bars + spine, gold
    mark = layer()
    md = ImageDraw.Draw(mark)
    bar_h = int(W * 0.105)
    radius = bar_h // 2
    spine_x = int(W * 0.235)
    spine_w = int(W * 0.085)
    top = int(W * 0.265)
    gap = int(W * 0.115)
    lengths = (int(W * 0.36), int(W * 0.26), int(W * 0.36))
    # subtle drop shadow
    shadow = layer()
    sd = ImageDraw.Draw(shadow)
    for i, ln in enumerate(lengths):
        y = top + i * (bar_h + gap)
        sd.rounded_rectangle((spine_x + W * 0.012, y + W * 0.012, spine_x + ln + W * 0.012,
                              y + bar_h + W * 0.012), radius=radius, fill=(0, 0, 0, 150))
    canvas.alpha_composite(glow(shadow, W * 0.022, 0.75))
    # spine
    bottom = top + 3 * bar_h + 2 * gap
    md.rounded_rectangle((spine_x, top, spine_x + spine_w, bottom), radius=spine_w // 2,
                         fill=GOLD_LIGHT + (255,))
    for i, ln in enumerate(lengths):
        y = top + i * (bar_h + gap)
        md.rounded_rectangle((spine_x, y, spine_x + ln, y + bar_h), radius=radius,
                             fill=GOLD + (255,))
    canvas.alpha_composite(glow(mark, W * 0.020, 0.45))
    canvas.alpha_composite(mark)

    # --- fine highlights along the bars
    hi = layer()
    hd = ImageDraw.Draw(hi)
    for i, ln in enumerate(lengths):
        y = top + i * (bar_h + gap)
        hd.rounded_rectangle((spine_x + int(W * 0.03), y + int(W * 0.012),
                              spine_x + ln - int(W * 0.03), y + int(W * 0.022)),
                             radius=int(bar_h * 0.10), fill=(255, 246, 224, 130))
    canvas.alpha_composite(hi)

    icon = canvas.convert("RGB").resize((S, S), Image.LANCZOS)
    icon.save(OUT / "AppIcon-1024.png")
    (OUT / "Contents.json").write_text('''{
  "images" : [
    {
      "filename" : "AppIcon-1024.png",
      "idiom" : "universal",
      "platform" : "ios",
      "size" : "1024x1024"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
''')
    print("wrote", OUT / "AppIcon-1024.png")


if __name__ == "__main__":
    main()
