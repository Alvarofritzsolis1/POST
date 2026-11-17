import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AlertTriangle, BookOpen, Bot, CheckCircle2, Clock3, Facebook, Inbox,
  MessageCircle, RefreshCcw, Send, ShieldCheck, Sparkles, Users,
} from "lucide-react";
import { change, net, type Catalog, type Page, type Requirement } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-center.css";
import GalancitoKnowledgeCenter from "./GalancitoKnowledgeCenter";

type Check = { criterion: string; state: "match" | "verify"; detail: string };
type Analysis = {
  label: string; state: string; requirement?: string; checks: Check[];
  missing: string[]; human_review_required: boolean;
};
type Lead = {
  id: string; name: string; company: string; specialty: string; workers: number | null;
  availability: string; experience: string; documents_state: string; status: string;
  requirement_id: string | null; ai_consent: boolean; ai_consent_state: string; ai_paused: boolean; unread: boolean;
  needs_support: boolean; support_reason: string;
  entity_type: "unknown" | "company" | "individual";
  has_employees: boolean | null;
  last_inbound_at: string | null; can_reply: boolean; analysis: Analysis;
  follow_up_on: string | null; follow_up_note: string;
};
type Post = { id: string; requirement_id: string; title: string; specialty: string;
  state: string; error: string | null; post_url: string | null };
type Center = {
  automatic_enabled: boolean; messaging_enabled: boolean; ai_enabled: boolean;
  auto_reply_enabled: boolean; ai_provider?: string; page_id: string; pending_ads: Post[]; leads: Lead[];
  guides_approved: number;
  counts: { pending_ads: number; contacts: number; unread: number; review: number; support: number };
};
type Onboarding = {
  phase: string; next_question: string | null;
  required_for_review: string[]; conditional: string[];
  not_applicable: string[]; prevention_examples: string[];
  notice: string; ask_for_files_now: boolean; human_followup: boolean;
};
type Chat = { id: string; direction: "inbound" | "outbound"; state: string; body: string;
  ai_generated: boolean; created_at: string; error: string | null };
type Detail = { lead: Lead; messages: Chat[] };
type Guide = { id: string; slug: string; trade: string; aliases: string[]; explanation: string;
  document_guidance: string[]; approved: boolean };
type Triage = {
  id: string; name: string; company: string; category: string;
  category_source: string; category_evidence: string; status: string; stage: string;
  urgency: "high" | "normal" | "none"; next_action: string;
  requirement_id: string | null; requirement_title: string | null;
  follow_up_on: string | null; follow_up_note: string;
  needs_support: boolean; unread: boolean; human_review_required: boolean;
};
type Tracking = {
  total: number; urgent: number; needs_human: number; unlinked: number;
  overdue: number; by_category: Record<string,number>;
  by_stage: Record<string,number>; by_requirement: Record<string,number>;
  rows: Triage[]; limited: boolean; disclaimer: string;
};
type TriageNote = { triage: Triage; ai_note: string; source: string; changes_applied: boolean };
const statuses: Record<string, string> = {
  new: "Nuevo", contacting: "En conversación", pending_review: "Por revisar",
  shortlisted: "Posible candidato", archived: "Archivado", pending: "Pendiente",
  disabled: "Conexión desactivada", not_queued: "Sin sincronizar",
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
  const [tab, setTab] = useState<"summary" | "tracking" | "inbox" | "pending" | "guides" | "knowledge" | "performance">("inbox");
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reply, setReply] = useState("");
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("");
  const [guides, setGuides] = useState<Guide[]>([]);
  const [adDraft, setAdDraft] = useState<{id: string; title: string; draft: string; source: string} | null>(null);
  const [guide, setGuide] = useState(freshGuide);
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const [triageNote, setTriageNote] = useState<TriageNote | null>(null);
  const [triageFilter, setTriageFilter] = useState<"all"|"high"|"unlinked"|"due">("all");

  const refresh = useCallback(async () => {
    const current = await net<Center>("/facebook/center");
    setCenter(current);
    setSelectedId((prev) =>
      prev && current.leads.some((lead) => lead.id === prev) ? prev : (current.leads[0]?.id || ""));
  }, []);
  const refreshTracking = useCallback(async () => {
    const data = await net<Tracking>("/facebook/galancito/seguimiento");
    setTracking(data);
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
    setOnboarding(null);
    setTriageNote(null);
  }, [selectedId, refreshDetail]);
  // Desde la campana de GALANT: abrir directamente el contacto que pidió ayuda.
  useEffect(() => {
    const openLinked = () => {
      const [prefix, kind, leadId] = window.location.hash.slice(1).split("/");
      if (prefix === "red" && kind === "facebook" && leadId) {
        setSelectedId(leadId);
        setTab("inbox");
      }
    };
    openLinked();
    window.addEventListener("hashchange", openLinked);
    return () => window.removeEventListener("hashchange", openLinked);
  }, []);

  useEffect(() => {
    if (!selectedId || tab !== "inbox") return;
    const refreshMessages = async () => {
      if (document.hidden) return;
      try {
        const update = await net<Detail>("/facebook/leads/" + selectedId);
        setDetail((previous) => {
          if (!previous || previous.lead.id !== selectedId) return update;
          // El polling no debe borrar ediciones del administrador aún sin guardar.
          return {...previous, messages: update.messages, lead: {
            ...previous.lead,
            ai_consent: update.lead.ai_consent,
            ai_consent_state: update.lead.ai_consent_state,
            ai_paused: update.lead.ai_paused,
            needs_support: update.lead.needs_support,
            support_reason: update.lead.support_reason,
            unread: update.lead.unread,
            can_reply: update.lead.can_reply,
            last_inbound_at: update.lead.last_inbound_at,
          }};
        });
      } catch { /* No borrar la conversación si hay un fallo temporal de red. */ }
    };
    const interval = window.setInterval(() => { void refreshMessages(); }, 10000);
    return () => window.clearInterval(interval);
  }, [selectedId, tab]);

  useEffect(() => {
    if (tab === "tracking") void refreshTracking().catch((e) => setError(errorText(e)));
  }, [tab, refreshTracking]);

  useEffect(() => {
    if (tab === "guides") void net<Guide[]>("/facebook/guides")
      .then(setGuides).catch((e) => setError(errorText(e)));
  }, [tab]);

  async function mutate(label: string, run: () => Promise<unknown>, message: string): Promise<boolean> {
    setSaving(label); setError(""); setNotice("");
    try {
      await run();
      setNotice(message);
      await refresh();
      if (tab === "tracking") await refreshTracking();
      if (selectedId) await refreshDetail(selectedId);
      return true;
    } catch (e) { setError(errorText(e)); return false; }
    finally { setSaving(""); }
  }
  function patchLead(patch: Partial<Lead>) {
    if (!selectedId) return;
    void mutate("lead", () => change("/facebook/leads/" + selectedId, patch, "PATCH"),
      "Ficha del interesado actualizada.");
  }
  async function analyzeLead() {
    if (!selectedId) return;
    setSaving("triage"); setError("");
    try {
      const data = await change<TriageNote>("/facebook/leads/" + selectedId + "/galancito/analyze");
      setTriageNote(data);
      setNotice("Análisis orientativo actualizado; no se cambió la ficha.");
    } catch (e) { setError(errorText(e)); }
    finally { setSaving(""); }
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
      .then((success) => { if (success) setReply(""); });
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
      .then(async (success) => {
        if (success) {
          setGuides(await net<Guide[]>("/facebook/guides"));
          setGuide(freshGuide());
        }
      }).catch((e) => setError(errorText(e)));
  }
  const lead = detail?.lead ?? null;
  const visible = center?.leads.filter((r) =>
    [r.name, r.company, r.specialty].some((x) => x.toLowerCase().includes(filter.toLowerCase()))) || [];

  return <div className="fbc">
    <header className="fbc-header">
      <div>
        <span className="fbc-eyebrow"><Facebook size={16} /> FACEBOOK · CENTRO DE CONTACTOS</span>
        <h2>Galancito · Contratistas e interesados</h2>
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
        ["Necesitan orientación", center?.counts.support ?? 0, "amber"],
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
      <span className={center?.ai_enabled ? "good" : ""}><Bot size={15} /> Galancito {center?.ai_enabled ? (center?.ai_provider === "ollama" ? "local · sin API de pago" : "IA disponible") : "sin configurar"}</span>
      <span className={center?.auto_reply_enabled ? "good" : "warning"}><Sparkles size={15} /> Respuestas automáticas {center?.auto_reply_enabled ? "habilitadas" : "desactivadas"}</span>
    </div>
    {error && <p role="alert" className="fbc-error">{error}</p>}
    {notice && <p role="status" className="fbc-notice">{notice}</p>}
    <nav aria-label="Centro Facebook" className="fbc-tabs">
      <button className={tab === "summary" ? "selected" : ""} onClick={() => setTab("summary")}>Resumen</button>
      <button className={tab === "inbox" ? "selected" : ""} onClick={() => setTab("inbox")}><Inbox size={16} /> Conversaciones</button>
      <button className={tab === "knowledge" ? "selected" : ""} onClick={() => setTab("knowledge")}><BookOpen size={16} /> Conocimientos</button>
      <button className={tab === "performance" ? "selected" : ""} onClick={() => setTab("performance")}>Rendimiento</button>
      <button className={tab === "pending" ? "selected" : ""} onClick={() => setTab("pending")}><Clock3 size={16} /> Anuncios pendientes</button>
      <button className={tab === "guides" ? "selected" : ""} onClick={() => setTab("guides")}><BookOpen size={16} /> Guías de oficios</button>
      <button className={tab === "tracking" ? "selected" : ""} onClick={() => setTab("tracking")}><ShieldCheck size={16} /> Seguimiento Galancito</button>
    </nav>
    {tab === "summary" && <GalancitoKnowledgeCenter mode="summary" />}
    {tab === "knowledge" && <GalancitoKnowledgeCenter />}
    {tab === "performance" && <GalancitoKnowledgeCenter mode="performance" />}
    {tab === "tracking" && <section className="fbc-tracking" aria-label="Seguimiento Galancito">
      <div className="fbc-tracking-head">
        <div>
          <h3>Seguimiento de interesados</h3>
          <p>Organiza conversaciones y necesidades por oficio. Galancito sugiere próximos pasos,
            pero ningún candidato queda aprobado o rechazado automáticamente.</p>
        </div>
        <button className="nw-btn" disabled={!!saving} onClick={() => void refreshTracking().catch((e) => setError(errorText(e)))}>
          <RefreshCcw size={16}/> Actualizar seguimiento
        </button>
      </div>
      {!tracking ? <p className="fbc-empty">Cargando seguimiento…</p> : <>
        <div className="fbc-tracking-counters">
          {[
            ["Interesados", tracking.total],
            ["Requieren atención", tracking.urgent],
            ["Apoyo humano", tracking.needs_human],
            ["Sin necesidad", tracking.unlinked],
            ["Seguimientos vencidos", tracking.overdue],
          ].map(([title, value]) => <div key={title} className="fbc-tracking-counter">
            <small>{title}</small><strong>{value}</strong>
          </div>)}
        </div>
        <div className="fbc-tracking-summaries">
          <section>
            <h4>Por especialidad</h4>
            {!Object.keys(tracking.by_category).length && <small>Sin datos para categorizar.</small>}
            {Object.entries(tracking.by_category).slice(0,10).map(([name,count]) =>
              <div key={name} className="fbc-tracking-line">
                <span>{name}</span><b>{count}</b>
              </div>)}
          </section>
          <section>
            <h4>Estado del seguimiento</h4>
            {Object.entries(tracking.by_stage).map(([name,count]) =>
              <div key={name} className="fbc-tracking-line">
                <span>{name}</span><b>{count}</b>
              </div>)}
          </section>
          <section>
            <h4>Necesidades relacionadas</h4>
            {Object.entries(tracking.by_requirement).slice(0,8).map(([name,count]) =>
              <div key={name} className="fbc-tracking-line">
                <span>{name}</span><b>{count}</b>
              </div>)}
          </section>
        </div>
        <div className="fbc-tracking-filters">
          {[
            ["all", "Todos"], ["high", "Prioritarios"], ["unlinked", "Sin necesidad"], ["due", "Seguimiento vencido"],
          ].map(([value,label]) => <button key={value} type="button"
            className={triageFilter === value ? "selected" : ""}
            onClick={() => setTriageFilter(value as typeof triageFilter)}>{label}</button>)}
        </div>
        <div className="fbc-tracking-table">
          {tracking.rows.filter((r) =>
            triageFilter === "all" ||
            (triageFilter === "high" && r.urgency === "high") ||
            (triageFilter === "unlinked" && !r.requirement_id) ||
            (triageFilter === "due" && r.stage === "Seguimiento vencido")
          ).map((r) => <article className="fbc-tracking-item" key={r.id}>
            <div><strong>{r.company || r.name}</strong>
              <small>{r.category} · {r.category_source === "sugerida" ? "oficio sugerido, por confirmar" :
                r.category_source === "declarada" ? "oficio registrado" : "oficio pendiente"}</small></div>
            <div><b>{r.stage}</b><small>{r.requirement_title || "Sin necesidad vinculada"}</small></div>
            <div><span>{r.next_action}</span><small>{r.follow_up_on ? "Seguimiento: " + r.follow_up_on : "Sin fecha de seguimiento"}</small></div>
            <button className="nw-btn" type="button" onClick={() => {
              setSelectedId(r.id); setTab("inbox");
            }}>Ver conversación</button>
          </article>)}
          {!tracking.rows.length && <p className="fbc-empty">Aún no hay interesados. El seguimiento aparecerá cuando lleguen mensajes.</p>}
        </div>
        {tracking.limited && <small>Se muestran 200 contactos recientes; los totales corresponden a esta vista.</small>}
        <small className="fbc-tracking-disclaimer">{tracking.disclaimer}</small>
      </>}
    </section>}
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
              <small>{statuses[item.status] || item.status}</small>
              {item.needs_support && <small className="fbc-support-mini">Necesita orientación</small>}</div>
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
                <small>{msg.ai_generated ? "Galancito IA · " : ""}{dateText(msg.created_at)} · {msg.state === "sent" ? "Enviado" : msg.direction === "inbound" ? "Recibido" : msg.state}</small>
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
          {lead.needs_support && <div className="fbc-support-alert" role="status">
            <AlertTriangle size={18}/>
            <div><b>Necesita orientación paso a paso</b>
              <p>{lead.support_reason || "La persona solicitó ayuda para avanzar."}</p>
              <small>No enviar una lista larga de documentos. Mantener revisión humana.</small>
            </div>
          </div>}
          <label className="fbc-check"><input type="checkbox" checked={lead.needs_support}
             onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, needs_support:e.target.checked}} : old)} />
             Mantener alerta de apoyo (administración puede desactivarla después de ayudar)</label>
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
          <div className="fbc-pair">
            <label>Próximo seguimiento
              <input type="date" value={lead.follow_up_on || ""} onChange={(e) => setDetail((old) =>
                old ? {...old, lead: {...old.lead, follow_up_on: e.target.value || null}} : old)} />
            </label>
            <label>Nota de seguimiento
              <input maxLength={240} value={lead.follow_up_note || ""} placeholder="Ej.: llamar al residente"
                onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead,
                  follow_up_note: e.target.value}} : old)} />
            </label>
          </div>
          <label>Etapa
            <select value={lead.status} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, status: e.target.value}} : old)}>
              {["new","contacting","pending_review","shortlisted","archived"].map(x => <option key={x} value={x}>{statuses[x]}</option>)}
            </select></label>
          <label>¿Cómo trabaja?
            <select value={lead.entity_type} onChange={(e) => {
              setOnboarding(null);
              setDetail((old) => old ? {...old, lead: {...old.lead, entity_type:e.target.value as Lead["entity_type"]}} : old);
            }}>
              <option value="unknown">Aún no lo sabemos</option>
              <option value="company">Tiene sociedad / empresa</option>
              <option value="individual">Persona natural, a su nombre</option>
            </select>
          </label>
          <label>¿Tiene trabajadores contratados?
            <select value={lead.has_employees === null ? "unknown" : String(lead.has_employees)}
              onChange={(e) => {
                setOnboarding(null);
                setDetail((old) => old ? {...old, lead: {...old.lead,
                  has_employees: e.target.value === "unknown" ? null : e.target.value === "true"}} : old);
              }}>
              <option value="unknown">No se sabe todavía</option>
              <option value="true">Sí, tiene trabajadores</option>
              <option value="false">No, trabaja solo</option>
            </select>
          </label>
          <label>Documentación (revisión humana)
            <select value={lead.documents_state} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, documents_state: e.target.value}} : old)}>
              <option value="unverified">No revisada</option><option value="declared">Declarada, no comprobada</option>
              <option value="verified">Verificada por administración</option>
            </select>
          </label>
          <div className="fbc-galancito-status">
            <Bot size={18}/><div>
              <strong>Galancito · Respuestas automáticas</strong>
              <small>Permiso de IA: {lead.ai_consent_state === "accepted" ? "Aceptado por Messenger" :
                lead.ai_consent_state === "requested" ? "Se solicitó permiso" :
                lead.ai_consent_state === "declined" ? "Prefiere atención humana" :
                "Sin solicitar"}</small>
              <small>El administrador puede pausar o reactivar al asistente; no puede otorgar consentimiento en nombre del contacto.</small>
            </div>
          </div>
          <label className="fbc-check"><input type="checkbox" checked={lead.ai_paused}
            onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, ai_paused: e.target.checked}} : old)} />
            Atención humana: Galancito en pausa para este contacto</label>
          <button type="button" disabled={!!saving} className="nw-btn nw-primary"
            onClick={() => patchLead({
              company: lead.company, specialty: lead.specialty,
              workers: lead.workers, availability: lead.availability,
              experience: lead.experience, status: lead.status,
              documents_state: lead.documents_state, ai_paused: lead.ai_paused,
              needs_support: lead.needs_support,
              entity_type: lead.entity_type, has_employees: lead.has_employees,
              requirement_id: lead.requirement_id,
              follow_up_on: lead.follow_up_on, follow_up_note: lead.follow_up_note,
            })}>Guardar ficha y seguimiento</button>
          <button type="button" className="nw-btn" disabled={!!saving}
            onClick={() => void analyzeLead()}>
            <Sparkles size={15}/> {saving === "triage" ? "Analizando…" : "Galancito: analizar seguimiento"}
          </button>
          {triageNote && <div className="fbc-triage-note">
            <b>Recomendación de Galancito (no cambia ningún estado)</b>
            <small>Oficio: {triageNote.triage.category} · {triageNote.triage.category_source === "sugerida" ? "sugerido" : "registrado o pendiente"}</small>
            <small>Etapa: {triageNote.triage.stage}</small>
            <p>{triageNote.triage.next_action}</p>
            {triageNote.ai_note && <p>{triageNote.ai_note}</p>}
            <small>Las decisiones y verificaciones documentales corresponden a administración.</small>
          </div>}
          <button type="button" className="nw-btn" disabled={!!saving}
            onClick={() => void mutate("guide", async () => {
              const guidance = await net<Onboarding>("/facebook/leads/" + lead.id + "/onboarding");
              setOnboarding(guidance);
            }, "Orientación interna cargada.")}>Ver requisitos aplicables (solo administración)</button>
          {onboarding && <div className="fbc-onboarding">
            <b>Orientación interna · no enviar toda la lista al maestro</b>
            {onboarding.next_question && <p>Primera pregunta: {onboarding.next_question}</p>}
            {!!onboarding.required_for_review.length && <><strong>Revisar más adelante</strong>
              {onboarding.required_for_review.map((x) => <small key={x}>• {x}</small>)}</>}
            {!!onboarding.conditional.length && <><strong>Según la situación</strong>
              {onboarding.conditional.map((x) => <small key={x}>• {x}</small>)}</>}
            {!!onboarding.not_applicable.length && <><strong>No corresponde automáticamente</strong>
              {onboarding.not_applicable.map((x) => <small key={x}>• {x}</small>)}</>}
            <strong>Ejemplos preventivos, no obligaciones definitivas</strong>
            {onboarding.prevention_examples.map((x) => <small key={x}>• {x}</small>)}
            <small>{onboarding.notice}</small>
          </div>}
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
        <div className="fbc-ad-actions">
          <button className="nw-btn" disabled={!!saving}
            onClick={() => void mutate("ad-draft", async () => {
              const draft = await change<{draft: string; source: string}>(
                "/facebook/requirements/" + ad.requirement_id + "/ad-draft");
              setAdDraft({id: ad.id, title: ad.title, ...draft});
            }, "Borrador de anuncio preparado para revisión.")}>
            <Sparkles size={15} /> Ver texto sugerido</button>
          {["failed", "not_queued"].includes(ad.state) && <button className="nw-btn"
            disabled={!!saving || !center?.automatic_enabled}
            onClick={() => void mutate(ad.id, () => change("/requirements/" + ad.requirement_id + "/facebook/sync"),
              "Se solicitó sincronización. Verifica el estado antes de repetir.")}>
            <RefreshCcw size={15} /> {ad.state === "failed" ? "Reintentar" : "Sincronizar"}</button>}
        </div>
        {ad.state === "uncertain" && <small>Comprueba primero en Facebook para no duplicar el anuncio.</small>}
      </article>)}
      {adDraft && <div className="fbc-ad-draft"><div className="fbc-ad-draft-header">
        <b>Texto propuesto: {adDraft.title}</b>
        <button className="nw-btn" onClick={() => setAdDraft(null)}>Cerrar</button></div>
        <pre>{adDraft.draft}</pre>
        <small>{adDraft.source === "ia_local" ? "Introducción redactada por Galancito local; datos provenientes de la necesidad" :
          adDraft.source === "ai" ? "Borrador de IA" : "Texto del requerimiento"}.
          Revisa los datos antes de publicar; la vista previa no publica nada.</small>
      </div>}
      {!center?.automatic_enabled && <div className="fbc-alert"><AlertTriangle size={18} /> El VPS tiene desactivado el envío automático. Hay que habilitar el publicador y verificar el token de página.</div>}
    </section>}
    {tab === "guides" && <div className="fbc-guides">
      <section>
        <h3>Guías aprobadas: {center?.guides_approved || 0} / 26 oficios</h3>
        <p>Agrega los oficios de tu empresa, incluidos los 26 que necesitas. Las guías solo se utilizan cuando el administrador las marca como aprobadas; no son requisitos legales automáticos.</p>
        <div className="fbc-guide-list">
          {guides.map((item) => <button key={item.id} type="button" onClick={() => setGuide({
            slug: item.slug,
            trade: item.trade, aliases: item.aliases.join("\n"),
            explanation: item.explanation, documents: item.document_guidance.join("\n"),
            approved: item.approved,
          })}>{item.trade} <small>{item.approved ? "Aprobada" : "Sin aprobar"}</small></button>)}
        </div>
      </section>
      <form onSubmit={saveGuide}>
        <h3>Editar o agregar oficio</h3>
        <label>Nombre del oficio<input required list="fbc-trade-guide-list" value={guide.trade} onChange={(e) => setGuide({...guide, trade: e.target.value})} placeholder="Ej.: Gasfitería" /></label>
        <datalist id="fbc-trade-guide-list">{catalog.specialties.map((x) => <option key={x} value={x}/>)}</datalist>
        <label>Palabras que usan los maestros (una por línea)<textarea value={guide.aliases} rows={3} onChange={(e) => setGuide({...guide, aliases: e.target.value})} placeholder={"gasfiter\nmaestro sanitario\ninstalador"} /></label>
        <label>Qué hace este oficio (palabras simples)<textarea value={guide.explanation} rows={3} onChange={(e) => setGuide({...guide, explanation: e.target.value})} placeholder="Ej.: Instala o repara cañerías, llaves de agua y desagües." /></label>
        <label>Documentos que administración confirmará (uno por línea)<textarea value={guide.documents} rows={4} onChange={(e) => setGuide({...guide, documents: e.target.value})} placeholder="No inventar documentos. Indica solo los revisados para esta especialidad." /></label>
        <label className="fbc-check"><input type="checkbox" checked={guide.approved} onChange={(e) => setGuide({...guide, approved: e.target.checked})} /> Guía revisada por administración</label>
        <button className="nw-btn nw-primary" type="submit" disabled={!!saving}>Guardar guía</button>
      </form>
    </div>}
  </div>;
}
