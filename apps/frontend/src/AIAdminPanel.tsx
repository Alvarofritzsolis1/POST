import { useEffect, useState } from "react";
import { ArrowLeft, Bot, FlaskConical, Settings2 } from "lucide-react";
import AIConfiguration from "./AIConfiguration";
import GalancitoTraining from "./GalancitoTraining";
import "./ai-admin-panel.css";

/** Administración de IA independiente de Configuración general. */
export default function AIAdminPanel({ onBack }: { onBack: () => void }) {
  const [training, setTraining] = useState(() => window.location.pathname.endsWith("/entrenamiento"));

  useEffect(() => {
    const update = () => setTraining(window.location.pathname.endsWith("/entrenamiento"));
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);

  const navigate = (next: boolean) => {
    window.history.pushState({ galantSection: "ai_admin" }, "", next ? "/admin/ia/entrenamiento" : "/admin/ia");
    setTraining(next);
    window.scrollTo({ top: 0, behavior: "instant" });
  };

  return (
    <section className="ai-admin-panel" aria-label="Administración de inteligencia artificial">
      <header className="ai-admin-heading">
        <button type="button" className="ai-admin-back" onClick={onBack}>
          <ArrowLeft size={17} aria-hidden="true" /> Volver
        </button>
        <div>
          <span className="ai-admin-eyebrow"><Bot size={14} aria-hidden="true" /> ADMINISTRACIÓN</span>
          <h1>Inteligencia artificial</h1>
          <p>Modelos, conexiones y práctica en un módulo independiente.</p>
        </div>
      </header>
      <nav className="ai-admin-tabs" aria-label="Herramientas de inteligencia artificial">
        <button type="button" aria-current={!training ? "page" : undefined} className={!training ? "active" : ""} onClick={() => navigate(false)}>
          <Settings2 size={17} aria-hidden="true" /> Modelos y conexiones
        </button>
        <button type="button" aria-current={training ? "page" : undefined} className={training ? "active" : ""} onClick={() => navigate(true)}>
          <FlaskConical size={17} aria-hidden="true" /> Práctica Bot
        </button>
      </nav>
      <div className="ai-admin-content">
        {training ? <GalancitoTraining back={() => navigate(false)} /> : <AIConfiguration openTraining={() => navigate(true)} />}
      </div>
    </section>
  );
}
