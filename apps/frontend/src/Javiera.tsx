import {lazy, Suspense, useEffect, useState} from "react";
import {request} from "./api";
import JavieraSimple from "./JavieraSimple";

const Javiera20=lazy(()=>import("./Javiera20"));
const JavieraLegacy=lazy(()=>import("./JavieraLegacy"));

/** Keep existing dossiers available until an organization imports its Excel master. */
export default function Javiera({configuration=false,onBack,onConfig}:{
  configuration?:boolean;onBack?:()=>void;onConfig?:()=>void
}){
  const [native,setNative]=useState<boolean|null>(null);
  const [error,setError]=useState("");
  const legacy=new URLSearchParams(window.location.search).get("legacy")==="1";
  useEffect(()=>{
    if(configuration)return;
    let alive=true;
    request<{current:{id:string}|null}>("/javiera/workbook")
      .then(x=>{if(alive)setNative(Boolean(x.current));})
      .catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
    return()=>{alive=false;};
  },[configuration]);
  if(error)return <div role="alert">{error}</div>;
  if(!configuration&&native===null)return <div role="status">Abriendo documentos…</div>;
  if(configuration||native||legacy)return <Suspense fallback={<div role="status">Abriendo documentos…</div>}>
    {legacy&&!native?<JavieraLegacy configuration={configuration} onBack={onBack} onConfig={onConfig}/>:
      <Javiera20 configuration={configuration} onBack={onBack} onConfig={onConfig}/>}
  </Suspense>;
  return <JavieraSimple onConfig={onConfig} onBack={onBack}/>;
}
