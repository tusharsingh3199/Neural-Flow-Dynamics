import {MapContainer,TileLayer} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import WeatherLayer from "./WeatherLayer";

export default function WeatherMap({weather, layer, frameIndex}){
  return(
    <MapContainer
      center={[20,78]}
      zoom={3}
      style={{height:"100vh",width:"100vw"}}
    >
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>

      <WeatherLayer
        frame={weather.frames[frameIndex]}
        layer={layer}
      />
    </MapContainer>
  );
}