import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Check, ChevronRight, CircleHelp, Clock3, ExternalLink,
  Eye, EyeOff, Loader2, MessageCircle, RefreshCcw, Search, Send, ShieldCheck,
  Sparkles, ThumbsUp, Trash2, UserRound, X,
} from "lucide-react";
import { change, net } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-interactions.css";

type Category = "interested" | "question" | "positive" | "negative" | "spam" | "ambiguous" | "human_review";
type ReviewState = "new" | "review" | "handled" | "dismissed";
type ActionJob = {
  id: string; action: string; state: string; message: string; error: string; at: string;
};
type Interaction = {
  id: string; remote_comment_id: string; record_id: string; post_title: string; post_specialty: string; post_url: string;
  author_name: string | null; author_picture_url: string | null; body: string;
  posted_at: string; parent_id: string | null; like_count: number; reply_count: number;
  is_page_author: boolean;
  classification: Category; classification_source: "manual" | "rules" | "ai";
  classification_score: number; review_state: ReviewState; reviewed_at: string | null;
  is_hidden: boolean; is_deleted: boolean; user_likes: boolean | null;
  can_reply: boolean; can_hide: boolean; can_delete: boolean; can_private_reply: boolean; can_like: boolean;
  private_reply_state: string; lead_id: string | null; history: ActionJob[];
};
type Inbox = { rows: Interaction[]; limited: boolean; mode: "manual" };
type AwaitingDelivery = { commentId: string; mode: "public" | "private"; text: string };
type Props = { onOpenInbox: () => void; onOpenLead: (id: string) => void; onOpenProfile: (id: string) => void };
type Filter = "all" | "pending" | "interested" | "review" | "negative" | "hidden" | "spam";

const categories: Record<Category, { label: string; tone: string }> = {
  interested: { label: "Interesado", tone: "good" },
  question: { label: "Consulta", tone: "info" },
  positive: { label: "Positivo", tone: "good" },
  negative: { label: "Negativo", tone: "danger" },
  spam: { label: "Posible spam", tone: "muted" },
  ambiguous: { label: "Sin clasificar", tone: "neutral" },
  human_review: { label: "Revisión humana", tone: "warning" },
};
const jobLabels: Record<string, string> = {
  public_reply: "Respuesta pública", private_reply: "Mensaje privado",
  hide: "Ocultado", unhide: "Restaurado", delete_comment: "Eliminación",
  like: "Me gusta", unlike: "Quitar Me gusta",
};
const jobStates: Record<string, string> = {
  done: "Confirmado por Meta", pending: "En cola", sending: "Enviando",
  failed: "Error", uncertain: "Sin confirmar",
};
const when = (stamp: string) => {
  try { return new Date(stamp).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }); }
  catch { return stamp; }
};
const initials = (name: string | null) => (name || "?").split(/\s+/).slice(0, 2).map(v => v[0] || "").join("").toUpperCase();
const hasPublicReply = (c: Interaction) => c.history.some(job => job.action === "public_reply" && job.state === "done");
const hasPendingJob = (c: Interaction) => c.history.some(job => ["pending", "sending"].includes(job.state));

function ProfileAvatar({ name, src, large = false }: { name: string | null; src: string | null; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  return <span className={"fbint-avatar" + (large ? " large" : "")} aria-label={"Avatar de " + (name || "usuario sin nombre")}>
    {src && !failed ? <img alt="" loading="lazy" src={src} referrerPolicy="no-referrer" onError={() => setFailed(true)} /> :
      (name ? initials(name) : <UserRound size={large ? 24 : 18} aria-hidden="true" />)}
  </span>;
}

export default function FacebookInteractions({ onOpenInbox, onOpenLead, onOpenProfile }: Props) {
  const [data, setData] = useState<Inbox | null>(null);
  const [activeId, setActiveId] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [privateDraft, setPrivateDraft] = useState<Record<string, string>>({});
  const [replyMode, setReplyMode] = useState<"public" | "private">("public");
  const [suggestSource, setSuggestSource] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [awaiting, setAwaiting] = useState<Record<string, AwaitingDelivery>>({});

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const result = await net<Inbox>("/facebook/publications/interactions/inbox");
      setData(result);
      if (!silent) setError("");
    } catch (err) {
      if (!silent) setError(errorText(err));
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => {
      if (!document.hidden && !busy) void load(true);
    }, 12000);
    return () => window.clearInterval(interval);
  }, [load, busy]);

  const rows = data?.rows || [];
  const active = rows.find(c => c.id === activeId) || null;
  useEffect(() => {
    if (!data || !Object.keys(awaiting).length) return;
    const finished = Object.entries(awaiting).flatMap(([jobId, wait]) => {
      const item = data.rows.find(c => c.id === wait.commentId);
      const job = item?.history.find(j => j.id === jobId);
      return job && ["done", "failed", "uncertain"].includes(job.state) ? [{ jobId, wait, job }] : [];
    });
    if (!finished.length) return;
    for (const { wait, job } of finished) {
      if (job.state === "done") {
        if (wait.mode === "private") {
          setPrivateDraft(previous => previous[wait.commentId] === wait.text
            ? { ...previous, [wait.commentId]: "" } : previous);
        } else {
          setDraft(previous => previous[wait.commentId] === wait.text
            ? { ...previous, [wait.commentId]: "" } : previous);
        }
        setNotice("Meta confirmó la respuesta. El historial quedó actualizado.");
      } else {
        setError(job.state === "uncertain"
          ? "Meta no confirmó el envío. Conservamos tu borrador: comprueba Facebook antes de repetir."
          : (job.error || "Meta rechazó el envío. Conservamos tu borrador."));
      }
    }
    setAwaiting(previous => {
      const next = { ...previous };
      for (const { jobId } of finished) delete next[jobId];
      return next;
    });
  }, [data, awaiting]);
  const thread = active ? rows.filter(c =>
    c.record_id === active.record_id && (c.parent_id === active.remote_comment_id ||
      (active.parent_id && c.remote_comment_id === active.parent_id))
  ).filter(c => c.id !== active.id).slice(0, 20) : [];
  const stats = useMemo(() => ({
    total: rows.filter(c => !c.is_page_author).length,
    interested: rows.filter(c => !c.is_page_author && c.classification === "interested" && !c.is_deleted).length,
    pending: rows.filter(c => !c.is_page_author && !hasPublicReply(c) && !c.is_deleted && !["dismissed", "handled"].includes(c.review_state)).length,
    review: rows.filter(c => !c.is_page_author && (c.review_state === "review" || c.classification === "human_review")).length,
  }), [rows]);
  const visible = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("es-CL");
    return rows.filter(c => {
      if (c.is_page_author && !term) return false;
      if (filter === "interested" && c.classification !== "interested") return false;
      if (filter === "negative" && c.classification !== "negative") return false;
      if (filter === "spam" && c.classification !== "spam") return false;
      if (filter === "hidden" && !c.is_hidden) return false;
      if (filter === "review" && c.review_state !== "review" && c.classification !== "human_review") return false;
      if (filter === "pending" && (hasPublicReply(c) || c.is_deleted || ["dismissed", "handled"].includes(c.review_state))) return false;
      return !term || (c.body + " " + (c.author_name || "") + " " + c.post_title + " " + c.post_specialty).toLocaleLowerCase("es-CL").includes(term);
    });
  }, [rows, filter, search]);

  async function execute(key: string, path: string, body?: unknown, method = "POST") {
    setBusy(key); setError(""); setNotice("");
    try {
      const response = await change<{ message?: string }>(path, body, method);
      setNotice(response?.message || (method === "PATCH" ? "Revisión guardada." : "Solicitud recibida. Esperando confirmación de Meta."));
      await load(true);
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally { setBusy(""); }
  }
  const urlFor = (c: Interaction) => "/facebook/publications/" + c.record_id + "/comments/" + c.id;

  async function send(c: Interaction) {
    const mode = replyMode;
    const isPrivate = mode === "private";
    const text = (isPrivate ? privateDraft[c.id] : draft[c.id])?.trim();
    if (!text) { setError("Escribe una respuesta antes de enviarla."); return; }
    if (isPrivate && !window.confirm("Meta permite una sola invitación privada por comentario. ¿Enviar ahora?")) return;
    setBusy(c.id); setError(""); setNotice("");
    try {
      const response = await change<{ id: string; state: string }>(
        urlFor(c) + (isPrivate ? "/private-reply" : "/reply"), { message: text });
      if (!response?.id || response.state !== "pending") {
        throw new Error("No se confirmó que la solicitud entrara en la cola.");
      }
      setAwaiting(prev => ({ ...prev, [response.id]: { commentId: c.id, mode, text } }));
      setNotice("Respuesta en cola. Conservaremos el borrador hasta la confirmación de Meta.");
      await load(true);
    } catch (err) {
      setError(errorText(err));
    } finally { setBusy(""); }
  }

  async function suggest(c: Interaction) {
    setBusy("suggest"); setError(""); setNotice("");
    try {
      const response = await change<{ draft: string; source: string; requires_review: boolean }>(urlFor(c) + "/suggest", {});
      if (response.draft) {
        setDraft(v => ({ ...v, [c.id]: response.draft }));
        setReplyMode("public");
        setSuggestSource(response.source === "ai" ? "Sugerencia IA — revisa antes de enviar" : "Plantilla local — revisa antes de enviar");
      } else {
        setNotice("Este comentario requiere una respuesta redactada por una persona.");
      }
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(""); }
  }

  async function analyze(c: Interaction) {
    setBusy("analyze"); setError(""); setNotice("");
    try {
      const response = await change<{ classification: Category; source: string; message: string }>(urlFor(c) + "/analyze", {});
      setNotice(response.message || "Análisis actualizado.");
      await load(true);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(""); }
  }

  async function review(c: Interaction, state: ReviewState, classification?: Category) {
    await execute("review", urlFor(c) + "/review", {
      review_state: state, ...(classification ? { classification } : {}),
    }, "PATCH");
  }

  async function remove(c: Interaction) {
    if (!window.confirm("¿Eliminar definitivamente el comentario de " + (c.author_name || "este usuario") + "? Esta acción no se puede deshacer.")) return;
    await execute("delete", urlFor(c), undefined, "DELETE");
  }

  async function refresh() {
    const ok = await execute("refresh", "/facebook/publications/interactions/refresh", {});
    if (ok) setNotice("Sincronización solicitada. Los comentarios aparecerán cuando Meta confirme la consulta.");
  }

  return <section className="fbint" aria-label="Centro de Interacciones de Facebook">
    <div className="fbint-heading">
      <div>
        <span className="fbint-eyebrow"><Sparkles size={14} /> RED DE OBRAS</span>
        <h3>Centro de Interacciones</h3>
        <p>Comentarios, interesados y seguimiento en un solo lugar.</p>
      </div>
      <div className="fbint-head-actions">
        <span className="fbint-manual"><ShieldCheck size={15} /> Respuestas manuales</span>
        <button className="nw-btn" type="button" disabled={!!busy} onClick={() => void refresh()}>
          <RefreshCcw size={15} /> Sincronizar
        </button>
      </div>
    </div>
    <div className="fbint-stats" aria-label="Resumen de últimos comentarios">
      <div><span>Recientes</span><strong>{stats.total}</strong></div>
      <div><span>Interesados</span><strong>{stats.interested}</strong></div>
      <div><span>Sin respuesta pública</span><strong>{stats.pending}</strong></div>
      <div><span>Revisar</span><strong>{stats.review}</strong></div>
    </div>
    <div className="fbint-toolbar">
      <label className="fbint-search"><Search size={16} /><input value={search}
        onChange={e => setSearch(e.target.value)} placeholder="Buscar persona, comentario u oficio" aria-label="Buscar interacciones" /></label>
      <div className="fbint-filters" role="group" aria-label="Filtrar comentarios">
        {([
          ["all", "Todos"], ["pending", "Pendientes"], ["interested", "Interesados"],
          ["review", "Revisar"], ["negative", "Negativos"], ["spam", "Spam"], ["hidden", "Ocultos"],
        ] as [Filter, string][]).map(([key, label]) =>
          <button key={key} type="button" className={filter === key ? "selected" : ""}
            aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}
      </div>
    </div>
    {error && <p className="fbint-alert error" role="alert"><AlertTriangle size={16} /> {error}</p>}
    {notice && <p className="fbint-alert notice" role="status"><Check size={16} /> {notice}</p>}
    {loading && <p className="fbint-empty"><Loader2 className="fbint-spin" size={17} /> Cargando comentarios…</p>}
    {!loading && !visible.length && <p className="fbint-empty">
      {data?.rows.length ? "No hay comentarios con este filtro." : "Aún no hay comentarios sincronizados de tus publicaciones."}
    </p>}
    <div className={"fbint-layout" + (active ? " detail-open" : "")}>
      <div className="fbint-feed" aria-label="Comentarios">
        {visible.map(c => <button key={c.id} type="button"
          className={"fbint-item" + (activeId === c.id ? " active" : "") + (c.is_deleted ? " deleted" : "")}
          onClick={() => {setActiveId(c.id);setShowHistory(false);setSuggestSource("");setReplyMode("public");}}>
          <ProfileAvatar name={c.author_name} src={c.author_picture_url} />
          <span className="fbint-item-main">
            <span className="fbint-item-top">
              <strong>{c.author_name || "Nombre no disponible"}</strong>
              <small>{when(c.posted_at)}</small>
            </span>
            <span className="fbint-item-text">{c.body || "(Sin texto)"}</span>
            <span className="fbint-item-bottom">
              <span className={"fbint-tag " + (categories[c.classification]?.tone || "neutral")}>
                {categories[c.classification]?.label || "Sin clasificar"}
              </span>
              {c.is_deleted && <span className="fbint-tag muted">Eliminado</span>}
              {c.is_hidden && !c.is_deleted && <span className="fbint-tag muted">Oculto</span>}
              {hasPendingJob(c) && <span className="fbint-tag warning">En proceso</span>}
              {hasPublicReply(c) && <span className="fbint-tag good">Respondido</span>}
              {c.reply_count > 0 && <span className="fbint-tag info">{c.reply_count} respuesta{c.reply_count === 1 ? "" : "s"}</span>}
              <small>{c.post_specialty || c.post_title}</small>
            </span>
          </span>
          <ChevronRight size={17} className="fbint-chevron" />
        </button>)}
      </div>
      {active && <aside className="fbint-detail" aria-label="Detalle y gestión del comentario">
        <div className="fbint-detail-header">
          <h4>Detalle del comentario</h4>
          <button type="button" className="fbint-icon" aria-label="Cerrar detalle" onClick={() => setActiveId("")}><X size={18}/></button>
        </div>
        <div className="fbint-person">
          <ProfileAvatar large name={active.author_name} src={active.author_picture_url} />
          <div><strong>{active.author_name || "Nombre no disponible en Meta"}</strong>
            <small>{when(active.posted_at)}</small>
            <span className={"fbint-tag " + (categories[active.classification]?.tone || "neutral")}>
              {categories[active.classification]?.label || "Sin clasificar"}
            </span>
          </div>
        </div>
        <div className="fbint-comment-body"><p>{active.body || "(Comentario sin texto)"}</p>
          <small>Publicación: {active.post_title}</small>
          {active.parent_id && <small>Respuesta dentro de un hilo</small>}
          {active.post_url && <a href={active.post_url} target="_blank" rel="noopener noreferrer">
            Abrir publicación en Facebook <ExternalLink size={13}/></a>}
        </div>
        {!!thread.length && <div className="fbint-thread">
          <strong>Interacción en el hilo · {thread.length}</strong>
          {thread.map(item => <button key={item.id} className="fbint-thread-reply"
            type="button" onClick={() => {setActiveId(item.id);setReplyMode("public");setShowHistory(false);}}>
            <ProfileAvatar name={item.author_name} src={item.author_picture_url}/>
            <span><b>{item.author_name || "Nombre no disponible"}</b><small>{item.body || "(Sin texto)"}</small></span>
          </button>)}
        </div>}
        <div className="fbint-section-title"><b>Clasificación y seguimiento</b>
          <button type="button" className="fbint-text-btn" disabled={!!busy || active.is_deleted}
            onClick={() => void analyze(active)}><Sparkles size={14}/> Analizar con Galancito</button>
        </div>
        <div className="fbint-controls">
          <label>Tipo de comentario
            <select value={active.classification} disabled={!!busy} onChange={e => void review(active, "review", e.target.value as Category)}>
              {Object.entries(categories).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
            </select>
          </label>
          <label>Estado
            <select value={active.review_state} disabled={!!busy} onChange={e => void review(active, e.target.value as ReviewState)}>
              <option value="new">Nuevo</option><option value="review">Revisar</option>
              <option value="handled">Gestionado</option><option value="dismissed">Descartado</option>
            </select>
          </label>
        </div>
        <small className="fbint-source">Clasificación {active.classification_source === "manual" ? "corregida por una persona" :
          active.classification_source === "ai" ? "analizada por Galancito; requiere revisión" :
          "preliminar mediante reglas locales"}. No es una evaluación de la persona.</small>
        {!active.is_deleted && !active.is_page_author && <>
          <div className="fbint-section-title"><b>Responder comentario</b><button className="fbint-text-btn"
            type="button" disabled={!!busy} onClick={() => void suggest(active)}>
            <Sparkles size={15}/> Sugerir texto
          </button></div>
          <div className="fbint-reply-tabs">
            <button type="button" className={replyMode === "public" ? "active" : ""} onClick={() => setReplyMode("public")}>Público</button>
            {active.can_private_reply && <button type="button" className={replyMode === "private" ? "active" : ""} onClick={() => setReplyMode("private")}>Privado</button>}
          </div>
          <textarea aria-label="Escribir respuesta" rows={3} maxLength={3900}
            value={(replyMode === "public" ? draft : privateDraft)[active.id] || ""}
            onChange={e => replyMode === "public"
              ? setDraft(v => ({ ...v, [active.id]: e.target.value }))
              : setPrivateDraft(v => ({ ...v, [active.id]: e.target.value }))}
            placeholder="Escribe una respuesta profesional…" />
          {suggestSource && replyMode === "public" && <small className="fbint-source">{suggestSource}</small>}
          {replyMode === "private" && <small className="fbint-source">Solo una invitación privada si Meta la permite. La conversación continúa cuando la persona responde.</small>}
          <button className="nw-btn fbint-send" type="button" disabled={!!busy || hasPendingJob(active) || Object.values(awaiting).some(j => j.commentId === active.id) || (replyMode === "public" ? !active.can_reply : !active.can_private_reply)}
            onClick={() => void send(active)}><Send size={15}/> Enviar {replyMode === "public" ? "respuesta" : "mensaje privado"}</button>
        </>}
        <div className="fbint-section-title"><b>Administrar</b></div>
        <div className="fbint-action-row">
          {active.can_like && <button type="button" className="nw-btn" disabled={!!busy}
            onClick={() => void execute("reaction", urlFor(active) + (active.user_likes ? "/unlike" : "/like"), {})}>
            <ThumbsUp size={15}/> {active.user_likes ? "Quitar Me gusta" : "Me gusta"}
          </button>}
          {active.can_hide && <button type="button" className="nw-btn" disabled={!!busy}
            onClick={() => void execute("hide", urlFor(active) + "/hide", {})}>
            {active.is_hidden ? <Eye size={15}/> : <EyeOff size={15}/>}
            {active.is_hidden ? "Restaurar" : "Ocultar"}
          </button>}
          {active.can_delete && <button type="button" className="nw-btn fbint-danger" disabled={!!busy}
            onClick={() => void remove(active)}><Trash2 size={15}/> Eliminar</button>}
          {active.lead_id && <>
            <button className="nw-btn" type="button" onClick={() => onOpenProfile(active.lead_id!)}>
              <UserRound size={15}/> Ver ficha</button>
            <button className="nw-btn" type="button" onClick={() => onOpenLead(active.lead_id!)}>
              <MessageCircle size={15}/> Ver Messenger</button>
          </>}
          {!active.lead_id && <button className="nw-btn" type="button" onClick={onOpenInbox}>
            <MessageCircle size={15}/> Conversaciones</button>}
          {!active.can_hide && !active.is_deleted && <small className="fbint-source">Meta no habilitó la moderación de este comentario.</small>}
        </div>
        <div className="fbint-section-title"><b>Historial de interacciones</b>
          <button className="fbint-text-btn" type="button" onClick={() => setShowHistory(v => !v)}>
            {showHistory ? "Ocultar" : "Ver todo"}</button></div>
        <ol className="fbint-timeline">
          <li><Clock3 size={14}/><span>Comentó la publicación <small>{when(active.posted_at)}</small></span></li>
          {active.history.filter(job => showHistory || job.action !== "private_reply").map(job => <li key={job.id}>
            {job.state === "done" ? <Check size={14}/> : <CircleHelp size={14}/>}
            <span>{jobLabels[job.action] || job.action} · {jobStates[job.state] || job.state}
              <small>{when(job.at)}{job.error ? " · " + job.error : ""}</small>
              {job.message && <small className="fbint-history-message">{job.message}</small>}
            </span>
          </li>)}
          {!active.history.length && <li><CircleHelp size={14}/><span>Sin acciones de moderación registradas.</span></li>}
        </ol>
        {active.private_reply_state === "sent" && !active.lead_id &&
          <p className="fbint-alert notice">Invitación privada confirmada. Aún no hay conversación de Messenger iniciada por la persona.</p>}
        {active.private_reply_state === "uncertain" &&
          <p className="fbint-alert error">El envío privado no se confirmó. Revisa Facebook antes de repetirlo.</p>}
      </aside>}
    </div>
    {data?.limited && <p className="fbint-source">Se muestran los últimos 200 comentarios almacenados. Usa Facebook para revisar publicaciones anteriores.</p>}
  </section>;
}
