import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot, MessageCircle, Send, ShieldCheck, Sparkles, X, Maximize2, Minimize2, RotateCcw, Download } from "lucide-react";
import { ApiError, request, downloadInternalReport, deleteInternalConversation } from "./api";
import { change, net } from "./networkApi";
import "./galancito.css";

type ChatLine = { role: "user" | "assistant"; text: string; source?: string; runId?: string; question?: string; rated?: boolean; reportable?: boolean };
type Reply = { name: string; answer: string; source: string; notice?: string; run_id?: string; external_used?: boolean;
  references?: {id: string; version: number; title: string}[]; reportable?: boolean;
  conversation_id?: string | null; history_saved?: boolean };
type Status = { name: string; local_ai_available: boolean; external_ai_available: boolean; read_only: boolean; can_teach?: boolean; internal_available?: boolean; web_available?: boolean; internal_ai_available?: boolean; local_model_status?: "not_configured"|"unavailable"|"connected"|"running"; reply_timeout_seconds?: number; general_model?: string; general_model_ready?: boolean; complex_api_available?: boolean };
type SavedConversation = {id:string;title:string;updated_at:string;expires_at:string;turns:number};
type SavedTurn = {role:"user"|"assistant";text:string;run_id?:string;reportable?:boolean;question?:string};
const EXAMPLES = [
  "¿Qué publicaciones siguen pendientes?",
  "¿Cómo mejorar el seguimiento de candidatos?",
  "Haz un resumen de las necesidades de las obras",
  "¿Qué versión tenemos y cómo está el VPS?",
];

export default function GalancitoWidget() {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [lastFailed, setLastFailed] = useState("");
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatLine[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeNotice, setProbeNotice] = useState("");
  async function testModel() {
    if (probing || busy) return;
    setProbing(true); setProbeNotice("");
    try {
      const result = await request<{status:string;responsive:boolean;message:string;elapsed_ms?:number}>(
        "/network/galancito/diagnostic", {method:"POST", body:"{}"});
      setProbeNotice(result.message +
        (typeof result.elapsed_ms === "number" ? " (" + (result.elapsed_ms / 1000).toFixed(1) + " s)" : ""));
      const updated = await net<Status>("/galancito/status");
      setStatus(updated);
    } catch (err) {
      setProbeNotice(err instanceof ApiError ? "Error HTTP " + err.status + " al probar Ollama." :
        "No se pudo completar la comprobación del modelo.");
    } finally { setProbing(false); }
  }
  // External providers must require an affirmative choice by the user.
  const [consent, setConsent] = useState(false);
  const [webConsent, setWebConsent] = useState(false);
  const [saveMemory, setSaveMemory] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [savedList, setSavedList] = useState<SavedConversation[]>([]);
  const [showSaved, setShowSaved] = useState(false);
  const [memoryBusy, setMemoryBusy] = useState(false);
  async function loadSaved() {
    try {
      const result = await net<{conversations:SavedConversation[]}>("/galancito/conversations");
      setSavedList(result.conversations);
    } catch { setError("No pude cargar tus conversaciones guardadas."); }
  }
  async function restoreSaved(id:string) {
    if (busy || memoryBusy) return;
    setMemoryBusy(true); setError("");
    try {
      const result = await net<{id:string;turns:SavedTurn[]}>("/galancito/conversations/"+encodeURIComponent(id));
      const turns:ChatLine[] = result.turns.map(turn=>turn.role === "assistant"
        ? {role:"assistant",text:turn.text,runId:turn.run_id,reportable:turn.reportable,question:turn.question}
        : {role:"user",text:turn.text});
      setHistory(turns); setConversationId(result.id); setSaveMemory(true); setShowSaved(false);
    } catch { setError("No pude restaurar la conversación seleccionada."); }
    finally { setMemoryBusy(false); }
  }
  async function eraseSaved(id:string) {
    if (busy || memoryBusy) return;
    setMemoryBusy(true); setError("");
    try {
      await deleteInternalConversation(id);
      setSavedList(prev=>prev.filter(item=>item.id!==id));
      if (conversationId===id) {
        setConversationId(null); setHistory([]);
      }
    } catch { setError("No pude eliminar la conversación."); }
    finally { setMemoryBusy(false); }
  }
  const [exporting, setExporting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [correcting, setCorrecting] = useState<number | null>(null);
  const [correction, setCorrection] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackNotice, setFeedbackNotice] = useState("");
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    void net<Status>("/galancito/status").then(setStatus)
      .catch(() => setStatus({name: "Galancito", local_ai_available: false, external_ai_available: false, read_only: true}));
  }, [open]);

  useEffect(() => {
    if (open) end.current?.scrollIntoView({behavior: "smooth", block: "nearest"});
  }, [open, history]);

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const question = message.trim();
    if (busy || question.length < 2) return;
    setMessage("");
    setError("");
    setLastFailed("");
    setHistory((prev) => [...prev, {role: "user", text: question}]);
    setBusy(true);
    const controller = new AbortController();
    // Permit the local model to load and infer under temporary VPS load.
    // The previous 9-second client deadline cut off requests prematurely.
    // The API advertises the actual Ollama budget, including a margin for
    // database work. Never abort before a permitted model response completes.
    const limitMs = Math.min(75000, Math.max(30000, (status?.reply_timeout_seconds ?? 36) * 1000));
    const deadline = window.setTimeout(() => controller.abort(), limitMs);
    try {
      const reply = await request<Reply>("/network/galancito/chat", {
        method: "POST", signal: controller.signal, body: JSON.stringify({
        message: question, area: "general",
        history: history.filter(item => item.role === "user").slice(-4).map(item =>
          ({role: "user", text: item.text.slice(0, 500)})),
        allow_external_ai: consent && !!status?.complex_api_available,
        allow_web: webConsent && !!status?.web_available,
        save_history: saveMemory,
        conversation_id: saveMemory ? conversationId : null,
        }),
      });
      if (saveMemory && reply.conversation_id) {
        setConversationId(reply.conversation_id);
        if (reply.history_saved) void loadSaved();
      }
      setHistory((prev) => [...prev, {role: "assistant", runId: reply.run_id, question,
        source: reply.source, reportable: Boolean(reply.reportable), text: reply.answer + (reply.references?.length ? "\nReferencia: " + reply.references.map(r => `${r.title} (v${r.version})`).join(", ") : "") +
        (reply.notice ? "\n" + reply.notice : "")}]);
    } catch (err) {
      setLastFailed(question);
      setHistory((prev) => [...prev, {role: "assistant", text:
        controller.signal.aborted
          ? `La consulta superó los ${Math.round(limitMs / 1000)} segundos. No recibí una respuesta; puedes reintentar cuando el modelo tenga más recursos.`
          : "No pude conectar con GALANT. Revisa la conexión o vuelve a intentar; no se confirmó ningún cambio."}]);
      setError(err instanceof ApiError ? `Error de conexión o servidor (HTTP ${err.status}). Puedes reintentar la última consulta.` : "La consulta no se completó. Puedes reintentar.");
    } finally { window.clearTimeout(deadline); setBusy(false); setWebConsent(false); }
  }

  async function rate(index: number, rating: "useful" | "incorrect", proposed?: string) {
    const line = history[index]; if (!line?.runId) return;
    setFeedbackBusy(true); setFeedbackNotice("");
    try {
      await change(`/galancito/runs/${line.runId}/feedback`, {rating, ...(proposed ? {correction: {
        title: "Corrección: " + (line.question || "Consulta").slice(0, 80), category: "Correcciones",
        kind: "correction", scope: "red_obras", content: proposed,
        phrases: line.question && line.question.length <= 180 ? [line.question] : [],
      }} : {})});
      setHistory(prev => prev.map((row, i) => i === index ? {...row, rated: true} : row));
      setCorrecting(null); setCorrection("");
      setFeedbackNotice(proposed ? "Corrección guardada como pendiente. Apruébala en Conocimientos." : "Evaluación guardada.");
    } catch { setFeedbackNotice("No se pudo guardar. Revisa que la corrección no incluya datos privados."); }
    finally { setFeedbackBusy(false); }
  }

  async function exportLine(question: string, kind: "pdf"|"xlsx"|"docx") {
    if (exporting) return;
    setExporting(true); setError("");
    try {
      const blob = await downloadInternalReport(question, kind);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = "galant-informe-" + new Date().toISOString().slice(0,10) + "." + kind;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible exportar este informe.");
    } finally { setExporting(false); }
  }

  function askExample(value: string) { setMessage(value); setOpen(true); }
  const examples = EXAMPLES;
  return <aside className={"galancito" + (expanded ? " is-expanded" : "")} aria-label="Asistente Galancito">
    {!open && <button className="galancito-trigger" type="button" onClick={() => setOpen(true)}
        title="Abrir Galancito, asistente de GALANT">
      <Bot size={22} /> <span>Galancito</span>
    </button>}
    {open && <section className="galancito-panel" role="dialog" aria-label="Galancito, asistente virtual" aria-modal="false">
      <header className="galancito-header">
        <div className="galancito-bot-icon"><Bot size={22}/></div>
        <div><strong>Galancito</strong><small>Asistente general de GALANT · solo lectura</small></div>
        <button className="galancito-close" type="button" onClick={() => setExpanded(value => !value)}
          aria-label={expanded ? "Reducir chat" : "Expandir chat"} title={expanded ? "Reducir" : "Pantalla completa"}>
          {expanded ? <Minimize2 size={18}/> : <Maximize2 size={18}/>}
        </button>
        <button className="galancito-close" type="button" disabled={busy}
          onClick={() => { setHistory([]); setConversationId(null); setError(""); setLastFailed(""); }}
          title="Nueva conversación" aria-label="Nueva conversación"><RotateCcw size={16}/></button>
        <button className="galancito-close" type="button" onClick={() => setOpen(false)} aria-label="Cerrar Galancito"><X size={19}/></button>
      </header>
      {status?.internal_available && <div className="galancito-memory">
        <label><input type="checkbox" checked={saveMemory} disabled={busy || memoryBusy}
          onChange={e=>{ setSaveMemory(e.target.checked); if(!e.target.checked) setConversationId(null); }} />
          Guardar conversación (30 días, sin consultas sensibles)
        </label>
        <button type="button" disabled={busy || memoryBusy}
          onClick={()=>{const next=!showSaved;setShowSaved(next);if(next) void loadSaved();}}>
          {showSaved ? "Ocultar historial" : "Conversaciones guardadas"}
        </button>
        {showSaved && <div className="galancito-memory-list">
          {!savedList.length && <small>No tienes conversaciones guardadas.</small>}
          {savedList.map(saved=><div key={saved.id} className="galancito-memory-entry">
            <button type="button" disabled={busy || memoryBusy} title="Abrir conversación"
              onClick={()=>void restoreSaved(saved.id)}>{saved.title}</button>
            <button type="button" disabled={busy || memoryBusy} aria-label={"Eliminar " + saved.title}
              onClick={()=>void eraseSaved(saved.id)}>Eliminar</button>
          </div>)}
        </div>}
      </div>}
      <div className="galancito-history" role="log" aria-label="Conversación con Galancito" aria-live="polite">
        {!history.length && <div className="galancito-greeting">
          <MessageCircle size={24}/>
          <b>¡Hola! Soy Galancito.</b>
          <p>Consulto información autorizada de GALANT y puedo ayudarte con informes, publicaciones, seguimiento y dudas generales.</p>
          <div className="galancito-examples">{examples.map(x =>
            <button type="button" key={x} onClick={() => askExample(x)}>{x}</button>)}</div>
        </div>}
        {history.map((entry,i) => <div key={i} className={"galancito-bubble " + entry.role}>
          <span>{entry.role === "assistant" ? "Galancito" : "Tú"}</span>
          <p>{entry.text}</p>
          {entry.role === "assistant" && entry.source && <small className="galancito-source">
            {({
              verified_local: "Datos comprobados de GALANT",
              ollama_4b: "Orientación de Qwen3.5 4B",
              external_api: "Análisis de API externa",
              public_web: "Búsqueda pública",
              local: "Respuesta directa",
              fallback: "Orientación básica sin modelo",
            } as Record<string,string>)[entry.source] || "Respuesta de Galancito"}
          </small>}
          {entry.reportable && entry.question && <details className="galancito-export">
            <summary><Download size={14}/> Exportar informe</summary>
            <div className="galancito-export-options">
              {(["pdf", "xlsx", "docx"] as const).map(kind => <button type="button" key={kind}
                disabled={exporting} onClick={() => void exportLine(entry.question!, kind)}>
                {kind.toUpperCase()}
              </button>)}
            </div>
          </details>}
          {entry.runId && <div className="galancito-feedback" aria-label="Evaluar respuesta">
            <button type="button" disabled={feedbackBusy || entry.rated} onClick={() => void rate(i, "useful")}>Útil</button>
            <button type="button" disabled={feedbackBusy || entry.rated} onClick={() => void rate(i, "incorrect")}>Incorrecta</button>

          </div>}
        </div>)}
        {feedbackNotice && <p role="status" className="galancito-feedback-notice">{feedbackNotice}</p>}
        {busy && <p className="galancito-thinking"><Sparkles size={14}/> Galancito está consultando y preparando la respuesta… </p>}
        <div ref={end}/>
      </div>
      <form className="galancito-compose" onSubmit={(e) => void send(e)}>
        {status?.can_teach && <div className="galancito-health" role="group" aria-label="Diagnóstico de Ollama">
          <span>Ollama: {({
            running:"cargado", connected:"conectado, sin modelo cargado",
            unavailable:"sin conexión", not_configured:"no habilitado",
          } as const)[status.local_model_status ?? "not_configured"]}</span>
          <button type="button" onClick={() => void testModel()}
            disabled={busy || probing || !status.local_ai_available}>
            {probing ? "Comprobando…" : "Probar respuesta"}
          </button>
          {probeNotice && <small role="status">{probeNotice}</small>}
        </div>}
        {status?.complex_api_available && <label className="galancito-privacy">
          <input type="checkbox" checked={consent} disabled={busy}
            onChange={e => setConsent(e.target.checked)} />
          <span>Permitir API externa para preguntas complejas y públicas (desactivado por defecto)</span>
        </label>}
        {status?.web_available && <label className="galancito-privacy">
          <input type="checkbox" checked={webConsent} disabled={busy}
            onChange={e => setWebConsent(e.target.checked)} />
          <span>Buscar en internet (envía únicamente esta pregunta pública)</span>
        </label>}
        <small>{status?.general_model_ready ? "Qwen3.5 4B configurado. Comprueba su respuesta desde administración; los datos reales se consultan con permisos." : "Qwen3.5 4B no está activado en el servidor. Las consultas verificables siguen disponibles."} No compartas claves ni documentos personales.</small>
        <div className="galancito-input-row">
          <input aria-label="Escribe tu pregunta a Galancito" value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Ej.: ¿Qué debo hacer primero?" maxLength={800}/>
          <button type="submit" disabled={busy || message.trim().length < 2} aria-label="Enviar pregunta"><Send size={18}/></button>
        </div>
        {error && <div role="alert" className="galancito-error">{error}
          {lastFailed && <button type="button" className="galancito-retry"
            onClick={() => { setMessage(lastFailed); setError(""); }}><RotateCcw size={14}/> Recuperar pregunta</button>}
        </div>}
        <div className="galancito-safety"><ShieldCheck size={13}/> Solo orienta, no modifica registros.</div>
      </form>
    </section>}
  </aside>;
}
