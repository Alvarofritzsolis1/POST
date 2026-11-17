import { useEffect, useRef, useState, type FormEvent } from "react";
import { Bot, MessageCircle, Send, ShieldCheck, Sparkles, X } from "lucide-react";
import { change, net } from "./networkApi";
import "./galancito.css";

type Area = "galant" | "red_obras";
type ChatLine = { role: "user" | "assistant"; text: string };
type Reply = { name: string; answer: string; source: "ai" | "local"; notice?: string };
type Status = { name: string; external_ai_available: boolean; read_only: boolean };
const EXAMPLES = [
  "¿Cómo publicar una necesidad?",
  "¿Qué documentos necesita un contratista?",
  "¿Cómo funciona Facebook?",
];

export default function GalancitoWidget({ area = "galant" }: { area?: Area }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatLine[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || status) return;
    void net<Status>("/galancito/status").then(setStatus)
      .catch(() => setStatus({name: "Galancito", external_ai_available: false, read_only: true}));
  }, [open, status]);

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
    try {
      const reply = await change<Reply>("/galancito/chat", {
        message: question, area,
        allow_external_ai: consent && !!status?.external_ai_available,
      });
      setHistory((prev) => [...prev, {role: "assistant", text: reply.answer +
        (reply.notice ? "\n" + reply.notice : "")}]);
    } catch {
      setHistory((prev) => [...prev, {role: "assistant", text:
        "Soy Galancito. No pude conectar con GALANT ahora. Puedes seguir trabajando; tu consulta no modificó ningún registro."}]);
      setError("No se pudo consultar el asistente.");
    } finally { setBusy(false); }
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
        <div><strong>Galancito</strong><small>Asistente virtual de GALANT · {area === "red_obras" ? "Red de Obras" : "Guía general"}</small></div>
        <button className="galancito-close" type="button" onClick={() => setOpen(false)} aria-label="Cerrar Galancito"><X size={19}/></button>
      </header>
      <div className="galancito-history" role="log" aria-label="Conversación con Galancito" aria-live="polite">
        {!history.length && <div className="galancito-greeting">
          <MessageCircle size={24}/>
          <b>¡Hola! Soy Galancito.</b>
          <p>Te ayudo a usar GALANT y Red de Obras, sin palabras complicadas. No modifico documentos ni adjudico trabajos.</p>
          <div className="galancito-examples">{EXAMPLES.map(x =>
            <button type="button" key={x} onClick={() => askExample(x)}>{x}</button>)}</div>
        </div>}
        {history.map((entry,i) => <div key={i} className={"galancito-bubble " + entry.role}>
          <span>{entry.role === "assistant" ? "Galancito" : "Tú"}</span>
          <p>{entry.text}</p>
        </div>)}
        {busy && <p className="galancito-thinking"><Sparkles size={14}/> Galancito está preparando una respuesta…</p>}
        <div ref={end}/>
      </div>
      <form className="galancito-compose" onSubmit={(e) => void send(e)}>
        <label className="galancito-privacy"><input type="checkbox" checked={consent}
          onChange={(e) => setConsent(e.target.checked)} disabled={!status?.external_ai_available}/>
          <span>Usar IA externa {status?.external_ai_available ? "(opcional)" : "(no configurada)"}</span>
        </label>
        <small>Si se activa, la consulta puede enviarse al proveedor de IA. No compartas RUT, contraseñas ni documentos personales.</small>
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
