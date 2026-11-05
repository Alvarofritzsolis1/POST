import { useState } from "react";
import { ArrowLeft } from "lucide-react";
import type { Site } from "./opsApi";
import type { Contractor } from "./AdministrativeControlV92";
import WeeklyAttendanceV81 from "./WeeklyAttendanceV81";
import ContractEntry from "./ContractEntry";
import "./contractor-detail-v13.css";

type DetailTab = "attendance" | "staff" | "contracts" | "severance";
const date = (value: string | null | undefined) => value ? value.slice(0, 10).split("-").reverse().join("/") : "—";
const labels: Record<string,string> = {
  vigente:"Vigente", por_vencer:"Por vencer", vencido:"Vencido: revisar",
  terminado:"Terminado", por_verificar:"Por verificar",
  indefinite:"Indefinido", fixed_term:"Plazo fijo", project:"Obra o faena", services:"Servicios",
  approved:"Validado", delivered:"Recibido", pending:"En revisión", observed:"Observado",
  rejected:"Rechazado", missing:"Pendiente", not_applicable:"No aplica",
};
const tone = (value: string) => ["vigente","approved"].includes(value) ? "ok"
  : ["vencido","rejected","observed"].includes(value) ? "bad"
  : ["not_applicable","terminado"].includes(value) ? "muted" : "warn";
const todayChile = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "America/Santiago",year:"numeric",month:"2-digit",day:"2-digit",
}).format(new Date());

export default function ContractorDetailV13({
  contractor, period, siteId, sites, initialWeek, role, onBack, onSaved, onDirtyChange, loading,
}: {
  contractor: Contractor; period: string; siteId: string; sites: Site[]; initialWeek: number | null;
  role: "admin" | "administrative"; onBack: () => void; onSaved: () => void;
  onDirtyChange: (dirty: boolean) => void; loading: boolean;
}) {
  const [tab, setTab] = useState<DetailTab>("attendance");
  const [dirty, setDirty] = useState(false);
  const changeDirty = (value: boolean) => { setDirty(value); onDirtyChange(value); };
  const switchTab = (next: DetailTab) => {
    if (dirty && next !== tab &&
      !window.confirm("Hay cambios en asistencia sin guardar. ¿Salir de esta pestaña?")) return;
    changeDirty(false);
    setTab(next);
  };
  const staff = contractor.staff;
  const people = tab === "severance"
    ? staff.filter((row) => row.labor_state === "terminado" || (row.finiquito_state !== "not_applicable" && row.finiquito_state !== "approved"))
    : tab === "contracts" ? staff.filter((row) => !!row.contract_id) : staff;
  const requiredWeeks = contractor.attendance_applicable
    ? contractor.weeks.filter((row) => row.dates.length && row.dates[0] <= todayChile()
      && !["excluded","not_required"].includes(row.state)) : [];
  const reviewed = requiredWeeks.filter((row) => ["completed_on_time","completed_late"].includes(row.state)).length;
  const metrics: [string, number | string, string][] = [
    ["Dotación vigente", contractor.staff_counts.vigente + contractor.staff_counts.por_vencer, "normal"],
    ["Por verificar", contractor.staff_counts.por_verificar, "warn"],
    ["Semanas revisadas", requiredWeeks.length ? reviewed + " / " + requiredWeeks.length : "No exigible", "normal"],
    ["Semanas pendientes", requiredWeeks.length - reviewed, requiredWeeks.length - reviewed ? "warn" : "ok"],
    ["Contratos por vencer", contractor.staff_counts.por_vencer, contractor.staff_counts.por_vencer ? "warn" : "ok"],
    ["Finiquitos pendientes", contractor.pending_finiquitos, contractor.overdue_finiquitos ? "bad" : "normal"],
  ];
  return <section className="av13-detail" aria-label={"Detalle de " + contractor.contractor}>
    <header className="av13-detail-header">
      <button type="button" onClick={onBack} className="av13-back">
        <ArrowLeft aria-hidden="true" size={19} /> Volver a contratistas
      </button>
      <div className="av13-identification">
        <div>
          <p className="av13-eyebrow">Control de asistencia · {sites.find((item) => item.id === siteId)?.name || "Obra asignada"} · {period}</p>
          <h2>{contractor.contractor}</h2>
          <p>{contractor.rut || "RUT pendiente"} · {contractor.classification ? "COD " + contractor.classification + " · " : ""}{contractor.contractor_active ? "Activo" : "Histórico"}</p>
        </div>
        <span className={"av92-badge " + (contractor.contractor_active ? "ok" : "muted")}>
          {contractor.contractor_active ? "Activo" : "Histórico"}
        </span>
      </div>
    </header>
    {loading && <p role="status" className="av92-muted">Actualizando los datos del contratista…</p>}
    <div className="av13-metrics" aria-label="Indicadores del contratista">
      {metrics.map(([label, value, severity]) => <div className={"av13-metric " + severity} key={label}>
        <span>{label}</span><strong>{value}</strong>
      </div>)}
    </div>
    <nav className="av13-tabs" aria-label="Apartados de este contratista">
      {([["attendance","Asistencia"],["staff","Trabajadores"],["contracts","Contratos"],["severance","Finiquitos"]] as const)
        .map(([key,label]) => <button type="button" key={key}
          aria-current={tab === key ? "page" : undefined}
          className={tab === key ? "current" : ""} onClick={() => switchTab(key)}>{label}</button>)}
    </nav>
    {tab === "attendance" && <WeeklyAttendanceV81
      siteId={siteId} sites={sites} period={period} canEdit={true}
      canReview={role === "admin"} selectedAssociationId={contractor.association_id}
      preferredWeekNumber={initialWeek} onSaved={() => { changeDirty(false); onSaved(); }}
      onDirtyChange={changeDirty} />}
    {tab !== "attendance" && <section className="av13-workers">
      <div className="av92-section-head"><div>
        <h3>{tab === "staff" ? "Trabajadores del contratista" : tab === "contracts" ? "Contratos laborales" : "Finiquitos y términos"}</h3>
        <p>Solo datos del contratista seleccionado. Los registros sin respaldo permanecen por verificar.</p>
      </div></div>
      <div className="av13-table-container"><table className="av92-table">
        <thead><tr><th>Trabajador</th><th>Contrato / inicio</th><th>Término</th><th>Situación</th><th>Finiquito</th></tr></thead>
        <tbody>{people.map((person) => <tr key={person.assignment_id}>
          <td><strong>{person.name}</strong><small>{person.rut || "RUT pendiente"}</small></td>
          <td>{labels[person.contract_type || ""] || "Por verificar"}<small>{date(person.start_date)}</small></td>
          <td>{date(person.labor_state === "terminado" ? person.termination_date : person.end_date)}</td>
          <td><span className={"av92-badge " + tone(person.labor_state)}>{labels[person.labor_state] || "Por verificar"}</span></td>
          <td><span className={"av92-badge " + (person.finiquito_overdue ? "bad" : tone(person.finiquito_state))}>
            {labels[person.finiquito_state] || "Por revisar"}</span></td>
        </tr>)}</tbody>
      </table>{!people.length && <p className="av92-empty">No existen registros para esta sección del contratista.</p>}</div>
      {tab === "contracts" && <details className="av92-register">
        <summary>Registrar nuevo contrato de trabajo</summary>
        <ContractEntry siteId={siteId} period={period} associationId={contractor.association_id}
          contractorName={contractor.contractor} onSaved={onSaved} />
      </details>}
      {tab === "severance" && <p className="av92-notice">
        Los finiquitos se validan en el módulo documental autorizado. Esta pantalla muestra su estado actual.
      </p>}
    </section>}
  </section>;
}
