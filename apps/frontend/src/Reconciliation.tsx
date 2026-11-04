import { useState } from "react";
import { read, send } from "./platformApi";

type Row = { contractor_id: string; association_id: string | null; name: string; rut: string | null;
  site: string | null; category: string; current: { nature: string; frequency: string; contract_status: string; historical_code: string };
  changes: Record<string, { from: string; to: string }>;
  evidence: Record<string, { value: string; source: string; event_id?: string }[]>;
  conflicts: string[]; warnings: string[] };
type Preview = { records: Row[]; summary: Record<string, number>; token: string };
type Backup = { id: string; sha256: string; created_at: string };
const labels: Record<string, string> = { recoverable: "Recuperable", unchanged: "Sin cambios", unresolved: "Sin evidencia", conflict: "Conflicto" };
export default function Reconciliation() {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [backup, setBackup] = useState("");
  const [manual, setManual] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState("");
  async function load() {
    setBusy(true); setError(""); setResult("");
    try {
      const [p, b] = await Promise.all([read<Preview>("/admin/reconciliation/preview"),
                                       read<Backup[]>("/admin/reconciliation/backups")]);
      setPreview(p); setBackups(b); setBackup(b[0]?.id || ""); setManual({});
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function apply() {
    if (!preview || !backup || !window.confirm("¿Confirmas las correcciones mostradas usando el respaldo verificado seleccionado?")) return;
    setBusy(true); setError(""); setResult("");
    try {
      const corrections = Object.entries(manual).map(([association_id, fields]) => ({ association_id, ...fields }));
      const response = await send<{ corrected: number; unresolved: number; conflicts: number }>(
        "/admin/reconciliation/commit", { token: preview.token, backup_id: backup, corrections });
      setResult(`${response.corrected} relaciones corregidas; ${response.unresolved} sin evidencia y ${response.conflicts} con conflictos en la vista previa.`);
      setPreview(null);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  function change(id: string, field: string, value: string) {
    setManual((old) => { const next = { ...(old[id] || {}) }; if (value) next[field] = value; else delete next[field];
      const all = { ...old }; if (Object.keys(next).length) all[id] = next; else delete all[id]; return all; });
  }
  return <section className="panel">
    <h2>Recuperación de clasificaciones históricas</h2>
    <p>Compara valores actuales con fuentes de importación y cambios explícitos. Los casos sin evidencia no se completan automáticamente. Los nombres numéricos y RUT duplicados requieren revisión de identidad.</p>
    <button disabled={busy} onClick={() => void load()}>Generar vista previa</button>
    {error && <p role="alert" className="form-error">{error}</p>}
    {result && <p role="status">{result}</p>}
    {preview && <>
      <p>{Object.entries(preview.summary).map(([key, value]) => `${labels[key] || key}: ${value}`).join(" · ")}</p>
      <label>Respaldo de PostgreSQL y documentos con restauración verificada
        <select value={backup} onChange={(e) => setBackup(e.target.value)}><option value="">Seleccionar respaldo</option>
          {backups.map((b) => <option key={b.id} value={b.id}>{new Date(b.created_at).toLocaleString("es-CL")} · SHA256 {b.sha256.slice(0, 12)}</option>)}
        </select>
      </label>
      {!backup && <p>El administrador del VPS debe generar y verificar un respaldo, y registrar su SHA256 antes de corregir datos.</p>}
      <div className="table-wrap"><table><thead><tr><th>Contratista / RUT</th><th>Obra</th><th>Situación</th><th>Actual → propuesto</th><th>Confirmación manual</th></tr></thead>
        <tbody>{preview.records.map((row, index) => <tr key={row.association_id || row.contractor_id + index}>
          <td><b>{row.name}</b><br />{row.rut || "Sin RUT"}</td><td>{row.site || "Sin obra"}</td>
          <td>{labels[row.category] || row.category}{row.conflicts.map((v) => <p className="form-error" key={v}>{v}</p>)}{row.warnings.map((v) => <p key={v}>{v}</p>)}</td>
          <td>Naturaleza: {row.current.nature} → {row.changes.nature?.to || "—"}<br />Frecuencia: {row.current.frequency} → {row.changes.frequency?.to || "—"}<br />COD: {row.current.historical_code || "—"}<br />{Object.entries(row.evidence).map(([key, values]) => <small key={key}>{key}: {values.map((v) => `${v.value} (${v.source})`).join(", ")}<br /></small>)}</td>
          <td>{row.association_id && <div className="worker-form">
            <label>Naturaleza<select value={manual[row.association_id]?.nature || ""} onChange={(e) => change(row.association_id!, "nature", e.target.value)}><option value="">Conservar/propuesta</option><option value="with_workers">Con trabajadores</option><option value="independent">Independiente</option></select></label>
            <label>Frecuencia<select value={manual[row.association_id]?.frequency || ""} onChange={(e) => change(row.association_id!, "frequency", e.target.value)}><option value="">Conservar/propuesta</option><option value="fixed">Fijo</option><option value="sporadic">Esporádico</option></select></label>
            <label>Estado<select value={manual[row.association_id]?.contract_status || ""} onChange={(e) => change(row.association_id!, "contract_status", e.target.value)}><option value="">Conservar</option><option value="active">Activo</option><option value="suspended">Suspendido</option><option value="inactive">Dado de baja</option></select></label>
          </div>}</td>
        </tr>)}</tbody></table></div>
      <button className="primary" disabled={busy || !backup} onClick={() => void apply()}>Aplicar cambios verificados y correcciones manuales</button>
    </>}
  </section>;
}
