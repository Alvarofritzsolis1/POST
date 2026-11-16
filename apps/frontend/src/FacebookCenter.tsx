import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AlertTriangle, BookOpen, Bot, CheckCircle2, Clock3, Facebook, Inbox,
  MessageCircle, RefreshCcw, Send, ShieldCheck, Sparkles, Users,
} from "lucide-react";
import { change, net, type Catalog, type Page, type Requirement } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-center.css";

type Check = { criterion: string; state: "match" | "verify"; detail: string };
type Analysis = {
  label: string; state: string; requirement?: string; checks: Check[];
  missing: string[]; human_review_required: boolean;
};
type Lead = {
  id: string; name: string; company: string; specialty: string; workers: number | null;
  availability: string; experience: string; documents_state: string; status: string;
  requirement_id: string | null; ai_consent: boolean; unread: boolean;
  last_inbound_at: string | null; can_reply: boolean; analysis: Analysis;
};
type Post = { id: string; requirement_id: string; title: string; specialty: string;
  state: string; error: string | null; post_url: string | null };
type Center = {
  automatic_enabled: boolean; messaging_enabled: boolean; ai_enabled: boolean;
  auto_reply_enabled: boolean; page_id: string; pending_ads: Post[]; leads: Lead[];
  guides_approved: number;
  counts: { pending_ads: number; contacts: number; unread: number; review: number };
};
type Chat = { id: string; direction: "inbound" | "outbound"; state: string; body: string;
  ai_generated: boolean; created_at: string; error: string | null };
type Detail = { lead: Lead; messages: Chat[] };
type Guide = { id: string; trade: string; aliases: string[]; explanation: string;
  document_guidance: string[]; approved: boolean };
const statuses: Record<string, string> = {
  new: "Nuevo", contacting: "En conversación", pending_review: "Por revisar",
  shortlisted: "Posible candidato", archived: "Archivado", pending: "Pendiente",
  failed: "Error", sending: "Enviando", uncertain: "Revisar en Meta",
};
const freshGuide = () => ({
  slug: "", trade: "", aliases: "", explanation: "", documents: "", approved: false,
});
const dateText = (v: string) => {
  try { return new Date(v).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }); }
  catch { return v; }
};

export default function FacebookCenter({ catalog }: { catalog: Catalog }) {
  const [center, setCenter] = useState<Center | null>(null);
  const [tab, setTab] = useState<"inbox" | "pending" | "guides">("inbox");
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reply, setReply] = useState("");
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("");
  const [guides, setGuides] = useState<Guide[]>([]);
  const [guide, setGuide] = useState(freshGuide);

  const refresh = useCallback(async () => {
    const current = await net<Center>("/facebook/center");
    setCenter(current);
    setSelectedId((prev) =>
      prev && current.leads.some((lead) => lead.id === prev) ? prev : (current.leads[0]?.id || ""));
  }, []);
  const refreshDetail = useCallback(async (id: string) => {
    if (!id) { setDetail(null); return; }
    const result = await net<Detail>("/facebook/leads/" + id);
    setDetail(result);
  }, []);
  useEffect(() => {
    void refresh().catch((e) => setError(errorText(e)));
    void net<Page<Requirement>>("/requirements?limit=100&offset=0")
      .then((data) => setRequirements(data.rows.filter((r) => r.state === "published")))
      .catch(() => {});
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh().catch(() => {});
    }, 12000);
    return () => window.clearInterval(interval);
  }, [refresh]);
  useEffect(() => {
    void refreshDetail(selectedId).catch((e) => setError(errorText(e)));
    setReply("");
  }, [selectedId, refreshDetail]);
  useEffect(() => {
    if (tab === "guides") void net<Guide[]>("/facebook/guides")
      .then(setGuides).catch((e) => setError(errorText(e)));
  }, [tab]);

  async function mutate(label: string, run: () => Promise<unknown>, message: string) {
    setSaving(label); setError(""); setNotice("");
    try {
      await run();
      setNotice(message);
      await refresh();
      if (selectedId) await refreshDetail(selectedId);
    } catch (e) { setError(errorText(e)); }
    finally { setSaving(""); }
  }
  function patchLead(patch: Partial<Lead>) {
    if (!selectedId) return;
    void mutate("lead", () => change("/facebook/leads/" + selectedId, patch, "PATCH"),
      "Ficha del interesado actualizada.");
  }
  async function suggest() {
    if (!selectedId) return;
    setSaving("draft"); setError("");
    try {
      const data = await change<{draft: string}>("/facebook/leads/" + selectedId + "/suggest");
      setReply(data.draft);
      setNotice("Borrador preparado. Puedes corregirlo antes de enviar.");
    } catch (e) { setError(errorText(e)); }
    finally { setSaving(""); }
  }
  function send(e: FormEvent) {
    e.preventDefault();
    if (!reply.trim() || !selectedId) return;
    void mutate("send", () => change("/facebook/leads/" + selectedId + "/reply", { message: reply }),
      "Respuesta guardada en la cola de envío. Confirma el estado enviado.")
      .then(() => setReply(""));
  }
  function saveGuide(e: FormEvent) {
    e.preventDefault();
    const slug = guide.slug || guide.trade.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!slug) return;
    void mutate("guide", () => change("/facebook/guides/" + encodeURIComponent(slug), {
      trade: guide.trade, aliases: guide.aliases.split("\n").map((x) => x.trim()).filter(Boolean),
      explanation: guide.explanation,
      document_guidance: guide.documents.split("\n").map((x) => x.trim()).filter(Boolean),
      approved: guide.approved,
    }, "PUT"), "Guía guardada para la IA y el administrador.")
      .then(async () => {
        setGuides(await net<Guide[]>("/facebook/guides"));
        setGuide(freshGuide());
      }).catch((e) => setError(errorText(e)));
  }
  const lead = detail?.lead ?? null;
  const visible = center?.leads.filter((r) =>
    [r.name, r.company, r.specialty].some((x) => x.toLowerCase().includes(filter.toLowerCase()))) || [];

  return <div className="fbc">
    <header className="fbc-header">
      <div>
        <span className="fbc-eyebrow"><Facebook size={16} /> FACEBOOK · CENTRO DE CONTACTOS</span>
        <h2>Contratistas e interesados</h2>
        <p>Una bandeja simple para conversar, orientar a maestros y encontrar apoyo para las obras.</p>
      </div>
      <button className="nw-btn" type="button" onClick={() => void refresh()} disabled={!!saving}>
        <RefreshCcw size={16} /> Actualizar
      </button>
    </header>
    <div className="fbc-stats">
      {[
        ["Por responder", center?.counts.unread ?? 0, "blue"],
        ["Interesados", center?.counts.contacts ?? 0, "teal"],
        ["Por evaluar", center?.counts.review ?? 0, "amber"],
        ["Anuncios pendientes", center?.counts.pending_ads ?? 0, "navy"],
      ].map(([title, value, color]) => <div key={title} className={"fbc-stat " + color}>
        <span>{title}</span><strong>{value}</strong>
      </div>)}
    </div>
    <div className="fbc-state-row">
      <span className={center?.messaging_enabled ? "good" : "warning"}>
        <MessageCircle size={15} /> Messenger {center?.messaging_enabled ? "configurado" : "sin configurar"}
      </span>
      <span className={center?.automatic_enabled ? "good" : "warning"}>
        <Facebook size={15} /> Publicación automática {center?.automatic_enabled ? "activa" : "desactivada"}
      </span>
      <span className={center?.ai_enabled ? "good" : ""}><Bot size={15} /> IA {center?.ai_enabled ? "disponible" : "sin configurar"}</span>
    </div>
    {error && <p role="alert" className="fbc-error">{error}</p>}
    {notice && <p role="status" className="fbc-notice">{notice}</p>}
    <nav aria-label="Centro Facebook" className="fbc-tabs">
      <button className={tab === "inbox" ? "selected" : ""} onClick={() => setTab("inbox")}><Inbox size={16} /> Conversaciones</button>
      <button className={tab === "pending" ? "selected" : ""} onClick={() => setTab("pending")}><Clock3 size={16} /> Anuncios pendientes</button>
      <button className={tab === "guides" ? "selected" : ""} onClick={() => setTab("guides")}><BookOpen size={16} /> Guías de oficios</button>
    </nav>
    {tab === "inbox" && <div className="fbc-inbox">
      <aside className="fbc-contacts">
        <div className="fbc-pane-title"><Users size={16} /><b>Personas que escribieron</b></div>
        <input className="fbc-search" aria-label="Buscar interesados" value={filter}
          onChange={(e) => setFilter(e.target.value)} placeholder="Buscar por oficio o empresa..." />
        <div className="fbc-contacts-list">
          {!visible.length && <p className="fbc-empty">Aún no hay mensajes sincronizados. Los contactos aparecerán cuando escriban a la página conectada.</p>}
          {visible.map((item) => <button key={item.id}
            onClick={() => setSelectedId(item.id)}
            className={"fbc-contact " + (item.id === selectedId ? "selected" : "")}>
            <div className="fbc-avatar">{(item.name || "?").charAt(0).toUpperCase()}</div>
            <div><strong>{item.company || item.name}</strong>
              <small>{item.specialty || "Oficio por confirmar"}</small>
              <small>{statuses[item.status] || item.status}</small></div>
            {item.unread && <span className="fbc-unread" aria-label="Sin leer" />}
          </button>)}
        </div>
      </aside>
      <section className="fbc-conversation">
        {!lead ? <div className="fbc-empty fbc-empty-center">
          <MessageCircle size={32} /><b>Selecciona un interesado</b>
          <p>Aquí podrás responder sin cambiar a Facebook.</p></div> :
          <>
            <div className="fbc-pane-title"><MessageCircle size={17} /><div>
              <b>{lead.company || lead.name}</b>
              <small>Messenger · {lead.can_reply ? "Respuestas habilitadas" : "Ventana de respuesta vencida"}</small>
            </div><button className="nw-btn" onClick={() =>
              void mutate("read", () => change("/facebook/leads/" + lead.id + "/read"),
                "Marcado como leído.")} disabled={!!saving}>Leído</button></div>
            <div className="fbc-chat-stream">
              {detail?.messages.map((msg) => <div key={msg.id} className={"fbc-bubble " + msg.direction}>
                <p>{msg.body || "Procesando respuesta…"}</p>
                <small>{msg.ai_generated ? "IA · " : ""}{dateText(msg.created_at)} · {msg.state === "sent" ? "Enviado" : msg.direction === "inbound" ? "Recibido" : msg.state}</small>
                {msg.error && <small>{msg.error}</small>}
              </div>)}
            </div>
            <form className="fbc-composer" onSubmit={send}>
              <textarea aria-label="Respuesta para el contratista" value={reply}
                onChange={(e) => setReply(e.target.value)} rows={3}
                placeholder="Escribe simple. Ej.: Hola, gracias. ¿Qué trabajo haces?" />
              <div className="fbc-composer-actions">
                <button className="nw-btn" type="button" disabled={!!saving}
                  onClick={() => void suggest()}><Sparkles size={16} /> {saving === "draft" ? "Preparando…" : "Sugerir respuesta"}</button>
                <button className="nw-btn nw-primary" type="submit"
                  disabled={!!saving || !reply.trim() || !lead.can_reply}>
                  <Send size={16} /> Responder
                </button>
              </div>
              {!lead.can_reply && <small>La ventana normal de Messenger terminó. Espera un nuevo mensaje o utiliza herramientas autorizadas por Meta.</small>}
            </form>
          </>}
      </section>
      <aside className="fbc-analysis">
        <div className="fbc-pane-title"><ShieldCheck size={17} /><b>Ficha y compatibilidad</b></div>
        {!lead ? <p className="fbc-empty">Selecciona una conversación.</p> : <>
          <label>Empresa o nombre comercial<input value={lead.company} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, company: e.target.value}} : old)} /></label>
          <label>Oficio o especialidad<input list="fbc-trades" value={lead.specialty} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, specialty: e.target.value}} : old)} /></label>
          <datalist id="fbc-trades">{catalog.specialties.map((x) => <option value={x} key={x}/>)}</datalist>
          <div className="fbc-pair">
            <label>Personas disponibles<input type="number" min={1} value={lead.workers ?? ""}
              onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, workers: e.target.value ? Number(e.target.value) : null}} : old)} /></label>
            <label>Disponible desde<input type="date" value={lead.availability} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, availability: e.target.value}} : old)} /></label>
          </div>
          <label>Relacionar con necesidad
            <select value={lead.requirement_id || ""} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, requirement_id: e.target.value || null}} : old)}>
              <option value="">Aún no asignada</option>
              {requirements.map((x) => <option key={x.id} value={x.id}>{x.site} · {x.title}</option>)}
            </select>
          </label>
          <label>Experiencia declarada<textarea value={lead.experience} rows={2}
            onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, experience: e.target.value}} : old)} /></label>
          <label>Etapa
            <select value={lead.status} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, status: e.target.value}} : old)}>
              {["new","contacting","pending_review","shortlisted","archived"].map(x => <option key={x} value={x}>{statuses[x]}</option>)}
            </select></label>
          <label>Documentación (revisión humana)
            <select value={lead.documents_state} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, documents_state: e.target.value}} : old)}>
              <option value="unverified">No revisada</option><option value="declared">Declarada, no comprobada</option>
              <option value="verified">Verificada por administración</option>
            </select>
          </label>
          <label className="fbc-check"><input type="checkbox" checked={lead.ai_consent}
            onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, ai_consent: e.target.checked}} : old)} />
            El contacto autorizó procesar sus mensajes con IA</label>
          <button type="button" disabled={!!saving} className="nw-btn nw-primary"
            onClick={() => patchLead({
              company: lead.company, specialty: lead.specialty,
              workers: lead.workers, availability: lead.availability,
              experience: lead.experience, status: lead.status,
              documents_state: lead.documents_state, ai_consent: lead.ai_consent,
              requirement_id: lead.requirement_id,
            })}>Guardar ficha</button>
          <div className="fbc-match">
            <b>{lead.analysis.label}</b>
            {lead.analysis.checks.map((c) => <p key={c.criterion}>
              {c.state === "match" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15}/>}
              <span>{c.criterion}: {c.detail}</span></p>)}
            {!!lead.analysis.missing.length && <>
              <strong>Datos por confirmar</strong>
              {lead.analysis.missing.map(x => <small key={x}>· {x}</small>)}</>}
            <small>La IA no habilita contratistas ni decide adjudicaciones.</small>
          </div>
        </>}
      </aside>
    </div>}
    {tab === "pending" && <section className="fbc-pending">
      <h3>Publicaciones que necesitan atención</h3>
      <p>Las necesidades se publican desde Red de Obras. Aquí solo revisas anuncios en cola, errores o envíos inciertos.</p>
      {!center?.pending_ads.length && <p className="fbc-empty">No hay anuncios pendientes ni errores registrados.</p>}
      {center?.pending_ads.map((ad) => <article key={ad.id} className="fbc-ad">
        <div><strong>{ad.title}</strong><small>{ad.specialty} · {statuses[ad.state] || ad.state}</small>
          {ad.error && <p>{ad.error}</p>}</div>
        {ad.state === "failed" && <button className="nw-btn" disabled={!!saving}
          onClick={() => void mutate(ad.id, () => change("/requirements/" + ad.requirement_id + "/facebook/sync"), "Sincronización solicitada.")}>
          <RefreshCcw size={15} /> Reintentar</button>}
        {ad.state === "uncertain" && <small>Comprueba primero en Facebook para no duplicar el anuncio.</small>}
      </article>)}
      {!center?.automatic_enabled && <div className="fbc-alert"><AlertTriangle size={18} /> El VPS tiene desactivado el envío automático. Hay que habilitar el publicador y verificar el token de página.</div>}
    </section>}
    {tab === "guides" && <div className="fbc-guides">
      <section>
        <h3>Conocimiento que aprende a usar GALANT</h3>
        <p>Agrega los oficios de tu empresa, incluidos los 26 que necesitas. Las guías solo se utilizan cuando el administrador las marca como aprobadas; no son requisitos legales automáticos.</p>
        <div className="fbc-guide-list">
          {guides.map((item) => <button key={item.id} type="button" onClick={() => setGuide({
            slug: item.trade.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,""),
            trade: item.trade, aliases: item.aliases.join("\n"),
            explanation: item.explanation, documents: item.document_guidance.join("\n"),
            approved: item.approved,
          })}>{item.trade} <small>{item.approved ? "Aprobada" : "Sin aprobar"}</small></button>)}
        </div>
      </section>
      <form onSubmit={saveGuide}>
        <h3>Editar o agregar oficio</h3>
        <label>Nombre del oficio<input required value={guide.trade} onChange={(e) => setGuide({...guide, trade: e.target.value})} placeholder="Ej.: Gasfitería" /></label>
        <label>Palabras que usan los maestros (una por línea)<textarea value={guide.aliases} rows={3} onChange={(e) => setGuide({...guide, aliases: e.target.value})} placeholder={"gasfiter\nmaestro sanitario\ninstalador"} /></label>
        <label>Qué hace este oficio (palabras simples)<textarea value={guide.explanation} rows={3} onChange={(e) => setGuide({...guide, explanation: e.target.value})} placeholder="Ej.: Instala o repara cañerías, llaves de agua y desagües." /></label>
        <label>Documentos que administración confirmará (uno por línea)<textarea value={guide.documents} rows={4} onChange={(e) => setGuide({...guide, documents: e.target.value})} placeholder="No inventar documentos. Indica solo los revisados para esta especialidad." /></label>
        <label className="fbc-check"><input type="checkbox" checked={guide.approved} onChange={(e) => setGuide({...guide, approved: e.target.checked})} /> Guía revisada por administración</label>
        <button className="nw-btn nw-primary" type="submit" disabled={!!saving}>Guardar guía</button>
      </form>
    </div>}
  </div>;
}
