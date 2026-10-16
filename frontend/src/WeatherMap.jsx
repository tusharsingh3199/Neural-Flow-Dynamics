
import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import WebGLWeatherLayer from "./WebGLWeatherLayer";

setWorkerUrl(workerUrl);

export default function WeatherMap({ weather, layer, frameIndex = 0 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const weatherLayerRef = useRef(null);
  const latestPropsRef = useRef({ weather, layer, frameIndex });

  // Always keep the latest React props available to map callbacks.
  useEffect(() => {
    latestPropsRef.current = { weather, layer, frameIndex };

    const map = mapRef.current;
    const weatherLayer = weatherLayerRef.current;
    if (!map || !weatherLayer) return;

    const updateLayer = () => {
      if (!map.getLayer(weatherLayer.id)) return;

      weatherLayer.setState({
        weather,
        layer,
        frameIndex,
        showWind: layer === "wind",
      });
    };

    if (map.isStyleLoaded()) {
      updateLayer();
    } else {
      map.once("load", updateLayer);
    }
  }, [weather, layer, frameIndex]);

  // Initialize the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: [78, 21],
      zoom: 3.4,
      minZoom: 2,
      maxZoom: 12,
      attributionControl: true,
      renderWorldCopies: true,
      canvasContextAttributes: { antialias: true },
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [
          {
            id: "osm-base",
            type: "raster",
            source: "osm",
            paint: {
              "raster-opacity": 1,
              "raster-fade-duration": 0,
            },
          },
        ],
      },
    });

    const weatherLayer = new WebGLWeatherLayer();
    mapRef.current = map;
    weatherLayerRef.current = weatherLayer;

    map.addControl(
      new maplibregl.NavigationControl({ visualizePitch: false }),
      "bottom-right"
    );

    const handleLoad = () => {
      if (!map.getLayer(weatherLayer.id)) {
        map.addLayer(weatherLayer);
      }

      const latest = latestPropsRef.current;
      weatherLayer.setState({
        weather: latest.weather,
        layer: latest.layer,
        frameIndex: latest.frameIndex,
        showWind: latest.layer === "wind",
      });
    };

    const handleError = (event) => {
      console.warn(
        "[NFD] MapLibre error:",
        event.error?.message || event.error
      );
    };

    map.on("load", handleLoad);
    map.on("error", handleError);

    return () => {
      map.off("load", handleLoad);
      map.off("error", handleError);
      map.remove();
      mapRef.current = null;
      weatherLayerRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="weather-map" />;
}
