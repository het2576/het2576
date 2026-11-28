"""Shared design system for the profile tiles.

Every tile is a standalone SVG. Text is converted to vector outlines
(shaped with HarfBuzz, drawn from Schibsted Grotesk), so the typography
renders identically on github.com, the mobile app and every OS, with no
font loading and nothing for GitHub's image proxy to block.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).parent / "fonts"

# Every row of the bento grid is 840 units wide. Tiles carry their own
# share of the gutter as transparent padding, so tiles placed edge to edge
# in the README line up with a 12-unit gap. The vertical padding is smaller
# because the browser adds a few pixels of line space under inline images.
ROW_W = 840
PAD_X = 6
PAD_TOP = 3
PAD_BOTTOM = 2
RADIUS = 14

# The palette follows GitHub's own canvases so tiles feel native in both
# themes. Grey does the structure; one orange ramp marks intensity wherever
# it appears (attention weights, contributions, language share).
THEMES = {
    "dark": {
        "page": "#0d1117",
        "tile": "#151b23",
        "line": "#262d37",
        "ink": "#f0f6fc",
        "text": "#d1d7e0",
        "muted": "#8b949e",
        "faint": "#3a424d",
        "chip": "#1a2129",
        "cell": "#f0f6fc",
        # the one accent: an orange intensity ramp, empty -> most
        "ramp": ["#21282f", "#5c2d0e", "#a24a14", "#e8752d", "#ffb070"],
    },
    "light": {
        "page": "#ffffff",
        "tile": "#f6f8fa",
        "line": "#d8dee4",
        "ink": "#1f2328",
        "text": "#31383f",
        "muted": "#59636e",
        "faint": "#c9d1d9",
        "chip": "#ffffff",
        "cell": "#1f2328",
        "ramp": ["#e6eaee", "#ffd8b5", "#fb9a52", "#e16f24", "#a94400"],
    },
}


def mix(stops: list[str], t: float) -> str:
    """Colour at position t (0..1) along evenly spaced hex stops."""
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    f = t - i
    a = [int(stops[i][k:k + 2], 16) for k in (1, 3, 5)]
    b = [int(stops[i + 1][k:k + 2], 16) for k in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


class Face:
    """One static weight of the typeface: shaping plus glyph outlines."""

    def __init__(self, weight: int):
        self.weight = weight
        tt = TTFont(FONT_DIR / f"SchibstedGrotesk-{weight}.woff2")
        tt.flavor = None
        buf = io.BytesIO()
        tt.save(buf)
        self.tt = tt
        self.upem = tt["head"].unitsPerEm
        self.glyphs = tt.getGlyphSet()
        self.order = tt.getGlyphOrder()
        self.cap = tt["OS/2"].sCapHeight
        self.hb_font = hb.Font(hb.Face(buf.getvalue()))
        self._paths: dict[int, str] = {}

    def shape(self, text: str, features: dict | None = None):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        feats = {"kern": True, "liga": True}
        if features:
            feats.update(features)
        hb.shape(self.hb_font, buf, feats)
        return list(zip(buf.glyph_infos, buf.glyph_positions))

    def path(self, gid: int) -> str:
        if gid not in self._paths:
            pen = SVGPathPen(self.glyphs)
            self.glyphs[self.order[gid]].draw(pen)
            self._paths[gid] = pen.getCommands()
        return self._paths[gid]


@lru_cache(maxsize=None)
def face(weight: int) -> Face:
    return Face(weight)


def measure(text: str, size: float, weight: int = 400, tracking: float = 0.0,
            features: dict | None = None) -> float:
    f = face(weight)
    run = f.shape(text, features)
    units = sum(p.x_advance for _, p in run) + tracking * f.upem * max(len(run) - 1, 0)
    return units * size / f.upem


def fit_size(lines: list[str], max_w: float, size: float, weight: int,
             tracking: float = 0.0, min_size: float = 24) -> float:
    while size > min_size and max(measure(l, size, weight, tracking) for l in lines) > max_w:
        size -= 0.5
    return size


def num(n: float) -> str:
    """Compact number formatting for SVG attributes."""
    s = f"{n:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Canvas:
    """A single tile SVG. Coordinates passed to drawing calls are relative
    to the tile's inner box (the padding is applied automatically)."""

    def __init__(self, width: float, inner_h: float, theme: str, title: str):
        self.width = width
        self.inner_w = width - 2 * PAD_X
        self.inner_h = inner_h
        self.height = inner_h + PAD_TOP + PAD_BOTTOM
        self.theme = theme
        self.c = THEMES[theme]
        self.title = title
        self.defs: dict[str, str] = {}
        self.style: list[str] = []
        self.parts: list[str] = []

    # colours -------------------------------------------------------------
    def col(self, name: str) -> str:
        return self.c.get(name, name)

    # primitives ----------------------------------------------------------
    def add(self, svg: str) -> None:
        self.parts.append(svg)

    def frame(self) -> None:
        self.add(
            f'<rect x="{num(PAD_X + .5)}" y="{num(PAD_TOP + .5)}" '
            f'width="{num(self.inner_w - 1)}" height="{num(self.inner_h - 1)}" '
            f'rx="{RADIUS}" fill="{self.col("tile")}" stroke="{self.col("line")}"/>'
        )

    def text(self, s: str, x: float, y: float, size: float, weight: int = 400,
             color: str = "text", tracking: float = 0.0, anchor: str = "start",
             features: dict | None = None, opacity: float | None = None,
             extra: str = "") -> float:
        """Draw text as outlines with its baseline at y. Returns the width."""
        if not s:
            return 0.0
        f = face(weight)
        run = f.shape(s, features)
        k = size / f.upem
        track = tracking * f.upem
        total = sum(p.x_advance for _, p in run) + track * max(len(run) - 1, 0)
        width = total * k
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        uses = []
        pen = 0.0
        for info, pos in run:
            gid = info.codepoint
            d = f.path(gid)
            if d:
                gid_ref = f"g{f.weight}-{gid}"
                self.defs.setdefault(gid_ref, f'<path id="{gid_ref}" d="{d}"/>')
                px = pen + pos.x_offset
                py = pos.y_offset
                attrs = f' x="{num(px)}"' if px else ""
                attrs += f' y="{num(-py)}"' if py else ""
                uses.append(f'<use href="#{gid_ref}"{attrs}/>')
            pen += pos.x_advance + track
        op = f' opacity="{num(opacity)}"' if opacity is not None else ""
        ks = f"{k:.6f}".rstrip("0")
        self.add(
            f'<g fill="{self.col(color)}"{op}{extra} transform="translate({num(PAD_X + x)} '
            f'{num(PAD_TOP + y)}) scale({ks} -{ks})">{"".join(uses)}</g>'
        )
        return width

    def rect(self, x, y, w, h, rx=0, fill="none", stroke=None, opacity=None,
             extra: str = "") -> None:
        s = f' stroke="{self.col(stroke)}"' if stroke else ""
        o = f' fill-opacity="{num(opacity)}"' if opacity is not None else ""
        r = f' rx="{num(rx)}"' if rx else ""
        self.add(
            f'<rect x="{num(PAD_X + x)}" y="{num(PAD_TOP + y)}" width="{num(w)}" '
            f'height="{num(h)}"{r} fill="{self.col(fill)}"{o}{s}{extra}/>'
        )

    def arrow(self, x: float, y: float, size: float = 11, color: str = "muted") -> None:
        """A small north-east arrow marking a tile as a link. (x, y) is the
        top-right corner of the icon."""
        x0, y0 = PAD_X + x - size, PAD_TOP + y
        x1, y1 = PAD_X + x, PAD_TOP + y + size
        self.add(
            f'<path d="M{num(x0)} {num(y1)}L{num(x1)} {num(y0)}M{num(x0 + size * .2)} '
            f'{num(y0)}H{num(x1)}V{num(y1 - size * .2)}" fill="none" '
            f'stroke="{self.col(color)}" stroke-width="1.5" stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    # output --------------------------------------------------------------
    def render(self) -> str:
        defs = "".join(self.defs.values())
        style = f"<style>{''.join(self.style)}</style>" if self.style else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{num(self.width)}" '
            f'height="{num(self.height)}" viewBox="0 0 {num(self.width)} {num(self.height)}" '
            f'role="img" aria-label="{escape(self.title, {chr(34): "&quot;"})}">'
            f"<title>{escape(self.title)}</title>{style}<defs>{defs}</defs>"
            f'{"".join(self.parts)}</svg>\n'
        )


def write(canvas: Canvas, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{name}.svg"
    p.write_text(canvas.render(), encoding="utf-8")
    return p
