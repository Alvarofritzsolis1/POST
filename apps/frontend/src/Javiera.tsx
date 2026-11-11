import {lazy,Suspense} from "react";
import JavieraSimple from "./JavieraSimple";

const JavieraLegacy=lazy(()=>import("./JavieraLegacy"));

/** Fast path: no HTML editors or advanced admin bundles on initial load. */
export default function Javiera({configuration=false,onBack,onConfig}:{
  configuration?:boolean;onBack?:()=>void;onConfig?:()=>void
}){
  const legacy=configuration||
    new URLSearchParams(window.location.search).get("legacy")==="1";
  if(legacy)return <Suspense fallback={<div role="status">Abriendo configuración avanzada…</div>}>
    <JavieraLegacy configuration={configuration} onBack={onBack} onConfig={onConfig}/>
  </Suspense>;
  return <JavieraSimple onConfig={onConfig} onBack={onBack}/>;
}
