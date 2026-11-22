import { useEffect, useState } from "react";
import { Check, ChevronRight, ClipboardCheck, RefreshCw } from "lucide-react";
import { request } from "./api";
import "./ai-human-audit.css";

type Channel = "messenger" | "general";
type Candidate = { run_id: string; created_at: string; channel: Channel; source: string };
type Queue = {
  channel: Channel; rubric_version: number; criteria: string[]; items: Candidate[];
};
type Evidence = {
  run_id: string; channel: Channel; question: string; answer: string;
  created_at: string; rubric_version: number; criteria: string[];
  history: Array<{ role: string; text: string }>;
};
const criterionNames: Record<string, string> = {
  understanding: "Comprensión del mensaje", profile: "Extracción y ficha", context: "Continuidad y contexto",
  naturalness: "Naturalidad", safety: "Seguridad y privacidad", helpfulness: "Utilidad real",
  accuracy: "Exactitud de datos", grounding: "Evidencia y fuentes", reasoning: "Razonamiento comprobable",
};
const date = (value: string) => new Date(value).toLocaleString("es-CL", {
  dateStyle: "short", timeStyle: "short", timeZone: "America/Santiago",
});
const errorText = (value: unknown) => value instanceof Error ? value.message : "No se pudo procesar la revisión";

export default function AIHumanAudit({ onPractice }: { onPractice: (channel: Channel, focus: string) => void }) {
  const [channel, setChannel] = useState<Channel>("messenger");
  const [queue, setQueue] = useState<Queue | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [ratings, setRatings] = useState<Record<string, boolean>>({});
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [weaknesses, setWeaknesses] = useState<string[]>([]);

  useEffect(() => {
    let mounted = true;
    setBusy(true);
    request<Queue>("/admin/ai/audit/queue?channel=" + channel)
      .then(result => { if (mounted) { setQueue(result); setError(""); } })
      .catch(err => { if (mounted) setError(errorText(err)); })
      .finally(() => { if (mounted) setBusy(false); });
    return () => { mounted = false; };
  }, [channel, revision]);

  async function inspect(runId: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await request<Evidence>("/admin/ai/audit/cases/" + encodeURIComponent(runId));
      setEvidence(result); setRatings({}); setAttested(false);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!evidence || !attested || evidence.criteria.some(key => ratings[key] === undefined)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await request("/admin/ai/audit/reviews", {
        method: "POST", body: JSON.stringify({
          run_id: evidence.run_id, ratings, source_reviewed: true,
        }),
      });
      setNotice("Evaluación humana registrada. No se modificó el modelo ni se guardó la conversación.");
      setWeaknesses(evidence.criteria.filter(key => ratings[key] === false));
      setEvidence(null); setRevision(i => i + 1);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  return <section className="ai-human-audit" aria-label="Auditoría humana de respuestas reales">
    <div className="ai-human-audit-head">
      <div>
        <span className="ai-human-audit-eyebrow"><ClipboardCheck size={14} /> EVALUACIÓN REAL</span>
        <h3>Revisar respuestas de producción</h3>
        <p>Una persona compara el mensaje original y la respuesta. Las notas se guardan sin texto privado.</p>
      </div>
      <button type="button" title="Actualizar casos" aria-label="Actualizar casos"
        disabled={busy} onClick={() => setRevision(n => n + 1)}><RefreshCw size={17} /></button>
    </div>
    <div className="ai-human-audit-switch" role="group" aria-label="Canal de revisión">
      {(["messenger", "general"] as const).map(item =>
        <button key={item} type="button" aria-pressed={channel === item}
          className={channel === item ? "active" : ""}
          onClick={() => { setChannel(item); setEvidence(null); setQueue(null); setNotice(""); setWeaknesses([]); }}>
          {item === "messenger" ? "Messenger" : "Galancito General"}
        </button>)}
    </div>
    {error && <p className="ai-human-audit-error" role="alert">{error}</p>}
    {notice && <p className="ai-human-audit-notice" role="status"><Check size={15} /> {notice}</p>}
    {weaknesses.length > 0 && <div className="ai-human-audit-focus" role="group" aria-label="Práctica de fallas detectadas">
      <strong>Se encontraron fallas reales en esta respuesta:</strong>
      <div>{weaknesses.map(key => <button key={key} type="button" onClick={() => onPractice(channel, key)}>
        Practicar {criterionNames[key] ?? key} <ChevronRight size={14} />
      </button>)}</div>
      <small>La práctica usa escenarios sintéticos similares. La calificación de Messenger solo cambia con nuevas respuestas reales auditadas.</small>
    </div>}
    {busy && !evidence && <p role="status" className="ai-human-audit-hint">Consultando registros verificables…</p>}
    {!busy && queue?.items.length === 0 &&
      <p className="ai-human-audit-hint">No hay respuestas pendientes con conversación original accesible en este canal. No se generarán casos ficticios.</p>}

    {!evidence && (queue?.items.length ?? 0) > 0 &&
      <div className="ai-human-audit-items">
        {queue?.items.slice(0, 8).map(item => <button type="button" disabled={busy}
          key={item.run_id} onClick={() => void inspect(item.run_id)}>
          <span><strong>Respuesta real</strong><small>{date(item.created_at)} · {item.source}</small></span>
          <ChevronRight size={16} />
        </button>)}
        {queue && queue.items.length > 8 &&
          <small>{queue.items.length - 8} adicionales detectadas. Se muestran primero las más recientes.</small>}
      </div>}

    {evidence && <div className="ai-human-audit-case">
      <div className="ai-human-audit-case-title">
        <b>Interacción del {date(evidence.created_at)}</b>
        <button type="button" disabled={busy} onClick={() => setEvidence(null)}>Cerrar</button>
      </div>
      {evidence.history.length > 0 && <details className="ai-human-audit-history">
        <summary>Ver contexto real del chat ({evidence.history.length} mensajes anteriores)</summary>
        <div>{evidence.history.map((item, index) => <p key={index}>
          <b>{item.role === "inbound" || item.role === "user" ? "Persona" : "GALANT / equipo"}</b> {item.text}
        </p>)}</div>
      </details>}
      <div className="ai-human-audit-exchange">
        <div><b>Mensaje recibido</b><p>{evidence.question}</p></div>
        <div><b>Respuesta enviada</b><p>{evidence.answer}</p></div>
      </div>
      <p className="ai-human-audit-hint">Verifica cada criterio sobre esta conversación real. Si falta evidencia para comprobarlo, no apruebes ese criterio.</p>
      <div className="ai-human-audit-ratings">
        {evidence.criteria.map(key => <label key={key}>{criterionNames[key] ?? key}
          <select value={ratings[key] === undefined ? "" : ratings[key] ? "pass" : "fail"}
            onChange={event => setRatings(prev => ({ ...prev, [key]: event.target.value === "pass" }))}>
            <option value="" disabled>Sin evaluar</option>
            <option value="pass">Cumple</option>
            <option value="fail">No cumple</option>
          </select>
        </label>)}
      </div>
      <label className="ai-human-audit-ack"><input type="checkbox" checked={attested}
        onChange={event => setAttested(event.target.checked)} />
        He revisado personalmente el mensaje y la respuesta originales.
      </label>
      <div className="ai-human-audit-actions">
        <button type="button" disabled={busy || !attested || evidence.criteria.some(key => ratings[key] === undefined)}
          onClick={() => void submit()}>Guardar evaluación verificada</button>
      </div>
    </div>}
    <p className="ai-human-audit-footnote">Solo el administrador puede acceder. Sin una muestra suficientemente amplia no habrá nota /100. Una muestra auditada no representa automáticamente todas las conversaciones. Cada respuesta se evalúa una sola vez.</p>
  </section>;
}
