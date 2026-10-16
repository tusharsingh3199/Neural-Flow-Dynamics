
import { MapContainer, TileLayer, ZoomControl } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import WeatherLayer from "./WeatherLayer";
import WeatherLegend from "./WeatherLegend";

export default function WeatherMap({ weather, layer, frameIndex, showWind }) {
  return (
    <MapContainer
      center={[20, 78]}
      zoom={3}
      minZoom={2}
      maxZoom={12}
      worldCopyJump
      zoomControl={false}
      style={{ position: "absolute", inset: 0, background: "#dbe7ef" }}
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />

      {weather && (
        <WeatherLayer
          weather={weather}
          layer={layer}
          frameIndex={frameIndex}
          showWind={showWind && layer === "wind_speed"}
        />
      )}

      {weather && <WeatherLegend layer={layer} />}
      <ZoomControl position="bottomright" />
    </MapContainer>
  );
}
