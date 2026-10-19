"""Статический слой фактов (T2.5, D27): HTML без JS, sitemap.xml, robots.txt.

Страницы индексируются (без noindex); приложение /karta/ и /api/ закрыты в robots.txt
и заголовком X-Robots-Tag во внутреннем Caddy. Все числа — из `data.Facts`.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import math
import shutil
from pathlib import Path
from urllib.parse import quote

import markdown

from rf_etl.facts import heromap
from rf_etl.facts.data import (MIN_BASE, MIN_COHORT, Facts, NeedFacts, Ranked, RegionFacts, load, niche_of_month,
                               region_of_week)

E = html.escape
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
          "ноября", "декабря")


def num(v: int | float) -> str:
    return f"{round(v):,}".replace(",", " ")


def pct(g: float | None) -> str:
    """ln(t / t−12) → «+5,1 %» (та же измеренная величина в процентах)."""
    if g is None:
        return "нет данных"
    p = (math.exp(g) - 1) * 100
    return (f"{p:+.1f}".replace(".", ",").replace("-", "−")) + " %"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(51, ("ниша", "ниши", "ниш")) → «ниша»."""
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    return forms[1] if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else forms[2]


def share(s: float | None) -> str:
    return "нет данных" if s is None else f"{s * 100:.0f} %"


def date_ru(d: dt.date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


ASSETS = Path(__file__).parent / "assets"
CSS = (ASSETS / "facts.css").read_text("utf-8")  # дизайн-направление T2.4, docs/04-ux.md
FONTS = ("fira-cond-800-cyrillic.woff2", "fira-cond-800-latin.woff2", "OFL-FiraSans.txt")


class Site:
    def __init__(self, facts: Facts, site_url: str, eco: dict, methodology_md: str | None, today: dt.date,
                 geojson: Path | None = None) -> None:
        self.f = facts
        self.geojson = geojson
        self.url = site_url.rstrip("/")
        self.eco = eco
        self.md = methodology_md
        self.today = today
        self.pages: dict[str, str] = {}  # путь URL → HTML

    def link(self, path: str) -> str:
        return self.url + path

    # --- каркас ---------------------------------------------------------------------------------------------
    def page(self, path: str, title: str, desc: str, body: str, pre: str = "") -> None:
        """pre — полноширинные секции до основного текста (hero и полоса цифр главной)."""
        eco = "".join(
            f'<span class="cur">{E(p["label"])}</span>' if p.get("current") or not p.get("url")
            else f'<a href="{E(p["url"])}">{E(p["label"])}</a>'
            for p in self.eco["products"])
        author = self.eco["author"]
        self.pages[path] = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(self.link(path))}"><link rel="stylesheet" href="/facts.css">
<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{E(self.link(path))}"><meta property="og:type" content="article"><meta property="og:locale" content="ru_RU">
</head><body>
<div class="beta"><b>Бета</b> · только измеренные данные реестра МСП ФНС, прогнозов пока нет</div>
<header class="top"><div class="in"><a class="logo" href="/"><i></i>Нишемер</a><nav><a href="/fakty/nisha-mesyaca/">Ниша месяца</a>
<a href="/fakty/region-nedeli/">Регион недели</a><a href="/metodologiya/">Методология</a></nav>
<a class="btn" href="/karta/">Карта</a></div></header>
{pre}<main>{body}</main>
<footer><div class="in"><div class="eco">{eco}</div>
<div><a href="{E(author["url"])}">{E(author["label"])}</a> · Данные: Единый реестр субъектов МСП (ФНС России), снимок на {date_ru(self.f.data_date)};
snapshot {E(self.f.snapshot)}, методология {E(self.f.methodology_version)}. Границы субъектов © участники OpenStreetMap.</div></div></footer>
</body></html>
"""

    def chart(self, series: list[tuple[dt.date, int]], label: str) -> str:
        """Столбики по снимкам — без JS, подпись и таблица рядом (доступно и индексируемо)."""
        if not series:
            return ""
        w, h, pad = 640, 180, 24
        mx = max(v for _, v in series) or 1
        bw = (w - pad) / len(series)
        bars = [f'<line class="gl" x1="0" x2="{w}" y1="{h - pad - (h - 2 * pad) * q:.1f}" y2="{h - pad - (h - 2 * pad) * q:.1f}"/>'
                for q in (0, .5, 1)]  # шкала прибора: ноль, половина, максимум
        for i, (d, v) in enumerate(series):
            bh = (h - 2 * pad) * v / mx
            x = pad / 2 + i * bw
            bars.append(f'<rect class="bar" x="{x + 2:.1f}" y="{h - pad - bh:.1f}" width="{bw - 4:.1f}" height="{bh:.1f}">'
                        f'<title>{d.year}: {num(v)}</title></rect>'
                        f'<text class="ax" x="{x + bw / 2:.1f}" y="{h - 6}" font-size="11" text-anchor="middle">{d.year}</text>')
        return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(label)}">{"".join(bars)}</svg>'
                f'<table><thead><tr><th>Снимок реестра</th><th class="n">Активных субъектов</th></tr></thead><tbody>'
                + "".join(f'<tr><td>{date_ru(d)}</td><td class="n">{num(v)}</td></tr>' for d, v in series)
                + "</tbody></table>")

    def ranked(self, items: list[Ranked], names: dict[str, str], href: str, growth: bool) -> str:
        if not items:
            return '<p class="mut">Недостаточно данных.</p>'
        head = "Изменение за 12 мес." if growth else "Активных субъектов"
        rows = "".join(
            f'<tr><td>{i}</td><td><a href="{href.format(quote(r.key))}">{E(names.get(r.key, r.key))}</a></td>'
            f'<td class="n">{pct(r.value) if growth else num(r.value)}</td>'
            + (f'<td class="n">{num(r.base or 0)}</td>' if growth else "") + "</tr>"
            for i, r in enumerate(items, 1))
        extra = '<th class="n">Год назад</th>' if growth else ""
        return f'<table><thead><tr><th>#</th><th></th><th class="n">{head}</th>{extra}</tr></thead><tbody>{rows}</tbody></table>'

    # --- страницы -------------------------------------------------------------------------------------------
    def need_page(self, n: NeedFacts, path: str | None = None, rubric: str | None = None) -> None:
        rn = {k: r.name for k, r in self.f.regions.items()}
        lead_reg = rn.get(n.top_regions[0].key, "") if n.top_regions else ""
        h1 = f"{rubric}: {n.name}" if rubric else f"{n.name}: где в России больше всего бизнеса"
        desc = (f"{n.name}: {num(n.active)} активных субъектов МСП в России на {date_ru(self.f.data_date)}, "
                f"за 12 месяцев {pct(n.growth)}. Лидер — {lead_reg}. Данные реестра МСП ФНС.")
        map_href = f"/karta/?mode=niche&need={quote(n.need_id)}&m=msp_active"
        why = (f'<p class="lead">Самый быстрый рост числа субъектов МСП по России за 12 месяцев среди всех ниш '
               f'таксономии ({len(self.f.needs)}).</p>' if rubric else "")
        body = f"""<p class="eyebrow">Факты · ниша · снимок {self.f.data_date:%d.%m.%Y}</p><h1>{E(h1)}</h1>{why}
<div class="kpi"><div><b>{num(n.active)}</b>активных субъектов МСП по РФ</div>
<div><b>{pct(n.growth)}</b>за 12 месяцев</div>
<div><b>{share(n.survival)}</b>новых работают через 12 месяцев{f' (когорта {date_ru(n.survival_cohort)})' if n.survival_cohort and n.survival is not None else ''}</div></div>
<a class="cta" href="{map_href}">Смотреть на карте с 2016 года</a>
<h2>Где больше всего</h2>{self.ranked(n.top_regions, rn, "/fakty/region/{}/", False)}
<h2>Где быстрее растёт</h2><p class="mut">Регионы, где 12 месяцев назад было не меньше {MIN_BASE} субъектов.</p>
{self.ranked(n.fastest_regions, rn, "/fakty/region/{}/", True)}
<h2>Динамика по России</h2>{self.chart(n.series, f"Число активных субъектов: {n.name}")}
<p class="mut">Субъект относится к нише по основному ОКВЭД в реестре МСП. Выживаемость — доля субъектов, вошедших
в реестр за 3 месяца до снимка и найденных в нём через 12 месяцев (когорты от {MIN_COHORT} субъектов).
<a href="/metodologiya/">Методология</a>.</p>"""
        self.page(path or f"/fakty/nisha/{n.need_id}/", f"{h1} — Нишемер", desc, body)

    def region_page(self, r: RegionFacts, path: str | None = None, rubric: str | None = None) -> None:
        nn = {k: n.name for k, n in self.f.needs.items()}
        h1 = f"{rubric}: {r.name}" if rubric else f"{r.name}: какой малый бизнес здесь есть"
        top = nn.get(r.top_needs[0].key, "") if r.top_needs else ""
        desc = (f"{r.name}: {num(r.active)} активных субъектов МСП на {date_ru(self.f.data_date)}, за 12 месяцев "
                f"{pct(r.growth)}. Самая массовая ниша — {top}. Данные реестра МСП ФНС.")
        body = f"""<p class="eyebrow">Факты · регион · снимок {self.f.data_date:%d.%m.%Y}</p><h1>{E(h1)}</h1>
<div class="kpi"><div><b>{num(r.active)}</b>активных субъектов МСП</div><div><b>{pct(r.growth)}</b>за 12 месяцев</div>
<div><b>{share(r.survival)}</b>новых работают через 12 месяцев</div></div>
<a class="cta" href="/karta/?mode=region&region={quote(r.region_id)}&m=msp_active">Открыть регион на карте</a>
<h2>Самые массовые ниши</h2>{self.ranked(r.top_needs, nn, "/fakty/nisha/{}/", False)}
<h2>Быстрее всего растут</h2><p class="mut">Ниши, где 12 месяцев назад было не меньше {MIN_BASE} субъектов.</p>
{self.ranked(r.fastest_needs, nn, "/fakty/nisha/{}/", True)}
<h2>Динамика: все субъекты МСП региона</h2>{self.chart(r.series, f"Число активных субъектов МСП: {r.name}")}
<p class="mut"><a href="/metodologiya/">Методология</a>.</p>"""
        self.page(path or f"/fakty/region/{r.region_id}/", f"{h1} — Нишемер", desc, body)

    def signals(self, n: int = 5) -> list[RegionFacts]:
        """Импульсы прибора: регионы с самым быстрым ростом числа субъектов МСП за 12 месяцев."""
        grown = [r for r in self.f.regions.values() if r.growth is not None and r.growth > 0]
        return sorted(grown, key=lambda r: (-(r.growth or 0), r.region_id))[:n]

    def hero_map(self, sig: list[RegionFacts]) -> str:
        if not self.geojson:
            return ""
        info = {k: (f"{r.name}: {pct(r.growth)} за 12 месяцев, {num(r.active)} субъектов", r.growth,
                    f"/fakty/region/{quote(k)}/") for k, r in self.f.regions.items()}
        cap = "Изменение числа субъектов МСП за 12 месяцев"
        pulses = [(r.region_id, f"{i:02d}") for i, r in enumerate(sig, 1)]  # номер — строка в «Сигналах»
        scanned = sum(r.growth is not None for r in self.f.regions.values())
        return (f'<div class="scope"><div class="scope-hd"><span>Скан · {cap.lower()}</span>'
                f'<span>{scanned}/{len(self.f.regions)} · {self.f.data_date:%d.%m.%Y}</span></div>'
                f'<figure class="hero-map">{heromap.svg(self.geojson, info, cap + " по субъектам РФ", pulses)}</figure>'
                f'<div class="scope-ft">{heromap.legend()}<span class="mut">регион — ссылка на его факты</span></div></div>')

    def hero(self) -> str:
        f = self.f
        total = sum(x.active for x in f.regions.values())
        big = f'{total / 1e6:.1f}'.replace(".", ",") + " млн" if total >= 1e6 else num(total)
        sig = self.signals()
        rows = "".join(f'<li><a href="/fakty/region/{quote(r.region_id)}/">{E(r.name)}</a><b>{pct(r.growth)}</b></li>'
                       for r in sig)
        nn = len(f.needs)
        return f"""<section class="hero"><div class="in"><div class="hero-txt">
<p class="eyebrow">Нишемер · реестр МСП ФНС</p>
<h1>Где в России загорается малый бизнес</h1>
<p class="lead">{nn} {plural(nn, ("ниша", "ниши", "ниш"))} по {len(f.regions)} субъектам РФ с 2016 года. Только измеренные факты:
сколько субъектов, как меняется их число, сколько новых работает через год.</p>
<a class="cta" href="/karta/">Открыть карту →</a></div>
{self.hero_map(sig)}
<aside class="readout"><p class="eyebrow">Сигналы · рост за 12 мес.</p><ol>{rows}</ol>
<dl><div><dt>Субъектов МСП</dt><dd>{big}</dd></div><div><dt>Ниш</dt><dd>{nn}</dd></div>
<div><dt>Регионов</dt><dd>{len(f.regions)}</dd></div><div><dt>Снимок</dt><dd>{f.data_date:%d.%m.%Y}</dd></div></dl></aside>
</div></section>"""

    def index(self, nom: str | None, row: str | None) -> None:
        n = self.f.needs.get(nom or "")
        r = self.f.regions.get(row or "")
        needs = "".join(f'<li><a href="/fakty/nisha/{quote(k)}/">{E(v.name)}</a></li>'
                        for k, v in sorted(self.f.needs.items(), key=lambda kv: kv[1].name))
        regs = "".join(f'<li><a href="/fakty/region/{quote(k)}/">{E(self.f.regions[k].name)}</a></li>'
                       for k in sorted(self.f.regions, key=lambda k: self.f.regions[k].name))
        body = f"""{f'<h2>Ниша месяца: <a href="/fakty/nisha-mesyaca/">{E(n.name)}</a></h2><p>{pct(n.growth)} за 12 месяцев по России, {num(n.active)} субъектов.</p>' if n else ''}
{f'<h2>Регион недели: <a href="/fakty/region-nedeli/">{E(r.name)}</a></h2><p>{num(r.active)} субъектов МСП, {pct(r.growth)} за 12 месяцев.</p>' if r else ''}
<h2>Все ниши</h2><ul class="cols">{needs}</ul><h2>Все регионы</h2><ul class="cols">{regs}</ul>"""
        self.page("/", "Нишемер — малый бизнес по регионам России: факты реестра МСП",
                  f"Сколько малого бизнеса каждой ниши в каждом регионе России и как это меняется с 2016 года. "
                  f"{len(self.f.needs)} ниш, {len(self.f.regions)} регионов, реестр МСП ФНС.", body, self.hero())

    def methodology(self) -> None:
        if not self.md:
            return
        body = '<div class="md">' + markdown.markdown(self.md, extensions=["tables", "fenced_code"]) + "</div>"
        self.page("/metodologiya/", "Методология — Нишемер",
                  "Как Нишемер считает факты о малом бизнесе: источники, отнесение к нишам, рост и выживаемость.", body)

    def build(self) -> None:
        for n in self.f.needs.values():
            self.need_page(n)
        for r in self.f.regions.values():
            self.region_page(r)
        nom, row = niche_of_month(self.f), region_of_week(self.f, self.today)
        if nom:
            self.need_page(self.f.needs[nom], "/fakty/nisha-mesyaca/", "Ниша месяца")
        if row:
            self.region_page(self.f.regions[row], "/fakty/region-nedeli/", "Регион недели")
        self.methodology()
        self.index(nom, row)

    def write(self, out_dir: str | Path) -> dict[str, object]:
        out = Path(out_dir)
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for path, doc in self.pages.items():
            p = out / path.strip("/") / "index.html" if path != "/" else out / "index.html"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(doc, "utf-8")
        (out / "facts.css").write_text(CSS, "utf-8")
        (out / "fonts").mkdir()
        for name in FONTS:  # Fira Sans Condensed 800 (SIL OFL 1.1) — шрифт экосистемы
            shutil.copyfile(ASSETS / name, out / "fonts" / name)
        lastmod = self.f.data_date.isoformat()
        urls = "".join(f"<url><loc>{E(self.link(p))}</loc><lastmod>{lastmod}</lastmod></url>" for p in sorted(self.pages))
        (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                         f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', "utf-8")
        (out / "robots.txt").write_text(f"User-agent: *\nDisallow: /karta/\nDisallow: /api/\nAllow: /\n\n"
                                        f"Sitemap: {self.link('/sitemap.xml')}\n", "utf-8")
        report = {"snapshot": self.f.snapshot, "pages": len(self.pages), "needs": len(self.f.needs),
                  "regions": len(self.f.regions), "niche_of_month": niche_of_month(self.f),
                  "region_of_week": region_of_week(self.f, self.today)}
        (out / "facts.json").write_text(json.dumps(report, ensure_ascii=False), "utf-8")
        return report


def build(marts_dir: str | Path, config_dir: str | Path, out_dir: str | Path, site_url: str,
          methodology: str | Path | None = None, today: dt.date | None = None) -> dict[str, object]:
    cfg = Path(config_dir)
    eco = json.loads((cfg / "ecosystem.json").read_text("utf-8"))
    md = Path(methodology).read_text("utf-8") if methodology else None
    geo = cfg / "geo" / "regions.geojson"
    site = Site(load(marts_dir, cfg), site_url, eco, md, today or dt.datetime.now(dt.UTC).date(),
                geo if geo.is_file() else None)
    site.build()
    return site.write(out_dir)
