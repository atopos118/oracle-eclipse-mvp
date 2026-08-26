from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
RNG = random.Random(20260719)


def radial_glow(size: tuple[int, int], center: tuple[int, int], radius: int, color: tuple[int, int, int]) -> Image.Image:
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    px = layer.load()
    cx, cy = center
    for y in range(max(0, cy - radius), min(height, cy + radius)):
        for x in range(max(0, cx - radius), min(width, cx + radius)):
            d = math.hypot(x - cx, y - cy) / radius
            if d < 1:
                alpha = int(170 * (1 - d) ** 2)
                px[x, y] = (*color, alpha)
    return layer.filter(ImageFilter.GaussianBlur(radius // 8))


def add_grain(image: Image.Image, strength: int = 11) -> None:
    px = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            r, g, b = px[x, y][:3]
            noise = RNG.randint(-strength, strength)
            px[x, y] = (
                max(0, min(255, r + noise)),
                max(0, min(255, g + noise)),
                max(0, min(255, b + noise)),
            )


def draw_bone_layer(size: tuple[int, int], polygon: list[tuple[int, int]]) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.polygon(polygon, fill=(210, 198, 165, 255), outline=(236, 225, 190, 230), width=5)
    for _ in range(85):
        x = RNG.randint(min(p[0] for p in polygon), max(p[0] for p in polygon))
        y = RNG.randint(min(p[1] for p in polygon), max(p[1] for p in polygon))
        rr = RNG.randint(2, 18)
        shade = RNG.choice([(126, 111, 82, 35), (245, 233, 201, 25), (75, 63, 47, 22)])
        draw.ellipse((x - rr, y - rr, x + rr, y + rr), fill=shade)
    return layer.filter(ImageFilter.GaussianBlur(0.8))


def incisions(draw: ImageDraw.ImageDraw, origin: tuple[int, int], scale: float, count: int) -> None:
    ox, oy = origin
    color = (72, 60, 43, 175)
    for i in range(count):
        x = ox + int((i % 4) * 82 * scale + RNG.randint(-12, 12))
        y = oy + int((i // 4) * 112 * scale + RNG.randint(-10, 10))
        draw.line(
            [(x, y), (x + int(28 * scale), y + int(52 * scale)), (x + int(8 * scale), y + int(91 * scale))],
            fill=color,
            width=max(2, int(5 * scale)),
        )
        if i % 2 == 0:
            draw.line(
                [(x - int(18 * scale), y + int(42 * scale)), (x + int(34 * scale), y + int(35 * scale))],
                fill=color,
                width=max(2, int(4 * scale)),
            )


def hero() -> None:
    size = (2400, 1350)
    image = Image.new("RGB", size, (12, 23, 20))
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 120):
        draw.line((x, 0, x, size[1]), fill=(25, 43, 38), width=1)
    for y in range(0, size[1], 120):
        draw.line((0, y, size[0], y), fill=(25, 43, 38), width=1)
    image = Image.alpha_composite(image.convert("RGBA"), radial_glow(size, (1900, 360), 580, (181, 113, 48)))
    eclipse = Image.new("RGBA", size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(eclipse)
    ed.ellipse((1540, -70, 2260, 650), fill=(222, 161, 72, 255))
    ed.ellipse((1475, -35, 2175, 665), fill=(5, 12, 12, 255))
    eclipse = eclipse.filter(ImageFilter.GaussianBlur(1.5))
    image = Image.alpha_composite(image, eclipse)
    polygon = [(1575, 650), (2210, 585), (2390, 805), (2350, 1320), (1660, 1345), (1460, 1110)]
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.polygon([(x + 35, y + 25) for x, y in polygon], fill=(0, 0, 0, 155))
    image = Image.alpha_composite(image, shadow.filter(ImageFilter.GaussianBlur(35)))
    bone = draw_bone_layer(size, polygon)
    bd = ImageDraw.Draw(bone)
    incisions(bd, (1690, 740), 1.15, 12)
    bd.line([(1700, 680), (1950, 840), (1870, 1140), (2210, 1280)], fill=(92, 78, 57, 110), width=7)
    image = Image.alpha_composite(image, bone)
    draw = ImageDraw.Draw(image)
    draw.rectangle((116, 120, 128, 1100), fill=(156, 48, 37, 220))
    draw.line((155, 1120, 980, 1120), fill=(99, 132, 119, 125), width=2)
    final = image.convert("RGB")
    add_grain(final, 7)
    final.save(ASSETS / "hero-eclipse.png", optimize=True)


def evidence() -> None:
    size = (1200, 1500)
    image = Image.new("RGB", size, (28, 31, 29))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 75):
        draw.line((0, y, size[0], y), fill=(38, 42, 39), width=1)
    polygon = [(235, 170), (850, 105), (1035, 390), (940, 1215), (600, 1400), (185, 1160), (120, 580)]
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.polygon([(x + 24, y + 28) for x, y in polygon], fill=(0, 0, 0, 175))
    image = Image.alpha_composite(image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(28)))
    bone = draw_bone_layer(size, polygon)
    bd = ImageDraw.Draw(bone)
    incisions(bd, (310, 320), 1.35, 20)
    bd.line([(260, 240), (535, 610), (430, 970), (760, 1320)], fill=(78, 66, 49, 125), width=7)
    image = Image.alpha_composite(image, bone)
    d = ImageDraw.Draw(image)
    d.rectangle((865, 1110, 1010, 1130), fill=(159, 50, 39, 235))
    d.rectangle((865, 1155, 1090, 1162), fill=(216, 207, 177, 155))
    final = image.convert("RGB")
    add_grain(final, 8)
    final.save(ASSETS / "evidence-oracle.png", optimize=True)


def mechanism() -> None:
    size = (1800, 1200)
    image = Image.new("RGB", size, (9, 19, 20))
    image = Image.alpha_composite(image.convert("RGBA"), radial_glow(size, (260, 600), 360, (213, 134, 49)))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.polygon([(330, 420), (1310, 535), (1310, 665), (330, 780)], fill=(226, 174, 90, 24))
    draw.polygon([(820, 555), (1310, 590), (1310, 610), (820, 645)], fill=(2, 7, 8, 210))
    draw.polygon([(820, 505), (1310, 560), (1310, 640), (820, 695)], fill=(5, 12, 13, 95))
    draw.ellipse((90, 430, 430, 770), fill=(232, 170, 70, 255), outline=(255, 215, 136, 230), width=5)
    draw.ellipse((735, 515, 875, 655), fill=(37, 49, 47, 255), outline=(112, 132, 124, 220), width=4)
    draw.ellipse((1285, 470, 1545, 730), fill=(49, 103, 109, 255), outline=(120, 174, 166, 220), width=5)
    draw.arc((1320, 505, 1510, 695), 85, 265, fill=(183, 204, 172, 210), width=12)
    draw.line((125, 940, 1640, 940), fill=(86, 112, 105, 110), width=2)
    for x in (260, 805, 1415):
        draw.line((x, 920, x, 960), fill=(171, 62, 45, 210), width=5)
    final = image.convert("RGB")
    add_grain(final, 5)
    final.save(ASSETS / "eclipse-mechanism.png", optimize=True)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    hero()
    evidence()
    mechanism()
    print(f"Generated assets in {ASSETS}")


if __name__ == "__main__":
    main()
