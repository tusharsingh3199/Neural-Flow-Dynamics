
import { useEffect, useState } from "react";
import "./App.css";

const API = "http://127.0.0.1:8000";

export default function App() {
  const [date, setDate] = useState("2026-06-15");
  const [weather, setWeather] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function fetchWeather() {
    setLoading(true);
    setError("");
    setWeather(null);

    try {
      const response = await fetch(
        `${API}/api/weather?date=${date}`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to fetch weather");
      }

      setWeather(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchWeather();
  }, []);

  return (
    <main>
      <h1>Neural Flow Dynamics</h1>
      <p>Global ERA5 Weather Explorer</p>

      <label>
        Select date:{" "}
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </label>

      <button onClick={fetchWeather} disabled={loading}>
        {loading ? "Loading..." : "Get Weather"}
      </button>

      {error && <p className="error">{error}</p>}

      {weather && (
        <section>
          <h2>Weather for {weather.date}</h2>
          <p>Available timestamps: {weather.available_times_utc.join(", ")}</p>

          {weather.frames.map((frame) => (
            <article key={frame.time}>
              <h3>{frame.time} UTC</h3>
              <p>
                Temperature at first grid point:{" "}
                {frame.t2m[0][0]?.toFixed(2)} °C
              </p>
              <p>
                Wind speed at first grid point:{" "}
                {frame.wind_speed[0][0]?.toFixed(2)} m/s
              </p>
              <p>
                Surface pressure at first grid point:{" "}
                {frame.sp[0][0]?.toFixed(2)} hPa
              </p>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
