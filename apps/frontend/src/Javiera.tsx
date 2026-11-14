import {lazy, Suspense} from "react";
const JavieraWorkbookAdmin=lazy(()=>import("./JavieraWorkbookAdmin"));
const JavieraSimple=lazy(()=>import("./JavieraSimple"));
const JavieraLegacy=lazy(()=>import("./JavieraLegacy"));

/**
 * La edición de Excel sigue en Administración.
 * Todas las altas documentales usan exclusivamente javiera_local_*,
 * NUNCA /ops/contractors ni /ops/workers.
 * Los expedientes y emisiones anteriores permanecen en la base de datos.
 */
export default function Javiera(props:{configuration?:boolean;onBack?:()=>void;onConfig?:()=>void}){
  const legacy=new URLSearchParams(window.location.search).get("legacy")==="1";
  return <Suspense fallback={<div role="status">Abriendo Proyecto Javiera…</div>}>
    {props.configuration
      ? <JavieraWorkbookAdmin onBack={props.onBack||(()=>window.history.back())}/>
      : legacy?<JavieraLegacy {...props}/>
      : <JavieraSimple onBack={props.onBack} onConfig={props.onConfig}/>}
  </Suspense>;
}
