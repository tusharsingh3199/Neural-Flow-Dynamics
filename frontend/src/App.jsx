import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WeatherMap from "./WeatherMap";
import { COLOR_SCALES, encode, legendGradient } from "./Colorscales";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const DEFAULT_TIMES = ["00:00", "06:00", "12:00", "18:00"];
const PLAY_MS = 1100;

const ICONS = {
  temperature: <path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z" />,
  wind: <path d="M3 8h10a3 3 0 1 0-3-3M3 12h15a3 3 0 1 1-3 3M3 16h7" />,
  pressure: <><circle cx="12" cy="13" r="8" /><path d="M12 13l4-4" /></>,
  rainfall: <><path d="M7 15a4 4 0 0 1 0-8 5 5 0 0 1 9.6 1A3.5 3.5 0 0 1 17 15z" /><path d="M9 18l-1 3M13 18l-1 3M17 18l-1 3" /></>,
};
const LAYERS = ["temperature", "wind", "pressure", "rainfall"];


const shortDate = d => new Date(`${d}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export default function App() {
  const [dates, setDates] = useState([]);
  const [cache, setCache] = useState({});
  const [coords, setCoords] = useState(null);
  const [slot, setSlot] = useState(0);
  const [layer, setLayer] = useState("temperature");
  const [playing, setPlaying] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [shown, setShown] = useState(null);
  const [error, setError] = useState("");
  const cacheRef = useRef({});
  const inflight = useRef(new Set());
  const slotRef = useRef(0);
  const datesRef = useRef([]);
  const viewDate = useRef("");

  useEffect(() => { cacheRef.current = cache; }, [cache]);

  // One flat timeline across all dates, so a single slider covers everything.
  const slots = useMemo(
    () => dates.flatMap(date => {
      const times = cache[date]?.frames?.map(f => f.time) || DEFAULT_TIMES;
      return times.map((time, idx) => ({ date, idx, time }));
    }),
    [dates, cache]
  );
  const current = slots[Math.min(slot, slots.length - 1)];

  const fetchDate = useCallback(async date => {
    if (!date || cacheRef.current[date] || inflight.current.has(date)) return;
    inflight.current.add(date);
    try {
      const r = await fetch(`${API_BASE}/api/weather?date=${encodeURIComponent(date)}`);
      if (!r.ok) throw new Error(`Weather request failed (${r.status})`);
      const payload = await r.json();
      if (!payload.latitude?.length || !payload.longitude?.length) throw new Error("Missing grid coordinates");
      setCoords(c => c || payload);
      setCache(prev => {
        const list = datesRef.current;
        const vi = list.indexOf(viewDate.current);
        const next = { ...prev, [date]: payload };
        for (const d of Object.keys(next)) {
          if (d !== date && vi >= 0 && Math.abs(list.indexOf(d) - vi) > 1) delete next[d];
        }
        return next;
      });
    } catch (e) {
      setError(e.message);
    } finally {
      inflight.current.delete(date);
    }
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/dates`)
      .then(r => { if (!r.ok) throw new Error(`Dates request failed (${r.status})`); return r.json(); })
      .then(p => {
        const list = (p.dates || []).slice().sort();
        if (!list.length) throw new Error("No data available");
        datesRef.current = list;
        viewDate.current = list[0];
        setDates(list);
        fetchDate(list[0]);
        fetchDate(list[1]);
      })
      .catch(e => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Called from event handlers (slider, play timer), never from an effect.
  const goTo = useCallback(i => {
    const target = slots[i];
    if (!target) return;
    slotRef.current = i;
    viewDate.current = target.date;
    setSlot(i);
    const k = datesRef.current.indexOf(target.date);
    fetchDate(target.date);
    if (target.idx >= 2) fetchDate(datesRef.current[k + 1]);
    if (target.idx <= 1) fetchDate(datesRef.current[k - 1]);
  }, [slots, fetchDate]);

  // Only swap the displayed frame once its data exists, so the map never blanks.
  const target = current && cache[current.date]?.frames?.[current.idx];
  const loading = !!current && !target;
  if (target && target !== shown) setShown(target);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const next = slots[slotRef.current + 1];
      if (!next) { setPlaying(false); return; }
      if (cacheRef.current[next.date]) goTo(slotRef.current + 1);
      else fetchDate(next.date); // wait for data
    }, PLAY_MS);
    return () => clearInterval(id);
  }, [playing, slots, goTo, fetchDate]);

  const scale = COLOR_SCALES[layer];
  const dayStarts = slots.map((s, i) => (s.idx === 0 && i > 0 ? i : null)).filter(i => i !== null);
  const pct = i => (slots.length > 1 ? (i / (slots.length - 1)) * 100 : 0);

  return (
    <div className="nfd-app">
      <WeatherMap coords={coords} frame={shown} layer={layer} />

      <div className="layers">
        {LAYERS.map(id => (
          <button key={id} title={id} aria-label={id} className={id === layer ? "on" : ""} onClick={() => setLayer(id)}>
            <svg viewBox="0 0 24 24">{ICONS[id]}</svg>
          </button>
        ))}
      </div>

      <div className="legend">
        <div className="bar" style={{ background: legendGradient(scale) }} />
        <div className="ticks">
          {scale.ticks.map((v, i) => (
            <span key={v} style={{ left: `${encode(v, scale) * 100}%` }}>
              {v}{i === scale.ticks.length - 1 ? ` ${scale.unit}` : ""}
            </span>
          ))}
        </div>
      </div>

      {slots.length > 0 && (
        <div className="timeline">
          <button className="play" aria-label={playing ? "pause" : "play"} onClick={() => setPlaying(p => !p)}>
            <svg viewBox="0 0 24 24">{playing ? <path d="M8 5v14M16 5v14" /> : <path d="M8 5l11 7-11 7z" />}</svg>
          </button>
          <div className="track">
            <div className="ticks-day">{dayStarts.map(i => <i key={i} style={{ left: `${pct(i)}%` }} />)}</div>
            <input
              type="range" min={0} max={slots.length - 1} value={Math.min(slot, slots.length - 1)}
              onChange={e => { setPlaying(false); goTo(Number(e.target.value)); }}
              onPointerDown={() => setDragging(true)}
              onPointerUp={() => setDragging(false)}
              onPointerCancel={() => setDragging(false)}
              aria-label="time"
            />
            {dragging && current && (
              <span className="bubble" style={{ left: `${pct(slot)}%` }}>{shortDate(current.date)} {current.time}</span>
            )}
          </div>
          <span className={`dot ${loading ? "busy" : ""}`} />
        </div>
      )}

      {error && <div className="toast" onClick={() => setError("")}>{error}</div>}
    </div>
  );
}