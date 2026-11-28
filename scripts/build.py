"""Build the static profile tiles from profile.toml.

    python scripts/build.py          # writes assets/dark/*.svg and assets/light/*.svg
"""
from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path

from design import PAD_TOP, PAD_X, ROW_W, Canvas, fit_size, measure, write

ROOT = Path(__file__).resolve().parent.parent


def load() -> dict:
    with open(ROOT / "profile.toml", "rb") as fh:
        return tomllib.load(fh)


# --------------------------------------------------------------------------
# Hero: name, headline and a causal attention map over the headline's tokens
# --------------------------------------------------------------------------

def attention(tokens: list[str], given: list[list[float]] | None) -> list[list[float]]:
    n = len(tokens)
    if given and len(given) == n and all(len(r) == i + 1 for i, r in enumerate(given)):
        return given
    rows = []
    for i in range(n):
        row = []
        for j in range(i + 1):
            h = hashlib.sha1(f"{tokens[i]}>{tokens[j]}".encode()).digest()[0] / 255
            row.append(0.55 if i == j else 0.08 + 0.6 * h * (0.6 + 0.4 * j / max(i, 1)))
        rows.append(row)
    return rows


def hero(p: dict, theme: str) -> Canvas:
    person, cfg = p["person"], p["hero"]
    title = f'{person["name"]}, {person["role"]}. {" ".join(person["headline"])}'
    c = Canvas(ROW_W, 300, theme, title)
    c.frame()

    tokens = cfg["tokens"]
    n = len(tokens)
    weights = attention(tokens, cfg.get("attention"))
    cell, gap = 24, 5
    grid = n * cell + (n - 1) * gap
    gx = c.inner_w - 40 - grid
    gy = c.inner_h - 34 - grid
    label_size = 12
    label_w = max(measure(t, label_size, 500) for t in tokens)

    x0 = 36
    c.text(person["name"], x0, 56, 18, 600, "ink")
    c.text(person["role"], x0, 80, 16, 400, "muted")

    max_w = gx - 14 - label_w - 40 - x0
    lines = person["headline"]
    size = fit_size(lines, max_w, 42, 600, tracking=-0.025, min_size=30)
    lead = round(size * 1.14)
    base2 = c.inner_h - 40 - 22 - 44
    for i, line in enumerate(lines):
        c.text(line, x0, base2 - (len(lines) - 1 - i) * lead, size, 600, "ink", tracking=-0.025)
    for i, line in enumerate(person["intro"]):
        c.text(line, x0, c.inner_h - 62 + i * 23, 16, 400, "muted")

    # token labels: rows on the left, columns along the top (rotated)
    for i, tok in enumerate(tokens):
        cy = gy + i * (cell + gap) + cell / 2
        c.text(tok, gx - 12, cy + label_size * 0.36, label_size, 500, "muted", anchor="end")
    for j, tok in enumerate(tokens):
        cx = gx + j * (cell + gap) + cell / 2
        before = len(c.parts)
        sx, sy = cx - 2, gy - 9
        c.text(tok, sx, sy, label_size, 500, "muted")
        g = c.parts.pop(before)
        c.add(f'<g transform="rotate(-55 {PAD_X + sx:.1f} {PAD_TOP + sy:.1f})">{g}</g>')

    # masked (future) cells stay static, then rows "generate" one at a time
    for i in range(n):
        for j in range(i + 1, n):
            c.rect(gx + j * (cell + gap) + .5, gy + i * (cell + gap) + .5, cell - 1, cell - 1,
                   rx=4.5, stroke="line")
    for i in range(n):
        before = len(c.parts)
        for j in range(i + 1):
            w = max(0.0, min(1.0, weights[i][j]))
            c.rect(gx + j * (cell + gap), gy + i * (cell + gap), cell, cell, rx=5,
                   fill="cell", opacity=0.07 + 0.88 * w)
        cells = "".join(c.parts[before:])
        del c.parts[before:]
        c.add(f'<g class="r" style="animation-delay:{0.35 + i * 0.16:.2f}s">{cells}</g>')
    c.style.append(
        ".r{animation:gen .5s cubic-bezier(.2,.7,.2,1) both}"
        "@keyframes gen{from{opacity:0}to{opacity:1}}"
        "@media (prefers-reduced-motion:reduce){.r{animation:none}}"
    )
    return c


# --------------------------------------------------------------------------
# Second row: what I'm doing now + portfolio
# --------------------------------------------------------------------------

def now(p: dict, theme: str) -> Canvas:
    rows = p["now"]
    title = ". ".join(f'{r["label"]}: {r["value"]}' for r in rows)
    c = Canvas(560, 204, theme, title)
    c.frame()
    pitch = 40
    first = (c.inner_h - (len(rows) - 1) * pitch) / 2 + 6
    label_w = max(measure(r["label"], 16, 400) for r in rows)
    vx = 32 + max(label_w + 24, 116)
    for i, r in enumerate(rows):
        y = first + i * pitch
        c.text(r["label"], 32, y, 16, 400, "muted")
        size = fit_size([r["value"]], c.inner_w - vx - 28, 16, 500, min_size=13)
        c.text(r["value"], vx, y, size, 500, "text")
    return c


def portfolio(p: dict, theme: str) -> Canvas:
    cfg = p["portfolio"]
    c = Canvas(280, 204, theme, f'{cfg["label"]}: {cfg["title"]}. {cfg["note"]}')
    c.frame()
    c.text(cfg["label"], 26, 44, 16, 400, "muted")
    c.arrow(c.inner_w - 26, 31, 12)
    size = fit_size([cfg["title"]], c.inner_w - 52, 30, 600, tracking=-0.02, min_size=18)
    c.text(cfg["title"], 26, c.inner_h - 58, size, 600, "ink", tracking=-0.02)
    c.text(cfg["note"], 26, c.inner_h - 30, 15, 400, "muted")
    return c


# --------------------------------------------------------------------------
# Third row: link tiles
# --------------------------------------------------------------------------

def link(item: dict, width: float, theme: str) -> Canvas:
    c = Canvas(width, 104, theme, f'{item["name"]}: {item["handle"]}')
    c.frame()
    c.text(item["name"], 22, 40, 16, 400, "muted")
    c.arrow(c.inner_w - 22, 27, 11)
    size = fit_size([item["handle"]], c.inner_w - 44, 18, 500, min_size=13)
    c.text(item["handle"], 22, 78, size, 500, "ink")
    return c


# --------------------------------------------------------------------------
# Stack
# --------------------------------------------------------------------------

def stack(p: dict, theme: str) -> Canvas:
    groups = p["stack"]
    title = "Stack. " + ". ".join(f'{g["group"]}: {", ".join(g["items"])}' for g in groups)
    chip_h, chip_pad, chip_gap, size = 32, 13, 8, 15
    label_w = max(measure(g["group"], 16, 400) for g in groups)
    cx0 = 32 + max(label_w + 28, 124)
    right = ROW_W - 12 - 28

    # lay out first to know the height
    placed, y = [], 28
    for g in groups:
        x, row_y = cx0, y
        chips = []
        for item in g["items"]:
            w = measure(item, size, 500) + 2 * chip_pad
            if x + w > right and x > cx0:
                x, row_y = cx0, row_y + chip_h + chip_gap
            chips.append((item, x, row_y, w))
            x += w + chip_gap
        placed.append((g["group"], y, chips))
        y = row_y + chip_h + 14
    inner_h = y - 14 + 28

    c = Canvas(ROW_W, inner_h, theme, title)
    c.frame()
    for group, gy, chips in placed:
        c.text(group, 32, gy + chip_h / 2 + 5.5, 16, 400, "muted")
        for item, x, cy, w in chips:
            c.rect(x + .5, cy + .5, w - 1, chip_h - 1, rx=9, fill="chip", stroke="line")
            c.text(item, x + w / 2, cy + chip_h / 2 + 5.2, size, 500, "text", anchor="middle")
    return c


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------

def footer(p: dict, theme: str) -> Canvas:
    cfg = p["footer"]
    c = Canvas(ROW_W, 120, theme, f'{cfg["title"]} {cfg["note"]} {cfg["email"]}')
    c.frame()
    c.text(cfg["title"], 32, 54, 24, 600, "ink", tracking=-0.015)
    c.text(cfg["note"], 32, 84, 16, 400, "muted")
    c.arrow(c.inner_w - 32, 52, 12, "ink")
    c.text(cfg["email"], c.inner_w - 32 - 12 - 12, 64, 17, 500, "ink", anchor="end")
    return c


# --------------------------------------------------------------------------

# README -------------------------------------------------------------------
# Rows are image tags placed edge to edge with no whitespace between them.
# Widths are each tile's share of the 840-unit row, scaled to 99.6% so
# rounding never pushes the last tile onto a new line.

ROW_SCALE = 99.6


def pct(width: float) -> str:
    return f"{width / ROW_W * ROW_SCALE:.2f}".rstrip("0").rstrip(".") + "%"


def attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def picture(dark: str, light: str, width: float, alt: str, href: str | None = None) -> str:
    tag = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{dark}">'
           f'<img src="{light}" width="{pct(width)}" alt="{attr(alt)}"></picture>')
    return f'<a href="{attr(href)}">{tag}</a>' if href else tag


def readme(p: dict, tiles: dict[str, Canvas]) -> str:
    h = p["person"]["handle"]
    assets = f"https://raw.githubusercontent.com/{h}/{h}/HEAD/assets"
    output = f"https://raw.githubusercontent.com/{h}/{h}/output"

    def static(name: str, href: str | None = None) -> str:
        t = tiles[name]
        return picture(f"{assets}/dark/{name}.svg", f"{assets}/light/{name}.svg",
                       t.width, t.title, href)

    def live(name: str, width: float, alt: str) -> str:
        return picture(f"{output}/{name}-dark.svg", f"{output}/{name}-light.svg", width, alt)

    links = p["links"]
    rows = [
        static("hero"),
        static("now") + static("portfolio", p["portfolio"]["url"]),
        "".join(static(f"link-{i + 1}", l["url"]) for i, l in enumerate(links)),
        static("stack"),
        live("stats-streak", ROW_W / 3, "Current and longest contribution streak")
        + live("stats-activity", ROW_W / 3, "Contributions this year, all time, pull requests and stars")
        + live("stats-languages", ROW_W / 3, "Top languages across public repositories"),
        live("contrib", ROW_W, "Contribution graph for the last 12 months with a snake eating it"),
        static("footer", f'mailto:{p["footer"]["email"]}'),
    ]
    views = (f'<img src="https://komarev.com/ghpvc/?username={h}&style=flat-square'
             f'&color=30363d&label=profile+views" alt="Profile views">')
    return (
        "<!-- Generated by scripts/build.py from profile.toml. Edit profile.toml, not this file. -->\n"
        '<div align="center">\n'
        + "<br>\n".join(rows)
        + "<br><br>\n" + views + "\n</div>\n"
    )


def build(out_root: Path = ROOT / "assets") -> list[Path]:
    p = load()
    written = []
    links = p["links"]
    per = ROW_W / len(links)
    tiles: dict[str, Canvas] = {}
    for theme in ("dark", "light"):
        out = out_root / theme
        tiles = {"hero": hero(p, theme), "now": now(p, theme), "portfolio": portfolio(p, theme)}
        for i, item in enumerate(links):
            tiles[f"link-{i + 1}"] = link(item, per, theme)
        tiles["stack"] = stack(p, theme)
        tiles["footer"] = footer(p, theme)
        for name, canvas in tiles.items():
            written.append(write(canvas, out, name))
    (ROOT / "README.md").write_text(readme(p, tiles), encoding="utf-8")
    return written


if __name__ == "__main__":
    files = build()
    total = sum(f.stat().st_size for f in files)
    print(f"wrote {len(files)} tiles ({total / 1024:.0f} KB) and README.md", file=sys.stderr)
