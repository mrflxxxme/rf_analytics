// Карта: MapLibre без подложки (docs/04-ux.md, «Визуальный стиль») + deck.gl GeoJsonLayer для заливки.
import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer } from "@deck.gl/layers";
import type { Feature, Geometry } from "geojson";
import type { Geo, RegionProps } from "./api";
import type { Palette, RGB } from "./model";

type F = Feature<Geometry, RegionProps>;

interface Props {
  geo: Geo;
  palette: Palette;
  fill: (regionId: string) => RGB | null;
  fillKey: string; // меняется — deck.gl пересчитывает цвета (с переходом)
  selected: string | null;
  onHover: (info: { region: RegionProps; x: number; y: number } | null) => void;
  onClick: (regionId: string) => void;
}

const BOUNDS: [number, number, number, number] = [19, 41, 191, 78];

export function MapView({ geo, palette, fill, fillKey, selected, onHover, onClick }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const handlers = useRef({ onHover, onClick });
  handlers.current = { onHover, onClick };

  useEffect(() => {
    if (!box.current) return;
    const map = new maplibregl.Map({
      container: box.current,
      style: { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": palette.bg } }] },
      bounds: BOUNDS,
      fitBoundsOptions: { padding: 12 },
      renderWorldCopies: false,
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
      minZoom: 0, // на телефоне вся РФ по ширине — это зум ≈ 0,4
      maxZoom: 8,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: "© участники OpenStreetMap" }));
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const ov = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(ov);
    overlay.current = ov;
    // Пока пользователь не двигал карту, держим всю РФ в кадре при любом размере (телефон, поворот).
    let touched = false;
    map.on("movestart", (e) => {
      if ((e as { originalEvent?: Event }).originalEvent) touched = true;
    });
    const ro = new ResizeObserver(() => {
      map.resize();
      if (!touched) map.fitBounds(BOUNDS, { padding: 12, animate: false });
    });
    ro.observe(box.current);
    return () => {
      ro.disconnect();
      overlay.current = null;
      map.remove();
    };
  }, []); // тема (?theme=) читается при загрузке и не меняется — фон карты задаём один раз

  useEffect(() => {
    overlay.current?.setProps({
      layers: [
        new GeoJsonLayer<RegionProps>({
          id: "regions",
          data: geo as unknown as GeoJSON.FeatureCollection<Geometry, RegionProps>,
          pickable: true,
          stroked: true,
          filled: true,
          getFillColor: (f: F) => {
            const c = fill(f.properties.region_id);
            return [...(c ?? palette.noData), 255];
          },
          getLineColor: (f: F) => (f.properties.region_id === selected ? [255, 255, 255, 255] : [...palette.border, 255]),
          getLineWidth: (f: F) => (f.properties.region_id === selected ? 2.5 : 0.6),
          lineWidthUnits: "pixels",
          autoHighlight: true,
          highlightColor: [255, 255, 255, 60],
          transitions: { getFillColor: 450 },
          updateTriggers: { getFillColor: fillKey, getLineColor: selected, getLineWidth: selected },
          onHover: (info) => {
            const f = info.object as F | undefined;
            handlers.current.onHover(f ? { region: f.properties, x: info.x, y: info.y } : null);
          },
          onClick: (info) => {
            const f = info.object as F | undefined;
            if (f) handlers.current.onClick(f.properties.region_id);
          },
        }),
      ],
    });
  }, [geo, palette, fill, fillKey, selected]);

  return <div ref={box} className="map" role="application" aria-label="Карта субъектов РФ" />;
}
