import { useEffect, useState } from "react";
import { Check, ChevronRight, ClipboardCheck, RefreshCw } from "lucide-react";
import { request } from "./api";
import "./ai-human-audit.css";

type Channel = "messenger" | "general";
type Candidate = { run_id: string; created_at: string; channel: Channel; source: string };
type Queue = {
  channel: Channel; rubric_version: number; criteria: string[]; items: Candidate[];
};
type RealTrial = {trial_id: string; verification_nonce: string; original: string;
  baseline: string; candidate: string; seed: number;
  elapsed_ms: number; model: string; criterion: string; variant: string; stage: string;
  provenance: string; diagnosis: {hypothesis: string; reason: string; mechanism: string}};
type AuditedCase = {source_id: string; source_at: string; failed_criteria: string[];
  model_verified: boolean; route: {hypothesis: string; reason: string; mechanism: string}};
type PendingTrial = {id: string; criterion: string; variant: string; created_at: string; can_cancel: boolean};
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
  const [ratings, setRatings] = useState<Record<string, boolean | null>>({});
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [weaknesses, setWeaknesses] = useState<string[]>([]);
  const [lastReviewed, setLastReviewed] = useState("");
  const [trial, setTrial] = useState<RealTrial | null>(null);
  const [criterionResolved, setCriterionResolved] = useState(false);
  const [safetyPassed, setSafetyPassed] = useState(false);
  const [auditedCases, setAuditedCases] = useState<AuditedCase[]>([]);
  const [pendingTrials, setPendingTrials] = useState<PendingTrial[]>([]);
  const [engineeringFindings, setEngineeringFindings] = useState<Array<{
    source_id: string; criterion: string; hypothesis: string; mechanism: string;
  }>>([]);

  useEffect(() => {
    let mounted = true;
    setBusy(true);
    Promise.all([
      request<Queue>("/admin/ai/audit/queue?channel=" + channel),
      request<{items: AuditedCase[]}>("/admin/ai/real-learning/cases?channel=" + channel),
      request<{items: PendingTrial[]}>("/admin/ai/real-learning/pending?channel=" + channel),
    ])
      .then(([result, cases, pending]) => { if (mounted) {
        setQueue(result); setAuditedCases(cases.items); setPendingTrials(pending.items); setError("");
      } })
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
      setLastReviewed(evidence.run_id);
      setTrial(null);
      setEvidence(null); setRevision(i => i + 1);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function replayReal(criterion: string, sourceId = lastReviewed, variant: "focused" | "alternative" = "focused") {
    if (!sourceId) return;
    setBusy(true); setError(""); setTrial(null);
    setCriterionResolved(false); setSafetyPassed(false);
    try {
      const result = await request<RealTrial>("/admin/ai/real-learning/replay", {
        method: "POST", body: JSON.stringify({source_id: sourceId, criterion, variant}),
      });
      setTrial(result);
      setNotice("Qwen respondió sobre un caso real. La comparación puede usar contexto parcial y no prueba mejora global.");
      setRevision(v => v + 1);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function practiceNext() {
    setBusy(true); setError("");
    try {
      const target = await request<{available: boolean; reason: string; source_id?: string;
        criterion?: string; variant?: "focused" | "alternative";
        engineering_findings?: Array<{
          source_id: string; criterion: string; hypothesis: string; mechanism: string;
        }>; }>(
          "/admin/ai/real-learning/next?channel=" + channel);
      setEngineeringFindings(target.engineering_findings || []);
      if (!target.available || !target.source_id || !target.criterion || !target.variant) {
        setNotice(target.reason);
        return;
      }
      setBusy(false);
      await replayReal(target.criterion, target.source_id, target.variant);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function rateReal(outcome: "better" | "same" | "worse") {
    if (!trial) return;
    setBusy(true); setError("");
    try {
      await request("/admin/ai/real-learning/trials/" + trial.trial_id + "/review", {
        method: "POST", body: JSON.stringify({outcome, source_reviewed: true, verification_nonce: trial.verification_nonce,
          criterion_resolved: outcome === "better" && criterionResolved,
          safety_passed: outcome === "better" && safetyPassed}),
      });
      setTrial(null); setRevision(v => v + 1);
      setNotice("Resultado humano guardado. Una muestra individual no demuestra aprendizaje general.");
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function cancelReal(trialId: string) {
    setBusy(true); setError("");
    try {
      await request("/admin/ai/real-learning/trials/" + trialId + "/cancel", {method: "POST"});
      setTrial(current => current?.trial_id === trialId ? null : current);
      setRevision(v => v + 1);
      setNotice("Ensayo interrumpido descartado. Ahora puedes repetir el caso sin inventar una valoración.");
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  async function propose(criterion: string) {
    setBusy(true); setError("");
    try {
      const result = await request<{message: string}>("/admin/ai/real-learning/proposals", {
        method: "POST", body: JSON.stringify({channel, criterion}),
      });
      setNotice(result.message);
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
          onClick={() => { setChannel(item); setEvidence(null); setQueue(null); setNotice(""); setWeaknesses([]); setLastReviewed(""); setTrial(null); }}>
          {item === "messenger" ? "Messenger" : "Galancito General"}
        </button>)}
    </div>
    {error && <p className="ai-human-audit-error" role="alert">{error}</p>}
    {notice && <p className="ai-human-audit-notice" role="status"><Check size={15} /> {notice}</p>}
    {weaknesses.length > 0 && <div className="ai-human-audit-focus" role="group" aria-label="Práctica de fallas detectadas">
      <strong>Se encontraron fallas reales en esta respuesta:</strong>
      <div>{weaknesses.map(key => <div className="ai-human-audit-focus-actions" key={key}>
        <b>{criterionNames[key] ?? key}</b>
        <button type="button" disabled={busy} onClick={() => void replayReal(key)}>
          Probar estrategia 1 <ChevronRight size={14} />
        </button>
        <button type="button" disabled={busy} onClick={() => void replayReal(key, lastReviewed, "alternative")}>
          Probar estrategia 2
        </button>
        <button type="button" disabled={busy} onClick={() => void propose(key)}>
          Proponer tras validar casos reservados
        </button>
        <button type="button" disabled={busy} onClick={() => onPractice(channel, key)}>
          Laboratorio complementario
        </button>
      </div>)}</div>
      <small>La propuesta exige 2 casos de práctica y 4 casos reservados independientes favorables, origen de Qwen verificable y 0 regresiones. Ninguna prueba modifica pesos ni envía mensajes.</small>
    </div>}
    {trial && <section className="ai-real-trial" aria-label="Comparación de respuestas de Qwen">
      <strong>Práctica real · {criterionNames[trial.criterion] ?? trial.criterion}</strong>
      <p>Modelo local: {trial.model} · {Math.round(trial.elapsed_ms / 100) / 10} s.
        Estrategia {trial.variant === "focused" ? "1" : "2"} · {trial.stage === "holdout" ? "Caso reservado" : "Práctica"}.
        Origen: {trial.provenance === "model_verified" ? "Modelo original trazado" : "Reconstrucción parcial"}.</p>
      <p>Hipótesis: {trial.diagnosis.reason} El ensayo no demuestra por sí solo qué componente causó el error.</p>
      <div className="ai-real-trial-comparison">
        <article><b>Respuesta de producción (referencia)</b><p>{trial.original}</p></article>
        <article><b>Qwen base · misma semilla</b><p>{trial.baseline}</p></article>
        <article><b>Qwen con corrección · misma semilla</b><p>{trial.candidate}</p></article>
      </div>
      <p>Para contar una mejora tienes que comprobar dos condiciones; una respuesta distinta no es suficiente.</p>
      <label className="ai-human-audit-ack">
        <input type="checkbox" checked={criterionResolved} onChange={value => setCriterionResolved(value.target.checked)} />
        El error específico auditado quedó resuelto en la candidata
      </label>
      <label className="ai-human-audit-ack">
        <input type="checkbox" checked={safetyPassed} onChange={value => setSafetyPassed(value.target.checked)} />
        La candidata conserva privacidad, permisos y seguridad
      </label>
      <div className="ai-real-trial-actions">
        <button type="button" disabled={busy || !criterionResolved || !safetyPassed} onClick={() => void rateReal("better")}>Error resuelto y seguro</button>
        <button type="button" disabled={busy} onClick={() => void rateReal("same")}>Igual</button>
        <button type="button" disabled={busy} onClick={() => void rateReal("worse")}>Empeoró</button>
        <button type="button" disabled={busy} onClick={() => void cancelReal(trial.trial_id)}>Descartar ensayo</button>
      </div>
    </section>}
    <div className="ai-real-practice-action">
      <button type="button" disabled={busy} onClick={() => void practiceNext()}>
        <Check size={14} /> Ejecutar siguiente práctica focalizada con Qwen real
      </button>
      <small>GALANT prioriza fallas auditadas, comprueba la ruta y selecciona una estrategia.
        Solo se registra mejora si revisas la respuesta, y ninguna guía se activa automáticamente.</small>
    </div>
    {engineeringFindings.length > 0 && <details className="ai-human-audit-history" open>
      <summary>{engineeringFindings.length} casos requieren corregir la infraestructura, no entrenar Qwen</summary>
      <div>{engineeringFindings.map((item, index) => <div key={item.source_id + item.criterion + index}
        className="ai-human-audit-recovery">
        <b>{criterionNames[item.criterion] || item.criterion} · {item.hypothesis.replaceAll("_", " ")}</b>
        <small>Revisar: {item.mechanism.replaceAll("_", " ")}. No se declara aprendizaje mientras el origen técnico esté pendiente.</small>
      </div>)}</div>
    </details>}
    {pendingTrials.length > 0 && <details className="ai-human-audit-history">
      <summary>Ensayos pendientes o interrumpidos ({pendingTrials.length})</summary>
      <div>{pendingTrials.map(item => <div key={item.id} className="ai-human-audit-recovery">
        <span>{criterionNames[item.criterion] ?? item.criterion} · {item.variant} · {date(item.created_at)}</span>
        <button type="button" disabled={busy} onClick={() => void cancelReal(item.id)}>
          Cancelar para repetir
        </button>
      </div>)}</div>
    </details>}
    {auditedCases.length > 0 && <details className="ai-human-audit-history">
      <summary>Fallas reales ya auditadas ({auditedCases.length})</summary>
      <div>{auditedCases.map(item => <div key={item.source_id} className="ai-human-audit-recovery">
        <b>{date(item.source_at)} · {item.model_verified ? "Qwen trazado" : "Ruta no confirmada"}</b>
        <small>{item.route.reason}</small>
        {item.failed_criteria.map(key => <div key={key}>
          <span>{criterionNames[key] ?? key}</span>
          <button type="button" disabled={busy} onClick={() => void replayReal(key, item.source_id, "focused")}>
            Estrategia 1
          </button>
          <button type="button" disabled={busy} onClick={() => void replayReal(key, item.source_id, "alternative")}>
            Estrategia 2
          </button>
        </div>)}
      </div>)}</div>
    </details>}
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
          <select value={ratings[key] === undefined ? "" : ratings[key] === null ? "unknown" : ratings[key] ? "pass" : "fail"}
            onChange={event => setRatings(prev => ({ ...prev, [key]: event.target.value === "unknown" ? null : event.target.value === "pass" }))}>
            <option value="" disabled>Sin evaluar</option>
            <option value="pass">Cumple</option>
            <option value="fail">No cumple</option>
            <option value="unknown">No comprobable</option>
          </select>
        </label>)}
      </div>
      <label className="ai-human-audit-ack"><input type="checkbox" checked={attested}
        onChange={event => setAttested(event.target.checked)} />
        He revisado personalmente el mensaje y la respuesta originales.
      </label>
      <div className="ai-human-audit-actions">
        <button type="button" disabled={busy || !attested || evidence.criteria.some(key => ratings[key] === undefined) || evidence.criteria.every(key => ratings[key] === null)}
          onClick={() => void submit()}>Guardar evaluación verificada</button>
      </div>
    </div>}
    <p className="ai-human-audit-footnote">Solo el administrador puede acceder. Sin una muestra suficientemente amplia no habrá nota /100. Una muestra auditada no representa automáticamente todas las conversaciones. Cada respuesta se evalúa una sola vez.</p>
  </section>;
}
