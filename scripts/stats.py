"""Generate the live stats tiles and frame the contribution snake.

Runs daily in GitHub Actions (see .github/workflows/profile.yml):

    python scripts/stats.py --user het2576 --out dist

Needs GITHUB_TOKEN in the environment. Use --mock to render sample data
locally without a token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

from design import PAD_TOP, PAD_X, ROW_W, THEMES, Canvas, fit_size, mix, write

ROOT = Path(__file__).resolve().parent.parent
TILE_W = ROW_W / 3
TILE_H = 236

# Contribution colours come from the shared orange ramp (empty cell, then
# four levels); the snake uses the tile's ink colour so orange stays the
# only accent.
SNAKE = {
    t: dict(ce=THEMES[t]["ramp"][0], c=THEMES[t]["ramp"], cs=THEMES[t]["ink"])
    for t in THEMES
}


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def gql(query: str, variables: dict, token: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


PROFILE_Q = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    contributionsCollection { contributionYears }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false,
                 privacy: PUBLIC) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}"""


def fetch(user: str, token: str) -> dict:
    repos, after, base = [], None, None
    while True:
        data = gql(PROFILE_Q, {"login": user, "after": after}, token)["user"]
        base = base or data
        repos += data["repositories"]["nodes"]
        page = data["repositories"]["pageInfo"]
        if not page["hasNextPage"]:
            break
        after = page["endCursor"]

    years = sorted(base["contributionsCollection"]["contributionYears"])
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = []
    for y in years:
        end = min(f"{y}-12-31T23:59:59Z", now)
        fields.append(
            f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", '
            f'to: "{end}") {{ totalCommitContributions '
            f"contributionCalendar {{ totalContributions weeks {{ contributionDays "
            f"{{ date contributionCount }} }} }} }}"
        )
    cal = gql(
        "query($login: String!) { user(login: $login) { " + " ".join(fields) + " } }",
        {"login": user}, token,
    )["user"]

    days: dict[str, int] = {}
    per_year = {}
    for y in years:
        block = cal[f"y{y}"]
        per_year[y] = {
            "total": block["contributionCalendar"]["totalContributions"],
            "commits": block["totalCommitContributions"],
        }
        for week in block["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]

    langs: dict[str, dict] = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            entry = langs.setdefault(name, {"size": 0, "color": e["node"]["color"] or "#8b949e"})
            entry["size"] += e["size"]

    return {
        "days": days,
        "per_year": per_year,
        "stars": sum(r["stargazerCount"] for r in repos),
        "prs": base["pullRequests"]["totalCount"],
        "followers": base["followers"]["totalCount"],
        "languages": langs,
    }


def mock() -> dict:
    import random
    rnd = random.Random(25)
    today = dt.date.today()
    days = {}
    for i in range(720):
        d = today - dt.timedelta(days=i)
        active = rnd.random() < (0.72 if i < 300 else 0.45)
        days[d.isoformat()] = rnd.choice([1, 1, 2, 3, 4, 6, 9, 14]) if active else 0
    for i in range(12):  # a current streak worth looking at
        days[(today - dt.timedelta(days=i)).isoformat()] = rnd.choice([1, 2, 3, 5, 8])
    by_year: dict[int, int] = {}
    for k, v in days.items():
        by_year[int(k[:4])] = by_year.get(int(k[:4]), 0) + v
    return {
        "days": days,
        "per_year": {y: {"total": t, "commits": int(t * .8)} for y, t in by_year.items()},
        "stars": 57,
        "prs": 38,
        "followers": 64,
        "languages": {
            "Python": {"size": 480000, "color": "#3572A5"},
            "TypeScript": {"size": 390000, "color": "#3178c6"},
            "JavaScript": {"size": 120000, "color": "#f1e05a"},
            "C++": {"size": 40000, "color": "#f34b7d"},
            "Jupyter Notebook": {"size": 900000, "color": "#DA5B0B"},
            "HTML": {"size": 70000, "color": "#e34c26"},
            "Shell": {"size": 9000, "color": "#89e051"},
            "Dockerfile": {"size": 3000, "color": "#384d54"},
        },
    }


# --------------------------------------------------------------------------
# Derived numbers
# --------------------------------------------------------------------------

def streaks(days: dict[str, int], today: dt.date) -> dict:
    ordered = sorted((dt.date.fromisoformat(k), v) for k, v in days.items()
                     if dt.date.fromisoformat(k) <= today)
    counts = dict(ordered)

    # current streak: a day without contributions *today* doesn't break it yet
    cur, d = 0, today
    if counts.get(d, 0) == 0:
        d -= dt.timedelta(days=1)
    while counts.get(d, 0) > 0:
        cur += 1
        d -= dt.timedelta(days=1)

    longest, run = 0, 0
    prev = None
    for day, n in ordered:
        if n > 0 and prev is not None and (day - prev).days == 1 and run:
            run += 1
        elif n > 0:
            run = 1
        else:
            run = 0
        longest = max(longest, run)
        prev = day

    recent = [counts.get(today - dt.timedelta(days=i), 0) for i in range(13, -1, -1)]
    nonzero = sorted(v for v in counts.values() if v > 0) or [1]
    q = [nonzero[int(len(nonzero) * f)] for f in (0.25, 0.5, 0.75)]
    levels = [0 if v == 0 else 1 + sum(v > t for t in q) for v in recent]
    return {"current": cur, "longest": max(longest, cur), "levels": levels}


def fmt(n: int) -> str:
    return f"{n:,}"


# --------------------------------------------------------------------------
# Tiles
# --------------------------------------------------------------------------

def big_number(c: Canvas, value: str, unit: str, y: float) -> None:
    w = c.text(value, 24, y, 56, 600, "ink", tracking=-0.02)
    if unit:
        c.text(unit, 24 + w + 9, y, 17, 400, "muted")


def row(c: Canvas, label: str, value: str, y: float) -> None:
    c.text(label, 24, y, 15, 400, "muted")
    c.text(value, c.inner_w - 24, y, 15, 500, "text", anchor="end")


def streak_tile(s: dict, theme: str) -> Canvas:
    title = f'Current streak: {s["current"]} days. Longest streak: {s["longest"]} days.'
    c = Canvas(TILE_W, TILE_H, theme, title)
    c.frame()
    c.text("Current streak", 24, 44, 16, 400, "muted")
    big_number(c, str(s["current"]), "day" if s["current"] == 1 else "days", 118)
    # the last 14 days, oldest first
    n = len(s["levels"])
    gap = 4
    size = (c.inner_w - 48 - gap * (n - 1)) / n
    for i, lv in enumerate(s["levels"]):
        x = 24 + i * (size + gap)
        if lv == 0:
            c.rect(x, 142, size, size, rx=3, fill="faint", opacity=0.45)
        else:
            c.rect(x, 142, size, size, rx=3, fill=SNAKE[theme]["c"][lv])
    c.text("Last 14 days", 24, 142 + size + 22, 13, 400, "muted")
    row(c, "Longest", f'{s["longest"]} days', 212)
    return c


def activity_tile(d: dict, year: int, theme: str) -> Canvas:
    this = d["per_year"].get(year, {"total": 0})["total"]
    all_time = sum(v["total"] for v in d["per_year"].values())
    title = (f"{fmt(this)} contributions in {year}. {fmt(all_time)} all time. "
             f'{fmt(d["prs"])} pull requests. {fmt(d["stars"])} stars earned.')
    c = Canvas(TILE_W, TILE_H, theme, title)
    c.frame()
    c.text(f"Contributions in {year}", 24, 44, 16, 400, "muted")
    big_number(c, fmt(this), "", 118)
    row(c, "All time", fmt(all_time), 160)
    row(c, "Pull requests", fmt(d["prs"]), 186)
    row(c, "Stars earned", fmt(d["stars"]), 212)
    return c


def languages_tile(d: dict, exclude: list[str], theme: str) -> Canvas:
    langs = {k: v for k, v in d["languages"].items() if k not in set(exclude)}
    total = sum(v["size"] for v in langs.values()) or 1
    # languages under 1% go into "Other" instead of showing as 0% rows
    top = [(k, v["size"] / total)
           for k, v in sorted(langs.items(), key=lambda kv: -kv[1]["size"])
           if v["size"] / total >= 0.01][:5]
    # shades of the accent ramp, strongest for the biggest share
    ramp = THEMES[theme]["ramp"]
    step = 0.75 / max(len(top) - 1, 1)
    shares = [(k, mix(ramp, 1 - i * step), p) for i, (k, p) in enumerate(top)]
    title = "Top languages: " + ", ".join(f"{k} {p:.0%}" for k, _, p in shares)
    c = Canvas(TILE_W, TILE_H, theme, title)
    c.frame()
    c.text("Top languages", 24, 44, 16, 400, "muted")

    bar_w, bar_y, gap = c.inner_w - 48, 64, 2
    other = max(0.0, 1 - sum(p for _, _, p in shares))
    segs = shares + ([("Other", "faint", other)] if other > 0.005 else [])
    avail = bar_w - gap * (len(segs) - 1)
    x = 24.0
    c.add(f'<clipPath id="bar"><rect x="{PAD_X + 24}" y="{PAD_TOP + bar_y}" '
          f'width="{bar_w}" height="8" rx="4"/></clipPath>')
    before = len(c.parts)
    for _, color, p in segs:
        w = max(avail * p, 2)
        c.rect(x, bar_y, w, 8, fill=color)
        x += w + gap
    group = "".join(c.parts[before:])
    del c.parts[before:]
    c.add(f'<g clip-path="url(#bar)">{group}</g>')

    for i, (name, color, p) in enumerate(shares):
        y = 108 + i * 26
        c.rect(24, y - 9.5, 9, 9, rx=2.5, fill=color)
        size = fit_size([name], c.inner_w - 48 - 19 - 46, 15, 500, min_size=12)
        c.text(name, 24 + 19, y, size, 500, "text")
        pct = f"{p * 100:.1f}%" if p < 0.1 else f"{p * 100:.0f}%"
        c.text(pct, c.inner_w - 24, y, 15, 400, "muted", anchor="end")
    return c


def snake_tile(src: str, theme: str) -> Canvas:
    """Put the snk animation inside a tile, recoloured to the theme palette."""
    m = re.search(r"<svg\b([^>]*)>", src)
    vb = re.search(r'viewBox="([^"]+)"', m.group(1)) if m else None
    vb_vals = [float(v) for v in vb.group(1).split()] if vb else [-16, -32, 880, 192]
    # snk leaves generous empty bands above and below the grid; crop the
    # view to where the snake actually travels (16-unit cells).
    ys = [float(y) for y in re.findall(r"translate\(-?[\d.]+px,\s*(-?[\d.]+)px\)", src)]
    if ys:
        y0, y1 = min(ys) - 3, max(ys) + 16 + 3
        if vb_vals[1] <= y0 < y1 <= vb_vals[1] + vb_vals[3]:
            vb_vals = [vb_vals[0], y0, vb_vals[2], y1 - y0]
    inner_w = ROW_W - 2 * PAD_X
    w = inner_w - 32
    h = w * vb_vals[3] / vb_vals[2]
    top = 62
    c = Canvas(ROW_W, top + h + 10, theme, "Contribution graph for the last 12 months, "
               "with a snake eating the contributions")
    c.frame()
    c.text("Last 12 months", 28, 40, 16, 400, "muted")
    s = SNAKE[theme]
    colours = (f':root{{--cb:transparent;--cs:{s["cs"]};--ce:{s["ce"]};'
               + "".join(f"--c{i}:{col};" for i, col in enumerate(s["c"])) + "}")
    body = src[m.end():src.rindex("</svg>")] if m else ""
    body = re.sub(r"<desc>.*?</desc>", "", body, flags=re.S)
    # our colour block goes last so it wins over snk's own :root rule
    body = body.replace("</style>", colours + "</style>", 1)
    c.add(f'<svg x="{PAD_X + 16}" y="{PAD_TOP + top}" width="{w:.1f}" height="{h:.1f}" '
          f'viewBox="{" ".join(f"{v:g}" for v in vb_vals)}">{body}</svg>')
    return c


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER", "het2576"))
    ap.add_argument("--out", default="dist")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)

    with open(ROOT / "profile.toml", "rb") as fh:
        cfg = tomllib.load(fh)
    exclude = cfg.get("stats", {}).get("exclude_languages", [])

    if args.mock:
        data = mock()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("GITHUB_TOKEN is not set", file=sys.stderr)
            return 1
        data = fetch(args.user, token)

    today = dt.datetime.now(dt.timezone.utc).date()
    s = streaks(data["days"], today)
    for theme in ("dark", "light"):
        write(streak_tile(s, theme), out, f"stats-streak-{theme}")
        write(activity_tile(data, today.year, theme), out, f"stats-activity-{theme}")
        write(languages_tile(data, exclude, theme), out, f"stats-languages-{theme}")
        snake = out / f"snake-{theme}.svg"
        if snake.exists():
            write(snake_tile(snake.read_text(encoding="utf-8"), theme), out, f"contrib-{theme}")
        else:
            print(f"{snake} not found, skipping the contribution tile", file=sys.stderr)
    print(f"streak {s['current']} (longest {s['longest']}), "
          f"{data['per_year'].get(today.year, {}).get('total', 0)} contributions this year",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
