
import { useEffect, useRef, useState } from "react";
import WeatherMap from "./WeatherMap";
import "./weather.css";

const API = "http://localhost:8000";

const LAYERS = [
  { id: "t2m", label: "Temperature", symbol: "°" },
  { id: "wind_speed", label: "Wind", symbol: "≋" },
  { id: "sp", label: "Pressure", symbol: "P" },
  { id: "tp", label: "Rainfall", symbol: "☂" },
];

export default function App() {
  const [dates, setDates] = useState([]);
  const [dateIndex, setDateIndex] = useState(0);
  const [weather, setWeather] = useState(null);
  const [layer, setLayer] = useState("t2m");
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [speed, setSpeed] = useState(800);

  const cache = useRef(new Map());
  const request = useRef(0);
  const loadingNext = useRef(false);

  const loadDate = async (date, index) => {
    if (cache.current.has(date)) {
      setWeather(cache.current.get(date));
      setDateIndex(index);
      setFrameIndex(0);
      setLoading(false);
      setError("");
      return;
    }

    const id = ++request.current;
    setLoading(true);
    setError("");

    try {
      const response = await fetch(
        `${API}/api/weather?date=${encodeURIComponent(date)}`
      );
      if (!response.ok) throw new Error(`Weather API error: ${response.status}`);

      const data = await response.json();
      cache.current.set(date, data);

      if (id !== request.current) return;
      setWeather(data);
      setDateIndex(index);
      setFrameIndex(0);
      setLoading(false);
    } catch (e) {
      if (id !== request.current) return;
      setError(e.message);
      setLoading(false);
      setPlaying(false);
    }
  };

  useEffect(() => {
    let cancelled = false;

    fetch(`${API}/api/dates`)
      .then(r => {
        if (!r.ok) throw new Error("Could not load available dates");
        return r.json();
      })
      .then(data => {
        if (cancelled) return;
        const available = [...data.dates].sort();
        setDates(available);

        if (available.length) {
          const preferred = available.indexOf("2026-10-01");
          loadDate(available[preferred >= 0 ? preferred : 0],
                   preferred >= 0 ? preferred : 0);
        } else {
          setLoading(false);
          setError("No weather dates are available.");
        }
      })
      .catch(e => {
        if (!cancelled) {
          setLoading(false);
          setError(e.message);
        }
      });

    return () => {
      cancelled = true;
      request.current++;
    };
  }, []);

  useEffect(() => {
    if (!playing || !weather?.frames?.length || loading) return;

    const timer = setTimeout(() => {
      if (frameIndex < weather.frames.length - 1) {
        setFrameIndex(i => i + 1);
        return;
      }

      const next = dateIndex + 1;
      if (next < dates.length && !loadingNext.current) {
        loadingNext.current = true;
        loadDate(dates[next], next).finally(() => {
          loadingNext.current = false;
        });
      } else {
        setPlaying(false);
      }
    }, speed);

    return () => clearTimeout(timer);
  }, [playing, weather, frameIndex, dateIndex, dates, speed, loading]);

  const frame = weather?.frames?.[frameIndex];

  const chooseDate = index => {
    setPlaying(false);
    loadDate(dates[index], index);
  };

  return (
    <main className="weather-app">
      <WeatherMap
        weather={weather}
        layer={layer}
        frameIndex={frameIndex}
        showWind={layer === "wind_speed"}
      />

      <nav className="layer-rail" aria-label="Weather layers">
        {LAYERS.map(item => (
          <button
            key={item.id}
            title={item.label}
            aria-label={item.label}
            aria-pressed={layer === item.id}
            className={`layer-circle ${layer === item.id ? "active" : ""}`}
            onClick={() => setLayer(item.id)}
          >
            <span className="layer-symbol">{item.symbol}</span>
            <span className="layer-label">{item.label}</span>
          </button>
        ))}
      </nav>

      {(loading || error) && (
        <div className={`status-toast ${error ? "has-error" : ""}`}>
          {error || "Loading weather…"}
        </div>
      )}

      {weather && frame && (
        <section className="timeline">
          <div className="timeline-top">
            <button
              className="play-button"
              onClick={() => setPlaying(v => !v)}
              aria-label={playing ? "Pause animation" : "Play animation"}
            >
              {playing ? "Ⅱ" : "▶"}
            </button>

            <div className="time-readout">
              <strong>{frame.time} <small>UTC</small></strong>
              <span>{weather.date} · ERA5</span>
            </div>

            <select
              aria-label="Playback speed"
              value={speed}
              onChange={e => setSpeed(Number(e.target.value))}
            >
              <option value={1400}>0.5×</option>
              <option value={800}>1×</option>
              <option value={400}>2×</option>
            </select>

            <select
              className="date-select"
              aria-label="Choose date"
              value={weather.date}
              onChange={e => chooseDate(dates.indexOf(e.target.value))}
            >
              {dates.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>

          <input
            className="time-slider"
            type="range"
            min={0}
            max={Math.max(0, weather.frames.length - 1)}
            value={frameIndex}
            onChange={e => {
              setPlaying(false);
              setFrameIndex(Number(e.target.value));
            }}
          />

          <div className="time-ticks">
            {weather.frames.map((f, i) => (
              <button
                key={f.time}
                className={i === frameIndex ? "current" : ""}
                onClick={() => {
                  setPlaying(false);
                  setFrameIndex(i);
                }}
              >
                {f.time}
              </button>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
