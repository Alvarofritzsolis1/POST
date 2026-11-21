import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowLeft, CircleAlert, Clock3, LoaderCircle, MessageCircle, RefreshCw, Send } from "lucide-react";
import { change, net } from "./networkApi";
import { errorText } from "./NetworkUI";

type Message = {
  id: string; direction: "inbound" | "outbound"; state: string;
  body: string; automated: boolean; error: string | null;
  created_at: string; updated_at: string;
};
type Thread = { lead_id: string; name: string; messages: Message[];
  can_reply: boolean; reply_notice: string };
const stateLabel = (state: string) => ({
  pending: "En cola", ai_pending: "Preparando", drafting: "Preparando",
  sending: "Enviando", sent: "Enviado por Meta",
  received: "Recibido", failed: "Error al enviar",
  uncertain: "Confirmación pendiente", cancelled: "Cancelado",
}[state] || state);
const time = (stamp: string) => {
  const date = new Date(stamp);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("es-CL", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  }) : "";
};

export default function RequirementCandidateChat({
  requirementId, leadId, name, contactMissing, onBack, onDraftDirty,
}: {
  requirementId: string; leadId: string; name: string;
  contactMissing: boolean; onBack: () => void; onDraftDirty: (value: boolean) => void;
}) {
  const [thread, setThread] = useState<Thread | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { onDraftDirty(Boolean(draft.trim())); }, [draft, onDraftDirty]);
  const chatPath = "/requirements/" + encodeURIComponent(requirementId) +
    "/candidates/" + encodeURIComponent(leadId) + "/chat";

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const result = await net<Thread>(chatPath);
      setThread(result);
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally { if (!quiet) setLoading(false); }
  }, [chatPath]);

  useEffect(() => {
    setThread(null);
    setDraft("");
    setError("");
    setNotice("");
    void refresh();
  }, [refresh]);
  useEffect(() => {
    const poll = () => { if (!document.hidden) void refresh(true); };
    const interval = window.setInterval(poll, 6000);
    window.addEventListener("focus", poll);
    return () => { window.clearInterval(interval); window.removeEventListener("focus", poll); };
  }, [refresh]);
  useEffect(() => {
    if (!loading && endRef.current?.parentElement) {
      const list = endRef.current.parentElement;
      list.scrollTop = list.scrollHeight;
    }
  }, [loading, thread?.messages.length]);

  async function send() {
    const message = draft.trim();
    if (!message || busy || !thread?.can_reply) return;
    setBusy(true); setNotice(""); setError("");
    try {
      await change(chatPath, {message});
      setDraft("");
      setNotice("Mensaje ingresado a la cola. Revisa su estado para confirmar el envío.");
      await refresh(true);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }
  function suggest() {
    setDraft("Podemos seguir coordinando por acá. Si te acomoda, también puedes dejar un teléfono o correo para que el equipo pueda contactarte. Es opcional.");
    setNotice("Sugerencia editable. Revisa el mensaje antes de enviarlo.");
  }
  return <div className="nwc-chat" aria-label={"Conversación con " + name}>
    <div className="nwc-chat-heading">
      <button type="button" className="nwc-chat-back" onClick={onBack}>
        <ArrowLeft size={17}/> Volver a la ficha
      </button>
      <div><strong><MessageCircle size={18}/> Chat · {name}</strong>
        <small>Messenger · Conversación de esta persona</small></div>
      <button type="button" className="nwc-chat-reload" onClick={() => void refresh()}
        aria-label="Actualizar conversación" title="Actualizar"><RefreshCw size={17}/></button>
    </div>
    {error && <div className="nwc-error" role="alert"><CircleAlert size={16}/>{error}
      <button type="button" onClick={()=>void refresh()}>Reintentar</button></div>}
    {loading && !thread ?
      <div className="nwc-empty"><LoaderCircle size={22} className="nwc-spin"/> Cargando mensajes…</div> :
      <div className="nwc-chat-timeline" role="log" aria-label="Historial de Messenger" aria-live="polite">
        {thread?.messages.length ? thread.messages.map(message =>
          <div key={message.id} className={"nwc-chat-line " + (message.direction === "outbound" ? "out" : "in")}>
            <div className="nwc-chat-bubble">
              <p>{message.body || "Mensaje sin texto"}</p>
              <small>{time(message.created_at)} · {message.direction === "inbound" ?
                "Recibido" : stateLabel(message.state)}{message.automated ? " · Galancito" : ""}</small>
              {message.error && <small className="nwc-chat-failed">{message.error}</small>}
            </div>
          </div>
        ) : <div className="nwc-empty">No hay mensajes sincronizados para este contacto.</div>}
        <div ref={endRef}/>
      </div>}
    <form className="nwc-chat-compose" onSubmit={(e:FormEvent)=>{e.preventDefault();void send();}}>
      {!thread?.can_reply && <div className="nwc-chat-blocked"><Clock3 size={16}/>
        {thread?.reply_notice || "Cargando autorización para responder…"}</div>}
      {contactMissing && thread?.can_reply && <button type="button" className="nwc-chat-suggestion"
        onClick={suggest}>Sugerir cómo pedir un medio de contacto <span>Opcional</span></button>}
      <label htmlFor="nwc-chat-text">Mensaje al contacto</label>
      <div className="nwc-chat-compose-row">
        <textarea id="nwc-chat-text" rows={3} maxLength={550}
          placeholder={thread?.can_reply ? "Escribe tu mensaje… (Enter envía)" : "Solo lectura"}
          disabled={!thread?.can_reply || busy} value={draft}
          onChange={e=>setDraft(e.target.value)} onKeyDown={keyDown}/>
        <button type="submit" disabled={!thread?.can_reply || busy || !draft.trim()}
          title="Enviar mensaje por Messenger">
          {busy ? <LoaderCircle size={17} className="nwc-spin"/> : <Send size={17}/>} Enviar
        </button>
      </div>
      {notice && <small className="nwc-chat-notice" role="status">{notice}</small>}
      <small>Enter envía · Shift+Enter agrega una línea. No se envía nada automáticamente.</small>
    </form>
  </div>;
}
