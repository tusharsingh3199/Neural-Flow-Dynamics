import {useEffect,useRef} from "react";

export default function WeatherLayer({frame,layer}){

  const canvasRef=useRef();

  useEffect(()=>{

    const canvas=canvasRef.current;
    const ctx=canvas.getContext("2d");

    canvas.width=window.innerWidth;
    canvas.height=window.innerHeight;

    const field=frame[layer];
    const h=field.length;
    const w=field[0].length;

    let min=Infinity,max=-Infinity;

    for(let i=0;i<h;i++)
      for(let j=0;j<w;j++){
        const v=field[i][j];
        if(v<min)min=v;
        if(v>max)max=v;
      }

    ctx.clearRect(0,0,canvas.width,canvas.height);

    for(let i=0;i<h;i++)
      for(let j=0;j<w;j++){

        const n=(field[i][j]-min)/(max-min);

        ctx.fillStyle=`hsl(${240-240*n},100%,50%)`;

        ctx.fillRect(j/w*canvas.width, i/h*canvas.height, 4, 4);
      }

  },[frame, layer]);

  return(
    <canvas
      ref={canvasRef}
      style={{
        position:"absolute",
        top:0,
        left:0,
        pointerEvents:"none",
        zIndex:500
      }}
    />
  );
}