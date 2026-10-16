import {useState,useEffect} from "react";
import WeatherMap from "./WeatherMap";

export default function App(){
  const [weather,setWeather]=useState(null);
  const [layer,setLayer]=useState("t2m");
  const [frameIndex,setFrameIndex]=useState(0);

  useEffect(()=>{
    fetch("http://localhost:8000/api/weather?date=2026-10-01")
      .then(r=>r.json())
      .then(setWeather);
  },[]);

  if(!weather) return <h1>Loading...</h1>;

  return(
    <>
      <div className="menu">
        <button onClick={()=>setLayer("t2m")}>Temperature</button>
        <button onClick={()=>setLayer("sp")}>Pressure</button>
        <button onClick={()=>setLayer("tp")}>Rainfall</button>
        <button onClick={()=>setLayer("wind_speed")}>Wind Speed</button>
      </div>

      <WeatherMap weather={weather} layer={layer} frameIndex={frameIndex}/>
      <div style={{
        position:"fixed",
        bottom:20,
        left:"50%",
        transform:"translateX(-50%)",
        zIndex:9999,
        background:"rgba(0,0,0,.8)",
        color:"white",
        padding:"12px",
        borderRadius:"10px",
        width:"500px"
      }}>

        <div style={{
          display:"flex",
          justifyContent:"space-between",
          marginBottom:"8px"
        }}>
          <span>{weather.date}</span>
          <span>{weather.frames[frameIndex].time} UTC</span>
        </div>

        <input
          type="range"
          min={0}
          max={weather.frames.length-1}
          value={frameIndex}
          onChange={e=>setFrameIndex(+e.target.value)}
          style={{width:"100%"}}
        />

      </div>
    </>
  );
}