#!/usr/bin/env python3
"""Generate a deterministic APNG demo for StrawPot.

Usage:
    python scripts/generate_demo_apng.py [--output docs/demo.apng]
    python scripts/generate_demo_apng.py --task "Add dark mode"
"""

import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# --- Layout ---
WIDTH = 1280
HEIGHT = 720
BG = (10, 10, 15)  # matches --color-bg: #0a0a0f
SURFACE = (18, 18, 26)  # --color-bg-surface: #12121a
BORDER = (42, 42, 58)  # --color-border: #2a2a3a
TEXT = (232, 232, 237)  # --color-text: #e8e8ed
MUTED = (136, 136, 160)  # --color-text-muted: #8888a0
STRAW = (232, 185, 49)  # --color-straw: #e8b931
GREEN = (74, 222, 128)  # --color-green: #4ade80

# --- Fonts ---
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


FONT_XL = _load_font(48)
FONT_LG = _load_font(32)
FONT_MD = _load_font(22)
FONT_SM = _load_font(18)
FONT_XS = _load_font(14)


def _new_frame() -> Image.Image:
    return Image.new("RGBA", (WIDTH, HEIGHT), BG)


def _center_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    return (WIDTH - tw) // 2


def _draw_card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int):
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=12,
                           fill=SURFACE, outline=BORDER)


# --- Frames ---

def frame_hook() -> Image.Image:
    """Frame 1: Hook — the promise."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)
    lines = [
        ("One task.", FONT_XL, TEXT),
        ("Six AI agents.", FONT_XL, TEXT),
        ("Zero coordination.", FONT_XL, STRAW),
    ]
    total_h = sum(draw.textbbox((0, 0), t, font=f)[3] + 16 for t, f, _ in lines)
    y = (HEIGHT - total_h) // 2
    for text, font, color in lines:
        x = _center_x(draw, text, font)
        draw.text((x, y), text, fill=color, font=font)
        y += draw.textbbox((0, 0), text, font=font)[3] + 16
    return img


def frame_input(task: str) -> Image.Image:
    """Frame 2: Input — what the user typed."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)
    label = "Input:"
    lx = _center_x(draw, label, FONT_MD)
    ly = HEIGHT // 2 - 60
    draw.text((lx, ly), label, fill=MUTED, font=FONT_MD)
    quoted = f'"{task}"'
    qx = _center_x(draw, quoted, FONT_LG)
    draw.text((qx, ly + 40), quoted, fill=TEXT, font=FONT_LG)
    return img


def frame_execution() -> Image.Image:
    """Frame 3: Execution — fast, barely readable."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)
    roles = [
        ("CEO", "plan"),
        ("PM", "spec"),
        ("Engineer", "tasks"),
        ("Tester", "tests"),
        ("Reviewer", "approve"),
    ]
    total_h = len(roles) * 36
    y = (HEIGHT - total_h) // 2
    for role, action in roles:
        line = f"{role} → {action}"
        x = _center_x(draw, line, FONT_MD)
        draw.text((x, y), role, fill=STRAW, font=FONT_MD)
        arrow = f" → {action}"
        rx = x + draw.textbbox((0, 0), role, font=FONT_MD)[2]
        draw.text((rx, y), arrow, fill=MUTED, font=FONT_MD)
        y += 36
    return img


def frame_output() -> Image.Image:
    """Frame 4: Output — the artifacts. This is the money shot."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)

    card_w = 340
    card_h = 240
    gap = 30
    total_w = card_w * 3 + gap * 2
    sx = (WIDTH - total_w) // 2
    cy = (HEIGHT - card_h) // 2

    # Card 1: Launch Plan
    _draw_card(draw, sx, cy, card_w, card_h)
    draw.text((sx + 20, cy + 20), "Launch Plan", fill=TEXT, font=FONT_LG)
    plan_lines = [
        "Target: product engineers",
        "Channel: GitHub + X",
        "Timeline: 2 days",
    ]
    py = cy + 70
    for line in plan_lines:
        draw.text((sx + 20, py), f"• {line}", fill=MUTED, font=FONT_SM)
        py += 28

    # Card 2: X Post
    cx2 = sx + card_w + gap
    _draw_card(draw, cx2, cy, card_w, card_h)
    draw.text((cx2 + 20, cy + 20), "X Post", fill=TEXT, font=FONT_LG)
    draw.text((cx2 + 20, cy + 70), '"Dark mode shipped.', fill=STRAW, font=FONT_SM)
    draw.text((cx2 + 20, cy + 98), ' Built with AI agents."', fill=STRAW, font=FONT_SM)
    draw.text((cx2 + 20, cy + 140), "On-brand copy,", fill=MUTED, font=FONT_SM)
    draw.text((cx2 + 20, cy + 168), "ready to publish.", fill=MUTED, font=FONT_SM)

    # Card 3: Engineering Tasks
    cx3 = cx2 + card_w + gap
    _draw_card(draw, cx3, cy, card_w, card_h)
    draw.text((cx3 + 20, cy + 20), "Tasks", fill=TEXT, font=FONT_LG)
    tasks = [
        "update UI theme",
        "add toggle",
        "test contrast",
    ]
    ty = cy + 70
    for t in tasks:
        draw.text((cx3 + 20, ty), f"☐ {t}", fill=MUTED, font=FONT_SM)
        ty += 28

    return img


def frame_punch() -> Image.Image:
    """Frame 5: Punch — the close."""
    img = _new_frame()
    draw = ImageDraw.Draw(img)
    check = "✓"
    line = "Full launch package generated"
    cx = _center_x(draw, f"{check} {line}", FONT_LG)
    cy = HEIGHT // 2 - 50
    draw.text((cx, cy), check, fill=GREEN, font=FONT_LG)
    cw = draw.textbbox((0, 0), f"{check} ", font=FONT_LG)[2]
    draw.text((cx + cw, cy), line, fill=TEXT, font=FONT_LG)

    sub = "Replaces PM, marketing, and ops for this task."
    sx = _center_x(draw, sub, FONT_MD)
    draw.text((sx, cy + 50), sub, fill=MUTED, font=FONT_MD)
    return img


def generate(task: str, output: Path):
    frames = [
        (frame_hook(), 1200),
        (frame_input(task), 1000),
        (frame_execution(), 1000),
        (frame_output(), 3300),
        (frame_punch(), 1500),
    ]

    imgs = [f for f, _ in frames]
    durations = [d for _, d in frames]

    imgs[0].save(
        str(output),
        save_all=True,
        append_images=imgs[1:],
        duration=durations,
        loop=0,
    )
    print(f"Generated {output} ({len(frames)} frames, {sum(durations)}ms)")


def main():
    parser = argparse.ArgumentParser(description="Generate StrawPot demo APNG")
    parser.add_argument("--task", default="Add dark mode to the app",
                        help="Demo task input")
    parser.add_argument("--output", default="docs/demo.apng",
                        help="Output file path")
    args = parser.parse_args()
    generate(args.task, Path(args.output))


if __name__ == "__main__":
    main()
