from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageColor, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT_ICO = ROOT / "static" / "local-ci.ico"
OUT_PNG = ROOT / "static" / "local-ci-icon-rendered.png"


def lerp(a: int, b: int, t: float) -> int:
    return int(round(a + (b - a) * t))


def make_linear_gradient(
    size: int,
    c1: tuple[int, int, int, int],
    c2: tuple[int, int, int, int],
    start: tuple[float, float],
    end: tuple[float, float],
) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()

    sx, sy = start
    ex, ey = end
    vx, vy = ex - sx, ey - sy
    vlen2 = vx * vx + vy * vy
    if vlen2 == 0:
        vlen2 = 1.0

    for y in range(size):
        for x in range(size):
            wx, wy = x - sx, y - sy
            t = (wx * vx + wy * vy) / vlen2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            px[x, y] = (
                lerp(c1[0], c2[0], t),
                lerp(c1[1], c2[1], t),
                lerp(c1[2], c2[2], t),
                lerp(c1[3], c2[3], t),
            )

    return img


def scale(n: float, factor: int) -> int:
    return int(round(n * factor))


def main() -> None:
    # Render at 1024 for sharp downsampling to ICO sizes.
    factor = 4
    size = 256 * factor

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    bg1 = ImageColor.getcolor("#0EA5E9", "RGBA")
    bg2 = ImageColor.getcolor("#22C55E", "RGBA")
    bg_grad = make_linear_gradient(
        size,
        bg1,
        bg2,
        (scale(24, factor), scale(24, factor)),
        (scale(232, factor), scale(232, factor)),
    )

    # Main rounded rect fill.
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle(
        [scale(16, factor), scale(16, factor), scale(240, factor), scale(240, factor)],
        radius=scale(56, factor),
        fill=255,
    )
    canvas.paste(bg_grad, (0, 0), mask)

    # Inner subtle stroke.
    draw.rounded_rectangle(
        [scale(24, factor), scale(24, factor), scale(232, factor), scale(232, factor)],
        radius=scale(48, factor),
        outline=(255, 255, 255, 41),
        width=scale(2, factor),
    )

    stroke1 = ImageColor.getcolor("#E2F3FF", "RGBA")
    stroke2 = ImageColor.getcolor("#DCFCE7", "RGBA")
    stroke_grad = make_linear_gradient(
        size,
        stroke1,
        stroke2,
        (scale(56, factor), scale(88, factor)),
        (scale(200, factor), scale(168, factor)),
    )

    # Pipeline connector paths with gradient stroke.
    stroke_mask = Image.new("L", (size, size), 0)
    sdraw = ImageDraw.Draw(stroke_mask)
    width = scale(14, factor)
    sdraw.line([scale(68, factor), scale(90, factor), scale(126, factor), scale(90, factor)], fill=255, width=width)
    sdraw.line([scale(126, factor), scale(90, factor), scale(126, factor), scale(166, factor)], fill=255, width=width)
    sdraw.line([scale(126, factor), scale(166, factor), scale(186, factor), scale(166, factor)], fill=255, width=width)

    # Ensure rounded caps by stamping circles at line ends.
    cap_r = width // 2
    for cx, cy in [
        (scale(68, factor), scale(90, factor)),
        (scale(126, factor), scale(90, factor)),
        (scale(126, factor), scale(166, factor)),
        (scale(186, factor), scale(166, factor)),
    ]:
        sdraw.ellipse([cx - cap_r, cy - cap_r, cx + cap_r, cy + cap_r], fill=255)

    canvas.paste(stroke_grad, (0, 0), stroke_mask)

    # Outer white nodes.
    for cx, cy in [(58, 90), (126, 90), (126, 166), (196, 166)]:
        draw.ellipse(
            [
                scale(cx - 20, factor),
                scale(cy - 20, factor),
                scale(cx + 20, factor),
                scale(cy + 20, factor),
            ],
            fill=(255, 255, 255, 245),
        )

    # Inner colored nodes.
    inner = [
        (58, 90, "#0EA5E9"),
        (126, 90, "#14B8A6"),
        (126, 166, "#22C55E"),
        (196, 166, "#16A34A"),
    ]
    for cx, cy, color in inner:
        draw.ellipse(
            [
                scale(cx - 9, factor),
                scale(cy - 9, factor),
                scale(cx + 9, factor),
                scale(cy + 9, factor),
            ],
            fill=ImageColor.getcolor(color, "RGBA"),
        )

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT_PNG)
    canvas.save(
        OUT_ICO,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {OUT_ICO}")


if __name__ == "__main__":
    main()
