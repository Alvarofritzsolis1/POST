import { useEffect, useState } from "react";
import { ArrowLeft, Bot, FlaskConical, GraduationCap, LayoutDashboard, Settings2, Zap } from "lucide-react";
import AIConfiguration from "./AIConfiguration";
import AIQualityOverview from "./AIQualityOverview";
import AIHumanAudit from "./AIHumanAudit";
import GalancitoTraining from "./GalancitoTraining";
import MaxPowerPanel from "./MaxPowerPanel";
import "./ai-admin-panel.css";

type Section = "resumen" | "conexiones" | "practica" | "aprendizaje" | "max-power";
type Channel = "messenger" | "general";

const sectionFromPath = (): Section => {
  const path = window.location.pathname;
  if (path.endsWith("/max-power")) return "max-power";
  if (path.endsWith("/entrenamiento")) return "practica";
  if (path.endsWith("/conexiones")) return "conexiones";
  if (path.endsWith("/aprendizaje")) return "aprendizaje";
  return "resumen";
};
const route: Record<Section, string> = {
  resumen: "/admin/ia", conexiones: "/admin/ia/conexiones",
  practica: "/admin/ia/entrenamiento", aprendizaje: "/admin/ia/aprendizaje",
  "max-power": "/admin/ia/max-power",
};

/** Centro de IA separado de la configuración general, sin rutas ni datos duplicados. */
export default function AIAdminPanel({ onBack }: { onBack: () => void }) {
  const [section, setSection] = useState<Section>(sectionFromPath);
  const [practiceTarget, setPracticeTarget] = useState<{ channel: Channel; focus: string }>({ channel: "general", focus: "" });

  useEffect(() => {
    const update = () => setSection(sectionFromPath());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  const navigate = (next: Section) => {
    if (window.location.pathname !== route[next])
      window.history.pushState({ galantSection: "ai_admin" }, "", route[next]);
    setSection(next);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const openPractice = (channel: Channel, focus = "") => {
    setPracticeTarget({ channel, focus });
    navigate("practica");
  };

  const tabs: Array<{ id: Section; label: string; icon: typeof Bot }> = [
    { id: "resumen", label: "Resumen", icon: LayoutDashboard },
    { id: "conexiones", label: "Conexiones", icon: Settings2 },
    { id: "practica", label: "Práctica Bot", icon: FlaskConical },
    { id: "aprendizaje", label: "Aprendizaje", icon: GraduationCap },
    { id: "max-power", label: "MAX POWER", icon: Zap },
  ];

  return <section className="ai-admin-panel" aria-label="Administración de inteligencia artificial">
    <header className="ai-admin-heading">
      <button type="button" className="ai-admin-back" onClick={onBack}><ArrowLeft size={17} aria-hidden="true" /> Volver</button>
      <div><span className="ai-admin-eyebrow"><Bot size={14} aria-hidden="true" /> ADMINISTRACIÓN</span>
        <h1>Inteligencia artificial</h1></div>
    </header>
    <nav className="ai-admin-tabs" aria-label="Herramientas de inteligencia artificial">
      {tabs.map(({ id, label, icon: Icon }) =>
        <button type="button" key={id} aria-current={section === id ? "page" : undefined}
          className={section === id ? "active" : ""} onClick={() => navigate(id)}>
          <Icon size={16} aria-hidden="true" /> {label}
        </button>)}
    </nav>
    <div className="ai-admin-content" key={section}>
      {section === "resumen" && <AIQualityOverview onPractice={openPractice}
        onConnections={() => navigate("conexiones")} onLearning={() => navigate("aprendizaje")} />}
      {section === "conexiones" && <AIConfiguration section="conexiones" openTraining={() => openPractice("general")} />}
      {section === "practica" && <GalancitoTraining initialProfile={practiceTarget.channel === "messenger" ? "postulantes" : "interno"}
        initialFocus={practiceTarget.focus} back={() => navigate("resumen")} />}
      {section === "max-power" && <MaxPowerPanel />}
      {section === "aprendizaje" && <div className="ai-admin-learning">
        <AIConfiguration section="aprendizaje" openTraining={() => openPractice("general")} />
        <AIHumanAudit onPractice={openPractice} />
      </div>}
    </div>
  </section>;
}
