import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { type Site } from "./opsApi";
import { read, send } from "./platformApi";
import "./workers.css";

type WorkerRow = {
  assignment_id: string; worker_id: string; worker_name: string; worker_rut: string;
  contractor_id: string; contractor_name: string; site_id: string; site_name: string;
  contract_id: string | null; contract_type: string | null; start_date: string | null;
  end_date: string | null; contract_status: string | null; termination_id: string | null;
  effective_date: string | null; finiquito_document_id: string | null;
  labor_state: string; finiquito_state: string; severity: string; alert: string;
};
type Registry = { rows: WorkerRow[]; page: number; page_size: number; summary: Record<string, number> };
type Termination = { id: string; effective_date: string; cause: string; ratification_mode: string;
  issued_at: string | null; signed_at: string | null; document_id: string | null;
  review_state: string; observation: string; reviewed_by: string | null; reviewed_at: string | null };
type Contract = { id: string; contract_type: string; start_date: string; end_date: string | null;
  status: string; notes: string; termination: Termination | null;
  amendments: { id: string; date: string; previous_end_date: string | null; new_end_date: string | null; reference: string }[];
  attachments: { id: string; document_id: string; kind: string }[] };
type Detail = { id: string; worker_id: string; association_id: string; name: string; rut: string;
  contractor_id: string; contractor: string; site_id: string; site: string;
  current: WorkerRow | null; contracts: Contract[];
  history: { id: string; entity_type: string; changes: Record<string, unknown>; created_at: string; actor_name?: string }[] };
type WorkerDocument = { association_id: string; subject: string; requirement: string; period: string;
  state: string; delivery_state: string; observation: string; document_id: string | null };
type CompanyOption = { id: string; site_id: string; contractor_id: string; name: string; nature: string };
const stateLabel: Record<string, string> = {
  active: "Vigente", ending_soon: "Próximo a vencer", expired_needs_review: "Vencido: revisar",
  ended: "Terminado", observed: "Observado", not_applicable: "No aplica", missing: "Pendiente de entrega",
  delivered: "Entregado, pendiente de revisión", pending: "Pendiente de revisión",
  pending_review: "Entregado, pendiente de revisión", approved: "Aprobado", rejected: "Rechazado",
  not_delivered: "No entregado", incomplete: "Incompleto", suspended: "Suspendido",
};
const typeLabel: Record<string, string> = { indefinite: "Indefinido", fixed_term: "Plazo fijo", project: "Obra o faena", services: "Servicios" };

const auditEntityLabel:Record<string,string>={
  worker:"Trabajador",worker_assignment:"Asignación laboral",contract:"Contrato",
  labor_contract:"Contrato laboral",contract_amendment:"Anexo de contrato",
  worker_termination:"Término laboral",termination:"Finiquito",contractor:"Contratista",
};
const auditFieldLabel:Record<string,string>={
  name:"Nombre",rut:"RUT",active:"Estado de asignación",status:"Estado",start_date:"Fecha de ingreso",
  end_date:"Fecha de término",termination_date:"Fecha efectiva de término",contract_type:"Tipo de contrato",
  labor_state:"Situación laboral",review_state:"Revisión",notes:"Observación",
  historical_code:"Clasificación",created:"Creación",imported:"Importación",created_at:"Fecha de registro",
};
const readableAuditValue=(value:unknown):string=>{
  if(value===null||value===undefined||value==="")return "Sin registrar";
  if(typeof value==="boolean")return value?"Sí":"No";
  if(typeof value==="number")return String(value);
  if(typeof value==="string"){
    if(/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value))return "Referencia interna";
    return stateLabel[value]||typeLabel[value]||value;
  }
  return "Dato actualizado";
};
const readableAudit=(changes:Record<string,unknown>):string=>{
  const results=Object.entries(changes||{}).map(([field,value])=>{
    if(field==="created"||field==="imported")return field==="created"?"Registro creado":"Registro incorporado";
    if(field.endsWith("_id")||field==="id")return "Vinculación del registro actualizada";
    const label=auditFieldLabel[field]||"Campo del registro";
    if(value&&typeof value==="object"&&"from" in value&&"to" in value){
      const diff=value as {from:unknown;to:unknown};
      return label+": "+readableAuditValue(diff.from)+" → "+readableAuditValue(diff.to);
    }
    return label+": "+readableAuditValue(value);
  });
  return results.length?results.join(" · "):"Cambio registrado";
};

const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "America/Santiago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
const date = (value: string | null | undefined) => value ? value.slice(0, 10).split("-").reverse().join("/") : "—";
const err = (e: unknown) => e instanceof Error ? e.message : "No fue posible completar la operación";
const blankContract = { contract_type: "indefinite", start_date: today(), end_date: "", status: "active", notes: "" };
const input = (path: string, body: unknown, method = "POST") => send<Record<string, unknown>>(path, body, method);

export default function Workers({ siteId, sites, period, canEdit, canReview, initialState, initialPending, initialAssignment }: {
  siteId: string; sites: Site[]; period: string; canEdit: boolean; canReview: boolean; initialState?: string; initialPending?: boolean; initialAssignment?: string;
}) {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [companies, setCompanies] = useState<CompanyOption[]>([]);
  const [draftCompanies, setDraftCompanies] = useState<CompanyOption[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState("summary");
  const [search, setSearch] = useState("");
  const [company, setCompany] = useState("");
  const [labor, setLabor] = useState(initialState || "");
  const [kind, setKind] = useState("");
  const [upcoming, setUpcoming] = useState(false);
  const [pending, setPending] = useState(false);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [siteDraft, setSiteDraft] = useState(siteId);
  const [workerDraft, setWorkerDraft] = useState({ name: "", rut: "", contractor_id: "" });
  const [editIdentity, setEditIdentity] = useState({ name: "", rut: "" });
  const [contractDraft, setContractDraft] = useState(blankContract);
  const [contractEdit, setContractEdit] = useState({ contract_type: "", end_date: "", status: "active", notes: "" });
  const [contractFile, setContractFile] = useState<File | null>(null);
  const [termDraft, setTermDraft] = useState({ effective_date: today(), cause: "", ratification_mode: "unrecorded", observation: "" });
  const [finiquitoFile, setFiniquitoFile] = useState<File | null>(null);
  const [finiquitoDates, setFiniquitoDates] = useState({ issued_at: "", signed_at: "" });
  const [reviewNote, setReviewNote] = useState("");
  const [amendment, setAmendment] = useState({ amendment_date: today(), new_end_date: "", reference: "", notes: "" });
  const [docRows, setDocRows] = useState<WorkerDocument[]>([]);
  const [docFile, setDocFile] = useState<File | null>(null);
  const [docNote, setDocNote] = useState("");
  const [catalogs, setCatalogs] = useState<{ termination_causes: Record<string, string>; extra_contract_types: Record<string, string> } | null>(null);

  const refresh = () => setRevision((v) => v + 1);
  async function act(task: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await task(); setNotice("Cambios guardados."); refresh(); }
    catch (e) { setError(err(e)); }
    finally { setBusy(false); }
  }
  useEffect(() => { setPage(1); setCompany(""); setSelected(""); setDetail(null); setSiteDraft(siteId); }, [siteId]);
  useEffect(() => { setLabor(initialState || ""); }, [initialState]);
  useEffect(() => { setPending(!!initialPending); }, [initialPending]);
  useEffect(() => { if (initialAssignment) { setSelected(initialAssignment); setTab("summary"); } }, [initialAssignment]);
  useEffect(() => { setPage(1); }, [search, company, labor, kind, upcoming, pending]);
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ page: String(page), page_size: "50" });
    if (siteId) query.set("site_id", siteId);
    if (company) query.set("contractor_id", company);
    if (search.trim()) query.set("search", search.trim());
    if (labor) query.set("labor_state", labor);
    if (kind) query.set("contract_type", kind);
    if (upcoming) query.set("upcoming", "true");
    if (pending) query.set("finiquito_pending", "true");
    void read<Registry>("/labor/workers?" + query.toString()).then((value) => { if (active) setRegistry(value); }).catch((e) => { if (active) setError(err(e)); });
    return () => { active = false; };
  }, [siteId, company, search, labor, kind, upcoming, pending, page, revision]);
  useEffect(() => {
    let active = true;
    void read<CompanyOption[]>("/labor/contractors" + (siteId ? "?site_id=" + encodeURIComponent(siteId) : ""))
      .then((rows) => { if (active) setCompanies(rows); }).catch((e) => { if (active) setError(err(e)); });
    return () => { active = false; };
  }, [siteId, revision]);
  useEffect(() => {
    let active = true;
    if (!siteDraft) { setDraftCompanies([]); return; }
    void read<CompanyOption[]>("/labor/contractors?site_id=" + encodeURIComponent(siteDraft))
      .then((rows) => { if (active) setDraftCompanies(rows); }).catch((e) => { if (active) setError(err(e)); });
    return () => { active = false; };
  }, [siteDraft, siteId, revision]);
  useEffect(() => { void read<typeof catalogs>("/admin/catalogs").then(setCatalogs).catch(() => {}); }, []);
  useEffect(() => {
    let active = true;
    if (!selected) { setDetail(null); return; }
    void read<Detail>("/labor/workers/" + encodeURIComponent(selected)).then((value) => { if (active) setDetail(value); }).catch((e) => { if (active) setError(err(e)); });
    return () => { active = false; };
  }, [selected, revision]);
  useEffect(() => { if (detail) { setEditIdentity({ name: detail.name, rut: detail.rut });
    const c = detail.contracts[0]; if (c) setContractEdit({ contract_type: c.contract_type,
      end_date: c.end_date || "", status: c.status, notes: c.notes }); } },
    [detail?.id, detail?.contracts[0]?.id, detail?.contracts[0]?.end_date, detail?.contracts[0]?.status, detail?.contracts[0]?.notes]);
  useEffect(() => {
    let active = true;
    if (!detail || tab !== "documents") return;
    void read<WorkerDocument[]>("/ops/document-reviews?period=" + encodeURIComponent(period) + "&site_id=" + encodeURIComponent(detail.site_id))
      .then((rows) => { if (active) setDocRows(rows.filter((r) => r.subject === detail.id)); })
      .catch((e) => { if (active) setError(err(e)); });
    return () => { active = false; };
  }, [detail?.id, detail?.site_id, tab, period, revision]);

  const types = useMemo(() => ({ ...typeLabel, ...(catalogs?.extra_contract_types || {}) }), [catalogs]);
  const current = detail?.contracts[0];
  const term = current?.termination;
  async function uploadPdf(file: File | null) { return file ? (await api.upload(file, "auto")).id : null; }
  async function createWorker() {
    if (!siteDraft || !workerDraft.contractor_id) throw new Error("Selecciona obra y contratista");
    const document_id = await uploadPdf(contractFile);
    const result = await input("/labor/workers", {
      site_id: siteDraft, ...workerDraft,
      contract: { ...contractDraft, end_date: contractDraft.end_date || null, document_id },
    });
    setCreateOpen(false); setWorkerDraft({ name: "", rut: "", contractor_id: "" });
    setContractDraft(blankContract); setContractFile(null);
    setSelected(String(result.assignment_id)); setTab("summary");
  }
  async function createContract() {
    if (!detail) return;
    const document_id = await uploadPdf(contractFile);
    await input("/labor/contracts", { assignment_id: detail.id, ...contractDraft,
      end_date: contractDraft.end_date || null, document_id });
    setContractFile(null); setContractDraft(blankContract);
  }
  async function submitTermination() {
    if (!current || !window.confirm("¿Confirmas el término efectivo de este contrato?")) return;
    await input("/labor/contracts/" + current.id + "/termination", termDraft);
  }
  async function uploadFiniquito() {
    if (!term || !finiquitoFile) return;
    const document_id = await uploadPdf(finiquitoFile);
    await input("/labor/terminations/" + term.id + "/document", {
      document_id, issued_at: finiquitoDates.issued_at || null,
      signed_at: finiquitoDates.signed_at || null, ratification_mode: termDraft.ratification_mode,
    });
    setFiniquitoFile(null);
  }
  async function review(state: string) {
    if (!term || !window.confirm("¿Confirmas la decisión de revisión?")) return;
    await input("/labor/terminations/" + term.id + "/review", { state, observation: reviewNote });
    setReviewNote("");
  }
  async function reviewDocument(row: WorkerDocument, state: string) {
    if (!detail) return;
    const document_id = await uploadPdf(docFile) || row.document_id;
    await send("/ops/document-reviews", { association_id: detail.association_id,
      subject: detail.id, period, requirement: row.requirement, state,
      observation: docNote, document_id }, "PUT");
    setDocFile(null); setDocNote("");
  }
  return <div className="workers-page">
    {error && <p role="alert" className="alert danger">{error}</p>}
    {notice && <p role="status" className="alert success">{notice}</p>}
    <section className="panel">
      <div className="workers-heading"><div><h2>Personas y situación laboral</h2><p>Todos los trabajadores de la obra, sin seleccionar previamente una empresa.</p></div>
        {canEdit && <button className="primary" onClick={() => { setCreateOpen(!createOpen); setSiteDraft(siteId); }}>Nuevo trabajador y contrato</button>}
      </div>
      <div className="kpi-grid">
        {([ ["total", "Trabajadores"], ["active", "Vigentes"], ["ending_soon", "Próximos"],
          ["expired", "Vencidos sin regularizar"], ["ended", "Terminados"], ["finiquito_pending", "Finiquitos pendientes"] ] as const).map(([key, label]) =>
          <button key={key} className={"kpi worker-kpi " + ((registry?.summary[key] ?? 0) > 0 && (key === "expired" || key === "finiquito_pending") ? "metric-danger" : (registry?.summary[key] ?? 0) > 0 && key === "ending_soon" ? "metric-warning" : "")} onClick={() => { setLabor(key === "expired" ? "expired_needs_review" : key === "active" || key === "ended" || key === "ending_soon" ? key : ""); setPending(key === "finiquito_pending"); }}>
            <small>{label}</small><strong>{registry?.summary[key] ?? 0}</strong>
          </button>)}
      </div>
      <div className="workers-filters toolbar">
        <label>Buscar nombre o RUT<input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar trabajador" /></label>
        <label>Contratista<select value={company} onChange={(e) => setCompany(e.target.value)}><option value="">Todos</option>{Array.from(new Map(companies.map((c) => [c.contractor_id, c])).values()).map((c) => <option key={c.id} value={c.contractor_id}>{c.name}</option>)}</select></label>
        <label>Estado laboral<select value={labor} onChange={(e) => setLabor(e.target.value)}><option value="">Todos</option>{["active", "ending_soon", "expired_needs_review", "ended", "observed"].map((v) => <option key={v} value={v}>{stateLabel[v]}</option>)}</select></label>
        <label>Tipo de contrato<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Todos</option>{Object.entries(types).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
        <label><input type="checkbox" checked={upcoming} onChange={(e) => setUpcoming(e.target.checked)} /> Próximos</label>
        <label><input type="checkbox" checked={pending} onChange={(e) => setPending(e.target.checked)} /> Finiquitos pendientes</label>
        <button onClick={refresh} disabled={busy}>Actualizar</button>
      </div>
      <div className="table-wrap"><table><thead><tr><th>Trabajador</th><th>RUT</th><th>Contratista</th><th>Obra</th><th>Contrato</th><th>Ingreso</th><th>Término pactado</th><th>Estado laboral</th><th>Finiquito</th><th>Acciones</th></tr></thead>
        <tbody>{registry?.rows.map((r) => <tr key={r.assignment_id}>
          <td><strong>{r.worker_name}</strong></td><td>{r.worker_rut}</td><td>{r.contractor_name}</td><td>{r.site_name}</td>
          <td>{types[r.contract_type || ""] || "Sin contrato"}</td><td>{date(r.start_date)}</td><td>{date(r.end_date)}</td>
          <td><span className={"worker-signal " + r.severity} title={r.alert}>{stateLabel[r.labor_state] || r.labor_state}</span></td>
          <td>{stateLabel[r.finiquito_state] || r.finiquito_state}</td><td><button onClick={() => { setSelected(r.assignment_id); setTab("summary"); }}>Ver y gestionar</button></td>
        </tr>)}</tbody></table></div>
      {!registry?.rows.length && <p className="empty">No hay trabajadores para estos filtros. Selecciona otra obra o crea una persona con su contrato.</p>}
      <div className="toolbar"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button><span>Página {page} · {registry?.summary.total ?? 0} asignaciones</span><button disabled={page * 50 >= (registry?.summary.total || 0)} onClick={() => setPage(page + 1)}>Siguiente</button></div>
    </section>
    {createOpen && canEdit && <section className="panel"><h2>Nuevo trabajador con contrato</h2>
      <form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(createWorker); }}>
        <label>Obra<select required value={siteDraft} onChange={(e) => { setSiteDraft(e.target.value); setWorkerDraft((v) => ({ ...v, contractor_id: "" })); }}><option value="">Seleccionar</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Contratista<select required value={workerDraft.contractor_id} onChange={(e) => setWorkerDraft((v) => ({ ...v, contractor_id: e.target.value }))}><option value="">Seleccionar</option>{draftCompanies.filter((c) => c.nature !== "independent").map((c) => <option key={c.id} value={c.contractor_id}>{c.name}</option>)}</select></label>
        <label>Nombre completo<input required value={workerDraft.name} onChange={(e) => setWorkerDraft((v) => ({ ...v, name: e.target.value }))} /></label>
        <label>RUT<input required value={workerDraft.rut} onChange={(e) => setWorkerDraft((v) => ({ ...v, rut: e.target.value }))} /></label>
        <ContractFields value={contractDraft} onChange={setContractDraft} types={types} />
        <label>Contrato PDF<input type="file" accept="application/pdf,.pdf" onChange={(e) => setContractFile(e.target.files?.[0] || null)} /></label>
        <button className="primary" disabled={busy}>Guardar trabajador y contrato</button>
      </form>
    </section>}
    {selected && detail && <section className="panel worker-detail">
      <div className="workers-heading"><div><h2>{detail.name}</h2><p>{detail.rut} · {detail.contractor} · {detail.site}</p></div><button onClick={() => setSelected("")}>Cerrar ficha</button></div>
      <div className="worker-tabs" role="tablist">{[["summary", "Resumen"], ["contract", "Contrato"], ["finiquito", "Finiquito"], ["documents", "Control documental"], ["history", "Historial"]].map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</div>
      {tab === "summary" && <div className="worker-summary">
        <p><b>Estado laboral:</b> {stateLabel[detail.current?.labor_state || "observed"]} · <b>Finiquito:</b> {stateLabel[detail.current?.finiquito_state || "not_applicable"]}</p>
        {detail.current?.alert && <p className={"worker-signal " + detail.current.severity}>{detail.current.alert}</p>}
        <p><b>Contrato actual:</b> {types[current?.contract_type || ""] || "Sin contrato"} · Ingreso {date(current?.start_date)} · Término pactado {date(current?.end_date)}</p>
        {term && <p><b>Desvinculación efectiva:</b> {date(term.effective_date)} · Registrada por usuario · Revisión: {stateLabel[term.review_state]}</p>}
        {canEdit && <button onClick={() => { setCreateOpen(true); setSiteDraft(""); setWorkerDraft({ name: detail.name, rut: detail.rut, contractor_id: "" }); }}>Nueva asignación en otra obra</button>}
        {canEdit && <form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(async () => {
          await input("/labor/workers/" + detail.id, editIdentity, "PATCH");
        }); }}><label>Corregir nombre<input required value={editIdentity.name} onChange={(e) => setEditIdentity((v) => ({ ...v, name: e.target.value }))} /></label>
          <label>Corregir RUT<input required value={editIdentity.rut} onChange={(e) => setEditIdentity((v) => ({ ...v, rut: e.target.value }))} /></label>
          <button disabled={busy || (editIdentity.name === detail.name && editIdentity.rut === detail.rut)}>Guardar identificación</button></form>}
      </div>}
      {tab === "contract" && <div>
        {detail.contracts.map((c) => <div className="worker-record" key={c.id}><h3>{types[c.contract_type] || c.contract_type} · {stateLabel[c.status] || c.status}</h3>
          <p>Inicio {date(c.start_date)} · Término pactado {date(c.end_date)} · {c.notes || "Sin observaciones"}</p>
          {c.attachments.map((a) => <p key={a.id}><a href={api.pdf(a.document_id)} target="_blank" rel="noreferrer">Ver PDF {a.kind === "contract" ? "del contrato" : "del anexo"}</a></p>)}
          {c.amendments.map((a) => <p key={a.id}>Anexo {a.reference} · {date(a.date)} · {date(a.previous_end_date)} → {date(a.new_end_date)}</p>)}
        </div>)}
        {canEdit && current && !term && <><h3>Registrar anexo o prórroga</h3><form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(async () => {
          await input("/labor/contracts/" + current.id + "/amendments", { ...amendment, new_end_date: amendment.new_end_date || null });
          setAmendment({ amendment_date: today(), new_end_date: "", reference: "", notes: "" });
        }); }}><label>Fecha del anexo<input type="date" required value={amendment.amendment_date} onChange={(e) => setAmendment((v) => ({ ...v, amendment_date: e.target.value }))} /></label>
          <label>Nueva fecha pactada<input type="date" value={amendment.new_end_date} onChange={(e) => setAmendment((v) => ({ ...v, new_end_date: e.target.value }))} /></label>
          <label>Referencia<input required value={amendment.reference} onChange={(e) => setAmendment((v) => ({ ...v, reference: e.target.value }))} /></label>
          <label>Observaciones<input value={amendment.notes} onChange={(e) => setAmendment((v) => ({ ...v, notes: e.target.value }))} /></label><button disabled={busy}>Guardar anexo</button></form></>}
        {canEdit && current && !term && <><h3>Corregir contrato vigente</h3><form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(async () => {
          await input("/labor/contracts/" + current.id, { ...contractEdit, end_date: contractEdit.end_date || null }, "PATCH");
        }); }}><label>Tipo<select value={contractEdit.contract_type} onChange={(e) => setContractEdit((v) => ({ ...v, contract_type: e.target.value }))}>{Object.entries(types).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>Término pactado<input type="date" value={contractEdit.end_date} onChange={(e) => setContractEdit((v) => ({ ...v, end_date: e.target.value }))} /></label>
          <label>Estado<select value={contractEdit.status} onChange={(e) => setContractEdit((v) => ({ ...v, status: e.target.value }))}><option value="active">Vigente</option><option value="suspended">Suspendido</option></select></label>
          <label>Observaciones<input value={contractEdit.notes} onChange={(e) => setContractEdit((v) => ({ ...v, notes: e.target.value }))} /></label>
          <button disabled={busy}>Guardar corrección</button></form></>}
        {canEdit && (term || !current) && <><h3>Nuevo contrato para esta persona</h3><form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(createContract); }}><ContractFields value={contractDraft} onChange={setContractDraft} types={types} />
          <label>Contrato PDF<input type="file" accept="application/pdf,.pdf" onChange={(e) => setContractFile(e.target.files?.[0] || null)} /></label><button disabled={busy}>Guardar nuevo contrato</button></form></>}
      </div>}
      {tab === "finiquito" && <div>
        {!term && <p>{current?.status === "ended" ? "Término histórico sin registro de finiquito: revisar." : "La relación laboral sigue vigente. El finiquito no aplica hasta registrar un término efectivo."}</p>}
        {!term && current && canEdit && <form className="worker-form" onSubmit={(e) => { e.preventDefault(); void act(submitTermination); }}>
          <label>Fecha efectiva de término<input type="date" required value={termDraft.effective_date} onChange={(e) => setTermDraft((v) => ({ ...v, effective_date: e.target.value }))} /></label>
          <label>Causal legal<select required value={termDraft.cause} onChange={(e) => setTermDraft((v) => ({ ...v, cause: e.target.value }))}><option value="">Seleccionar causal</option>{Object.entries(catalogs?.termination_causes || {}).map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select></label>
          <label>Modalidad de ratificación<select value={termDraft.ratification_mode} onChange={(e) => setTermDraft((v) => ({ ...v, ratification_mode: e.target.value }))}><option value="unrecorded">Sin registrar</option><option value="electronic">Electrónica</option><option value="notary">Notaría</option><option value="labor_inspection">Inspección del Trabajo</option><option value="other">Otra</option></select></label>
          <label>Observación<input value={termDraft.observation} onChange={(e) => setTermDraft((v) => ({ ...v, observation: e.target.value }))} /></label><button disabled={busy}>Registrar término efectivo</button></form>}
        {term && <div className="worker-record"><p><b>Causal:</b> {catalogs?.termination_causes[term.cause] || term.cause} · <b>Fecha efectiva:</b> {date(term.effective_date)}</p><p><b>Modalidad:</b> {term.ratification_mode} · <b>Emisión:</b> {date(term.issued_at)} · <b>Firma:</b> {date(term.signed_at)}</p>
          <p><b>Revisión:</b> {stateLabel[term.review_state]} {term.observation && " · " + term.observation}</p>
          {term.document_id && <a href={api.pdf(term.document_id)} target="_blank" rel="noreferrer">Ver finiquito PDF</a>}
          {canReview && <><div className="worker-form"><label>Subir o reemplazar finiquito PDF<input type="file" accept="application/pdf,.pdf" onChange={(e) => setFiniquitoFile(e.target.files?.[0] || null)} /></label>
            <label>Fecha de emisión<input type="date" value={finiquitoDates.issued_at} onChange={(e) => setFiniquitoDates((v) => ({ ...v, issued_at: e.target.value }))} /></label>
            <label>Fecha de firma o ratificación<input type="date" value={finiquitoDates.signed_at} onChange={(e) => setFiniquitoDates((v) => ({ ...v, signed_at: e.target.value }))} /></label>
            <button disabled={!finiquitoFile || busy} onClick={() => void act(uploadFiniquito)}>Entregar para revisión</button></div>
          {term.document_id && <div className="worker-form"><label>Motivo de revisión<input value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} /></label><button disabled={busy} onClick={() => void act(() => review("approved"))}>Aprobar</button><button disabled={busy || !reviewNote.trim()} onClick={() => void act(() => review("observed"))}>Observar</button><button disabled={busy || !reviewNote.trim()} onClick={() => void act(() => review("rejected"))}>Rechazar</button></div>}</>}
        </div>}
      </div>}
      {tab === "documents" && <div><p>Requisitos individuales del período {period}; una entrega requiere revisión humana.</p>
        {docRows.map((r) => <div className="worker-record" key={r.requirement}><b>{r.requirement}</b> · {stateLabel[r.delivery_state] || r.delivery_state}
          {r.document_id && <> · <a href={api.pdf(r.document_id)} target="_blank" rel="noreferrer">Ver PDF</a></>}
          {canReview && <div className="worker-form"><label>PDF<input type="file" accept="application/pdf,.pdf" onChange={(e) => setDocFile(e.target.files?.[0] || null)} /></label><label>Observación<input value={docNote} onChange={(e) => setDocNote(e.target.value)} /></label>
            <button disabled={busy || !docFile} onClick={() => void act(() => reviewDocument(r, "pending"))}>Registrar entrega</button>
            <button disabled={busy || !r.document_id} onClick={() => void act(() => reviewDocument(r, "approved"))}>Aprobar</button>
            <button disabled={busy || !docNote.trim()} onClick={() => void act(() => reviewDocument(r, "observed"))}>Observar</button></div>}</div>)}
        {!docRows.length && <p className="empty">Sin requisitos individuales exigibles para esta clasificación y período.</p>}
      </div>}
      {tab === "history" && <div className="v15-worker-history" aria-label="Historial de movimientos laborales">
        {detail.history.map(h=><article className="worker-record v15-worker-audit" key={h.id}>
          <div className="v15-worker-audit-head"><strong>{auditEntityLabel[h.entity_type]||"Movimiento laboral"}</strong>
            <time>{new Date(h.created_at).toLocaleString("es-CL",{timeZone:"America/Santiago"})}</time></div>
          <span>Responsable: {h.actor_name||"Sin nombre registrado"}</span>
          <p>{readableAudit(h.changes)}</p>
        </article>)}
        {!detail.history.length&&<p className="empty">Sin cambios registrados.</p>}
      </div>}
    </section>}
  </div>;
}

function ContractFields({ value, onChange, types }: { value: typeof blankContract; onChange: (value: typeof blankContract) => void; types: Record<string, string> }) {
  return <><label>Tipo de contrato<select required value={value.contract_type} onChange={(e) => onChange({ ...value, contract_type: e.target.value })}>{Object.entries(types).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
    <label>Fecha de ingreso<input type="date" required value={value.start_date} onChange={(e) => onChange({ ...value, start_date: e.target.value })} /></label>
    <label>Fecha de término pactada<input type="date" required={value.contract_type === "fixed_term"} value={value.end_date} onChange={(e) => onChange({ ...value, end_date: e.target.value })} /></label>
    <label>Estado<select value={value.status} onChange={(e) => onChange({ ...value, status: e.target.value })}><option value="active">Vigente</option><option value="suspended">Suspendido</option></select></label>
    <label>Observaciones<input value={value.notes} onChange={(e) => onChange({ ...value, notes: e.target.value })} /></label></>;
}
