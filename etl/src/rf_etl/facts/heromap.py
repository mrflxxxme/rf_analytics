"""Hero-карта главной (T2.4): статичный SVG субъектов РФ без JS.

Заливка — класс по изменению числа субъектов МСП за 12 месяцев (измерено); цвета классов задают токены
`--r0…--r5`, `--rn` в CSS темы. Регион — ссылка на свою страницу фактов, подсказка — `<title>`.
Проекция — коническая равновеликая Альберса (параллели 52° и 64°, меридиан 100° в. д.); координаты
округлены до пикселя viewBox, близкие точки отброшены — HTML главной остаётся лёгким.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

W = 1000  # ширина viewBox
BINS = (-0.02, 0.0, 0.02, 0.04, 0.06)  # границы классов по exp(g) − 1
LABELS = ("< −2 %", "−2…0 %", "0…2 %", "2…4 %", "4…6 %", "> 6 %")

_P1, _P2, _L0 = math.radians(52), math.radians(64), 100.0
_N = (math.sin(_P1) + math.sin(_P2)) / 2
_C = math.cos(_P1) ** 2 + 2 * _N * math.sin(_P1)


def _proj(lon: float, lat: float) -> tuple[float, float]:
    if lon < 0:  # Чукотка за антимеридианом
        lon += 360
    rho = math.sqrt(_C - 2 * _N * math.sin(math.radians(lat))) / _N
    th = _N * math.radians(lon - _L0)
    return rho * math.sin(th), rho * math.cos(th)  # y вниз, север сверху


def bin_class(g: float | None) -> str:
    """ln(t / t−12) → класс заливки; None → «нет данных»."""
    if g is None:
        return "rn"
    p = math.exp(g) - 1
    return f"r{sum(p > b for b in BINS)}"


def legend() -> str:
    items = "".join(f'<span><i class="r{i}"></i>{html.escape(t)}</span>' for i, t in enumerate(LABELS))
    return f'<span class="leg">{items}<span><i class="rn"></i>нет данных</span></span>'


def svg(geojson: str | Path, info: dict[str, tuple[str, float | None, str | None]], label: str) -> str:
    """info: region_id → (подсказка, рост ln, ссылка или None)."""
    feats = json.loads(Path(geojson).read_text("utf-8"))["features"]
    shapes: list[tuple[dict[str, str], list[list[tuple[float, float]]]]] = []
    for f in feats:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        shapes.append((f["properties"], [[_proj(x, y) for x, y in ring] for poly in polys for ring in poly]))
    xs = [x for _, rings in shapes for r in rings for x, _ in r]
    ys = [y for _, rings in shapes for r in rings for _, y in r]
    x0, y0 = min(xs), min(ys)
    k = (W - 4) / (max(xs) - x0)
    h = math.ceil((max(ys) - y0) * k) + 4
    out = []
    for props, rings in shapes:
        d = []
        for ring in rings:
            pts = [(round((x - x0) * k) + 2, round((y - y0) * k) + 2) for x, y in ring]
            keep = [pts[0]]
            for p in pts[1:]:
                if abs(p[0] - keep[-1][0]) + abs(p[1] - keep[-1][1]) >= 2:
                    keep.append(p)
            if len(keep) < 3:
                continue
            rel = " ".join(f"{b[0] - a[0]} {b[1] - a[1]}" for a, b in zip(keep, keep[1:], strict=False))
            d.append(f"M{keep[0][0]} {keep[0][1]}l{rel}z")
        if not d:
            continue
        rid = props["region_id"]
        tip, growth, href = info.get(rid, (props.get("name", rid), None, None))
        path = f'<path class="{bin_class(growth)}" d="{"".join(d)}"><title>{html.escape(tip)}</title></path>'
        out.append(f'<a href="{html.escape(href)}">{path}</a>' if href else path)
    return (f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{html.escape(label)}">'
            + "".join(out) + "</svg>")
