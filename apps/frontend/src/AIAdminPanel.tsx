import { lazy, Suspense, useEffect, useState } from "react";
import { ArrowLeft, Bot, LayoutDashboard, MessageCircle, Zap } from "lucide-react";
import AIQualityOverview from "./AIQualityOverview";
import MaxPowerPanel from "./MaxPowerPanel";
import "./ai-admin-panel.css";

const MessengerSimulator = lazy(() => import("./MessengerSimulator"));
const AIConfiguration = lazy(() => import("./AIConfiguration"));
const AIHumanAudit = lazy(() => import("./AIHumanAudit"));
const GalancitoTraining = lazy(() => import("./GalancitoTraining"));

type Section = "resumen" | "max-power" | "simulador";
type Channel = "messenger" | "general";
type Detail = "config" | "history" | "audit" | "learning" | null;
const route: Record<Section, string> = {
  resumen: "/admin/ia",
  "max-power": "/admin/ia/max-power",
  simulador: "/admin/ia/simulador-messenger",
};

export function resolveAIAdminPath(path: string): { section: Section; detail: Detail } {
  const clean = path.replace(/\/+$/, "");
  if (clean.endsWith("/simulador-messenger")) return {section:"simulador", detail:null};
  if (clean.endsWith("/entrenamiento")) return {section:"max-power", detail:"history"};
  if (clean.endsWith("/aprendizaje")) return {section:"max-power", detail:"learning"};
  if (clean.endsWith("/max-power")) return {section:"max-power", detail:null};
  if (clean.endsWith("/conexiones")) return {section:"resumen", detail:"config"};
  return {section:"resumen", detail:null};
}

export default function AIAdminPanel({ onBack }: { onBack: () => void }) {
  const [view, setView] = useState(() => resolveAIAdminPath(window.location.pathname));
  const [channel, setChannel] = useState<Channel>("general");
  const {section, detail} = view;
  useEffect(() => {
    const update = () => {
      if (!/^\/admin\/(?:configuracion\/)?ia(?:\/|$)/.test(window.location.pathname)) return;
      const next = resolveAIAdminPath(window.location.pathname);
      setView(next);
      // Old links remain valid; canonicalize without adding a second history entry.
      if (window.location.pathname !== route[next.section])
        window.history.replaceState({galantSection:"ai_admin"}, "", route[next.section]);
    };
    update();
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const navigate = (next: Section, nextDetail: Detail = null) => {
    if (window.location.pathname !== route[next])
      window.history.pushState({galantSection:"ai_admin"}, "", route[next]);
    setView({section:next, detail:nextDetail});
    window.scrollTo({top:0, behavior:"instant"});
  };
  const openPractice = (nextChannel: Channel, _focus = "") => {
    setChannel(nextChannel);
    navigate("max-power", "history");
  };
  const toggleDetail = (next: Detail) => setView(current => ({
    ...current, detail:current.detail === next ? null : next
  }));
  const tabs: Array<{id:Section; label:string; icon:typeof Bot}> = [
    {id:"resumen", label:"Resumen", icon:LayoutDashboard},
    {id:"simulador", label:"Simulador Messenger", icon:MessageCircle},
    {id:"max-power", label:"MAX POWER", icon:Zap},
  ];
  return <section className="ai-admin-panel" aria-label="Administración de inteligencia artificial">
    <header className="ai-admin-heading">
      <button type="button" className="ai-admin-back" onClick={onBack}><ArrowLeft size={17} aria-hidden="true"/> Volver</button>
      <div><span className="ai-admin-eyebrow"><Bot size={14} aria-hidden="true"/> ADMINISTRACIÓN</span>
        <h1>Inteligencia artificial</h1></div>
    </header>
    <nav className="ai-admin-tabs" aria-label="Herramientas de inteligencia artificial">
      {tabs.map(({id,label,icon:Icon}) => <button type="button" key={id}
        aria-current={section === id ? "page" : undefined} className={section === id ? "active" : ""}
        onClick={() => navigate(id)}><Icon size={16} aria-hidden="true"/> {label}</button>)}
    </nav>
    <div className="ai-admin-content" key={section}>
      {section === "resumen" && <>
        <AIQualityOverview onPractice={openPractice} onConnections={() => toggleDetail("config")}
          onLearning={() => navigate("max-power")}/>
        {detail === "config" && <Suspense fallback={<p role="status">Cargando configuración…</p>}>
          <section className="ai-admin-detail" aria-label="Configuración del motor">
            <button type="button" className="ai-admin-back" onClick={() => toggleDetail("config")}>Cerrar configuración</button>
            <AIConfiguration section="conexiones" openTraining={() => navigate("max-power")}/>
          </section>
        </Suspense>}
      </>}
      {section === "simulador" && <Suspense fallback={<p role="status">Abriendo el simulador…</p>}><MessengerSimulator/></Suspense>}
      {section === "max-power" && <>
        <MaxPowerPanel/>
        <section className="ai-admin-detail" aria-label="Evidencia y mantenimiento de MAX POWER">
          <h2>Resultados y mantenimiento</h2>
          <p>MAX POWER programa las evaluaciones locales y administra sus recursos. Consulta el historial sin iniciar una segunda práctica. Las revisiones y aprobaciones conservan sus controles de seguridad.</p>
          <div className="ai-admin-tabs">
            {([{id:"history",label:"Historial y errores"},{id:"learning",label:"Conocimiento validado"},{id:"audit",label:"Revisión de producción"}] as const).map(item =>
              <button type="button" key={item.id} aria-expanded={detail === item.id}
                className={detail === item.id ? "active" : ""} onClick={() => toggleDetail(item.id)}>{item.label}</button>)}
          </div>
          <Suspense fallback={<p role="status">Cargando evidencia…</p>}>
            {detail === "history" && <GalancitoTraining key={channel} initialProfile={channel === "messenger" ? "postulantes" : "interno"}
              automatic back={() => toggleDetail("history")}/>}
            {detail === "learning" && <AIConfiguration section="aprendizaje" openTraining={() => toggleDetail("history")}/>}
            {detail === "audit" && <AIHumanAudit onPractice={openPractice}/>}
          </Suspense>
        </section>
      </>}
    </div>
  </section>;
}
