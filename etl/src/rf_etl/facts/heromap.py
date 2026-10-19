"""Hero-карта главной (T2.4): статичный SVG субъектов РФ без JS — «прибор-радар».

Заливка — класс по изменению числа субъектов МСП за 12 месяцев (измерено); цвета классов задают токены
`--r0…--r5`, `--rn` в CSS темы. Регион — ссылка на свою страницу фактов, подсказка — `<title>`.
Поверх — градусная сетка (меридианы через 20°, параллели через 10°) и импульсы в регионах с самым
быстрым ростом. Проекция — коническая равновеликая Альберса (параллели 52° и 64°, меридиан 100° в. д.);
координаты округлены до пикселя viewBox, близкие точки отброшены — HTML главной остаётся лёгким.
"""

from __future__ import annotations

import html
import json
import math
from collections.abc import Sequence
from pathlib import Path

W = 1000  # ширина viewBox
BINS = (-0.02, 0.0, 0.02, 0.04, 0.06)  # границы классов по exp(g) − 1
TICKS = ("−2", "0", "+2", "+4", "+6")  # подписи границ на шкале, %

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
    """Шкала прибора: шесть делений заливки, подписи — на границах классов."""
    cells = "".join(f'<i class="r{i}"></i>' for i in range(len(BINS) + 1))
    ticks = "".join(f'<span style="left:{(i + 1) * 100 / (len(BINS) + 1):.2f}%">{t}</span>' for i, t in enumerate(TICKS))
    return (f'<div class="scale"><div class="cells">{cells}</div><div class="ticks">{ticks}<em>%</em></div>'
            f'<span class="nd"><i class="rn"></i>нет данных</span></div>')


def _centroid(ring: list[tuple[float, float]]) -> tuple[float, float, float]:
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        c = x1 * y2 - x2 * y1
        a, cx, cy = a + c, cx + (x1 + x2) * c, cy + (y1 + y2) * c
    if abs(a) < 1e-9:
        return ring[0][0], ring[0][1], 0.0
    return cx / (3 * a), cy / (3 * a), abs(a) / 2


def svg(geojson: str | Path, info: dict[str, tuple[str, float | None, str | None]], label: str,
        pulses: Sequence[tuple[str, str]] = ()) -> str:
    """info: region_id → (подсказка, рост ln, ссылка или None); pulses: (region_id, подпись) — импульсы."""
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

    def px(x: float, y: float) -> tuple[int, int]:
        return round((x - x0) * k) + 2, round((y - y0) * k) + 2

    out, centers = [], {}
    for props, rings in shapes:
        d, best = [], (0.0, 0.0, -1.0)
        for ring in rings:
            pts = [px(x, y) for x, y in ring]
            keep = [pts[0]]
            for p in pts[1:]:
                if abs(p[0] - keep[-1][0]) + abs(p[1] - keep[-1][1]) >= 2:
                    keep.append(p)
            if len(keep) < 3:
                continue
            c = _centroid([(float(a), float(b)) for a, b in keep])
            best = c if c[2] > best[2] else best
            rel = " ".join(f"{b[0] - a[0]} {b[1] - a[1]}" for a, b in zip(keep, keep[1:], strict=False))
            d.append(f"M{keep[0][0]} {keep[0][1]}l{rel}z")
        if not d:
            continue
        rid = props["region_id"]
        centers[rid] = best[:2]
        tip, growth, href = info.get(rid, (props.get("name", rid), None, None))
        path = f'<path class="{bin_class(growth)}" d="{"".join(d)}"><title>{html.escape(tip)}</title></path>'
        out.append(f'<a href="{html.escape(href)}">{path}</a>' if href else path)

    grat = []  # градусная сетка прибора
    for lon in range(20, 200, 20):
        pts = [px(*_proj(lon if lon <= 180 else lon - 360, lat)) for lat in range(40, 83)]
        grat.append("M" + "L".join(f"{a} {b}" for a, b in pts))
    for lat in range(40, 90, 10):
        pts = [px(*_proj(lon, lat)) for lon in range(18, 192)]
        grat.append("M" + "L".join(f"{a} {b}" for a, b in pts))
    blips, placed = [], []  # подпись уходит влево/вниз, если рядом уже есть импульс
    for i, (rid, tag) in enumerate(pulses):
        if rid not in centers:
            continue
        x, y = centers[rid]
        near = sum(abs(x - a) + abs(y - b) < 90 for a, b in placed)
        dx, dy, anchor = ((10, -9, "start"), (-10, -9, "end"), (10, 24, "start"), (-10, 24, "end"))[near % 4]
        placed.append((x, y))
        blips.append(f'<g class="pulse" style="--i:{i}" transform="translate({x:.0f} {y:.0f})">'
                     f'<circle class="ring" r="6"/><circle class="dot" r="3.5"/>'
                     f'<text x="{dx}" y="{dy}" text-anchor="{anchor}">{html.escape(tag)}</text></g>')
    return (f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{html.escape(label)}">'
            f'<path class="grat" aria-hidden="true" d="{"".join(grat)}"/>'
            + "".join(out) + f'<g class="blips" aria-hidden="true">{"".join(blips)}</g></svg>')
