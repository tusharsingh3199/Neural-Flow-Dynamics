
import { useCallback, useEffect, useMemo, useState } from "react";
import WeatherMap from "./WeatherMap";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const LAYERS = [
  { id: "temperature", label: "Temperature", symbol: "°", icon: "thermometer" },
  { id: "wind", label: "Wind", symbol: "↗", icon: "wind" },
  { id: "pressure", label: "Pressure", symbol: "P", icon: "gauge" },
  { id: "rainfall", label: "Rainfall", symbol: "☂", icon: "cloud-rain" },
];

const LEGENDS = {
  temperature: {
    title: "Temperature",
    unit: "°C",
    min: -60,
    max: 45,
    labels: ["−60", "−30", "0", "20", "45"],
  },
  wind: {
    title: "Wind speed",
    unit: "m/s",
    min: 0,
    max: 40,
    labels: ["0", "10", "20", "30", "40"],
  },
  pressure: {
    title: "Surface pressure",
    unit: "hPa",
    min: 870,
    max: 1080,
    labels: ["870", "920", "970", "1020", "1080"],
  },
  rainfall: {
    title: "Precipitation",
    unit: "mm",
    min: 0,
    max: 50,
    labels: ["0", "12.5", "25", "37.5", "50"],
  },
};

function formatDate(dateString) {
  if (!dateString) return "Loading date…";
  const date = new Date(`${dateString}T00:00:00`);
  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
}

function formatTime(time) {
  if (!time) return "--:--";
  return time;
}

export default function App() {
  const [dates, setDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [weatherCache, setWeatherCache] = useState({});
  const [frameIndex, setFrameIndex] = useState(0);
  const [layer, setLayer] = useState("temperature");
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const weather = weatherCache[selectedDate] || null;
  const frames = weather?.frames || [];
  const frame = frames[frameIndex] || null;

  const legend = LEGENDS[layer];

  useEffect(() => {
    let cancelled = false;

    async function loadDates() {
      try {
        setError("");
        const response = await fetch(`${API_BASE}/api/dates`);
        if (!response.ok) throw new Error(`Dates request failed (${response.status})`);

        const payload = await response.json();
        const availableDates = (payload.dates || []).slice().sort();

        if (cancelled) return;
        setDates(availableDates);

        if (availableDates.length) {
          setSelectedDate(availableDates[0]);
        } else {
          setError("The backend returned no available dates.");
        }
      } catch (err) {
        if (!cancelled) setError(err.message || "Could not load dates.");
      }
    }

    loadDates();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedDate || weatherCache[selectedDate]) return;

    const controller = new AbortController();

    async function loadWeather() {
      setLoading(true);
      setError("");

      try {
        const url = `${API_BASE}/api/weather?date=${encodeURIComponent(selectedDate)}`;
        const response = await fetch(url, { signal: controller.signal });

        if (!response.ok) {
          throw new Error(`Weather request failed (${response.status})`);
        }

        const payload = await response.json();

        if (!payload.latitude?.length || !payload.longitude?.length) {
          throw new Error("The weather response is missing grid coordinates.");
        }

        setWeatherCache((previous) => ({
          ...previous,
          [selectedDate]: payload,
        }));
        setFrameIndex(0);
      } catch (err) {
        if (err.name !== "AbortError") {
          setError(err.message || "Could not load weather data.");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    loadWeather();
    return () => controller.abort();
  }, [selectedDate, weatherCache]);

  const changeDate = useCallback((nextDate) => {
    if (!nextDate) return;
    setSelectedDate(nextDate);
    setFrameIndex(0);
  }, []);

  const moveFrame = useCallback((direction) => {
    if (!frames.length) return;

    setFrameIndex((current) => {
      const next = current + direction;

      if (next >= 0 && next < frames.length) return next;

      if (direction > 0) {
        const dateIndex = dates.indexOf(selectedDate);
        const nextDate = dates[dateIndex + 1];
        if (nextDate) {
          setSelectedDate(nextDate);
          return 0;
        }
      }

      if (direction < 0) {
        const dateIndex = dates.indexOf(selectedDate);
        const previousDate = dates[dateIndex - 1];
        if (previousDate) {
          setSelectedDate(previousDate);
          return Math.max(0, (weatherCache[previousDate]?.frames?.length || 1) - 1);
        }
      }

      setPlaying(false);
      return current;
    });
  }, [dates, frames.length, selectedDate, weatherCache]);

  useEffect(() => {
    if (!playing || !frames.length || loading) return undefined;

    const timer = window.setInterval(() => {
      setFrameIndex((current) => {
        if (current + 1 < frames.length) return current + 1;

        const dateIndex = dates.indexOf(selectedDate);
        const nextDate = dates[dateIndex + 1];

        if (nextDate) {
          setSelectedDate(nextDate);
          return 0;
        }

        setPlaying(false);
        return current;
      });
    }, 900);

    return () => window.clearInterval(timer);
  }, [playing, frames.length, loading, dates, selectedDate]);

  const sliderValue = frames.length > 1
    ? Math.min(frameIndex, frames.length - 1)
    : 0;

  const timelineLabel = useMemo(() => {
    if (!frame) return "Waiting for weather data";
    return `${formatDate(selectedDate)} · ${formatTime(frame.time)}`;
  }, [frame, selectedDate]);

  return (
    <main className="nfd-app">
      <WeatherMap
        weather={weather}
        layer={layer}
        frameIndex={frameIndex}
      />

      <aside className="layer-toolbar" aria-label="Weather layers">
        {LAYERS.map((item) => (
          <button
            key={item.id}
            className={`layer-button ${layer === item.id ? "active" : ""}`}
            onClick={() => setLayer(item.id)}
            title={item.label}
            aria-label={item.label}
            aria-pressed={layer === item.id}
          >
            <span className="layer-symbol">{item.symbol}</span>
            <span className="layer-label">{item.label}</span>
          </button>
        ))}
      </aside>

      <div className="map-status">
        <span className={`status-dot ${loading ? "loading" : ""}`} />
        <span>{loading ? "Loading weather" : "ERA5 weather"}</span>
        {weather?.source && <span className="source-name">{weather.source}</span>}
      </div>

      <section className="legend-panel" aria-label={`${legend.title} legend`}>
        <div className="legend-heading">
          <div>
            <strong>{legend.title}</strong>
            <span>{legend.unit}</span>
          </div>
          <small>{formatDate(selectedDate)}</small>
        </div>
        <div className="legend-gradient" />
        <div className="legend-labels">
          {legend.labels.map((label) => <span key={label}>{label}</span>)}
        </div>
      </section>

      <section className="timeline-panel" aria-label="Weather timeline">
        <div className="timeline-top">
          <div>
            <div className="timeline-date">{timelineLabel}</div>
            <div className="timeline-subtitle">
              {frame ? `Frame ${frameIndex + 1} of ${frames.length}` : "No frame loaded"}
            </div>
          </div>

          <div className="timeline-actions">
            <button
              className="control-button"
              onClick={() => moveFrame(-1)}
              disabled={!frames.length}
              title="Previous frame"
              aria-label="Previous frame"
            >
              ‹
            </button>
            <button
              className="play-button"
              onClick={() => setPlaying((value) => !value)}
              disabled={!frames.length}
              title={playing ? "Pause animation" : "Play animation"}
              aria-label={playing ? "Pause animation" : "Play animation"}
            >
              {playing ? "Ⅱ" : "▶"}
            </button>
            <button
              className="control-button"
              onClick={() => moveFrame(1)}
              disabled={!frames.length}
              title="Next frame"
              aria-label="Next frame"
            >
              ›
            </button>
          </div>
        </div>

        <input
          className="timeline-slider"
          type="range"
          min="0"
          max={Math.max(0, frames.length - 1)}
          step="1"
          value={sliderValue}
          disabled={!frames.length}
          onChange={(event) => setFrameIndex(Number(event.target.value))}
          aria-label="Weather forecast time"
        />

        <div className="timeline-bottom">
          <span>{frames[0]?.time || "--:--"}</span>
          <span>{frame?.time || "--:--"}</span>
          <span>{frames[frames.length - 1]?.time || "--:--"}</span>
        </div>

        {error && <div className="error-message">{error}</div>}
      </section>
    </main>
  );
}
