import { useEffect, useState } from "react";
import { request } from "./api";
import { send, download } from "./platformApi";
type Input = {
  kind: string;
  rows: Record<string, string>[];
  filename: string;
  file_sha256: string;
};
type Preview = {
  input: Input;
  token: string;
  summary: Record<string, number>;
  rows: {
    row: Record<string, string>;
    category: string;
    errors: string[];
    warnings: string[];
    changes: Record<string, { from: unknown; to: unknown }>;
  }[];
};
type Batch = { id: string; filename: string; kind: string; created_at: string; result: Record<string, number> };
const resultNames: Record<string,string> = {
  created:"Creados", updated:"Actualizados", skipped:"Omitidos",unchanged:"Sin cambios",
  contractors:"Contratistas", workers:"Trabajadores", associations:"Asignaciones",
  errors:"Errores", warnings:"Advertencias", imported:"Importados", linked:"Vinculados",
  created_contractors:"Contratistas creados", linked_contractors:"Contratistas vinculados",
  created_workers:"Trabajadores creados", assigned_workers:"Trabajadores asignados",
  historical_statuses_count:"Estados históricos conservados",
};
const resultSummary=(result:Record<string,unknown>)=>
  Object.entries(result).filter(([,value])=>typeof value==="number")
    .map(([key,value])=>(resultNames[key]||"Registros de "+key.replaceAll("_"," "))+": "+String(value)).join(" · ");
const importFieldNames:Record<string,string>={
 name:"Nombre",rut:"RUT",contractor_name:"Contratista",contractor_rut:"RUT contratista",
 worksite:"Obra",site:"Obra",site_id:"Obra",specialty:"Especialidad",
 historical_code:"Código",contract_status:"Estado",nature:"Naturaleza",
 frequency:"Frecuencia",phone:"Teléfono",email:"Correo",start_date:"Ingreso",
 end_date:"Término",legal_representative:"Representante legal",
};
const readableImportValue=(value:unknown)=>{
 if(value===null||value===undefined||value==="")return "Sin registrar";
 if(typeof value==="boolean")return value?"Sí":"No";
 if(typeof value==="string"&&/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value))return "Referencia interna";
 return typeof value==="string"||typeof value==="number"?String(value):"Dato actualizado";
};
const names: Record<string, string> = {
  new: "Nuevos / nuevas relaciones",
  existing: "Existentes",
  updatable: "Actualizables",
  error: "Con errores",
};
export default function BulkImport({
  readOnly,
  siteId,
}: {
  readOnly: boolean;
  siteId: string;
}) {
  const [kind, setKind] = useState("contractors"),
    [file, setFile] = useState<File | null>(null),
    [preview, setPreview] = useState<Preview | null>(null),
    [draft, setDraft] = useState<Input | null>(null),
    [mapping, setMapping] = useState("{}"),
    [approve, setApprove] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [page, setPage] = useState(0);
  const [history, setHistory] = useState<Batch[]>([]);
  useEffect(() => { void request<Batch[]>("/ops/imports/bulk/history").then(setHistory).catch(() => {}); }, []);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }
  async function load() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    form.append("column_map", mapping);
    form.append("default_site", siteId);
    const p = await request<Preview>("/ops/imports/bulk/preview", {
      method: "POST",
      body: form,
    });
    setPreview(p);
    setDraft(p.input);
    setApprove(false);
    setPage(0);
    setNotice("");
  }
  async function review() {
    if (!draft) return;
    const p = await send<Preview>("/ops/imports/bulk/review", draft);
    setPreview(p);
    setDraft(p.input);
    setApprove(false);
  }
  const dirty =
    !!preview && JSON.stringify(preview.input) !== JSON.stringify(draft);
  const currentStep=notice.startsWith("Importación guardada")?7:preview?(dirty?3:5):file?1:0;
  const stages=["Archivo","Encabezados","Validación","Duplicados","Resumen","Confirmación","Resultado"];
  return (
    <section className="panel">
      <h2>Importación masiva</h2>
      <ol className="v15-import-steps" aria-label="Etapas de importación">
        {stages.map((name,index)=><li key={name} className={currentStep>index+1?"done":currentStep===index+1?"current":""} aria-current={currentStep===index+1?"step":undefined}>
          <span>{index+1}</span>{name}
        </li>)}
      </ol>
      <p>
        Carga varias obras en un archivo. Revisa las observaciones y los cambios
        antes de confirmar.
      </p>
      <div className="toolbar">
        <label>
          Tipo de carga
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setMapping("{}");
              setPreview(null);
              setDraft(null);
              setNotice("");
            }}
          >
            <option value="contractors">Contratistas</option>
            <option value="workers">Trabajadores</option>
          </select>
        </label>
        <a
          className="secondary"
          href={"/api/v1/ops/imports/bulk/templates/" + kind}
        >
          Descargar plantilla Excel
        </a>
      </div>
      <p className="muted">
        Contratistas: solo 11 columnas (ID, OBRA, ESPECIALIDAD, NOMBRECONTRATISTA,
        RUT, COD, ESTADO, TELEFONO, CORREO, REPRESENTANTE LEGAL y RUTR.LEGAL).
        COD: CT fijo, CE esporádico, CI independiente. ESTADO: ACTIVO o INACTIVO.
        Reimporta para corregir registros existentes sin duplicarlos; los cambios
        necesitan confirmación. Trabajadores: selecciona la obra arriba y usa
        su plantilla independiente.
      </p>
      {!readOnly && (
        <>
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              setFile(e.dataTransfer.files[0] || null);
              setPreview(null);
              setNotice("");
            }}
          >
            <label>
              Arrastra tu Excel o selecciona un archivo
              <input
                type="file"
                accept=".xlsx,.csv"
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setPreview(null);
                  setNotice("");
                }}
              />
            </label>
            <strong>{file?.name}</strong>
          </div>
          {kind === "workers" && <details>
            <summary>Mapeo opcional de encabezados</summary>
            <p>
              Ejemplo:{" "}
              {'{"name":"Razón social","contractor_rut":"RUT empresa"}'}
            </p>
            <textarea
              aria-label="Mapeo de columnas"
              value={mapping}
              onChange={(e) => setMapping(e.target.value)}
            />
          </details>}
          <button
            className="primary"
            disabled={!file || busy}
            onClick={() => void run(load)}
          >
            Previsualizar archivo
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {busy && <p role="status">Procesando…</p>}
      {preview && draft && (
        <>
          <div className="kpi-grid">
            {Object.entries(preview.summary).map(([k, v]) => (
              <div className="kpi" key={k}>
                <small>{names[k]}</small>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          <p>
            Edita los campos y vuelve a validar. Para una obra inexistente, un
            administrador debe crearla desde Configuración.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fila</th>
                  <th>Resultado</th>
                  <th>Obra</th>
                  <th>Nombre</th>
                  <th>RUT</th>
                  {kind === "contractors" && <><th>COD</th><th>Estado</th></>}
                  {kind === "workers" && (
                    <>
                      <th>Contratista / RUT</th>
                      <th>Ingreso</th>
                      <th>Término</th>
                    </>
                  )}
                  <th>Observaciones y cambios</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.slice(page * 50, (page + 1) * 50).map((r, i) => {
                  const n = page * 50 + i;
                  return (
                    <tr key={n}>
                      <td>{r.row.row_id}</td>
                      <td>{names[r.category]}</td>
                      {[
                        "site",
                        "name",
                        "rut",
                        ...(kind === "workers"
                          ? ["contractor_name", "start_date", "end_date"]
                          : []),
                      ].map((key) => (
                        <td key={key}>
                          <input
                            aria-label={key + " fila " + (n + 1)}
                            value={draft.rows[n][key] || ""}
                            onChange={(e) =>
                              setDraft({
                                ...draft,
                                rows: draft.rows.map((v, j) =>
                                  j === n ? { ...v, [key]: e.target.value } : v,
                                ),
                              })
                            }
                          />
                          {key === "contractor_name" && (
                            <input
                              aria-label={"RUT contratista fila " + (n + 1)}
                              placeholder="RUT contratista opcional"
                              value={draft.rows[n].contractor_rut || ""}
                              onChange={(e) =>
                                setDraft({
                                  ...draft,
                                  rows: draft.rows.map((v, j) =>
                                    j === n
                                      ? { ...v, contractor_rut: e.target.value }
                                      : v,
                                  ),
                                })
                              }
                            />
                          )}
                        </td>
                      ))}
                      {kind === "contractors" && (["historical_code", "status"] as const).map((key) => (
                        <td key={key}>
                          <select
                            aria-label={(key === "historical_code" ? "COD" : "Estado") + " fila " + (n + 1)}
                            value={draft.rows[n][key] || ""}
                            onChange={(e) => setDraft({
                              ...draft,
                              rows: draft.rows.map((v, j) => j === n ? { ...v, [key]: e.target.value } : v),
                            })}
                          >
                            <option value="">Seleccionar</option>
                            {(key === "historical_code" ? ["CT", "CE", "CI"] : ["ACTIVO", "INACTIVO"]).map((value) => (
                              <option value={value} key={value}>{value}</option>
                            ))}
                          </select>
                        </td>
                      ))}
                      <td>
                        {r.errors.map((v) => (
                          <p className="form-error" key={v}>
                            ! {v}
                          </p>
                        ))}
                        {r.warnings.map((v) => (
                          <p key={v}>△ {v}</p>
                        ))}
                        {Object.entries(r.changes).map(([key, v]) => (
                          <p key={key}>
                            {importFieldNames[key]||"Dato de la importación"}: {readableImportValue(v.from)} → {readableImportValue(v.to)}
                          </p>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="toolbar">
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>
              Anterior
            </button>
            <span>
              Página {page + 1} de {Math.ceil(preview.rows.length / 50)}
            </span>
            <button
              disabled={(page + 1) * 50 >= preview.rows.length}
              onClick={() => setPage(page + 1)}
            >
              Siguiente
            </button>
          </div>
          <div className="toolbar">
            <button disabled={busy} onClick={() => void run(review)}>
              Validar correcciones
            </button>
            <button
              onClick={() =>
                void run(async () => {
                  await download(
                    "/ops/imports/bulk/observations",
                    draft,
                    "observaciones.xlsx",
                  );
                })
              }
            >
              Descargar observaciones Excel
            </button>
          </div>
          <label className="check">
            <input
              type="checkbox"
              checked={approve}
              onChange={(e) => setApprove(e.target.checked)}
            />
            Apruebo los cambios mostrados para registros existentes
          </label>
          <button
            className="primary"
            disabled={
              busy ||
              dirty ||
              preview.summary.error > 0 ||
              (preview.summary.updatable > 0 && !approve)
            }
            onClick={() =>
              void run(async () => {
                const result = await send<Record<string, unknown>>(
                  "/ops/imports/bulk/commit",
                  {
                    ...preview.input,
                    token: preview.token,
                    approve_updates: approve,
                  },
                );
                setNotice("Importación guardada correctamente."+ (resultSummary(result) ? " "+resultSummary(result) : ""));
                setHistory(await request<Batch[]>("/ops/imports/bulk/history"));
                setPreview(null);
                setDraft(null);
                window.dispatchEvent(new Event("galant-changed"));
              })
            }
          >
            Confirmar importación
          </button>
        </>
      )}
      <details><summary>Historial de importaciones</summary>
        {history.map((batch) => <p key={batch.id} className="v15-import-history">
          <strong>{batch.filename}</strong> · {batch.kind==="contractors"?"Contratistas":batch.kind==="workers"?"Trabajadores":"Tipo no reconocido"}
          <small>{new Date(batch.created_at).toLocaleString("es-CL")}</small>
          <span>{resultSummary(batch.result)||"Sin resumen adicional"}</span>
        </p>)}
        {!history.length && <p>Sin importaciones confirmadas.</p>}
      </details>
    </section>
  );
}
