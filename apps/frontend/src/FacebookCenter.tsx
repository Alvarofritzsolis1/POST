import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  AlertTriangle, BookOpen, Bot, CheckCircle2, Clock3, Facebook, Inbox,
  MessageCircle, RefreshCcw, Send, ShieldCheck, Sparkles, Users,
} from "lucide-react";
import { change, net, type Catalog, type Page, type Requirement } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-center.css";
import GalancitoKnowledgeCenter from "./GalancitoKnowledgeCenter";
import FacebookOverview from "./FacebookOverview";
import FacebookPersonSheet from "./FacebookPersonSheet";
import PersonAvatar from "./PersonAvatar";
import "./facebook-minimal-layout.css";
import "./facebook-tracking-refresh.css";
import "./facebook-navigation-patch.css";
import NetworkFacebook from "./NetworkFacebook";
import FacebookPublications from "./FacebookPublications";
import FacebookInteractions from "./FacebookInteractions";

type Check = { criterion: string; state: "match" | "verify"; detail: string };
type Analysis = {
  label: string; state: string; requirement?: string; checks: Check[];
  missing: string[]; human_review_required: boolean;
};
type Evidence = { source: string; message_id: string | null; at: string };
const fieldLabels: Record<string, string> = {
  display_name: "Nombre", name_opt_out: "Preferencia de nombre", specialty: "Oficio principal",
  entity_type: "Tipo de postulante", interest_type: "Interés", team_available: "Modalidad",
  workers: "Personas", experience: "Experiencia", work_communes: "Comunas",
  availability: "Disponibilidad",
};
const sourceLabels: Record<string, string> = {
  message: "Declarado en Messenger", manual: "Registrado por administración", meta: "Perfil de Facebook",
};
type ContactProfile = {
  summary: string; completed: number; total: number; percent: number;
  missing: string[]; next_field: string | null; evidence: string; specialty_origin: string; sources?: Record<string, Evidence>;
};
type Lead = {
  id: string; name: string; company: string; specialty: string; workers: number | null;
  availability: string; experience: string; documents_state: string; status: string;
  requirement_id: string | null; ai_consent: boolean; ai_consent_state: string; ai_paused: boolean; unread: boolean;
  needs_support: boolean; support_reason: string;
  entity_type: "unknown" | "company" | "individual";
  has_employees: boolean | null;
  interest_type: "unknown" | "service_offer" | "employment" | "both";
  team_available: boolean | null; work_area: string; profile: ContactProfile;
  last_inbound_at: string | null; can_reply: boolean; analysis: Analysis;
  trades?: string[]; linked_needs?: string[]; work_communes?: string[];
  trade_sources?: (Evidence & { trade: string })[];
  follow_up_on: string | null; follow_up_note: string;
  last_message?: { text: string; direction: "inbound" | "outbound" } | null;
};
const editableFields = [
  "name", "company", "specialty", "workers", "availability", "experience", "status",
  "documents_state", "ai_paused", "needs_support", "entity_type", "has_employees",
  "interest_type", "team_available", "work_area", "requirement_id", "follow_up_on", "follow_up_note",
] as const satisfies readonly (keyof Lead)[];
type Post = { id: string; requirement_id: string; title: string; specialty: string;
  state: string; error: string | null; post_url: string | null;
  updated_at?: string; attempts?: number };
type Center = {
  automatic_enabled: boolean; manual_enabled?: boolean; messaging_enabled: boolean; ai_enabled: boolean;
  auto_reply_enabled: boolean; ai_provider?: string; page_id: string;
  auto_reply?: { configured: boolean; missing: string[]; verification: string; last_delivery: string };
  connection?: { state: string; checked_at: string | null; error: string | null; page_name: string | null };
  messenger_delivery?: { state: string; error: string | null; updated_at: string | null };
  inbox_sync?: { state: string; checked_at: string | null; error: string | null; summary: string | null };
  pending_ads: Post[]; publications: Post[]; leads: Lead[];
  guides_approved: number;
  counts: { pending_ads: number; published_ads: number; failed_ads: number;
    total_ads: number; contacts: number; unread: number; review: number; support: number };
};
type Onboarding = {
  phase: string; next_question: string | null;
  required_for_review: string[]; conditional: string[];
  not_applicable: string[]; prevention_examples: string[];
  notice: string; ask_for_files_now: boolean; human_followup: boolean;
};
type Chat = {
  source_message_id?: string | null; id: string; direction: "inbound" | "outbound"; state: string; body: string;
  ai_generated: boolean; automated: boolean; created_at: string; updated_at?: string; error: string | null };
const replyStages: Record<string, {percent: number; label: string}> = {
  pending: {percent: 15, label: "Respuesta en cola"},
  ai_pending: {percent: 30, label: "Galancito está pensando"},
  drafting: {percent: 65, label: "Galancito está escribiendo"},
  sending: {percent: 90, label: "Enviando a Messenger"},
  sent: {percent: 100, label: "Meta confirmó el envío"},
};
const progressFor = (message: Chat) => {
  if (message.direction !== "outbound") return null;
  if (message.state === "sent" &&
      Date.now() - Date.parse(message.updated_at || message.created_at) > 45000) return null;
  return replyStages[message.state] || null;
};
type Detail = { lead: Lead; messages: Chat[] };
type Guide = { id: string; slug: string; trade: string; aliases: string[]; explanation: string;
  document_guidance: string[]; approved: boolean };
type NeedCoincidence = {
  id: string; title: string; specialty: string; matched_trades: string[];
  coincidence_percent: number; coverage_percent: number;
  reasons: string[]; missing: string[]; linked: boolean; review_required: boolean;
};
type NeedLink = { id: string; title: string; specialty: string };
type TraceItem = { event: string; trade: string | null; requirement_id: string | null;
  source: string; at: string };
type Triage = {
  id: string; name: string; company: string; category: string;
  category_source: string; category_evidence: string; status: string; stage: string;
  urgency: "high" | "normal" | "none"; next_action: string;
  requirement_id: string | null; requirement_title: string | null;
  follow_up_on: string | null; follow_up_note: string;
  needs_support: boolean; unread: boolean; human_review_required: boolean;
  trades?: string[]; links?: NeedLink[]; matches?: NeedCoincidence[];
  recent_trace?: TraceItem[]; profile_state?: string; profile_pending?: string[];
};
type Tracking = {
  total: number; urgent: number; needs_human: number; unlinked: number;
  overdue: number; by_category: Record<string,number>;
  by_stage: Record<string,number>; by_requirement: Record<string,number>;
  rows: Triage[]; limited: boolean; disclaimer: string;
};
type TriageNote = { triage: Triage; ai_note: string; source: string; changes_applied: boolean };
type LeadInsights = {
  contact_id: string; source: string; next_action: string; review_required: boolean;
  summary: { name: string; specialty: string; company: string; workers: number | null; availability: string; stage: string };
  missing: string[];
  suggestions: { field: string; value: string | number; evidence: string; source: string; confirmed: boolean }[];
  matches: { id: string; title: string; site: string; specialty: string; score: number; workers: number; start_date: string; reasons: string[]; review_required: boolean }[];
};
const statuses: Record<string, string> = {
  new: "Nuevo", contacting: "En conversación", pending_review: "Por revisar",
  shortlisted: "Posible candidato", archived: "Archivado", pending: "Pendiente",
  disabled: "Conexión desactivada", not_queued: "Sin sincronizar",
  failed: "Error de publicación", sending: "Enviando", uncertain: "Revisar en Meta",
  published: "Publicado en Facebook", deleted: "Retirado de Facebook",
  cancelled: "Cancelado", verified: "Identidad comprobada",
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
  const [tab, setTab] = useState<"overview" | "summary" | "tracking" | "inbox" | "pending" | "publications" | "interactions" | "testing" | "guides" | "knowledge" | "performance">("overview");
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reply, setReply] = useState("");
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("");
  const [inboxFilter, setInboxFilter] = useState<"all" | "unread">("all");
  const [guides, setGuides] = useState<Guide[]>([]);
  const [adDraft, setAdDraft] = useState<{id: string; title: string; draft: string; source: string} | null>(null);
  const [guide, setGuide] = useState(freshGuide);
  const [tracking, setTracking] = useState<Tracking | null>(null);
  const [sheetPerson, setSheetPerson] = useState<Triage | null>(null);
  const closeSheet = useCallback(() => setSheetPerson(null), []);
  const [triageNote, setTriageNote] = useState<TriageNote | null>(null);
  const [insights, setInsights] = useState<LeadInsights | null>(null);
  const [mobilePane, setMobilePane] = useState<"chat" | "profile">("chat");
  const [showProfile, setShowProfile] = useState(false);
  const [inboxHeight, setInboxHeight] = useState<number | null>(null);
  const inboxRef = useRef<HTMLDivElement | null>(null);
  const toolsRef = useRef<HTMLDetailsElement | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);
  const selectedIdRef = useRef("");
  const savedLeadRef = useRef<Lead | null>(null);
  const latestInboundRef = useRef<Record<string, string>>({});
  const recheckedProfilesRef = useRef<Set<string>>(new Set());
  const nearBottomRef = useRef(true);
  const centerPollingRef = useRef(false);
  const inboxPollingRef = useRef(false);
  const [triageFilter, setTriageFilter] = useState<"all"|"high"|"support"|"unlinked"|"due">("all");
  const [trackingQuery, setTrackingQuery] = useState("");
  selectedIdRef.current = selectedId;
  // Las opciones secundarias no deben cubrir la conversación al cambiar de vista.
  useEffect(() => {
    if (toolsRef.current) toolsRef.current.open = false;
  }, [tab]);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (toolsRef.current && event.target instanceof Node && !toolsRef.current.contains(event.target)) {
        toolsRef.current.open = false;
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  // Mantener el cuadro de respuesta dentro del viewport al cambiar a conversaciones.
  useEffect(() => {
    if (tab !== "inbox") return;
    const fit = () => {
      if (!inboxRef.current) return;
      const top = Math.max(0, inboxRef.current.getBoundingClientRect().top);
      setInboxHeight(Math.max(320, Math.min(800, Math.round(window.innerHeight - top - 12))));
    };
    fit();
    window.addEventListener("resize", fit, {passive: true});
    return () => window.removeEventListener("resize", fit);
  }, [tab]);

  const refresh = useCallback(async (force = false) => {
    // An operator's explicit refresh must not be skipped just because an
    // automatic poll is already underway.
    if (centerPollingRef.current && !force) return;
    if (!force) centerPollingRef.current = true;
    try {
      const current = await net<Center>("/facebook/center");
      // Reuse the same object when the server returned no changes. This stops
      // the entire inbox and tracking tree repainting on every poll.
      setCenter(previous => previous && JSON.stringify(previous) === JSON.stringify(current)
        ? previous : current);
      setSelectedId(prev => prev || (current.leads[0]?.id || ""));
    } finally {
      if (!force) centerPollingRef.current = false;
    }
  }, []);
  // Estado fresco del worker; al finalizar la comprobación desaparece el estado pendiente.
  useEffect(() => {
    if (!["pending", "sending"].includes(center?.connection?.state || "") &&
        !["pending", "sending"].includes(center?.inbox_sync?.state || "")) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh().catch(() => {});
    }, 1500);
    return () => window.clearInterval(timer);
  }, [center?.connection?.state, center?.inbox_sync?.state, refresh]);
  const refreshTracking = useCallback(async () => {
    const data = await net<Tracking>("/facebook/galancito/seguimiento");
    setTracking(data);
  }, []);
  const refreshInsights = useCallback(async (id: string) => {
    if (!id) { setInsights(null); return; }
    const response = await net<LeadInsights>("/facebook/leads/" + id + "/insights");
    setInsights(response.contact_id === id ? response : null);
  }, []);
  const refreshDetail = useCallback(async (id: string) => {
    if (!id) { setDetail(null); return; }
    let result = await net<Detail>("/facebook/leads/" + id);
    // Re-evaluate older names declared in chat without an operator copying text.
    if (result.lead.name === "Interesado de Facebook" &&
        result.messages.some((msg) => msg.direction === "inbound") &&
        !recheckedProfilesRef.current.has(id)) {
      recheckedProfilesRef.current.add(id);
      try {
        const updated = await change<Lead>("/facebook/leads/" + id + "/refresh-profile", {});
        result = {...result, lead: {...result.lead, ...updated}};
      } catch {
        // Keep the inbox readable even when optional profile reconciliation fails.
      }
    }
    latestInboundRef.current[id] = [...result.messages].reverse().find((m) => m.direction === "inbound")?.id || "";
    if (selectedIdRef.current === id) {
      savedLeadRef.current = result.lead;
      setDetail(result);
    }
  }, []);
  useEffect(() => {
    let active = true;
    void net<Page<Requirement>>("/requirements?limit=100&offset=0")
      .then(data => { if (active) setRequirements(data.rows.filter(r => r.state === "published")); })
      .catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    const update = () => {
      if (active && !document.hidden) void refresh().catch(e => setError(errorText(e)));
    };
    update();
    // Chat messages have their own, smaller poll. The heavier dashboard
    // snapshot never needs a full reload every three seconds.
    const interval = window.setInterval(update, tab === "inbox" ? 9000 : 30000);
    window.addEventListener("focus", update);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", update);
    };
  }, [refresh, tab]);
  useEffect(() => {
    if (tab !== "inbox") return;
    nearBottomRef.current = true;
    void refreshDetail(selectedId).catch((e) => setError(errorText(e)));
    setInsights(null);
    void refreshInsights(selectedId).catch((e) => setError(errorText(e)));
    setReply("");
    setOnboarding(null);
    setTriageNote(null);
  }, [selectedId, tab, refreshDetail, refreshInsights]);
  useEffect(() => {
    if (chatRef.current && nearBottomRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [selectedId, detail?.lead.id, detail?.messages.length]);
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
      if (document.hidden || inboxPollingRef.current) return;
      inboxPollingRef.current = true;
      try {
        const update = await net<Detail>("/facebook/leads/" + selectedId);
        const newestInbound = [...update.messages].reverse().find((m) => m.direction === "inbound")?.id || "";
        const previousInbound = latestInboundRef.current[selectedId];
        if (newestInbound !== previousInbound) {
          latestInboundRef.current[selectedId] = newestInbound;
          if (previousInbound && newestInbound) void refreshInsights(selectedId).catch(() => {});
        }
        if (selectedIdRef.current !== selectedId) return;
        const saved = savedLeadRef.current;
        savedLeadRef.current = update.lead;
        setDetail((previous) => {
          if (saved?.id !== selectedId || previous?.lead.id !== selectedId) return update;
          const lead = {...update.lead};
          for (const field of editableFields) {
            if (previous.lead[field] !== saved[field]) Object.assign(lead, {[field]: previous.lead[field]});
          }
          // Keep the same React state when no message or profile value changed.
          const sameMessages = previous.messages.length === update.messages.length &&
            previous.messages.every((msg, index) => {
              const next = update.messages[index];
              return msg.id === next.id && msg.state === next.state &&
                msg.updated_at === next.updated_at && msg.body === next.body &&
                msg.error === next.error;
            });
          return sameMessages && JSON.stringify(previous.lead) === JSON.stringify(lead)
            ? previous : {...update, lead};
        });
      } catch { /* No borrar la conversación si hay un fallo temporal de red. */ }
      finally { inboxPollingRef.current = false; }
    };
    const interval = window.setInterval(() => { void refreshMessages(); }, 3000);
    return () => window.clearInterval(interval);
  }, [selectedId, tab, refreshInsights]);

  useEffect(() => {
    if (tab !== "tracking") return;
    void refreshTracking().catch((e) => setError(errorText(e)));
    const interval = window.setInterval(() => {
      if (!document.hidden) void refreshTracking().catch(() => {});
    }, 15000);
    return () => window.clearInterval(interval);
  }, [tab, refreshTracking]);

  useEffect(() => {
    if (tab === "guides") void net<Guide[]>("/facebook/guides")
      .then(setGuides).catch((e) => setError(errorText(e)));
  }, [tab]);

  async function mutate(label: string, run: () => Promise<unknown>, message: string): Promise<boolean> {
    setSaving(label); setError(""); setNotice("");
    try {
      await run();
      if (message) setNotice(message);
      await refresh(true);
      if (tab === "tracking") await refreshTracking();
      if (selectedId) {
        await refreshDetail(selectedId);
        await refreshInsights(selectedId);
      }
      return true;
    } catch (e) { setError(errorText(e)); return false; }
    finally { setSaving(""); }
  }
  function patchLead(patch: Partial<Lead>) {
    if (!selectedId) return;
    void mutate("lead", () => change("/facebook/leads/" + selectedId, patch, "PATCH"),
      "Ficha del interesado actualizada.");
  }
  function resumeAutoReplies() {
    if (!selectedId || !detail || saving) return;
    if (detail.lead.ai_consent_state === "declined") {
      setError("La persona rechazó el uso de IA. Debe autorizarlo nuevamente en Messenger.");
      return;
    }
    const contactId = selectedId;
    // A single persisted update clears BOTH human handoff flags. It never
    // changes or manufactures the sender's provider-specific AI consent.
    void mutate("resume-ai", () => change("/facebook/leads/" + contactId,
      { ai_paused: false, needs_support: false }, "PATCH"),
      "Se reactivaron las respuestas automáticas para los próximos mensajes.");
  }
  function openSourceMessage(id: string) {
    setShowProfile(false);
    setMobilePane("chat");
    nearBottomRef.current = false;
    requestAnimationFrame(() => {
      const message = document.getElementById("fbc-message-" + id);
      message?.focus({preventScroll: true});
      message?.scrollIntoView({block: "nearest"});
    });
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
  function sendMessage() {
    const text = reply.trim();
    const contactId = selectedId;
    if (!text || !contactId || saving || !detail?.lead.can_reply || detail.lead.id !== contactId) return;
    void mutate("send", () => change("/facebook/leads/" + contactId + "/reply", { message: text }), "")
      .then((success) => {
        if (success && selectedIdRef.current === contactId) {
          setReply((current) => current.trim() === text ? "" : current);
          nearBottomRef.current = true;
        }
      });
  }
  function send(e: FormEvent) {
    e.preventDefault();
    sendMessage();
  }
  function composerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter is a newline. Respect composing keyboards.
    if (e.key === "Enter" && !e.shiftKey && !e.altKey && !e.metaKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      sendMessage();
    }
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
  const messageIds = new Map(detail?.messages.filter(msg => msg.source_message_id)
    .map(msg => [msg.source_message_id, msg.id]) ?? []);
  const evidenceRows = [
    ...Object.entries(lead?.profile.sources ?? {}).filter(([field]) => field in fieldLabels)
      .map(([field, origin]) => ({key: field, label: fieldLabels[field], origin})),
    ...(lead?.trade_sources ?? []).map(origin => ({key: origin.trade, label: origin.trade, origin})),
  ];
  const currentInsights = insights?.contact_id === selectedId ? insights : null;
  const visible = center?.leads.filter((r) =>
    (inboxFilter === "all" || r.unread) &&
    [r.name, r.company, r.specialty, ...(r.trades || [])]
      .some((x) => x.toLocaleLowerCase("es-CL").includes(filter.toLocaleLowerCase("es-CL")))) || [];

  // Nunca inferir validez en tiempo real de un error antiguo. Un GET verificado
  // en el worker puede resolverlo sin borrar ni reintentar publicaciones históricas.
  const connection = center?.connection;
  const lastResolvedPost = [...(center?.publications || [])]
    .filter((post) => post.state === "failed" || post.state === "published")
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""))[0];
  const tokenError = (value?: string | null) => /c[oó]digo Meta 190|HTTP 400.*190|token.*(?:invalid|expired|inv[aá]lido|vencid)/i.test(value || "");
  const verifiedAfterFailure = connection?.state === "verified" &&
    (connection.checked_at || "") >= (lastResolvedPost?.updated_at || "");
  const lastFailedToken = lastResolvedPost?.state === "failed" && tokenError(lastResolvedPost.error);
  const failedCheck = connection?.state === "failed";
  const failedCheckIsNewer = failedCheck && (connection?.checked_at || "") >= (lastResolvedPost?.updated_at || "");
  const tokenInvalid = (lastFailedToken && !verifiedAfterFailure) || (failedCheck && failedCheckIsNewer);
  const checkingConnection = connection?.state === "pending" || connection?.state === "sending";
  const syncingInbox = ["pending", "sending"].includes(center?.inbox_sync?.state || "");
  const connectionVerified = connection?.state === "verified" && !tokenInvalid;
  const messengerBlocked = center?.messenger_delivery?.state === "failed";
  const messengerUncertain = center?.messenger_delivery?.state === "uncertain";
  const lastOutbound = detail?.messages.filter(message => message.direction === "outbound").at(-1);
  const lastSendFailed = tab === "inbox" && !!lastOutbound && (lastOutbound.state === "failed" || !!lastOutbound.error);
  return <div className="fbc">
    <header className="fbc-header">
      <div className="fbc-header-title"><h2>Centro de Facebook</h2></div>
      <div className="fbc-status-line">
      <span className={"fbc-connection-square " + (messengerBlocked || messengerUncertain || tokenInvalid || lastSendFailed ? "problem" :
        connectionVerified && center?.messaging_enabled ? "good" : "pending")} role="status"
        title={lastSendFailed ? "El último envío de este chat falló" : connectionVerified ? "Token de página verificado" : "Conexión sin confirmar"}>
        {messengerBlocked || messengerUncertain || tokenInvalid || lastSendFailed ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
        {messengerBlocked || messengerUncertain || tokenInvalid || lastSendFailed ? "Revisar" :
          checkingConnection ? "Comprobando" : connectionVerified && center?.messaging_enabled ? "Conectado" : "Sin verificar"}
      </span>
      <details className="fbc-connection-details">
        <summary>Diagnóstico</summary>
        <div className="fbc-connection-content">
          <p>Facebook: {connectionVerified ? "Token verificado" : connection?.state === "failed" ? "Error de autenticación" : "Pendiente de comprobación"}.</p>
          <p>Messenger: {center?.messaging_enabled ? "Habilitado" : "Deshabilitado"}.
            {center?.auto_reply?.configured ? " · Respuestas automáticas configuradas" : " · Respuestas automáticas pendientes"}.</p>
          {!center?.auto_reply?.configured && !!center?.auto_reply?.missing?.length &&
            <div className="fbc-auto-check" role="status">
              <b>Qué falta para que Galancito responda solo</b>
              <ul>{center.auto_reply.missing.map(item => <li key={item}>{item}</li>)}</ul>
              <small>Se corrige en la configuración de IA y Messenger; no basta con que Facebook diga «Vigente».</small>
            </div>}
          {center?.auto_reply?.configured &&
            <p className="fbc-auto-confirm">Respuestas automáticas listas para una prueba externa. La conexión de Meta y el envío real deben confirmarse.</p>}
          {center?.inbox_sync?.state === "synced" && <p>{center.inbox_sync.summary}</p>}
          {center?.inbox_sync?.state === "failed" && <p role="alert">{center.inbox_sync.error || "Fallo al recuperar conversaciones"}</p>}
          {tokenInvalid && <p role="alert">Revisar token de página en el VPS.</p>}
          {(messengerBlocked || messengerUncertain) && <p role="alert">{center?.messenger_delivery?.error || "No se confirmó el envío."}</p>}
          {lastSendFailed && <p role="alert">Último mensaje no enviado: {lastOutbound?.error || "Revisa la conexión de Meta."}</p>}
          <div className="fbc-diagnostic-actions">
            <button type="button" className="nw-btn" disabled={!!saving || checkingConnection || !(center?.automatic_enabled || center?.manual_enabled)}
              onClick={() => void mutate("verify-connection", () => change("/facebook/tests/verify", {}), "")}>
              <RefreshCcw size={14}/> Verificar token
            </button>
            <button type="button" className="nw-btn" disabled={!!saving || syncingInbox || !center?.messaging_enabled}
              onClick={() => void mutate("inbox-sync", () => change("/facebook/inbox/sync", {}), "")}>
              <RefreshCcw size={14}/> {syncingInbox ? "Recuperando..." : "Recuperación puntual"}
            </button>
          </div>
        </div>
      </details>
    <details className="fbc-tools" ref={toolsRef}>
      <summary>Herramientas</summary>
      <div>
        <button type="button" className="nw-btn" onClick={() => setTab("summary")}>Resumen IA</button>
        <button type="button" className="nw-btn" onClick={() => setTab("performance")}>Rendimiento</button>
        <button type="button" className="nw-btn" onClick={() => setTab("testing")}>Comprobar conexión</button>
        <button type="button" className="nw-btn" onClick={() => setTab("guides")}>Guías de oficios</button>
      </div>
    </details>
      </div>
    </header>
    {error && <p role="alert" className="fbc-error">{error}</p>}
    {notice && <p role="status" className="fbc-notice">{notice}</p>}
    <nav aria-label="Centro Facebook" className="fbc-tabs fbc-tabs-simple">
      <button type="button" className={tab === "overview" ? "selected" : ""} aria-pressed={tab === "overview"} onClick={() => setTab("overview")}>
        Resumen
      </button>
      <button className={tab === "publications" || tab === "pending" ? "selected" : ""} onClick={() => setTab("publications")}>
        <Facebook size={16} /> Publicaciones
      </button>
      <button className={tab === "interactions" ? "selected" : ""} onClick={() => setTab("interactions")}>
        <MessageCircle size={16} /> Interacciones
      </button>
      <button className={tab === "inbox" ? "selected" : ""} onClick={() => setTab("inbox")}>
        <Inbox size={16} /> Conversaciones
      </button>
      <button className={tab === "tracking" ? "selected" : ""} onClick={() => setTab("tracking")}>
        <ShieldCheck size={16} /> Seguimiento
      </button>
    </nav>
    {tab === "overview" && <FacebookOverview
      loading={!center && !error}
      counts={center?.counts}
      leads={center?.leads || []}
      publications={center?.publications || []}
      onOpenConversations={(unreadOnly) => {setInboxFilter(unreadOnly ? "unread" : "all"); setTab("inbox");}}
      onOpenTracking={() => setTab("tracking")}
      onOpenPublications={() => setTab("publications")}
      onOpenPending={() => setTab("pending")}
      onOpenContact={(id) => {setSelectedId(id); setInboxFilter("all"); setShowProfile(false); setMobilePane("chat"); setTab("inbox");}}
    />}
    {tab === "summary" && <GalancitoKnowledgeCenter mode="summary" />}
    {tab === "knowledge" && <GalancitoKnowledgeCenter />}
    {tab === "performance" && <GalancitoKnowledgeCenter mode="performance" />}
    {tab === "tracking" && <section className="fbc-tracking fbtrack" aria-label="Seguimiento Galancito">
      <div className="fbtrack-heading">
        <div><h3>Seguimiento de interesados</h3><p>Revisa contactos, prioridades y necesidades de obra.</p></div>
        <button className="nw-btn" type="button" disabled={!!saving}
          onClick={() => void refreshTracking().catch((e) => setError(errorText(e)))}>
          <RefreshCcw size={16}/> Actualizar
        </button>
      </div>
      {!tracking?<p className="fbc-empty" role="status">Cargando seguimiento…</p>:<>
        <div className="fbtrack-metrics" aria-label="Indicadores, selecciona para filtrar">
          {([
            ["all","Interesados",tracking.total,"normal",<Users size={19}/>],
            ["high","Requieren atención",tracking.urgent,"warning",<AlertTriangle size={19}/>],
            ["support","Apoyo humano",tracking.needs_human,"info",<MessageCircle size={19}/>],
            ["unlinked","Sin necesidad",tracking.unlinked,"mint",<ShieldCheck size={19}/>],
            ["due","Seguimientos vencidos",tracking.overdue,"danger",<Clock3 size={19}/>],
          ] as const).map(([key,label,value,tone,icon])=>
            <button key={key} type="button" aria-pressed={triageFilter===key}
              className={"fbtrack-metric "+tone+(triageFilter===key?" active":"")}
              onClick={()=>setTriageFilter(key)}>
              <span className="fbtrack-metric-heading">{icon}<span>{label}</span></span>
              <strong>{value}</strong>
            </button>)}
        </div>
        <div className="fbtrack-analysis">
          <section><div className="fbtrack-analysis-head"><b>Por especialidad</b><small>Selecciona un oficio</small></div>
            {!Object.keys(tracking.by_category).length&&<small>No hay especialidades registradas.</small>}
            {Object.entries(tracking.by_category).slice(0,5).map(([name,count])=>
              <button className="fbtrack-graph-row" type="button" key={name}
                onClick={()=>{setTrackingQuery(name);setTriageFilter("all");}} aria-label={"Ver contactos de "+name}>
                <span>{name}</span><div className="fbtrack-track"><span style={{width:(tracking.rows.length?100*count/tracking.rows.length:0)+"%"}}/></div><b>{count}</b>
              </button>)}
          </section>
          <section><div className="fbtrack-analysis-head"><b>Estado de seguimiento</b><small>Selecciona un estado</small></div>
            <div className="fbtrack-stages">{Object.entries(tracking.by_stage).slice(0,6).map(([name,count])=>
              <button key={name} type="button" onClick={()=>{setTrackingQuery(name);setTriageFilter("all");}}
                aria-label={"Filtrar seguimiento: "+name}>{name}<b>{count}</b></button>)}
              {!Object.keys(tracking.by_stage).length&&<small>Sin información todavía.</small>}
            </div></section>
        </div>
        <div className="fbtrack-controls">
          <div className="fbtrack-filters" role="group" aria-label="Filtrar seguimiento">
            {([["all","Todos"],["high","Prioritarios"],["support","Apoyo humano"],
              ["unlinked","Sin necesidad"],["due","Vencidos"]] as const).map(([key,label])=>
              <button type="button" aria-pressed={triageFilter===key}
                className={triageFilter===key?"active":""} key={key}
                onClick={()=>setTriageFilter(key)}>{label}</button>)}
          </div>
          {(trackingQuery||triageFilter!=="all")&&<button type="button" className="fbtrack-clear"
            onClick={()=>{setTrackingQuery("");setTriageFilter("all");}}>Limpiar filtros</button>}
          <input type="search" aria-label="Buscar personas u oficios" placeholder="Buscar persona, oficio o necesidad…"
            value={trackingQuery} onChange={e=>setTrackingQuery(e.target.value)}/>
        </div>
        <div className="fbtrack-list" aria-label="Fichas de interesados">
          {tracking.rows.filter(r=>(
            !trackingQuery.trim()||[r.name,r.company,r.category,r.stage,r.next_action,...(r.trades||[]),
              ...(r.links||[]).map(l=>l.title),...(r.matches||[]).map(m=>m.title)].join(" ")
              .toLocaleLowerCase("es-CL").includes(trackingQuery.trim().toLocaleLowerCase("es-CL"))
          )).filter(r=>triageFilter==="all"||
            (triageFilter==="high"&&r.urgency==="high")||
            (triageFilter==="support"&&r.needs_support)||
            (triageFilter==="unlinked"&&!(r.links?.length||r.requirement_id))||
            (triageFilter==="due"&&r.stage==="Seguimiento vencido")
          ).map(r=><article className="fbtrack-person" key={r.id}>
            <PersonAvatar name={r.name && r.name !== "Interesado de Facebook" ? r.name : r.company || "Contacto sin nombre"} size="md" className="fbtrack-avatar-portrait" />
            <div className="fbtrack-person-main">
              <strong>{r.name&&r.name!=="Interesado de Facebook"?r.name:r.company||"Contacto sin nombre"}</strong>
              <div className="fbtrack-person-tags">
                {(r.trades?.length?r.trades:[r.category]).filter(Boolean).slice(0,3).map(t=>
                  <span className="trade" key={t}>{t}</span>)}
                <span className={r.needs_support?"amber":r.urgency==="high"?"red":"mint"}>{r.stage}</span>
              </div>
            </div>
            <div className="fbtrack-work">
              <b>{r.links?.length?r.links.length+" necesidad(es) vinculada(s)":"Sin necesidad vinculada"}</b>
              <small>{r.links?.length?r.links.map(x=>x.title).join(" · "):"Pendiente de relacionar"}</small>
            </div>
            <div className="fbtrack-next"><b>Próximo paso</b>
              <small>{r.next_action}</small>
            </div>
            <div className="fbtrack-person-actions">
              <button className="fbtrack-open" type="button" onClick={()=>setSheetPerson(r)}>Ver ficha</button>
              <button className="fbtrack-chat" type="button" onClick={()=>{
                setSelectedId(r.id);setShowProfile(false);setMobilePane("chat");setTab("inbox");
              }}>Ver chat</button>
            </div>
          </article>)}
          {!tracking.rows.length&&<p className="fbc-empty">Aún no hay contactos para mostrar.</p>}
          {!!tracking.rows.length&&!tracking.rows.some(r=>
            (!trackingQuery.trim()||[r.name,r.company,r.category,r.stage,r.next_action,...(r.trades||[]),
              ...(r.links||[]).map(l=>l.title),...(r.matches||[]).map(m=>m.title)].join(" ")
              .toLocaleLowerCase("es-CL").includes(trackingQuery.trim().toLocaleLowerCase("es-CL"))) &&
            (triageFilter==="all"||(triageFilter==="high"&&r.urgency==="high")||
            (triageFilter==="support"&&r.needs_support)||
            (triageFilter==="unlinked"&&!(r.links?.length||r.requirement_id))||
            (triageFilter==="due"&&r.stage==="Seguimiento vencido"))
          )&&<p className="fbc-empty">No hay contactos que coincidan con estos filtros.</p>}
        </div>
        {tracking.limited&&<small className="fbtrack-foot">La lista muestra hasta 200 contactos recientes. Los contadores pueden representar un total mayor.</small>}
      </>}
    </section>}
    {sheetPerson && <FacebookPersonSheet person={sheetPerson}
      onClose={closeSheet} onChanged={()=>void refreshTracking().catch(()=>{})}
      onOpenChat={(id)=>{setSheetPerson(null);setSelectedId(id);setShowProfile(false);setMobilePane("chat");setTab("inbox");}}/>}
    {tab === "inbox" && <>
    <div className="fbc-mobile-tabs" role="group" aria-label="Vista de conversación">
      <button type="button" className={mobilePane === "chat" ? "active" : ""} onClick={() => setMobilePane("chat")}>Conversación</button>
      <button type="button" className={mobilePane === "profile" ? "active" : ""} onClick={() => setMobilePane("profile")}>Ficha inteligente</button>
    </div>
    <div ref={inboxRef} style={inboxHeight ? {height: inboxHeight} : undefined} className={"fbc-inbox " + (mobilePane === "profile" ? "show-profile" : "show-chat") + (showProfile ? " profile-open" : "")}>
      <aside className="fbc-contacts">
        <div className="fbc-pane-title"><Users size={16} /><b>Conversaciones</b></div>
        <div className="fbmin-inbox-switch" role="group" aria-label="Filtrar conversaciones">
          <button type="button" className={inboxFilter === "all" ? "selected" : ""}
            aria-pressed={inboxFilter === "all"} onClick={() => setInboxFilter("all")}>Todas</button>
          <button type="button" className={inboxFilter === "unread" ? "selected" : ""}
            aria-pressed={inboxFilter === "unread"} onClick={() => setInboxFilter("unread")}>Sin leer</button>
        </div>
        <input className="fbc-search" aria-label="Buscar interesados" value={filter}
          onChange={(e) => setFilter(e.target.value)} placeholder="Buscar persona, empresa u oficio..." />
        <div className="fbc-contacts-list">
          {!visible.length && <p className="fbc-empty">{inboxFilter === "unread"
            ? "No hay conversaciones sin leer con este filtro."
            : filter ? "No encontramos contactos con esa búsqueda." :
            "Aún no hay mensajes sincronizados. Los contactos aparecerán cuando escriban a la página conectada."}</p>}
          {visible.map((item) => <button key={item.id}
            onClick={() => { setSelectedId(item.id); setMobilePane("chat"); }}
            className={"fbc-contact " + (item.id === selectedId ? "selected" : "")}>
            <PersonAvatar name={item.name && item.name !== "Interesado de Facebook" ? item.name : item.company || "Contacto sin nombre"} size="md" className="fbc-avatar-portrait" />
            <div><strong>{item.name && item.name !== "Interesado de Facebook" ? item.name : item.company || "Contacto sin nombre"}</strong>
              {item.company && item.name && item.name !== "Interesado de Facebook" && item.company !== item.name && <small>{item.company}</small>}
              {item.last_message?.text ? <small className="fbc-contact-preview">{item.last_message.direction === "outbound" ? "Tú: " : ""}{item.last_message.text}</small> :
                <small>{item.specialty || "Oficio por confirmar"}</small>}
              {item.follow_up_on && <small>Seguimiento: {item.follow_up_on}</small>}
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
            <div className="fbc-pane-title"><PersonAvatar name={lead.name && lead.name !== "Interesado de Facebook" ? lead.name : lead.company || "Contacto sin nombre"} size="md" /><div>
              <b>{lead.name && lead.name !== "Interesado de Facebook" ? lead.name : "Contacto sin nombre"}</b>
              <small>{lead.company ? lead.company + " · " : ""}{lead.specialty ? lead.specialty + " · " : ""}
                {lead.can_reply ? "Puedes responder" : "Fuera de la ventana de respuesta"}</small>
            </div>
            {lead.name === "Interesado de Facebook" &&
              currentInsights?.suggestions.filter((item) => item.field === "name").slice(0,1).map((item) =>
                <button type="button" className="nw-btn fbc-name-confirm" key="name-suggestion" disabled={!!saving}
                  title="Nombre declarado por la persona; requiere tu confirmación"
                  onClick={() => patchLead({name: String(item.value)})}>
                  <CheckCircle2 size={14}/> Guardar: {String(item.value)}
                </button>)}
            {lead.unread && <button type="button" className="nw-btn fbc-read-btn" onClick={() =>
              void mutate("read", () => change("/facebook/leads/" + lead.id + "/read"), "")} disabled={!!saving}>Leído</button>}
            <button type="button"
              className={"fbc-auto-toggle " + ((lead.ai_paused || lead.needs_support) ? "is-off" : "is-on")}
              aria-pressed={!lead.ai_paused && !lead.needs_support}
              aria-label={(lead.ai_paused || lead.needs_support ? "Volver a respuestas por IA" : "Pausar IA") + " para este contacto"}
              title={center?.auto_reply_enabled ? "Control de respuestas automáticas de esta conversación" :
                "Las respuestas automáticas están desactivadas en el servidor"}
              disabled={!!saving || !center?.auto_reply_enabled ||
                ((lead.ai_paused || lead.needs_support) && lead.ai_consent_state === "declined")}
              onClick={() => (lead.ai_paused || lead.needs_support)
                ? resumeAutoReplies() : patchLead({ai_paused: true})}>
              <Bot size={15} aria-hidden="true" />
              <span>Respuestas IA</span>
              <strong>{(lead.ai_paused || lead.needs_support) ? "Volver a IA" : "Pausar"}</strong>
            </button>
            <button type="button" className="nw-btn fbc-profile-toggle" aria-expanded={showProfile}
              onClick={() => {
                setMobilePane(showProfile ? "chat" : "profile");
                setShowProfile(!showProfile);
              }}>
              <Users size={15} /> {showProfile ? "Cerrar ficha" : "Ver ficha"}
            </button></div>
            {!center?.auto_reply_enabled && <div className="fbc-auto-unavailable" role="status">
              Las respuestas automáticas están desactivadas en el servidor. Revísalas en Configuración de Messenger.
            </div>}
            {(lead.ai_paused || lead.needs_support) && <div className="fbc-bot-paused" role="status">
              <Users size={16}/>
              <span><strong>Atención humana activa.</strong> Las respuestas automáticas están pausadas.
                {lead.needs_support && lead.support_reason ? " Motivo: " + lead.support_reason : ""}
                {lead.ai_consent_state === "declined"
                  ? " La persona rechazó IA: no se puede volver a activarla sin su permiso."
                  : ""}
              </span>
              <button type="button" className="nw-btn fbc-resume-ai"
                disabled={!!saving || !center?.auto_reply_enabled || lead.ai_consent_state === "declined"}
                onClick={resumeAutoReplies}>
                <Bot size={15}/> Volver a respuestas por IA
              </button>
            </div>}
            <div className="fbc-chat-stream" ref={chatRef} onScroll={(e) => {
              const element = e.currentTarget;
              nearBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
            }}>
              {detail?.messages.map((msg) => {
                const stage = progressFor(msg);
                return <div key={msg.id} id={"fbc-message-" + msg.id} tabIndex={-1} className={"fbc-bubble " + msg.direction}>
                  {msg.direction === "inbound" && <PersonAvatar
                    name={lead.name && lead.name !== "Interesado de Facebook" ? lead.name : lead.company || "Contacto sin nombre"}
                    size="xs" className="galant-bubble-avatar" />}
                  {msg.automated && ["pending", "ai_pending", "drafting"].includes(msg.state) ?
                    <div className="fbc-typing" role="status" aria-label={msg.state === "ai_pending" ? "Galancito está pensando" : "Galancito está escribiendo"}>
                      <span className="fbc-typing-avatar"><Bot size={17}/></span>
                      <span className="fbc-typing-content">
                        <span className="fbc-typing-dots" aria-hidden="true"><i/><i/><i/></span>
                        <small>{msg.state === "ai_pending" ? "Galancito está pensando…" : "Galancito está escribiendo…"}</small>
                      </span>
                    </div> :
                    <p>{msg.body || (msg.state === "sending" ? "Enviando respuesta…" : "Preparando respuesta…")}</p>}
                  {stage && <div className={"fbc-reply-progress " + msg.state} role="status"
                    aria-label={stage.label + ": " + stage.percent + "%"}>
                    <div className="fbc-reply-progress-heading">
                      <span><Bot size={13} /> {stage.label}</span>
                      <strong>{stage.percent}%</strong>
                    </div>
                    <div className="fbc-reply-track" role="progressbar"
                      aria-label="Etapa de envío de respuesta" aria-valuemin={0}
                      aria-valuemax={100} aria-valuenow={stage.percent}>
                      <span style={{width: stage.percent + "%"}} />
                    </div>
                  </div>}
                  <small>{msg.automated ? "Galancito · " : ""}{dateText(msg.created_at)} · {
                    msg.state === "sent" ? "Envío confirmado por Meta" :
                    msg.direction === "inbound" ? "Recibido" :
                    msg.state === "ai_pending" ? "En cola IA" :
                    msg.state === "drafting" ? "Redactando" :
                    msg.state === "sending" ? "Enviando" : msg.state}</small>
                  {msg.error && <small className="fbc-send-error">{msg.error}</small>}
                </div>;
              })}
            </div>
            <form className="fbc-composer" onSubmit={send}>
              <textarea aria-label="Respuesta para el contratista" value={reply}
                onChange={(e) => setReply(e.target.value)} onKeyDown={composerKeyDown} rows={1}
                title="Enter envía; Shift + Enter agrega una línea"
                placeholder="Escribe un mensaje..." />
              <div className="fbc-composer-actions">
                <details className="fbc-quick-replies">
                  <summary>Respuestas rápidas</summary>
                  <div className="fbc-reply-chips" aria-label="Respuestas rápidas">
                {[
                  ["Preguntar oficio", "Hola, gracias por escribirnos. ¿En qué oficio te especializas?"],
                  ["Disponibilidad", "¿Desde qué fecha podrías comenzar a trabajar?"],
                  ["Cantidad de personas", "¿Cuántas personas integran tu cuadrilla?"],
                  ["Experiencia", "¿En qué tipo de obras has trabajado anteriormente?"],
                ].map(([label, text]) => <button key={label} type="button" disabled={!!saving}
                  onClick={() => setReply(text)}>{label}</button>)}
                  </div>
                </details>
                <button className="nw-btn" type="button" disabled={!!saving}
                  onClick={() => void suggest()}><Sparkles size={16} /> {saving === "draft" ? "Preparando…" : "Sugerir respuesta"}</button>
                <button className="nw-btn nw-primary" type="submit"
                  disabled={!!saving || !reply.trim() || !lead.can_reply}>
                  <Send size={16} /> {saving === "send" ? "Encolando..." : "Enviar"}
                </button>
              </div>
              {!lead.can_reply && <small>La ventana normal de Messenger terminó. Espera un nuevo mensaje o utiliza herramientas autorizadas por Meta.</small>}
            </form>
          </>}
      </section>
      <aside className="fbc-analysis" aria-label="Ficha del contacto">
        <button type="button" className="fbc-profile-close" onClick={() => {
          setShowProfile(false); setMobilePane("chat");
        }} aria-label="Cerrar ficha">Cerrar ficha ×</button>
        <div className="fbc-pane-title"><ShieldCheck size={17} /><b>Ficha inteligente</b></div>
        {!lead ? <p className="fbc-empty">Selecciona una conversación.</p> : <>
          {lead.needs_support && <div className="fbc-support-alert" role="status">
            <AlertTriangle size={18}/>
            <div><b>Necesita orientación paso a paso</b>
              <p>{lead.support_reason || "La persona solicitó ayuda para avanzar."}</p>
              <small>Responder con palabras sencillas, sin exigir enlaces ni documentos por Messenger.</small>
            </div>
          </div>}
          <section className="fbc-person-profile" aria-label="Resumen progresivo de la persona">
            <div className="fbc-person-profile-heading">
              <b>Ficha que Galancito va completando</b>
              <span className="fbc-profile-ready">{lead.trades?.length || lead.specialty ? "Perfil básico" : "Por conocer oficio"}</span>
            </div>
            <details className="fbmin-ai-summary"><summary>Ver resumen de Galancito</summary>
              <p className="fbc-person-summary">{lead.profile.summary}</p>
              <small>{lead.profile.evidence}</small>
            </details>
            <div className="fbc-person-fields">
              <div><small>Nombre</small><strong>{lead.name && lead.name !== "Interesado de Facebook" ? lead.name : "Por registrar"}</strong></div>
              <div><small>Interés</small><strong>{lead.interest_type === "service_offer" ? "Ofrece servicios" :
                lead.interest_type === "employment" ? "Busca empleo" :
                lead.interest_type === "both" ? "Busca empleo y ofrece servicios" : "Por aclarar"}</strong></div>
              <div><small>Oficios / trabajos</small><strong>{lead.trades?.length ? lead.trades.join(" · ") : lead.specialty || "Sin informar"}</strong></div>
              <div><small>Modalidad</small><strong>{lead.team_available == null ? "Sin dato" :
                lead.team_available ? "Puede venir con equipo" : "Trabaja solo/a"}</strong></div>
              <div><small>Personas</small><strong>{lead.workers ?? "Sin dato"}</strong></div>
              <div><small>Experiencia</small><strong>{lead.experience || "Por consultar"}</strong></div>
              <div><small>Comunas</small><strong>{lead.work_communes?.join(" · ") || lead.work_area || "Por consultar"}</strong></div>
              <div><small>Disponibilidad</small><strong>{lead.availability || "Por consultar"}</strong></div>
              <div><small>Necesidades vinculadas</small><strong>{lead.linked_needs?.length ? lead.linked_needs.map(id => requirements.find(r => r.id === id)?.title || "Necesidad histórica").join(" · ") : requirements.find(r => r.id === lead.requirement_id)?.title || "Sin vincular"}</strong></div>
            </div>
            <details className="fbc-profile-pending">
              <summary>Origen de los datos</summary>
              {evidenceRows.map(({key, label, origin}) => {
                const messageId = messageIds.get(origin.message_id);
                return <p key={key}><strong>{label}</strong>
                  {" · "}{sourceLabels[origin.source] || origin.source}{" · "}{dateText(origin.at)}
                  {messageId && <>{" · "}<button type="button" className="nw-btn"
                    onClick={() => openSourceMessage(messageId)}>Ver mensaje</button></>}
                </p>;
              })}
              {!evidenceRows.length && <p>La ficha histórica no tiene un mensaje de origen registrado.</p>}
            </details>
            {!!lead.profile.missing.length && <details className="fbc-profile-pending">
              <summary>Falta conocer ({lead.profile.missing.length})</summary>
              <p>{lead.profile.missing.join(" · ")}</p>
            </details>}
          </section>
          <section className="fbc-lead-overview" aria-label="Resumen del contacto">
            <div className="fbc-lead-identity">
              <div className="fbc-avatar">{lead.name && lead.name !== "Interesado de Facebook" ? lead.name.slice(0,1).toUpperCase() : "?"}</div>
              <div><strong>{lead.name && lead.name !== "Interesado de Facebook" ? lead.name : "Contacto sin nombre"}</strong>
                <small>{lead.company || lead.specialty || "Información por confirmar"}</small></div>
              <span className="fbc-stage">{statuses[lead.status] || lead.status}</span>
            </div>
            <label>Nombre de la persona
              <input aria-label="Nombre de la persona" value={lead.name === "Interesado de Facebook" ? "" : lead.name}
                placeholder="Escribir o confirmar nombre" maxLength={160}
                onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, name: e.target.value}} : old)} />
            </label>
            {currentInsights?.suggestions.filter((item) => item.field === "name").map((item) => <div className="fbc-suggestion" key="name">
              <span><Sparkles size={14} /> El contacto dijo: <b>{item.value}</b></span>
              <button type="button" className="nw-btn" disabled={!!saving}
                onClick={() => patchLead({name: String(item.value)})}>Confirmar nombre</button>
            </div>)}
            <div className="fbc-summary-data">
              <div><small>Oficio</small><strong>{lead.specialty || "Por confirmar"}</strong></div>
              <div><small>Personas</small><strong>{lead.workers ?? "Sin dato"}</strong></div>
              <div><small>Disponible desde</small><strong>{lead.availability || "Sin confirmar"}</strong></div>
            </div>
            <div className="fbc-next-action">
              <span><Sparkles size={15} /> Próximo paso sugerido</span>
              <p>{currentInsights?.next_action || "Confirmar oficio y disponibilidad del contacto."}</p>
            </div>
          </section>
          <section className="fbc-smart-matches" aria-label="Coincidencias sugeridas">
            <div className="fbc-section-head"><b>Necesidades compatibles</b><small>Revisión humana</small></div>
            {!currentInsights?.matches.length && <p className="fbc-hint">Sin coincidencias confirmables. Registra el oficio para buscar necesidades activas.</p>}
            {currentInsights?.matches.map((item) => <article key={item.id} className="fbc-smart-match">
              <div className="fbc-smart-match-top"><strong>{item.title}</strong>
                <span>{item.score} pts.</span></div>
              <small>{item.site} · {item.specialty}</small>
              <p>{item.reasons.slice(0,2).join(" · ")}</p>
              <button type="button" className="nw-btn" disabled={!!saving || lead.requirement_id === item.id}
                onClick={() => patchLead({requirement_id: item.id})}>
                {lead.requirement_id === item.id ? "Vinculada" : "Vincular necesidad"}
              </button>
            </article>)}
            <small>El puntaje es orientativo, no una probabilidad de contratación ni una adjudicación.</small>
          </section>
          <section className="fbc-simple-followup" aria-label="Seguimiento">
            <div className="fbc-section-head"><b>Seguimiento</b></div>
            <div className="fbc-pair">
              <label>Próxima fecha
                <input type="date" value={lead.follow_up_on || ""}
                  onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, follow_up_on: e.target.value || null}} : old)} />
              </label>
              <label>Etapa
                <select value={lead.status} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, status: e.target.value}} : old)}>
                  {["new","contacting","pending_review","shortlisted","archived"].map(x => <option key={x} value={x}>{statuses[x]}</option>)}
                </select>
              </label>
            </div>
            <label>Nota de seguimiento
              <input maxLength={240} value={lead.follow_up_note || ""} placeholder="Ej.: confirmar fecha con residente"
                onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, follow_up_note: e.target.value}} : old)} />
            </label>
          </section>
          <details className="fbc-advanced">
            <summary>Más datos y opciones</summary>
            <div className="fbc-advanced-content">
          <label className="fbc-check"><input type="checkbox" checked={lead.needs_support}
             onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, needs_support:e.target.checked}} : old)} />
             Mantener alerta de apoyo (administración puede desactivarla después de ayudar)</label>
          <label>Empresa o nombre comercial<input value={lead.company} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, company: e.target.value}} : old)} /></label>
          <label>Oficio o especialidad<input list="fbc-trades" value={lead.specialty} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, specialty: e.target.value}} : old)} /></label>
          <datalist id="fbc-trades">{catalog.specialties.map((x) => <option value={x} key={x}/>)}</datalist>
          <div className="fbc-pair">
            <label>Personas disponibles<input type="number" min={1} value={lead.workers ?? ""}
              onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, workers: e.target.value ? Number(e.target.value) : null}} : old)} /></label>
            <label>Disponible desde<input type="text" placeholder="Ej.: mañana, próxima semana o AAAA-MM-DD" value={lead.availability} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, availability: e.target.value}} : old)} /></label>
          </div>
          <label>Comunas en las que puede trabajar
            <input maxLength={120} value={lead.work_area} placeholder="Por confirmar"
              onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, work_area:e.target.value}} : old)} />
          </label>
          <label>Tipo de interés
            <select value={lead.interest_type} onChange={(e) =>
              setDetail((old) => old ? {...old, lead: {...old.lead,
                interest_type:e.target.value as Lead["interest_type"]}} : old)}>
              <option value="unknown">Aún no lo sabemos</option>
              <option value="service_offer">Ofrece servicios</option>
              <option value="employment">Busca trabajo como empleado</option>
              <option value="both">Busca empleo y ofrece servicios</option>
            </select>
          </label>
          <label>¿Puede venir con otras personas?
            <select value={lead.team_available === null ? "unknown" : String(lead.team_available)}
              onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead,
                team_available:e.target.value === "unknown" ? null : e.target.value === "true"}} : old)}>
              <option value="unknown">Aún no confirmado</option>
              <option value="true">Sí, puede venir con equipo</option>
              <option value="false">Trabaja solo/a</option>
            </select>
          </label>
          <label>Relacionar con necesidad
            <select value={lead.requirement_id || ""} onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, requirement_id: e.target.value || null}} : old)}>
              <option value="">Aún no asignada</option>
              {requirements.map((x) => <option key={x.id} value={x.id}>{x.site} · {x.title}</option>)}
            </select>
          </label>
          <label>Experiencia declarada<textarea value={lead.experience} rows={2}
            onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, experience: e.target.value}} : old)} /></label>
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
              <option value="false">No declara trabajadores contratados</option>
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
              <small>Permiso de IA: {lead.ai_consent_state.startsWith("accepted") && lead.ai_consent ? "Aceptado por Messenger" :
                lead.ai_consent_state.startsWith("requested") ? "Se solicitó permiso" :
                lead.ai_consent_state === "declined" ? "Prefiere atención humana" :
                "Sin solicitar"}</small>
              <small>El administrador puede pausar o reactivar al asistente; no puede otorgar consentimiento en nombre del contacto.</small>
            </div>
          </div>
          <label className="fbc-check"><input type="checkbox" checked={lead.ai_paused}
            onChange={(e) => setDetail((old) => old ? {...old, lead: {...old.lead, ai_paused: e.target.checked}} : old)} />
            Atención humana: Galancito en pausa para este contacto</label>
            </div>
          </details>
          <button type="button" disabled={!!saving} className="nw-btn nw-primary fbc-save-lead"
            onClick={() => {
              const saved = savedLeadRef.current;
              const patch = Object.fromEntries(editableFields.filter(field => lead[field] !== saved?.[field])
                .map(field => [field, lead[field]]));
              if (Object.keys(patch).length) patchLead(patch);
            }}>Guardar ficha y seguimiento</button>
          <details className="fbc-deep-review">
            <summary>Orientación y validaciones</summary>
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
          </details>
        </>}
      </aside>
    </div></>}
    {tab === "interactions" && <FacebookInteractions
      onOpenInbox={() => setTab("inbox")}
      onOpenLead={(leadId) => { setSelectedId(leadId); setShowProfile(false); setMobilePane("chat"); setTab("inbox"); }}
      onOpenProfile={(leadId) => {
        void net<Tracking>("/facebook/galancito/seguimiento").then(result => {
          setTracking(result);
          const person = result.rows.find(row => row.id === leadId);
          if (person) setSheetPerson(person);
          else {
            setSelectedId(leadId);
            setShowProfile(true);
            setMobilePane("profile");
            setTab("inbox");
          }
        }).catch(() => {
          setSelectedId(leadId);
          setShowProfile(true);
          setMobilePane("profile");
          setTab("inbox");
        });
      }}
    />}
    {tab === "publications" && <FacebookPublications
      posts={center?.publications || []}
      automaticEnabled={!!center?.automatic_enabled}
      onChanged={async () => { await refresh(true); }}
      onSync={async (ad) => {
        await change("/requirements/" + ad.requirement_id + "/facebook/sync");
        await refresh(true);
        setNotice("Sincronización solicitada; espera la confirmación de Meta.");
      }}
      onOpenInbox={() => setTab("inbox")}
      onOpenLead={(leadId) => { setSelectedId(leadId); setTab("inbox"); }}
    />}
    {tab === "testing" && <NetworkFacebook catalog={catalog} />}
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
