import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot, MessageCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { request } from "./api";
import { change, net } from "./networkApi";
import "./galancito.css";

type Area = "red_obras";
type ChatLine = { role: "user" | "assistant"; text: string; source?: string; runId?: string; question?: string; rated?: boolean };
type Reply = { name: string; answer: string; source: string; notice?: string; run_id?: string;
  references?: {id: string; version: number; title: string}[] };
type Status = { name: string; local_ai_available: boolean; external_ai_available: boolean; read_only: boolean; can_teach?: boolean };
const EXAMPLES = [
  "¿Cómo publicar una necesidad?",
  "¿Qué documentos necesita un contratista?",
  "¿Cómo funciona Facebook?",
];

export default function GalancitoWidget({ area = "red_obras" }: { area?: Area }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatLine[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [consent, setConsent] = useState(false);
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
    setHistory((prev) => [...prev, {role: "user", text: question}]);
    setBusy(true);
    const controller = new AbortController();
    // Allow time for the server to collect facts and query the selected model.
    const deadline = window.setTimeout(() => controller.abort(), 18000);
    try {
      const reply = await request<Reply>("/network/galancito/chat", {
        method: "POST", signal: controller.signal, body: JSON.stringify({
        message: question, area,
        previous_user_messages: history.filter(line => line.role === "user")
          .slice(-4).map(line => line.text.slice(0, 250)),
        allow_external_ai: consent && !!status?.external_ai_available,
        }),
      });
      setHistory((prev) => [...prev, {role: "assistant", source: reply.source, runId: reply.run_id, question,
        text: reply.answer + (reply.references?.length ? "\nReferencia: " + reply.references.map(r => `${r.title} (v${r.version})`).join(", ") : "") +
        (reply.notice ? "\n" + reply.notice : "")}]);
    } catch {
      setHistory((prev) => [...prev, {role: "assistant", text:
        controller.signal.aborted
          ? "Soy Galancito. Esta consulta tardó más de lo previsto. Puedes intentar con una pregunta más breve o solicitar atención humana."
          : "Soy Galancito. No pude conectar con GALANT ahora. Puedes seguir trabajando; tu consulta no modificó ningún registro."}]);
      setError("No se pudo consultar el asistente.");
    } finally { window.clearTimeout(deadline); setBusy(false); }
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

  function askExample(value: string) { setMessage(value); setOpen(true); }
  return <aside className="galancito" aria-label="Asistente Galancito">
    {!open && <button className="galancito-trigger" type="button" onClick={() => setOpen(true)}
        title="Abrir Galancito, asistente de GALANT">
      <Bot size={22} /> <span>Galancito</span>
    </button>}
    {open && <section className="galancito-panel" role="dialog" aria-label="Galancito, asistente virtual" aria-modal="false">
      <header className="galancito-header">
        <div className="galancito-bot-icon"><Bot size={22}/></div>
        <div><strong>Galancito</strong><small>Asesor de Red de Obras · no modifica registros</small></div>
        <button className="galancito-close" type="button" onClick={() => setOpen(false)} aria-label="Cerrar Galancito"><X size={19}/></button>
      </header>
      <div className="galancito-history" role="log" aria-label="Conversación con Galancito" aria-live="polite">
        {!history.length && <div className="galancito-greeting">
          <MessageCircle size={24}/>
          <b>¡Hola! Soy Galancito.</b>
          <p>Te ayudo a buscar contratistas y entender las necesidades de Red de Obras. No modifico documentos ni adjudico trabajos.</p>
          <div className="galancito-examples">{EXAMPLES.map(x =>
            <button type="button" key={x} onClick={() => askExample(x)}>{x}</button>)}</div>
        </div>}
        {history.map((entry,i) => <div key={i} className={"galancito-bubble " + entry.role}>
          <span>{entry.role === "assistant" ? ("Galancito · " + (entry.source === "ai" ? "IA externa" : entry.source === "fallback" ? "orientación local (IA no disponible)" : "orientación local")) : "Tú"}</span>
          <p>{entry.text}</p>
          {entry.runId && <div className="galancito-feedback" aria-label="Evaluar respuesta">
            <button type="button" disabled={feedbackBusy || entry.rated} onClick={() => void rate(i, "useful")}>Útil</button>
            <button type="button" disabled={feedbackBusy || entry.rated} onClick={() => void rate(i, "incorrect")}>Incorrecta</button>
            {status?.can_teach && <button type="button" disabled={feedbackBusy} onClick={() => { setCorrecting(i); setCorrection(""); }}>Proponer corrección</button>}
            {correcting === i && <><label>Respuesta correcta (sin datos privados)<textarea value={correction} maxLength={24000}
              onChange={e => setCorrection(e.target.value)} /></label>
              <button type="button" disabled={feedbackBusy || correction.trim().length < 2} onClick={() => void rate(i, "incorrect", correction.trim())}>Guardar para aprobación</button>
              <button type="button" onClick={() => setCorrecting(null)}>Cancelar</button></>}
          </div>}
        </div>)}
        {feedbackNotice && <p role="status" className="galancito-feedback-notice">{feedbackNotice}</p>}
        {busy && <p className="galancito-thinking"><Sparkles size={14}/> Galancito está preparando una respuesta…</p>}
        <div ref={end}/>
      </div>
      <form className="galancito-compose" onSubmit={(e) => void send(e)}>
        {status?.local_ai_available && !consent && <div className="galancito-safety">
          <ShieldCheck size={14}/> Modelo local disponible · sin consumo de API externa
        </div>}
        {consent && status?.external_ai_available && <div className="galancito-safety">
          <Sparkles size={14}/> IA externa autorizada · se indicará el origen de cada respuesta
        </div>}
        <label className="galancito-privacy"><input type="checkbox" checked={consent}
          onChange={(e) => setConsent(e.target.checked)} disabled={!status?.external_ai_available}/>
          <span>Utilizar equipo IA externo {status?.external_ai_available ? "(requiere consentimiento)" : "(no habilitado)"}</span>
        </label>
        <small>{status?.local_ai_available
          ? "Los mensajes se procesan dentro del VPS. No ingreses RUT, contraseñas ni documentos personales."
          : "Cuando el modelo local no está activo, Galancito ofrece ayuda básica. No compartas información privada."}</small>
        <div className="galancito-input-row">
          <input aria-label="Escribe tu pregunta a Galancito" value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Ej.: ¿Qué debo hacer primero?" maxLength={800}/>
          <button type="submit" disabled={busy || message.trim().length < 2} aria-label="Enviar pregunta"><Send size={18}/></button>
        </div>
        {error && <span role="alert" className="galancito-error">{error}</span>}
        <div className="galancito-safety"><ShieldCheck size={13}/> Solo orienta, no modifica registros.</div>
      </form>
    </section>}
  </aside>;
}
