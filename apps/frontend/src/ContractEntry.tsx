import { useEffect, useState, type FormEvent } from "react";
import { request } from "./api";
import "./administrative.css";

type Person = { assignment_id: string; name: string; rut: string | null };
type Company = { association_id: string; contractor_id: string; contractor: string; active: boolean };
type Roster = { contractors: { workers: Person[] }[] };
type ContractType = "indefinite" | "fixed_term" | "project";
const errorText = (value: unknown) => value instanceof Error ? value.message : String(value);

export default function ContractEntry({ siteId, period }: { siteId: string; period: string }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companySearch, setCompanySearch] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [workers, setWorkers] = useState<Person[]>([]);
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [assignmentId, setAssignmentId] = useState("");
  const [name, setName] = useState("");
  const [rut, setRut] = useState("");
  const [kind, setKind] = useState<ContractType>("fixed_term");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setCompanies([]); setCompanyId(""); setCompanySearch(""); setAssignmentId(""); setWorkers([]);
  }, [siteId, period]);
  useEffect(() => {
    if (!companySearch.trim() || !siteId) { setCompanies([]); return; }
    let active = true;
    const timer = window.setTimeout(() => {
      void request<{ items: Company[] }>(`/attendance-v81/contractors?site_id=${encodeURIComponent(siteId)}&q=${encodeURIComponent(companySearch.trim())}`)
        .then((data) => { if (active) { setCompanies(data.items); setError(""); } })
        .catch((cause) => { if (active) setError(errorText(cause)); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [siteId, companySearch, revision]);
  useEffect(() => {
    if (!companyId || !siteId) { setWorkers([]); return; }
    let active = true;
    void request<Roster>(`/attendance-v81/roster?site_id=${encodeURIComponent(siteId)}&period=${encodeURIComponent(period)}&association_id=${encodeURIComponent(companyId)}`)
      .then((data) => { if (active) setWorkers(data.contractors[0]?.workers || []); })
      .catch((cause) => { if (active) setError(errorText(cause)); });
    return () => { active = false; };
  }, [siteId, period, companyId, revision]);
  const company = companies.find((row) => row.association_id === companyId);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(""); setNotice("");
    if (!company) { setError("Selecciona un contratista."); return; }
    if (kind === "fixed_term" && !endDate) { setError("El contrato a plazo fijo requiere una fecha de término."); return; }
    if (endDate && endDate < startDate) { setError("El término no puede ser anterior al inicio."); return; }
    if (mode === "existing" && !assignmentId) { setError("Selecciona un trabajador existente."); return; }
    setBusy(true);
    try {
      const contract = { contract_type: kind, start_date: startDate, end_date: endDate || null,
        notes, status: "active", document_id: null };
      if (mode === "new") {
        await request("/labor/workers", { method: "POST",
          body: JSON.stringify({ site_id: siteId, contractor_id: company.contractor_id,
            name: name.trim(), rut: rut.trim(), contract }) });
      } else {
        await request("/labor/contracts", { method: "POST",
          body: JSON.stringify({ ...contract, assignment_id: assignmentId }) });
      }
      setNotice("Contrato registrado correctamente. Se conservó la trazabilidad de la operación.");
      setName(""); setRut(""); setAssignmentId(""); setStartDate(""); setEndDate(""); setNotes("");
      setRevision((value) => value + 1);
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section className="panel administrative-contracts">
    <div><h2>Nuevo contrato de trabajo</h2><p>Registra los datos del contrato sin adjuntar documentos.</p></div>
    <form onSubmit={(event) => void save(event)}>
      <label>Buscar contratista por nombre o RUT
        <input value={companySearch} onChange={(event) => setCompanySearch(event.target.value)}
          placeholder="Escribe el nombre o RUT" autoComplete="off" />
      </label>
      <label>Contratista <select required value={companyId} onChange={(event) => { setCompanyId(event.target.value); setAssignmentId(""); }}>
        <option value="">Seleccionar contratista</option>
        {companies.filter((row) => row.active).map((row) =>
          <option key={row.association_id} value={row.association_id}>{row.contractor}</option>)}
      </select></label>
      <fieldset><legend>Trabajador</legend>
        <div className="administrative-mode">
          <label><input type="radio" name="worker-mode" checked={mode === "new"} onChange={() => setMode("new")} /> Nuevo trabajador</label>
          <label><input type="radio" name="worker-mode" checked={mode === "existing"} onChange={() => setMode("existing")} /> Trabajador existente</label>
        </div>
        {mode === "new" ? <div className="administrative-form-grid">
          <label>Nombre completo <input required value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>RUT <input required value={rut} onChange={(event) => setRut(event.target.value)} placeholder="12.345.678-9" /></label>
        </div> : <label>Trabajador <select required value={assignmentId} onChange={(event) => setAssignmentId(event.target.value)}>
          <option value="">Seleccionar trabajador</option>
          {workers.map((person) => <option key={person.assignment_id} value={person.assignment_id}>{person.name} · {person.rut || "Sin RUT"}</option>)}
        </select></label>}
      </fieldset>
      <div className="administrative-form-grid">
        <label>Tipo de contrato <select value={kind} onChange={(event) => setKind(event.target.value as ContractType)}>
          <option value="fixed_term">Plazo fijo</option><option value="indefinite">Indefinido</option>
          <option value="project">Obra o faena</option>
        </select></label>
        <label>Fecha de inicio <input required type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
        {kind !== "indefinite" && <label>Fecha de término {kind === "fixed_term" ? "(obligatoria)" : "(si corresponde)"}
          <input required={kind === "fixed_term"} type="date" min={startDate || undefined} value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>}
      </div>
      <label>Observaciones (opcional) <textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      {error && <p role="alert" className="alert danger">{error}</p>}
      {notice && <p role="status" className="alert success">{notice}</p>}
      <button className="primary" type="submit" disabled={busy || !companyId}>{busy ? "Guardando…" : "Registrar contrato"}</button>
    </form>
  </section>;
}
