import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot, MessageCircle, Send, ShieldCheck, Sparkles, X, Maximize2, Minimize2, RotateCcw, Download } from "lucide-react";
import { ApiError, request, downloadInternalReport, deleteInternalConversation } from "./api";
import { change, net } from "./networkApi";
import "./galancito.css";

type Area = "red_obras" | "interno";
type ChatLine = { role: "user" | "assistant"; text: string; runId?: string; question?: string; rated?: boolean; reportable?: boolean };
type Reply = { name: string; answer: string; source: string; notice?: string; run_id?: string;
  references?: {id: string; version: number; title: string}[]; reportable?: boolean;
  conversation_id?: string | null; history_saved?: boolean };
type Status = { name: string; local_ai_available: boolean; external_ai_available: boolean; read_only: boolean; can_teach?: boolean; internal_available?: boolean; web_available?: boolean; internal_ai_available?: boolean };
type SavedConversation = {id:string;title:string;updated_at:string;expires_at:string;turns:number};
type SavedTurn = {role:"user"|"assistant";text:string;run_id?:string;reportable?:boolean;question?:string};
const EXAMPLES = [
  "¿Cómo publicar una necesidad?",
  "¿Qué documentos necesita un contratista?",
  "¿Cómo funciona Facebook?",
];

export default function GalancitoWidget({ area = "red_obras" }: { area?: Area }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<Area>(area);
  const [lastFailed, setLastFailed] = useState("");
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatLine[]>([]);
  const profileHistory = useRef<Record<Area, ChatLine[]>>({red_obras: [], interno: []});
  function switchProfile(next: Area) {
    if (busy || mode === next) return;
    profileHistory.current[mode] = history;
    setMode(next);
    setHistory(profileHistory.current[next]);
    setError(""); setLastFailed(""); setFeedbackNotice("");
    setWebConsent(false);
    if (next === "interno" && saveMemory) void loadSaved();
  }
  const [status, setStatus] = useState<Status | null>(null);
  const [consent, setConsent] = useState(false);
  const [webConsent, setWebConsent] = useState(false);
  const [localAnalysis, setLocalAnalysis] = useState(false);
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
      profileHistory.current.interno = turns;
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
        setConversationId(null); setHistory([]); profileHistory.current.interno=[];
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
    const deadline = window.setTimeout(() => controller.abort(), 30000);
    try {
      const reply = await request<Reply>("/network/galancito/chat", {
        method: "POST", signal: controller.signal, body: JSON.stringify({
        message: question, area: mode,
        history: mode === "interno" ? history.filter(item => item.role === "user").slice(-4).map(item =>
          ({role: "user", text: item.text.slice(0, 500)})) : [],
        allow_external_ai: mode === "red_obras" && consent && !!status?.external_ai_available,
        allow_web: mode === "interno" && webConsent && !!status?.web_available,
        allow_local_analysis: mode === "interno" && !webConsent && localAnalysis && !!status?.internal_ai_available,
        save_history: mode === "interno" && saveMemory,
        conversation_id: mode === "interno" && saveMemory ? conversationId : null,
        }),
      });
      if (mode === "interno" && saveMemory && reply.conversation_id) {
        setConversationId(reply.conversation_id);
        if (reply.history_saved) void loadSaved();
      }
      setHistory((prev) => [...prev, {role: "assistant", runId: reply.run_id, question,
        reportable: mode === "interno" && Boolean(reply.reportable), text: reply.answer + (reply.references?.length ? "\nReferencia: " + reply.references.map(r => `${r.title} (v${r.version})`).join(", ") : "") +
        (reply.notice ? "\n" + reply.notice : "")}]);
    } catch (err) {
      setLastFailed(question);
      setHistory((prev) => [...prev, {role: "assistant", text:
        controller.signal.aborted
          ? "La consulta superó los 30 segundos. No recibí una respuesta; puedes reintentar cuando el modelo tenga más recursos."
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
  const examples = mode === "interno" ? [
    "¿Qué versión está desplegada?", "Haz un resumen de las publicaciones",
    "¿Cuántas necesidades vigentes hay?", "¿Cómo está el rendimiento del VPS?",
  ] : EXAMPLES;
  return <aside className={"galancito" + (expanded ? " is-expanded" : "")} aria-label="Asistente Galancito">
    {!open && <button className="galancito-trigger" type="button" onClick={() => setOpen(true)}
        title="Abrir Galancito, asistente de GALANT">
      <Bot size={22} /> <span>Galancito</span>
    </button>}
    {open && <section className="galancito-panel" role="dialog" aria-label="Galancito, asistente virtual" aria-modal="false">
      <header className="galancito-header">
        <div className="galancito-bot-icon"><Bot size={22}/></div>
        <div><strong>{mode === "interno" ? "Galancito Interno" : "Galancito"}</strong><small>{mode === "interno" ? "Consultas verificadas · solo lectura" : "Asesor de Red de Obras · solo lectura"}</small></div>
        <button className="galancito-close" type="button" onClick={() => setExpanded(value => !value)}
          aria-label={expanded ? "Reducir chat" : "Expandir chat"} title={expanded ? "Reducir" : "Pantalla completa"}>
          {expanded ? <Minimize2 size={18}/> : <Maximize2 size={18}/>}
        </button>
        <button className="galancito-close" type="button" disabled={busy}
          onClick={() => { setHistory([]); profileHistory.current[mode] = []; if (mode === "interno") setConversationId(null); setError(""); setLastFailed(""); }}
          title="Nueva conversación" aria-label="Nueva conversación"><RotateCcw size={16}/></button>
        <button className="galancito-close" type="button" onClick={() => setOpen(false)} aria-label="Cerrar Galancito"><X size={19}/></button>
      </header>
      {status?.internal_available && <nav className="galancito-modes" aria-label="Perfil de Galancito">
        <button type="button" disabled={busy} className={mode === "red_obras" ? "selected" : ""} aria-pressed={mode === "red_obras"}
          onClick={() => switchProfile("red_obras")}>Red de Obras</button>
        <button type="button" disabled={busy} className={mode === "interno" ? "selected" : ""} aria-pressed={mode === "interno"}
          onClick={() => switchProfile("interno")}>Interno 360°</button>
      </nav>}
      {mode === "interno" && <div className="galancito-memory">
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
          <p>{mode === "interno" ? "Consulto datos autorizados de GALANT, versiones y reportes breves. Las funciones sin conexión aparecerán como no disponibles." :
            "Te ayudo a buscar contratistas y entender las necesidades de Red de Obras. No modifico documentos ni adjudico trabajos."}</p>
          <div className="galancito-examples">{examples.map(x =>
            <button type="button" key={x} onClick={() => askExample(x)}>{x}</button>)}</div>
        </div>}
        {history.map((entry,i) => <div key={i} className={"galancito-bubble " + entry.role}>
          <span>{entry.role === "assistant" ? "Galancito" : "Tú"}</span>
          <p>{entry.text}</p>
          {mode === "interno" && entry.reportable && entry.question && <details className="galancito-export">
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
            {mode === "red_obras" && status?.can_teach && <button type="button" disabled={feedbackBusy} onClick={() => { setCorrecting(i); setCorrection(""); }}>Proponer corrección</button>}
            {mode === "red_obras" && correcting === i && <><label>Respuesta correcta (sin datos privados)<textarea value={correction} maxLength={24000}
              onChange={e => setCorrection(e.target.value)} /></label>
              <button type="button" disabled={feedbackBusy || correction.trim().length < 2} onClick={() => void rate(i, "incorrect", correction.trim())}>Guardar para aprobación</button>
              <button type="button" onClick={() => setCorrecting(null)}>Cancelar</button></>}
          </div>}
        </div>)}
        {feedbackNotice && <p role="status" className="galancito-feedback-notice">{feedbackNotice}</p>}
        {busy && <p className="galancito-thinking"><Sparkles size={14}/> {mode === "interno" ? "Consultando datos autorizados…" : "Preparando respuesta…"} </p>}
        <div ref={end}/>
      </div>
      <form className="galancito-compose" onSubmit={(e) => void send(e)}>
        {mode === "red_obras" && status?.local_ai_available && <div className="galancito-safety">
          <ShieldCheck size={14}/> Modelo local configurado · conexión no verificada en vivo
        </div>}
        {mode === "red_obras" && status?.external_ai_available && <label className="galancito-privacy"><input type="checkbox" checked={consent}
          onChange={(e) => setConsent(e.target.checked)} disabled={!status?.external_ai_available}/>
          <span>Permitir modelo externo en esta conversación</span>
        </label>}
        {mode === "interno" && status?.internal_ai_available && <label className="galancito-privacy">
          <input type="checkbox" checked={localAnalysis} disabled={busy || webConsent}
            onChange={event=>setLocalAnalysis(event.target.checked)}/>
          <span>Añadir recomendación de IA local (orientativa, sin modificar registros)</span>
        </label>}
        {mode === "interno" && status?.web_available && <label className="galancito-privacy">
          <input type="checkbox" checked={webConsent} disabled={busy}
            onChange={event => setWebConsent(event.target.checked)} />
          <span>Buscar en internet (envía solo esta pregunta al buscador público)</span>
        </label>}
        <small>{mode === "interno" ? "Consultas a registros autorizados. Para búsqueda pública, no incluyas datos personales ni de las obras." : "No ingreses RUT, claves ni documentos personales."}</small>
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
