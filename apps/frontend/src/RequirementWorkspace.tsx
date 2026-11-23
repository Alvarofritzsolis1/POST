import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowRight, Check, CheckCircle2, CircleAlert, Clock3, Mail, Phone, MessageCircle,
  ExternalLink, FileText, Facebook, Filter, LoaderCircle, MessageSquare,
  RefreshCw, Search, Users, BriefcaseBusiness
} from "lucide-react";
import PersonAvatar from "./PersonAvatar";
import RequirementCandidateChat from "./RequirementCandidateChat";
import { change, net, type Capacity, type Requirement } from "./networkApi";
import { dateText, errorText } from "./NetworkUI";
import "./requirement-workspace.css";

type Stage = "suggested" | "interested" | "contacted" | "evaluating" | "selected" | "discarded";
type Tracking = { stage: Stage; note: string; follow_up_on: string | null; version: number; updated_at: string | null };
type Candidate = {
  id: string; source: string; name: string; company: string; trades: string[];
  type: string; entity_type: string; workers: number | null; availability: string;
  work_area: string; experience: string; phone: string; email: string;
  phone_opt_out: boolean; email_opt_out: boolean;
  contact_action: string; contact_source: {phone:string;email:string};
  last_inbound_at: string | null; linked: boolean;
  profile: { summary: string; percent: number; missing: string[] };
  fit: { compatibility: number | null; data_coverage: number; reasons: string[]; missing: string[] };
  tracking: Tracking;
};
type CapacityMatch = { id: string; score: number; reasons: string[]; capacity: Capacity };
type Comment = { id: string; name: string; picture_url: string | null; body: string;
  classification: string; review_state: string; posted_at: string; identity_confirmed: boolean };
type CandidatesResponse = {
  requirement_id: string; candidates: Candidate[]; candidate_total: number;
  source_limited: boolean; capacities: CapacityMatch[]; comments: Comment[];
  classification_warning: string | null;
  summary: Record<Stage, number>;
};
const STAGES: { value: Stage; label: string }[] = [
  { value: "suggested", label: "Sugerido" },
  { value: "interested", label: "Interesado confirmado" },
  { value: "contacted", label: "Contactado" },
  { value: "evaluating", label: "En evaluación" },
  { value: "selected", label: "Preseleccionado" },
  { value: "discarded", label: "Descartado" },
];
const stageLabel = (stage: Stage) => STAGES.find(s => s.value === stage)?.label || "Sugerido";
const init = (candidate: Candidate | undefined) => ({
  stage: candidate?.tracking.stage || "suggested" as Stage,
  note: candidate?.tracking.note || "",
  follow_up_on: candidate?.tracking.follow_up_on || "",
});
const easyDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? dateText(value) : value || "Por confirmar";

export default function RequirementWorkspace({
  requirement, children, onCapacity, onEdit,
}: {
  requirement: Requirement;
  children: ReactNode;
  onCapacity: (candidate: CapacityMatch) => void;
  onEdit: () => void;
}) {
  const [tab, setTab] = useState<"candidates" | "facebook" | "admin">("candidates");
  const [data, setData] = useState<CandidatesResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [chatLeadId, setChatLeadId] = useState("");
  const [chatDraftDirty, setChatDraftDirty] = useState(false);
  useEffect(() => {
    window.dispatchEvent(new CustomEvent("galant-network-chat-draft", { detail: chatDraftDirty }));
    return () => { window.dispatchEvent(new CustomEvent("galant-network-chat-draft", { detail: false })); };
  }, [chatDraftDirty]);
  const [query, setQuery] = useState("");
  const [stageFilter, setStageFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState<{stage:Stage; note:string; follow_up_on:string}>({stage:"suggested", note:"", follow_up_on:""});

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const next = await net<CandidatesResponse>("/requirements/" + encodeURIComponent(requirement.id) + "/candidates?limit=150");
      setData(next);
      setSelectedId(prev => prev && next.candidates.some(candidate => candidate.id === prev) ? prev : (next.candidates[0]?.id || ""));
      setError("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [requirement.id]);

  useEffect(() => { void load(); }, [load]);
  const candidates = data?.candidates || [];
  const selected = candidates.find(candidate => candidate.id === selectedId);
  const formChanged = !!selected && (
    form.stage !== selected.tracking.stage ||
    form.note !== selected.tracking.note ||
    form.follow_up_on !== (selected.tracking.follow_up_on || "")
  );
  useEffect(() => {
    setForm(init(selected));
  }, [selected?.id, selected?.tracking.version]);

  useEffect(() => {
    const sync = () => {
      if (!document.hidden && !formChanged && !saving) void load(true);
    };
    const timer = window.setInterval(sync, 60000);
    window.addEventListener("focus", sync);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", sync);
    };
  }, [load, formChanged, saving]);

  const filtered = useMemo(() => candidates.filter(candidate => {
    const text = [candidate.name, candidate.company, ...candidate.trades, candidate.work_area]
      .join(" ").toLocaleLowerCase("es-CL");
    const stateOK = stageFilter === "all" ||
      (stageFilter === "linked" ? candidate.linked : candidate.tracking.stage === stageFilter);
    return stateOK && text.includes(query.trim().toLocaleLowerCase("es-CL"));
  }), [candidates, query, stageFilter]);

  function choose(id: string) {
    if (id === selectedId) return;
    if ((formChanged || chatDraftDirty) && !window.confirm("Hay cambios sin guardar en la ficha o en un mensaje. ¿Descartarlos?")) return;
    setSelectedId(id);
    setChatLeadId("");
    setChatDraftDirty(false);
    setNotice("");
  }

  function confirmAbandon() {
    return (!formChanged && !chatDraftDirty) || window.confirm("Hay cambios sin guardar en la ficha o en un mensaje. ¿Descartarlos?");
  }

  async function save() {
    if (!selected || saving) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const updated = await change<Tracking>(
        "/requirements/" + encodeURIComponent(requirement.id) +
        "/candidates/" + encodeURIComponent(selected.id) + "/follow-up",
        { stage: form.stage, note: form.note.trim(), follow_up_on: form.follow_up_on || null,
          version: selected.tracking.version }, "PUT"
      );
      setData(prev => prev ? ({
        ...prev,
        candidates: prev.candidates.map(candidate => candidate.id === selected.id
          ? { ...candidate, tracking: updated } : candidate),
        summary: updated.stage === selected.tracking.stage ? prev.summary : {
          ...prev.summary,
          [selected.tracking.stage]: Math.max(0, (prev.summary[selected.tracking.stage] || 0) - 1),
          [updated.stage]: (prev.summary[updated.stage] || 0) + 1,
        },
      }) : prev);
      setNotice("Seguimiento guardado");
      window.dispatchEvent(new Event("galant-network-follow-up-saved"));
      window.dispatchEvent(new Event("galant-network-changed"));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return <div className="nwc-shell">
    <div className="nwc-topline">
      <div className="nwc-titleline">
        <span className="nwc-symbol"><BriefcaseBusiness size={22}/></span>
        <div>
          <span className="nwc-eyebrow">CENTRO DE SEGUIMIENTO · {requirement.site}</span>
          <h2>{requirement.title}</h2>
          <p>{requirement.specialty} · {requirement.workers} {requirement.workers === 1 ? "trabajador" : "trabajadores"} · Inicio {requirement.start_date_pending ? "por confirmar" : dateText(requirement.start_date)}</p>
        </div>
      </div>
      <div className="nwc-header-actions">
        <span className={"nwc-priority " + (requirement.priority === "urgent" || requirement.priority === "high" ? "is-urgent" : "")}>
          {requirement.priority === "urgent" ? "Urgente" : requirement.priority === "high" ? "Alta prioridad" : requirement.priority === "low" ? "Baja prioridad" : "Normal"}
        </span>
        {requirement.editable && <button className="nwc-ghost" type="button" onClick={() => { if (confirmAbandon()) onEdit(); }}><FileText size={16}/> Editar solicitud</button>}
      </div>
    </div>
    {data?.classification_warning && <div className="nwc-warning" role="status"><CircleAlert size={18}/>{data.classification_warning}</div>}
    <div className="nwc-kpis" aria-label="Resumen del seguimiento">
      <div><strong>{data?.candidate_total ?? "—"}</strong><span>Posibles perfiles</span></div>
      <div><strong>{data?.summary.interested ?? "—"}</strong><span>Interesados confirmados</span></div>
      <div><strong>{(data?.summary.contacted || 0) + (data?.summary.evaluating || 0)}</strong><span>En seguimiento</span></div>
      <div><strong>{data?.summary.selected ?? "—"}</strong><span>Preseleccionados</span></div>
      <div><strong>{data?.capacities.length ?? "—"}</strong><span>Otras obras</span></div>
    </div>
    <nav className="nwc-tabs" aria-label="Secciones del requerimiento">
      <button type="button" className={tab === "candidates" ? "active" : ""} onClick={() => { if (confirmAbandon()) { setTab("candidates"); setChatLeadId(""); setChatDraftDirty(false); } }} aria-current={tab==="candidates"?"page":undefined}><Users size={17}/> Candidatos</button>
      <button type="button" className={tab === "facebook" ? "active" : ""} onClick={() => { if (confirmAbandon()) { setTab("facebook"); setChatLeadId(""); setChatDraftDirty(false); } }} aria-current={tab==="facebook"?"page":undefined}><Facebook size={17}/> Publicación e interacciones <span>{data?.comments.length || 0}</span></button>
      <button type="button" className={tab === "admin" ? "active" : ""} onClick={() => { if (confirmAbandon()) { setTab("admin"); setChatLeadId(""); setChatDraftDirty(false); } }} aria-current={tab==="admin"?"page":undefined}><FileText size={17}/> Partidas y documentos</button>
      <button className="nwc-refresh" type="button" onClick={() => void load()} aria-label="Actualizar candidatos" title="Actualizar candidatos"><RefreshCw size={17}/></button>
    </nav>
    {error && <div className="nwc-error" role="alert"><CircleAlert size={18}/>{error} <button type="button" onClick={() => void load()}>Reintentar</button></div>}

    {tab === "candidates" && <div className="nwc-content">
      <section className="nwc-list" aria-label="Posibles candidatos">
        <div className="nwc-listhead">
          <div><h3>Candidatos relacionados</h3><small>{filtered.length} perfiles visibles · Sugerencias sujetas a revisión</small></div>
          <label className="nwc-search"><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Buscar por nombre u oficio" aria-label="Buscar candidatos"/></label>
          <label className="nwc-filter"><Filter size={15}/><select value={stageFilter} onChange={e => setStageFilter(e.target.value)} aria-label="Filtrar candidatos por etapa">
            <option value="all">Todas las etapas</option>
            <option value="linked">Relacionados a la necesidad</option>
            {STAGES.map(s=><option key={s.value} value={s.value}>{s.label}</option>)}
          </select></label>
        </div>
        {loading && !data ? <div className="nwc-empty"><LoaderCircle className="nwc-spin" size={23}/> Buscando perfiles relacionados…</div> :
          filtered.length ? <div className="nwc-people">
            {filtered.map(candidate => <button type="button" key={candidate.id} className={"nwc-person" + (candidate.id === selectedId ? " selected" : "")}
              aria-pressed={candidate.id === selectedId} onClick={() => choose(candidate.id)}>
              <PersonAvatar name={candidate.name} size="md"/>
              <span className="nwc-person-body"><strong>{candidate.name}</strong>
                <small>{candidate.trades.slice(0,2).join(" · ") || "Oficio por confirmar"}</small>
                <span className="nwc-person-status">{candidate.linked && <em>Vinculado</em>}
                <em className={candidate.tracking.stage === "suggested" ? "muted" : "highlight"}>{stageLabel(candidate.tracking.stage)}</em></span>
              </span>
              <span className="nwc-fit">{candidate.fit.compatibility === null ? "—" : candidate.fit.compatibility + "%"}<small>afinidad</small></span>
            </button>)}
          </div> : <div className="nwc-empty">No hay perfiles para este filtro. Las coincidencias requieren un oficio declarado; prueba otra búsqueda.</div>}
        {data?.source_limited && <p className="nwc-listnote">La búsqueda se limita a los 1500 contactos más recientes. Refina el alcance antes de considerar completa esta lista.</p>}
        {!!data?.capacities.length && <div className="nwc-caps">
          <h3>Contratistas disponibles en otras obras</h3>
          {data.capacities.map(match => <div className="nwc-cap" key={match.id}>
            <div><strong>{match.capacity.contractor}</strong><small>{match.capacity.site} · {match.capacity.workers} personas · {match.score}% afinidad</small></div>
            <button type="button" onClick={() => { if (confirmAbandon()) onCapacity(match); }}>Coordinar <ArrowRight size={14}/></button>
          </div>)}
        </div>}
      </section>
      <section className="nwc-profile" aria-label="Ficha del candidato">
        {selected && chatLeadId === selected.id ?
          <RequirementCandidateChat key={selected.id} requirementId={requirement.id}
            leadId={selected.id} name={selected.name} contactMissing={!selected.phone && !selected.email && !selected.phone_opt_out && !selected.email_opt_out}
            onBack={() => { if (confirmAbandon()) { setChatLeadId(""); setChatDraftDirty(false); } }}
            onDraftDirty={setChatDraftDirty}/> :
         !selected ? <div className="nwc-empty"><Users size={30}/><strong>Selecciona un perfil</strong><span>Visualiza su ficha y registra el seguimiento sin salir de la solicitud.</span></div> : <>
          <div className="nwc-profile-top">
            <PersonAvatar name={selected.name} size="lg"/>
            <div><span className="nwc-eyebrow">FICHA DE CONTACTO · GALANCITO</span><h3>{selected.name}</h3>
              <p>{selected.company || (selected.type === "employment" ? "Busca trabajo individual" : "Ofrece servicios / modalidad por confirmar")}</p>
              <div className="nwc-chips">{selected.trades.map(t=><span key={t}>{t}</span>)}{selected.linked && <span className="is-linked"><Check size={13}/> Relacionado</span>}</div>
            </div>
            <button type="button" className="nwc-open-chat" onClick={() => {
              if (confirmAbandon()) setChatLeadId(selected.id);
            }} aria-label={"Abrir chat con " + selected.name}>
              <MessageCircle size={17}/> Chat
            </button>
          </div>
          <div className="nwc-scoreline">
            <div><strong>{selected.fit.compatibility === null ? "—" : selected.fit.compatibility + "%"}</strong><span>Compatibilidad de oficio, dotación y fecha</span></div>
            <div><strong>{selected.fit.data_coverage}%</strong><span>Criterios de comparación conocidos</span></div>
            <div><strong>{selected.profile.percent}%</strong><span>Ficha profesional completada</span></div>
          </div>
          <div className="nwc-profile-columns">
            <section className="nwc-profile-card"><h4><CheckCircle2 size={16}/> Coincidencias</h4>
              <ul>{selected.fit.reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul>
              {selected.fit.missing.length > 0 && <p className="nwc-softwarn"><CircleAlert size={15}/>{selected.fit.missing.join(" · ")}</p>}
            </section>
            <section className="nwc-profile-card"><h4><BriefcaseBusiness size={16}/> Datos declarados</h4>
              <dl><div><dt>Equipo</dt><dd>{selected.workers === null ? "Sin informar" : selected.workers + " persona(s)"}</dd></div>
                <div><dt>Disponibilidad</dt><dd>{easyDate(selected.availability)}</dd></div>
                <div><dt>Zona</dt><dd>{selected.work_area || "Por confirmar"}</dd></div>
              </dl>
            </section>
          </div>
          <section className="nwc-contact-block" aria-label="Datos para comunicarse con el candidato">
            <div className="nwc-contact-title"><h4><MessageCircle size={16}/> Contacto y coordinación</h4>
              <span>{selected.phone || selected.email ? "Datos disponibles" : "Faltan datos"}</span>
            </div>
            <div className="nwc-contact-grid">
              <div className={"nwc-contact-field" + (!selected.phone ? " is-pending" : "")}>
                <Phone size={18}/>
                <div><small>Teléfono / WhatsApp</small>
                  {selected.phone ? <a href={"tel:" + selected.phone}>{selected.phone}</a> :
                    <strong>{selected.phone_opt_out ? "No desea compartirlo" : "Pendiente"}</strong>}
                </div>
              </div>
              <div className={"nwc-contact-field" + (!selected.email ? " is-pending" : "")}>
                <Mail size={18}/>
                <div><small>Correo electrónico</small>
                  {selected.email ? <a href={"mailto:" + selected.email}>{selected.email}</a> :
                    <strong>{selected.email_opt_out ? "No desea compartirlo" : "Pendiente"}</strong>}
                </div>
              </div>
            </div>
            <div className="nwc-contact-next">
              <CircleAlert size={16}/>
              <span>{selected.contact_action}</span>
            </div>
          </section>
          <section className="nwc-profile-summary">
            <h4><FileText size={16}/> Resumen para el residente</h4>
            <p>{selected.profile.summary}</p>
            {selected.profile.missing.length > 0 && <details>
              <summary>Ver {selected.profile.missing.length} datos por completar</summary>
              <ul>{selected.profile.missing.map(item=><li key={item}>{item}</li>)}</ul>
            </details>}
          </section>
          <form className="nwc-track" onSubmit={e => { e.preventDefault(); void save(); }}>
            <div className="nwc-trackhead"><h4><Clock3 size={17}/> Seguimiento del residente</h4><span>Solo para esta solicitud</span></div>
            <div className="nwc-trackfields">
              <label>Etapa<select value={form.stage} onChange={e => setForm(old => ({...old,stage:e.target.value as Stage}))}>{STAGES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}</select></label>
              <label>Próxima gestión<input type="date" value={form.follow_up_on} onChange={e => setForm(old => ({...old,follow_up_on:e.target.value}))}/></label>
            </div>
            <label>Observación<textarea rows={2} maxLength={2000} value={form.note} placeholder="Ej. Confirmar disponibilidad y experiencia en obra" onChange={e => setForm(old => ({...old,note:e.target.value}))}/></label>
            <div className="nwc-trackactions"><span>{notice || "No se envían mensajes desde esta ficha."}</span>
              <button type="submit" disabled={!formChanged || saving}>{saving ? <LoaderCircle className="nwc-spin" size={16}/> : <Check size={16}/>} Guardar seguimiento</button>
            </div>
          </form>
        </>}
      </section>
    </div>}

    {tab === "facebook" && <div className="nwc-social">
      <div className="nwc-social-header">
        <div><h3>Publicación e interacciones</h3><p>Un comentario público no equivale a una postulación ni confirma la identidad de Messenger.</p></div>
        {requirement.facebook?.post_url && <a href={requirement.facebook.post_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/> Abrir publicación</a>}
      </div>
      <div className="nwc-social-state"><Facebook size={20}/> Estado: {requirement.facebook?.state || "Sin publicación vinculada"} · {data?.comments.length || 0} comentarios relevantes identificados</div>
      {data?.comments.length ? <div className="nwc-comments">{data.comments.map(comment => <article className="nwc-comment" key={comment.id}>
        {comment.picture_url ? <img src={comment.picture_url} alt="" loading="lazy" referrerPolicy="no-referrer"/> : <PersonAvatar name={comment.name} size="md"/>}
        <div><div className="nwc-commentline"><strong>{comment.name}</strong><span>{dateText(comment.posted_at.slice(0,10))} · {comment.classification === "interested" ? "Interés detectado" : "Revisión pendiente"}</span></div>
          <p>{comment.body}</p><small>Interacción pública; requiere verificación para asociar una ficha.</small>
        </div></article>)}</div> : <div className="nwc-empty"><MessageSquare size={28}/> No hay comentarios relevantes sincronizados para este anuncio.</div>}
    </div>}

    {tab === "admin" && <div className="nwc-admin">{children}</div>}
  </div>;
}
