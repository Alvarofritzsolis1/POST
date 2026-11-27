import { useState } from "react";
import { Download, FileJson, ShieldCheck } from "lucide-react";
import { request } from "./api";
import "./ai-feedback-panel.css";

export default function AIFeedbackPanel() {
  const [days, setDays] = useState(0);
  const [includeCode, setIncludeCode] = useState(false);
  const [includeText, setIncludeText] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [coverage, setCoverage] = useState<Record<string, number> | null>(null);
  const [findings, setFindings] = useState<Record<string, number> | null>(null);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  async function download() {
    setBusy(true); setError(""); setCounts(null); setFindings(null); setCoverage(null);
    try {
      const data = await request<{counts: Record<string, number>; generated_at: string; coverage: Record<string, number>; findings: Record<string, number>}>(
        "/admin/ai/red-obras/feedback-export?days=" + days + "&include_text=" + includeText + "&include_code=" + includeCode);
      const blob = new Blob([JSON.stringify(data, null, 2)], {type:"application/json"});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "galant-red-obras-diagnostico-" + data.generated_at.slice(0,10) + ".json";
      document.body.appendChild(anchor);
      anchor.click(); anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setCounts(data.counts); setFindings(data.findings); setCoverage(data.coverage);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo generar el diagnóstico.");
    } finally { setBusy(false); }
  }
  return <section className="ai-feedback-panel" aria-label="Sobrealimentación de Red de Obras">
    <header><span className="ai-feedback-kicker">EVIDENCIA DE PRODUCCIÓN</span>
      <h2>Diagnóstico y mejora continua</h2>
      <p>Descarga información real de Red de Obras para revisar respuestas, fichas, errores y rendimiento. No modifica Galancito ni inicia entrenamiento.</p></header>
    <div className="ai-feedback-grid">
      {["Conversaciones y entregas", "Fichas y oficios", "Publicaciones y comentarios", "Métricas y auditorías", "Seguimiento de postulantes", "Práctica y conocimiento"].map(label =>
        <div key={label}><FileJson size={20} aria-hidden="true"/><strong>{label}</strong></div>)}
    </div>
    <div className="ai-feedback-export">
      <h3>Descargar diagnóstico de Red de Obras</h3>
      <p>JSON estructurado, con identificadores de relación y fechas. Los recuentos corresponden a registros disponibles, no a notas inventadas.</p>
      <label>Período <select value={days} disabled={busy} onChange={e => setDays(Number(e.target.value))}>
        <option value={0}>Todo el historial disponible</option><option value={7}>7 días</option><option value={30}>30 días</option><option value={90}>90 días</option>
      </select></label>
      <label className="ai-feedback-check"><input type="checkbox" checked={includeText} disabled={busy} onChange={e=>setIncludeText(e.target.checked)}/>
        Incluir contenido de chats y publicaciones para análisis de respuestas</label>
      <label className="ai-feedback-check"><input type="checkbox" checked={includeCode} disabled={busy} onChange={e=>setIncludeCode(e.target.checked)}/> Incluir código fuente del backend de IA y Red de Obras</label>
      <p className="ai-feedback-notice"><ShieldCheck size={18} aria-hidden="true"/> Solo administradores. Los textos pueden contener información personal pese a la redacción automática. Revisa el archivo antes de compartirlo. No se envía a proveedores externos.</p>
      <button type="button" disabled={busy} onClick={download}><Download size={18} aria-hidden="true"/>{busy?"Generando diagnóstico…":"Descargar diagnóstico"}</button>
      {error && <p role="alert" className="ai-feedback-error">{error}</p>}
      {counts && <p role="status">Archivo generado: {Object.values(counts).reduce((a,b)=>a+b,0).toLocaleString("es-CL")} registros en {Object.keys(counts).length} colecciones.</p>}
    </div>
    {coverage && <section aria-label="Cobertura de evidencia"><h3>Cobertura de evidencia</h3><p>Vínculos comprobables: {coverage.runs_linked_to_exported_message} de {coverage.messenger_runs} ejecuciones Messenger y {coverage.profile_sources_linked} de {coverage.profile_sources_recorded} orígenes de ficha. Trazas nuevas: {coverage.runs_with_trace_v2}. Los registros sin evidencia quedan pendientes, no se califican.</p></section>}
    {findings && <section aria-label="Indicadores observados"><h3>Indicadores para revisar</h3><p>No equivalen a fallos confirmados: requieren contrastar la evidencia.</p><div className="ai-feedback-grid">{Object.entries({messages_with_recorded_error:"Mensajes con error registrado",leads_missing_profile_fields:"Fichas con campos pendientes",leads_needing_support:"Contactos que requieren apoyo",runs_reported_incorrect:"Respuestas reportadas incorrectas",runs_with_fallback:"Ejecuciones con fallback",runs_without_message_link:"Ejecuciones sin vínculo al mensaje"}).map(([key,label])=><div key={key}><strong>{findings[key].toLocaleString("es-CL")}</strong><span>{label}</span></div>)}</div></section>}
  </section>;
}
