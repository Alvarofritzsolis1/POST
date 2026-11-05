import { useCallback, useEffect, useState } from "react";
import { read, send } from "./platformApi";
import "./contract-alerts.css";

type Code = "TH" | "TM" | "F";
type ContractRow = {
  assignment_id: string;
  site_id: string;
  site: string;
  contractor: string;
  worker: string;
  rut: string | null;
  worker_code: string;
  contract_type: string | null;
  start_date: string | null;
  end_date: string | null;
  days_remaining: number | null;
  state: string;
};
type Payload = { as_of: string; total: number; summary: Record<string, number>; rows: ContractRow[] };
const stateNames: Record<string, string> = {
  expired: "Vencido · revisar", urgent: "Urgente (0–7 días)",
  attention: "Atención (8–15 días)", soon: "Próximo (16–30 días)",
  active: "Vigente (+30 días)", indefinite: "Indefinido",
  inactive: "Inactivo / F", unverified: "Por verificar",
};
const codeNames: Record<Code, string> = {
  TH: "TH · Trabajador hombre",
  TM: "TM · Trabajadora mujer",
  F: "F · Finiquitado (inactivo)",
};
const displayDate = (date: string | null) => date ? date.slice(0, 10).split("-").reverse().join("-") : "INDEFINIDO";
const label = (row: ContractRow) => row.state === "indefinite" ? "Sin vencimiento" :
  row.days_remaining === null ? "—" : row.days_remaining < 0
    ? `Venció hace ${Math.abs(row.days_remaining)} días` : `${row.days_remaining} días`;

export default function ContractAlerts({siteId = "", onOpenWorker}: {
  siteId?: string;
  onOpenWorker?: (assignmentId: string) => void;
}) {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const fetchRows = useCallback(async () => {
    const query = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
    const result = await read<Payload>("/labor/contract-alerts" + query);
    setData(result);
  }, [siteId]);
  useEffect(() => {
    let alive = true;
    const update = async () => {
      try {
        const result = await read<Payload>(
          "/labor/contract-alerts" + (siteId ? `?site_id=${encodeURIComponent(siteId)}` : ""),
        );
        if (alive) { setData(result); setError(""); }
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause));
      }
    };
    void update();
    const refresh = () => { if (!document.hidden) void update(); };
    window.addEventListener("galant-changed", refresh);
    return () => { alive = false; window.removeEventListener("galant-changed", refresh); };
  }, [siteId]);

  async function changeCode(row: ContractRow, worker_code: Code) {
    if (worker_code === row.worker_code) return;
    if (worker_code === "F" && !window.confirm(
      "¿Marcar a este trabajador como F (inactivo)? Esto no aprobará un finiquito ni eliminará su historial.",
    )) return;
    setBusy(row.assignment_id); setError(""); setNotice("");
    try {
      await send("/labor/workers/" + encodeURIComponent(row.assignment_id) + "/code",
        {worker_code}, "PATCH");
      await fetchRows();
      setNotice("COD actualizado. Se registró la modificación en la trazabilidad.");
      window.dispatchEvent(new Event("galant-changed"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy("");
    }
  }

  const rows = (data?.rows || []).filter(row =>
    (filter === "all" || (filter === "pending" ? ["expired", "urgent", "attention", "soon"].includes(row.state) : row.state === filter)) &&
    (row.worker + " " + row.rut + " " + row.contractor + " " + row.site)
      .toLocaleLowerCase("es-CL").includes(search.toLocaleLowerCase("es-CL")),
  );
  const urgent = (data?.summary.expired || 0) + (data?.summary.urgent || 0);
  const nearing = (data?.summary.attention || 0) + (data?.summary.soon || 0);

  return <section className="ca-root panel" aria-labelledby="contract-alerts-title">
    <div className="ca-heading">
      <div><h2 id="contract-alerts-title">Alertas contractuales</h2>
        <p>Contratos por obra, próximos vencimientos y códigos TH / TM / F.
          Los estados se calculan con fecha actual, sin cambiar los contratos históricos.</p></div>
      <button type="button" className="secondary" onClick={() => void fetchRows().catch(
        cause => setError(cause instanceof Error ? cause.message : String(cause)),
      )}>Actualizar</button>
    </div>
    <div className="ca-metrics">
      <button type="button" onClick={() => setFilter("pending")}>
        <span>Urgentes / vencidos</span><strong>{urgent}</strong></button>
      <button type="button" onClick={() => setFilter("pending")}>
        <span>Por vencer (8–30 días)</span><strong>{nearing}</strong></button>
      <button type="button" onClick={() => setFilter("indefinite")}>
        <span>Indefinidos</span><strong>{data?.summary.indefinite ?? "—"}</strong></button>
      <button type="button" onClick={() => setFilter("inactive")}>
        <span>Inactivos / F</span><strong>{data?.summary.inactive ?? "—"}</strong></button>
    </div>
    <div className="ca-filters">
      <label>Buscar<input type="search" value={search} onChange={e => setSearch(e.target.value)}
        placeholder="Trabajador, RUT, contratista u obra" /></label>
      <label>Estado<select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">Todos los contratos</option>
        <option value="pending">Alertas de vencimiento</option>
        <option value="expired">Vencidos</option>
        <option value="urgent">Urgentes</option>
        <option value="attention">Atención</option>
        <option value="soon">Próximos</option>
        <option value="indefinite">Indefinidos</option>
        <option value="inactive">Inactivos</option>
        <option value="unverified">Por verificar</option>
      </select></label>
    </div>
    {error && <p className="alert danger" role="alert">{error}</p>}
    {notice && <p className="alert success" role="status">{notice}</p>}
    {!data && !error && <p role="status">Consultando contratos…</p>}
    <div className="ca-table-scroll">
      <table className="ca-table">
        <thead><tr>
          <th>Obra</th><th>Contratista</th><th>Trabajador</th><th>COD editable</th>
          <th>Vencimiento</th><th>Días</th><th>Estado</th><th>Acción</th>
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.assignment_id}>
          <td>{row.site}</td><td>{row.contractor}</td>
          <td><strong>{row.worker}</strong><small>{row.rut || "RUT pendiente"}</small></td>
          <td><select aria-label={`COD de ${row.worker}`} value={row.worker_code || ""}
              disabled={busy === row.assignment_id}
              onChange={e => void changeCode(row, e.target.value as Code)}>
              <option value="" disabled>Sin clasificar</option>
              {(Object.keys(codeNames) as Code[]).map(code =>
                <option key={code} value={code}>{codeNames[code]}</option>)}
            </select></td>
          <td>{row.end_date ? displayDate(row.end_date) : "INDEFINIDO"}</td>
          <td>{label(row)}</td>
          <td><span className={"ca-state ca-" + row.state}>{stateNames[row.state] || "Por verificar"}</span></td>
          <td>{onOpenWorker ? <button type="button" className="secondary"
            onClick={() => onOpenWorker(row.assignment_id)}>Ver ficha</button> : "—"}</td>
        </tr>)}</tbody>
      </table>
      {data && !rows.length && <p className="ca-empty">No hay trabajadores para estos filtros.</p>}
    </div>
    <p className="ca-footnote">El código F desactiva la dotación operativa, pero no sustituye el finiquito firmado.
      Para reactivar un código TH/TM debe existir un contrato vigente sin término efectivo registrado.</p>
  </section>;
}
