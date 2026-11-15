import { useMemo, useState } from "react";

type Status = "active" | "suspended" | "offboarding" | "inactive";
type Classification = "CT" | "CI" | "ESP";
type CatalogData = {
  status_mapping: Record<string, Status>;
  classification_mapping: Record<string, Classification>;
  expiry_alert_days: number[];
  attendance_due_days: number;
  termination_due_days: number | null;
  termination_causes: Record<string, string>;
  extra_contract_types: Record<string, string>;
};
const states: { value: Status; label: string }[] = [
  { value: "active", label: "Activo" },
  { value: "suspended", label: "Suspendido" },
  { value: "offboarding", label: "En salida" },
  { value: "inactive", label: "Inactivo" },
];
const classes: { value: Classification; label: string }[] = [
  { value: "CT", label: "CT · Contratista" },
  { value: "CI", label: "CI · Independiente" },
  { value: "ESP", label: "ESP · Esporádico" },
];

export default function CatalogEditor({ json, onChange }: { json: string; onChange: (value: string) => void }) {
  const [statusName, setStatusName] = useState("");
  const [statusValue, setStatusValue] = useState<Status>("active");
  const [className, setClassName] = useState("");
  const [classValue, setClassValue] = useState<Classification>("CT");
  const [error, setError] = useState("");
  const data = useMemo<CatalogData | null>(() => {
    try { return json ? JSON.parse(json) as CatalogData : null; }
    catch { return null; }
  }, [json]);

  if (!data) return <p role="status">Cargando reglas de la organización…</p>;

  function change(next: CatalogData) {
    setError("");
    onChange(JSON.stringify(next, null, 2));
  }
  function add(kind: "status_mapping" | "classification_mapping") {
    const key = (kind === "status_mapping" ? statusName : className).trim().toUpperCase();
    if (!key) { setError("Escribe primero el valor recibido."); return; }
    if (Object.prototype.hasOwnProperty.call(data[kind], key)) {
      setError("Ese valor ya está registrado. Edita su interpretación en la lista.");
      return;
    }
    if (kind === "status_mapping") {
      change({ ...data, status_mapping: { ...data.status_mapping, [key]: statusValue } });
      setStatusName("");
    } else {
      change({ ...data, classification_mapping: { ...data.classification_mapping, [key]: classValue } });
      setClassName("");
    }
  }
  function remove(kind: "status_mapping" | "classification_mapping", key: string) {
    if (kind === "status_mapping") {
      if (Object.keys(data.status_mapping).length <= 1) {
        setError("Debe existir al menos una interpretación de estado."); return;
      }
      const copy = { ...data.status_mapping };
      delete copy[key];
      change({ ...data, status_mapping: copy });
    } else {
      const copy = { ...data.classification_mapping };
      delete copy[key];
      change({ ...data, classification_mapping: copy });
    }
  }

  return <div className="settings-catalog-editor">
    <h3>Estados importados</h3>
    <p>Asocia el texto recibido desde Excel con el estado utilizado por GALANT.</p>
    <div className="settings-mappings">
      {Object.entries(data.status_mapping).map(([source, target]) => <div className="settings-mapping" key={source}>
        <strong>{source}</strong>
        <select aria-label={"Interpretación de " + source} value={target} onChange={e => change({ ...data, status_mapping: { ...data.status_mapping, [source]: e.target.value as Status } })}>
          {states.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <button type="button" aria-label={"Quitar " + source} onClick={() => remove("status_mapping", source)}>Quitar</button>
      </div>)}
    </div>
    <div className="settings-mapping-add">
      <input aria-label="Nuevo estado recibido" placeholder="Nuevo estado recibido" value={statusName} onChange={e => setStatusName(e.target.value)} />
      <select aria-label="Interpretación del nuevo estado" value={statusValue} onChange={e => setStatusValue(e.target.value as Status)}>
        {states.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>
      <button type="button" onClick={() => add("status_mapping")}>Agregar</button>
    </div>
    <details className="settings-details">
      <summary>Clasificaciones de contratistas</summary>
      <p>CT, CI y ESP son categorías de contratistas. No son los códigos de trabajador TH, TM y F.</p>
      <div className="settings-mappings">
        {Object.entries(data.classification_mapping).map(([source, target]) => <div className="settings-mapping" key={source}>
          <strong>{source}</strong>
          <select aria-label={"Clasificación de " + source} value={target} onChange={e => change({ ...data, classification_mapping: { ...data.classification_mapping, [source]: e.target.value as Classification } })}>
            {classes.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <button type="button" aria-label={"Quitar " + source} onClick={() => remove("classification_mapping", source)}>Quitar</button>
        </div>)}
      </div>
      <div className="settings-mapping-add">
        <input aria-label="Nueva clasificación recibida" placeholder="Nueva clasificación" value={className} onChange={e => setClassName(e.target.value)} />
        <select aria-label="Interpretación de nueva clasificación" value={classValue} onChange={e => setClassValue(e.target.value as Classification)}>
          {classes.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
        <button type="button" onClick={() => add("classification_mapping")}>Agregar</button>
      </div>
    </details>
    <details className="settings-details">
      <summary>Plazos y alertas</summary>
      <p>Configura entre uno y cinco avisos distintos, de 1 a 365 días.</p>
      <div className="settings-alert-days">
        {data.expiry_alert_days.map((days, i) => <label key={i}>Aviso {i + 1}
          <span><input aria-label={"Días del aviso " + (i + 1)} type="number" required min={1} max={365} value={days} onChange={e => change({ ...data, expiry_alert_days: data.expiry_alert_days.map((d, j) => j === i ? Number(e.target.value) : d) })} />
          <button type="button" disabled={data.expiry_alert_days.length <= 1} onClick={() => change({ ...data, expiry_alert_days: data.expiry_alert_days.filter((_, j) => j !== i) })}>Quitar</button></span>
        </label>)}
        {data.expiry_alert_days.length < 5 && <button type="button" onClick={() => change({ ...data, expiry_alert_days: [...data.expiry_alert_days, 1] })}>Agregar aviso</button>}
      </div>
      <label>Plazo de asistencia (días, 0–14)
        <input type="number" min={0} max={14} required value={data.attendance_due_days} onChange={e => change({ ...data, attendance_due_days: Number(e.target.value) })} />
      </label>
      <label>Plazo para término de contrato (opcional, 0–365)
        <input type="number" min={0} max={365} value={data.termination_due_days ?? ""} onChange={e => change({ ...data, termination_due_days: e.target.value === "" ? null : Number(e.target.value) })} />
      </label>
    </details>
    <p className="settings-catalog-hint">Las causales legales y tipos de contrato ya registrados se conservan sin cambios. Pulsa «Guardar reglas» para aplicar los ajustes.</p>
    {error && <p role="alert" className="form-error">{error}</p>}
  </div>;
}
