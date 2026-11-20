import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Copy, ExternalLink, EyeOff, Facebook, Loader2,
  MessageCircle, MoreHorizontal, Pencil, RefreshCcw, Search, Send, ShieldCheck,
  Trash2, Users, X,
} from "lucide-react";
import { change, net } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-publications.css";

export type FacebookAd = {
  id: string;
  requirement_id: string;
  title: string;
  specialty: string;
  state: string;
  error: string | null;
  post_url: string | null;
  updated_at?: string;
  attempts?: number;
  comment_count?: number | null;
  reaction_count?: number | null;
  share_count?: number | null;
};

type Comment = {
  id: string; author_name: string | null; body: string; posted_at: string;
  parent_id: string | null; is_hidden: boolean; like_count: number;
  can_reply: boolean; can_hide: boolean; can_private_reply: boolean;
  private_reply_state: "not_sent" | "pending" | "sent" | "failed" | "uncertain";
};
type Job = { id: string; action: string; state: string; error: string; created_at: string };
type PublicationDetail = {
  id: string; state: string; message: string; permalink_url: string;
  comment_count: number | null; reaction_count: number | null;
  share_count: number | null; checked_at: string | null;
  comments: Comment[]; comments_limited: boolean; jobs: Job[];
};

type Props = {
  posts: FacebookAd[];
  automaticEnabled: boolean;
  onSync: (ad: FacebookAd) => Promise<void>;
  onChanged: () => Promise<void>;
  onOpenInbox: () => void;
};

const when = (value?: string | null) => {
  if (!value) return "Sin sincronizar";
  try {
    return new Date(value).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" });
  } catch { return value; }
};
const jobNames: Record<string, string> = {
  refresh: "Sincronización", public_reply: "Respuesta pública",
  private_reply: "Mensaje privado", hide: "Ocultar comentario",
  unhide: "Mostrar comentario", edit: "Edición",
};
const stateLabels: Record<string, string> = {
  published: "Publicada", failed: "Error", uncertain: "Verificar en Facebook",
  pending: "En cola", sending: "Enviando", not_queued: "Sin sincronizar",
  deleted: "Eliminada", disabled: "Desactivada", cancelled: "Cancelada",
};
const isPending = (value: string) => value === "pending" || value === "sending";
const isReview = (value: string) => ["failed", "uncertain", "not_queued"].includes(value);

export default function FacebookPublications({
  posts, automaticEnabled, onSync, onChanged, onOpenInbox,
}: Props) {
  const [filter, setFilter] = useState<"all" | "published" | "review">("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"recent" | "comments">("recent");
  const [active, setActive] = useState("");
  const [detail, setDetail] = useState<PublicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [publicDraft, setPublicDraft] = useState<Record<string, string>>({});
  const [privateDraft, setPrivateDraft] = useState<Record<string, string>>({});
  const [writingFor, setWritingFor] = useState("");
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState("");

  const visible = useMemo(() => {
    const term = search.trim().toLocaleLowerCase("es-CL");
    return [...posts].filter((ad) => {
      if (filter === "published" && ad.state !== "published") return false;
      if (filter === "review" && !isReview(ad.state)) return false;
      return !term || (ad.title + " " + ad.specialty).toLocaleLowerCase("es-CL").includes(term);
    }).sort((a, b) => sort === "comments"
      ? ((b.comment_count ?? -1) - (a.comment_count ?? -1))
      : (b.updated_at || "").localeCompare(a.updated_at || ""));
  }, [filter, posts, search, sort]);
  const current = posts.find((item) => item.id === active);

  useEffect(() => {
    if (!active) { setDetail(null); return; }
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    const get = async () => {
      try {
        const result = await net<PublicationDetail>("/facebook/publications/" + active);
        if (!cancelled) { setDetail(result); setError(""); }
      } catch (e) {
        if (!cancelled) setError(errorText(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void get();
    // Only the expanded publication polls. The page's Messenger inbox is not affected.
    const poll = window.setInterval(() => {
      if (!document.hidden) void get();
    }, 6500);
    return () => { cancelled = true; window.clearInterval(poll); };
  }, [active]);

  useEffect(() => {
    if (!active || current?.state !== "published") return;
    let cancelled = false;
    const refresh = async () => {
      try {
        await change("/facebook/publications/" + active + "/refresh", {});
      } catch (e) { if (!cancelled) setError(errorText(e)); }
    };
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 60000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [active, current?.state]);

  async function reload() {
    if (!active) return;
    const result = await net<PublicationDetail>("/facebook/publications/" + active);
    setDetail(result);
    await onChanged();
  }

  async function action(key: string, url: string, data?: unknown, method = "POST") {
    setBusy(key); setError(""); setNotice("");
    try {
      await change(url, data, method);
      setNotice("Solicitud recibida. El publicador debe confirmar el resultado con Meta.");
      await reload();
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally { setBusy(""); }
  }

  async function sendComment(comment: Comment, privateMode: boolean) {
    const draft = (privateMode ? privateDraft : publicDraft)[comment.id]?.trim();
    if (!draft) { setError("Escribe un mensaje antes de enviarlo."); return; }
    if (privateMode && !window.confirm(
      "Meta permite una sola respuesta privada por comentario. ¿Enviar esta invitación a conversar?")) return;
    const uri = "/facebook/publications/" + active + "/comments/" + comment.id
      + (privateMode ? "/private-reply" : "/reply");
    const success = await action(comment.id, uri, { message: draft });
    if (success) {
      if (privateMode) setPrivateDraft((v) => ({ ...v, [comment.id]: "" }));
      else setPublicDraft((v) => ({ ...v, [comment.id]: "" }));
      setWritingFor("");
    }
  }

  async function remove(ad: FacebookAd) {
    if (!window.confirm("¿Solicitar la eliminación de «" + ad.title
      + "» en Facebook? GALANT la marcará como retirada solo cuando Meta lo confirme.")) return;
    const successful = await action("delete", "/facebook/publications/" + ad.id, undefined, "DELETE");
    if (successful) { await onChanged(); setActive(""); }
  }

  const published = posts.filter((ad) => ad.state === "published").length;
  const needingReview = posts.filter((ad) => isReview(ad.state)).length;
  return <section className="fbpub" aria-label="Administración de publicaciones de Facebook">
    <div className="fbpub-head">
      <div>
        <h3>Publicaciones</h3>
        <p>Administra anuncios, revisa comentarios y continúa las conversaciones autorizadas.</p>
      </div>
      <button className="nw-btn" type="button" onClick={() => void onChanged()}>
        <RefreshCcw size={15} /> Actualizar estados
      </button>
    </div>
    <div className="fbpub-stats">
      <div><span>Publicadas</span><strong>{published}</strong></div>
      <div><span>Necesitan revisión</span><strong>{needingReview}</strong></div>
      <div><span>Total registradas</span><strong>{posts.length}</strong></div>
    </div>
    <div className="fbpub-toolbar">
      <div className="fbpub-filters" aria-label="Filtrar publicaciones">
        <button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>Todas</button>
        <button className={filter === "published" ? "active" : ""} onClick={() => setFilter("published")}>Publicadas</button>
        <button className={filter === "review" ? "active" : ""} onClick={() => setFilter("review")}>Revisar</button>
      </div>
      <label className="fbpub-search"><Search size={15} />
        <input aria-label="Buscar publicación" placeholder="Buscar oficio o anuncio"
          value={search} onChange={(event) => setSearch(event.target.value)} />
      </label>
      <select aria-label="Ordenar publicaciones" value={sort} onChange={(event) => setSort(event.target.value as "recent" | "comments")}>
        <option value="recent">Más recientes</option>
        <option value="comments">Más comentadas</option>
      </select>
    </div>
    {error && <p className="fbpub-error" role="alert"><AlertTriangle size={16} /> {error}</p>}
    {notice && <p className="fbpub-notice" role="status"><CheckCircle2 size={16} /> {notice}</p>}
    {!visible.length && <p className="fbpub-empty">No hay publicaciones para mostrar con este filtro.</p>}
    <div className="fbpub-list">
      {visible.map((ad) => <article className={"fbpub-card" + (active === ad.id ? " expanded" : "")} key={ad.id}>
        <div className="fbpub-card-main">
          <div className="fbpub-card-info">
            <div className="fbpub-title-row">
              <strong>{ad.title}</strong>
              <span className={"fbpub-state " + (ad.state === "published" ? "good" : isReview(ad.state) ? "bad" : "")}>
                {ad.state === "published" && <CheckCircle2 size={13} />}
                {stateLabels[ad.state] || ad.state}
              </span>
            </div>
            <div className="fbpub-meta"><span>{ad.specialty}</span><span>{when(ad.updated_at)}</span></div>
            {ad.error && <p className="fbpub-error-small">{ad.error}</p>}
            {ad.state === "uncertain" && <small>Comprueba el estado real en Facebook antes de reintentar.</small>}
          </div>
          <div className="fbpub-actions">
            {ad.state === "published" && <button type="button" className="nw-btn"
                onClick={() => { setActive(active === ad.id ? "" : ad.id); setEditing(false); setWritingFor(""); }}>
              <MessageCircle size={15} /> {active === ad.id ? "Cerrar" : "Comentarios y gestión"}
            </button>}
            {ad.post_url && <a className="nw-btn" href={ad.post_url} target="_blank" rel="noopener noreferrer">
              <Facebook size={15} /> <span className="fbpub-desktop">Ver en Facebook</span><ExternalLink size={13} />
            </a>}
            {["failed", "not_queued"].includes(ad.state) && <button type="button" className="nw-btn"
                disabled={!!busy || !automaticEnabled} onClick={async () => {
                  setBusy(ad.id);
                  try { await onSync(ad); } catch (e) { setError(errorText(e)); }
                  finally { setBusy(""); }
                }}><RefreshCcw size={15} /> Sincronizar</button>}
            {ad.state === "published" && <details className="fbpub-more">
              <summary aria-label={"Más opciones de " + ad.title}><MoreHorizontal size={19} /></summary>
              <div>
                <button onClick={() => { setActive(ad.id); setEditing(true); }}><Pencil size={14} /> Editar texto</button>
                <button onClick={() => { setActive(ad.id); setEditing(false); }}><MessageCircle size={14} /> Ver comentarios</button>
                <button onClick={() => void remove(ad)}><Trash2 size={14} /> Solicitar eliminación</button>
              </div>
            </details>}
          </div>
        </div>
        {active === ad.id && <div className="fbpub-expanded">
          <div className="fbpub-expanded-head">
            <div><h4>Detalle de publicación</h4><small>{detail?.checked_at ? "Facebook consultado: " + when(detail.checked_at) : "Sin consulta confirmada de Facebook"}</small></div>
            <button type="button" className="fbpub-icon" aria-label="Cerrar detalle" onClick={() => setActive("")}><X size={18} /></button>
          </div>
          {loading && !detail && <p className="fbpub-empty"><Loader2 size={16} className="fbpub-spin" /> Cargando datos guardados…</p>}
          {detail && <>
            <div className="fbpub-metrics">
              <div><strong>{detail.comment_count ?? "—"}</strong><span>Comentarios</span></div>
              <div><strong>{detail.reaction_count ?? "—"}</strong><span>Reacciones</span></div>
              <div><strong>{detail.share_count ?? "—"}</strong><span>Compartidos</span></div>
            </div>
            <p className="fbpub-metric-note">Las cifras provienen de Meta cuando están disponibles. No representan visitas ni alcance.</p>
            <div className="fbpub-copy">
              <div className="fbpub-inline-title"><b>Texto del anuncio</b>
                <button className="nw-btn" type="button" disabled={!detail.message}
                  onClick={async () => {
                    try { await navigator.clipboard.writeText(detail.message); setNotice("Texto copiado para reutilizar como borrador."); }
                    catch { setError("Tu navegador impidió copiar. Selecciona el texto manualmente."); }
                  }}><Copy size={14} /> Reutilizar texto</button>
              </div>
              <p>{detail.message || "Sin texto remoto confirmado. Sincroniza esta publicación para consultarlo."}</p>
              {editing && <div className="fbpub-composer">
                <label htmlFor="fbpub-edit-text">Modificar texto de la publicación</label>
                <textarea id="fbpub-edit-text" rows={5} maxLength={3900}
                  value={editDraft || detail.message}
                  onChange={(event) => setEditDraft(event.target.value)} />
                <div className="fbpub-composer-actions">
                  <small>Una actualización posterior de la necesidad puede reemplazar esta edición.</small>
                  <button className="nw-btn" onClick={() => {setEditing(false);setEditDraft("");}}>Cancelar</button>
                  <button className="nw-btn primary" disabled={!!busy || !(editDraft || detail.message).trim()}
                    onClick={async () => {
                      if (await action("edit", "/facebook/publications/" + active + "/edit", {message: editDraft || detail.message})) {
                        setEditing(false); setEditDraft("");
                      }
                    }}><Pencil size={15} /> Guardar en Facebook</button>
                </div>
              </div>}
            </div>
            <div className="fbpub-comment-title">
              <div><h4>Comentarios</h4><p>Identificamos al autor solo cuando Meta entrega su nombre.</p></div>
              <button className="nw-btn" type="button" disabled={!!busy}
                onClick={() => void action("refresh", "/facebook/publications/" + active + "/refresh", {})}>
                <RefreshCcw size={14} /> Sincronizar
              </button>
            </div>
            {detail.jobs.some((job) => isPending(job.state)) && <p className="fbpub-pending"><Loader2 size={15} className="fbpub-spin" /> Facebook está procesando una solicitud. La confirmación aparecerá aquí.</p>}
            {!detail.comments.length && <p className="fbpub-empty">No hay comentarios disponibles. Si acabas de abrir la publicación, espera la sincronización con Meta.</p>}
            <div className="fbpub-comments">
              {detail.comments.map((c) => <div className={"fbpub-comment" + (c.is_hidden ? " hidden" : "")} key={c.id}>
                <div className="fbpub-avatar"><Users size={17} /></div>
                <div className="fbpub-comment-content">
                  <div className="fbpub-comment-person">
                    <strong>{c.author_name || "Nombre no disponible en Meta"}</strong>
                    <small>{when(c.posted_at)}</small>
                    {c.is_hidden && <span>Oculto</span>}
                  </div>
                  <p>{c.body || "(Comentario sin texto)"}</p>
                  {c.parent_id && <small>Respuesta en el hilo</small>}
                  <div className="fbpub-comment-actions">
                    {c.can_reply && <button type="button" onClick={() => setWritingFor(writingFor === "public:" + c.id ? "" : "public:" + c.id)}>
                      <MessageCircle size={14} /> Responder
                    </button>}
                    {c.can_private_reply && <button type="button" className="fbpub-private"
                      onClick={() => setWritingFor(writingFor === "private:" + c.id ? "" : "private:" + c.id)}>
                      <Send size={14} /> Mensaje privado
                    </button>}
                    {c.can_hide && <button type="button" onClick={() => void action(c.id, "/facebook/publications/" + active + "/comments/" + c.id + "/hide", {})}>
                      <EyeOff size={14} /> {c.is_hidden ? "Mostrar" : "Ocultar"}
                    </button>}
                  </div>
                  {c.private_reply_state === "sent" && <p className="fbpub-private-note"><ShieldCheck size={14} /> Mensaje privado confirmado. Podrás conversar por Messenger si la persona responde.</p>}
                  {c.private_reply_state === "pending" && <p className="fbpub-private-note">Invitación privada en cola.</p>}
                  {c.private_reply_state === "uncertain" && <p className="fbpub-private-note">No se confirmó el mensaje privado. Verifica en Meta; no se enviará de nuevo automáticamente.</p>}
                  {c.private_reply_state === "failed" && <p className="fbpub-private-note">Meta rechazó la respuesta privada. Verifica permisos y plazo.</p>}
                  {writingFor === "public:" + c.id && <div className="fbpub-composer">
                    <label htmlFor={"fbpub-public-" + c.id}>Respuesta pública a {c.author_name || "esta persona"}</label>
                    <textarea id={"fbpub-public-" + c.id} rows={3} maxLength={3900} placeholder="Escribe una respuesta profesional…"
                      value={publicDraft[c.id] || ""} onChange={(e) => setPublicDraft((p) => ({...p, [c.id]: e.target.value}))} />
                    <button className="nw-btn primary" disabled={!!busy} onClick={() => void sendComment(c, false)}>
                      <Send size={14} /> Enviar respuesta
                    </button>
                  </div>}
                  {writingFor === "private:" + c.id && <div className="fbpub-composer private">
                    <label htmlFor={"fbpub-private-" + c.id}>Una invitación privada a {c.author_name || "esta persona"}</label>
                    <textarea id={"fbpub-private-" + c.id} rows={3} maxLength={3900}
                      placeholder="Hola, gracias por tu interés. ¿Quieres enviarnos más información por Messenger?"
                      value={privateDraft[c.id] || ""} onChange={(e) => setPrivateDraft((p) => ({...p, [c.id]: e.target.value}))} />
                    <p>Meta permite solo una respuesta privada por comentario y dentro de su plazo. Para continuar después, la persona debe responder en Messenger.</p>
                    <button className="nw-btn primary" disabled={!!busy} onClick={() => void sendComment(c, true)}>
                      <Send size={14} /> Enviar una vez
                    </button>
                  </div>}
                </div>
              </div>)}
            </div>
            {detail.comments_limited && <p className="fbpub-metric-note">Se muestran los 150 comentarios más recientes disponibles. Consulta la publicación en Facebook para revisar el resto.</p>}
            <div className="fbpub-follow-up">
              <div><b>Seguimiento en Messenger</b><p>Cuando alguien responda al mensaje privado, Galancito podrá continuar en la bandeja de conversaciones. No se equiparan automáticamente los IDs públicos con los de Messenger.</p></div>
              <button className="nw-btn" type="button" onClick={onOpenInbox}><MessageCircle size={15} /> Ver conversaciones</button>
            </div>
            {!!detail.jobs.length && <details className="fbpub-history">
              <summary>Historial de acciones</summary>
              {detail.jobs.map((job) => <div key={job.id}>
                <span>{jobNames[job.action] || job.action} · {when(job.created_at)}</span>
                <strong>{job.state === "done" ? "Confirmado" : job.state === "failed" ? "Error" : job.state === "uncertain" ? "No confirmado" : "En cola"}</strong>
                {job.error && <small>{job.error}</small>}
              </div>)}
            </details>}
          </>}
        </div>}
      </article>)}
    </div>
    {!automaticEnabled && <p className="fbpub-error">El envío automático está desactivado en el VPS. Revisa la conexión antes de gestionar nuevas publicaciones.</p>}
  </section>;
}
