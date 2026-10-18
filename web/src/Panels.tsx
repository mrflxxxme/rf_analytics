// Топ-10, шкала времени, легенда, подвал (D28).
import { useEffect, useRef, useState } from "react";
import eco from "../../config/ecosystem.json";
import { formatPeriod, formatValue, type MetricId, type Scale } from "./model";

export function TopList(props: {
  title: string;
  items: { id: string; label: string; value: number }[];
  metric: MetricId;
  selected: string | null;
  onPick: (id: string) => void;
  hint: string;
}) {
  const { title, items, metric, selected, onPick, hint } = props;
  const max = Math.max(1e-9, ...items.map((i) => Math.abs(i.value)));
  return (
    <section className="top" aria-label={title}>
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="muted">Нет данных на этот период.</p>
      ) : (
        <ol>
          {items.map((it) => (
            <li key={it.id}>
              <button className={it.id === selected ? "on" : ""} onClick={() => onPick(it.id)} title={hint}>
                <span className="lbl">{it.label}</span>
                <span className="val">{formatValue(metric, it.value)}</span>
                <span className="meter" style={{ width: `calc((100% - 40px) * ${Math.abs(it.value) / max})` }} />
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function Timeline(props: { periods: string[]; t: string | null; onChange: (t: string) => void }) {
  const { periods, t, onChange } = props;
  const found = t ? periods.indexOf(t) : -1;
  const idx = found >= 0 ? found : periods.length - 1;
  const [playing, setPlaying] = useState(false);
  const state = useRef({ idx, periods, onChange });
  state.current = { idx, periods, onChange };

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const s = state.current;
      if (s.idx >= s.periods.length - 1) return setPlaying(false);
      s.onChange(s.periods[s.idx + 1]!);
    }, 900);
    return () => window.clearInterval(id);
  }, [playing]);

  const play = () => {
    if (playing) return setPlaying(false);
    // С конца — начинаем сначала: «как росла ниша с 2017».
    if (idx >= periods.length - 1) onChange(periods[0]!);
    setPlaying(true);
  };
  const stop = () => setPlaying(false);

  if (periods.length === 0) return <div className="timeline" />;
  const cur = periods[idx]!;
  return (
    <div className="timeline">
      <button className="play" onClick={play} aria-label={playing ? "Пауза" : "Проиграть динамику"}>
        {playing ? "❚❚" : "▶"}
      </button>
      <span className="tl-edge">{periods[0]!.slice(0, 4)}</span>
      <input
        type="range"
        min={0}
        max={periods.length - 1}
        value={idx}
        aria-label="Период"
        aria-valuetext={formatPeriod(cur)}
        onChange={(e) => {
          stop();
          onChange(periods[Number(e.target.value)]!);
        }}
      />
      <span className="tl-cur">{formatPeriod(cur)}</span>
    </div>
  );
}

export function Legend(props: { scale: Scale; metric: MetricId; unitNote: string }) {
  const { scale, metric, unitNote } = props;
  const stops = scale.diverging ? "var(--div)" : "var(--seq)";
  return (
    <div className="legend" aria-label="Легенда">
      <div className="ramp" style={{ background: stops }} />
      <div className="ends">
        <span>{formatValue(metric, scale.min)}</span>
        {scale.diverging && <span>0 %</span>}
        <span>{formatValue(metric, scale.max)}</span>
      </div>
      <div className="muted small">{unitNote}</div>
    </div>
  );
}

type Product = { id: string; label: string; url: string | null; current?: boolean };

export function Footer(props: { snapshot: string | null }) {
  const products = eco.products as Product[];
  return (
    <footer className="foot">
      <div className="eco" aria-label="Экосистема">
        {products.map((p) =>
          p.url && !p.current ? (
            <a key={p.id} href={p.url}>{p.label}</a>
          ) : (
            <span key={p.id} className={p.current ? "cur" : ""}>{p.label}</span>
          ),
        )}
      </div>
      <div className="by">
        <a href={eco.author.url}>{eco.author.label}</a>
        <span className="muted">
          {" · "}данные: реестр МСП ФНС{props.snapshot ? ` · snapshot ${props.snapshot}` : ""} ·{" "}
          <a href="/metodologiya/">методология</a> · <a href="/">факты</a>
        </span>
      </div>
    </footer>
  );
}
