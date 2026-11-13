import {lazy, Suspense} from "react";
const Javiera20=lazy(()=>import("./Javiera20"));
const JavieraLegacy=lazy(()=>import("./JavieraLegacy"));

/** One entry flow, whether or not an Excel master has already been imported. */
export default function Javiera(props:{configuration?:boolean;onBack?:()=>void;onConfig?:()=>void}){
  const legacy=new URLSearchParams(window.location.search).get("legacy")==="1";
  return <Suspense fallback={<div role="status">Abriendo documentos…</div>}>
    {legacy&&!props.configuration?<JavieraLegacy {...props}/>:<Javiera20 {...props}/>}
  </Suspense>;
}
