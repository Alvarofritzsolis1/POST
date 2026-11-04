import {useCallback,useEffect,useMemo,useRef,useState,type FormEvent} from "react"
import MonthlyDocuments from "./MonthlyDocuments"
import {ArrowDownToLine,CheckCircle2,ChevronRight,FileSpreadsheet,LoaderCircle,Plus,RefreshCcw,Search,Users,XCircle} from "lucide-react"
import {
  opsApi,type Contractor,type ContractorInput,type ImportPreview,type ImportResult,
  type ImportRow,type OpsChange,type Site,type Worker,type WorkerInput
} from "./opsApi"

const natureOptions=[
  {value:"unclassified",label:"Sin clasificar"},
  {value:"independent",label:"Independiente sin trabajadores"},
  {value:"with_workers",label:"Contratista con trabajadores"}
]
const frequencyOptions=[
  {value:"unclassified",label:"Sin clasificar"},
  {value:"fixed",label:"Fijo"},
  {value:"sporadic",label:"Esporádico"}
]
const statusOptions=[
  {value:"active",label:"Activo"},
  {value:"suspended",label:"Suspendido"},
  {value:"offboarding",label:"En proceso de baja"},
  {value:"inactive",label:"Dado de baja"}
]
const historyOptions=[
  {value:"historical_approved",label:"Aprobado histórico (sin PDF verificado)"},
  {value:"historical_pending",label:"Pendiente histórico"},
  {value:"historical_not_applicable",label:"No aplica histórico"}
]
const importColumns=[
  {key:"kind",label:"Tipo de fila"},{key:"name",label:"Nombre"},{key:"rut",label:"RUT"},
  {key:"contractor_rut",label:"RUT contratista"},{key:"historical_code",label:"Código histórico"},
  {key:"contractor_name",label:"Nombre empresa"},{key:"worker_name",label:"Nombre trabajador"},
  {key:"worker_rut",label:"RUT trabajador"}
]
const label=(options:{value:string;label:string}[],value:string)=>options.find(x=>x.value===value)?.label||value
const changeLabels:Record<string,string>={name:"Nombre",rut:"RUT",nature:"Naturaleza",frequency:"Frecuencia",historical_code:"Código histórico",contract_status:"Estado contractual",active:"Asignación",created:"Creación",imported_statuses:"Estados históricos"}
function describeChange(changes:Record<string,unknown>){
  return Object.entries(changes).map(([field,value])=>{
    if(field==="created")return "Registro creado"
    if(field==="imported")return "Registro importado"
    if(field==="imported_statuses")return "Estados históricos importados o actualizados"
    if(value&&typeof value==="object"&&"from" in value&&"to" in value){
      const transition=value as {from:unknown;to:unknown}
      return `${changeLabels[field]||field}: ${String(transition.from??"vacío")} → ${String(transition.to??"vacío")}`
    }
    return `${changeLabels[field]||field}: ${String(value)}`
  }).join(" · ")
}
const blankContractor=(siteId:string):ContractorInput=>({site_id:siteId,name:"",rut:null,historical_code:null,nature:"unclassified",frequency:"unclassified",contract_status:"active"})
const blankWorker=(siteId:string,contractorId:string):WorkerInput=>({site_id:siteId,contractor_id:contractorId,name:"",rut:null})
const errorText=(err:unknown)=>err instanceof Error?err.message:"No fue posible completar la operación"
const templateUrl=(kind:string)=>"/api/v1/ops/imports/templates/"+encodeURIComponent(kind)+"?format=xlsx"

export default function Operations({readOnly,externalSiteId,mode,onImport,onSiteChange,onWorkers,classificationFilter="all"}:{readOnly:boolean;externalSiteId?:string;mode?:string;onImport?:()=>void;onSiteChange?:(id:string)=>void;onWorkers?:(assignmentId?:string)=>void;classificationFilter?:string}){
  const [sites,setSites]=useState<Site[]>([])
  const [siteId,setSiteId]=useState(externalSiteId||"")
  useEffect(()=>{if(externalSiteId)setSiteId(externalSiteId)},[externalSiteId])
  const [contractors,setContractors]=useState<Contractor[]>([])
  const [selectedId,setSelectedId]=useState<string|null>(null)
  const [workers,setWorkers]=useState<Worker[]>([])
  const [history,setHistory]=useState<OpsChange[]|null>(null)
  const [historyOpen,setHistoryOpen]=useState(false)
  const [search,setSearch]=useState("")
  const [codeFilter,setCodeFilter]=useState("all")
  const [contractorForm,setContractorForm]=useState<"new"|"edit"|null>(null)
  const [contractorDraft,setContractorDraft]=useState<ContractorInput>(blankContractor(""))
  const [workerForm,setWorkerForm]=useState<"new"|string|null>(null)
  const [workerDraft,setWorkerDraft]=useState<WorkerInput>(blankWorker("",""))
  const [workerActive,setWorkerActive]=useState(true)
  const [importOpen,setImportOpen]=useState(false)
  const [importFile,setImportFile]=useState<File|null>(null)
  const [preview,setPreview]=useState<ImportPreview|null>(null)
  const [editedRows,setEditedRows]=useState<Set<number>>(new Set())
  const [mapping,setMapping]=useState<Record<string,string>>({})
  const [columnMap,setColumnMap]=useState<Record<string,string>>({})
  const [importResult,setImportResult]=useState<ImportResult|null>(null)
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const activeSite=useRef(siteId)
  const activeSelected=useRef(selectedId)
  const contractorRequest=useRef(0)
  const workerRequest=useRef(0)
  activeSite.current=siteId
  activeSelected.current=selectedId

  const loadContractors=useCallback(async(id:string)=>{
    if(activeSite.current!==id)return
    const requestId=++contractorRequest.current
    setLoading(true)
    try{
      const items=await opsApi.contractors(id)
      if(requestId===contractorRequest.current&&activeSite.current===id){setContractors(items);setError("")}
    }catch(err){if(requestId===contractorRequest.current&&activeSite.current===id)setError(errorText(err))}
    finally{if(requestId===contractorRequest.current&&activeSite.current===id)setLoading(false)}
  },[])
  const loadWorkers=useCallback(async(id:string,contractorId:string,associationId:string)=>{
    if(activeSite.current!==id||activeSelected.current!==associationId)return
    const requestId=++workerRequest.current
    try{
      const items=await opsApi.workers(id,contractorId)
      if(requestId===workerRequest.current&&activeSite.current===id&&activeSelected.current===associationId)setWorkers(items)
    }catch(err){if(requestId===workerRequest.current&&activeSite.current===id&&activeSelected.current===associationId)setError(errorText(err))}
  },[])
  useEffect(()=>{
    let active=true
    void opsApi.sites().then(items=>{
      if(!active)return
      setSites(items)
      setSiteId(current=>current||items[0]?.id||"")
    }).catch(err=>{if(active)setError(errorText(err))})
    return()=>{active=false}
  },[])
  useEffect(()=>{
    ++contractorRequest.current;++workerRequest.current
    setSelectedId(null);setContractors([]);setWorkers([]);setLoading(false);setHistory(null);setHistoryOpen(false);setContractorForm(null);setWorkerForm(null);setPreview(null);setImportResult(null)
    if(siteId)void loadContractors(siteId)
  },[siteId,loadContractors])
  const visibleContractors=contractors.filter(item=>item.site_id===siteId)
  const selected=visibleContractors.find(item=>item.id===selectedId)||null
  useEffect(()=>{setHistory(null);setHistoryOpen(false)},[selectedId])
  useEffect(()=>{
    ++workerRequest.current;setWorkers([])
    if(siteId&&selected)void loadWorkers(siteId,selected.contractor_id,selected.id)
  },[siteId,selected?.contractor_id,selected?.id,loadWorkers])
  useEffect(()=>{
    if(!siteId)return
    const refresh=()=>{void loadContractors(siteId);if(selected)void loadWorkers(siteId,selected.contractor_id,selected.id)}
    const timer=window.setInterval(refresh,10000)
    window.addEventListener('focus',refresh)
    return()=>{window.clearInterval(timer);window.removeEventListener('focus',refresh)}
  },[siteId,selected?.id,selected?.contractor_id,loadContractors,loadWorkers])
  const filtered=useMemo(()=>visibleContractors.filter(item=>{
    const term=search.trim().toLocaleLowerCase("es-CL")
    const matches=!term||item.name.toLocaleLowerCase("es-CL").includes(term)||(item.rut||"").toLocaleLowerCase("es-CL").includes(term)
    const kind=item.nature==='independent'?'CI':item.nature==='with_workers'?'CT':'SIN CLASIFICAR'
    return matches&&(classificationFilter==='all'||kind===classificationFilter)&&(codeFilter==="all"||
      (codeFilter==="ESP" ? item.frequency==="sporadic" : codeFilter==="other" ? !["CT","CI"].includes((item.historical_code||"").toUpperCase()) : kind===codeFilter))
  }),[visibleContractors,search,codeFilter,classificationFilter])
  const statusSymbols=useMemo(()=>{
    const values=new Set<string>()
    for(const row of preview?.rows||[])for(const raw of Object.values(row.historical_statuses||{}))if(raw)values.add(raw.toUpperCase())
    return [...values].sort()
  },[preview])
  const mappingComplete=statusSymbols.every(symbol=>Boolean(mapping[symbol]))

  function startContractor(mode:"new"|"edit",item?:Contractor){
    setError("");setNotice("")
    setContractorDraft(item?{
      site_id:siteId,name:item.name,rut:item.rut,historical_code:item.historical_code,
      nature:item.nature,frequency:item.frequency,contract_status:item.contract_status
    }:blankContractor(siteId))
    setContractorForm(mode)
  }
  async function saveContractor(event:FormEvent){
    event.preventDefault();if(readOnly||!siteId)return
    setBusy(true);setError("");setNotice("")
    const payload={...contractorDraft,name:contractorDraft.name.trim(),rut:contractorDraft.rut?.trim()||null,historical_code:contractorDraft.historical_code?.trim().toUpperCase()||null}
    try{
      const item=contractorForm==="edit"&&selected?await opsApi.updateContractor(selected.id,{
        name:payload.name,rut:payload.rut,historical_code:payload.historical_code,
        nature:payload.nature,frequency:payload.frequency,contract_status:payload.contract_status
      }):await opsApi.createContractor(payload)
      if(activeSite.current!==siteId)return
      await loadContractors(siteId)
      setSelectedId(item.id)
      setContractorForm(null)
      setNotice("Contratista guardado.")
    }catch(err){if(activeSite.current===siteId)setError(errorText(err))}
    finally{setBusy(false)}
  }
  function startWorker(item?:Worker){
    if(!selected)return
    setWorkerDraft(item?{site_id:siteId,contractor_id:selected.contractor_id,name:item.name,rut:item.rut}:blankWorker(siteId,selected.contractor_id))
    setWorkerActive(item?.active??true)
    setWorkerForm(item?.id||"new");setError("");setNotice("")
  }
  async function toggleHistory(){
    if(historyOpen){setHistoryOpen(false);return}
    if(!selected)return
    setHistoryOpen(true)
    try{
      const [association,company]=await Promise.all([
        opsApi.history("contractor_worksite",selected.id),
        opsApi.history("contractor",selected.contractor_id)
      ])
      if(activeSelected.current===selected.id&&activeSite.current===siteId)setHistory([...association,...company].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at)))
    }catch(err){if(activeSelected.current===selected.id&&activeSite.current===siteId){setError(errorText(err));setHistoryOpen(false)}}
  }
  async function saveWorker(event:FormEvent){
    event.preventDefault();if(readOnly||!selected)return
    setBusy(true);setError("");setNotice("")
    const payload={...workerDraft,name:workerDraft.name.trim(),rut:workerDraft.rut?.trim()||null}
    try{
      if(workerForm&&workerForm!=="new")await opsApi.updateWorker(workerForm,{name:payload.name,rut:payload.rut,active:workerActive})
      else await opsApi.createWorker(payload)
      if(activeSite.current!==siteId||activeSelected.current!==selected.id)return
      await Promise.all([loadWorkers(siteId,selected.contractor_id,selected.id),loadContractors(siteId)])
      setWorkerForm(null)
      setNotice("Trabajador guardado en la obra seleccionada.")
    }catch(err){if(activeSite.current===siteId&&activeSelected.current===selected.id)setError(errorText(err))}
    finally{setBusy(false)}
  }
  async function previewFile(){
    if(!siteId||!importFile)return
    setBusy(true);setError("");setNotice("");setPreview(null);setImportResult(null)
    try{
      const next=await opsApi.previewImport(importFile,siteId,Object.fromEntries(Object.entries(columnMap).filter(([,value])=>value.trim()).map(([key,value])=>[key,value.trim()])))
      if(activeSite.current===siteId){setPreview(next);setEditedRows(new Set());setMapping({})}
    }catch(err){if(activeSite.current===siteId)setError(errorText(err))}
    finally{setBusy(false)}
  }
  function editImportRow(index:number,key:keyof ImportRow,value:string){
    setPreview(current=>current?{...current,rows:current.rows.map((row,i)=>i===index?{...row,[key]:value}:row)}:null)
    setEditedRows(current=>new Set(current).add(index))
  }
  async function commitImport(){
    if(!siteId||!preview||readOnly||!mappingComplete)return
    setBusy(true);setError("");setNotice("")
    try{
      const result=await opsApi.commitImport(siteId,preview.rows,mapping,preview)
      if(activeSite.current!==siteId)return
      setImportResult(result);setPreview(null)
      await loadContractors(siteId)
      if(selected)await loadWorkers(siteId,selected.contractor_id,selected.id)
      setNotice("Importación confirmada. Consulta el informe de filas y registros procesados.")
    }catch(err){if(activeSite.current===siteId)setError(errorText(err))}
    finally{setBusy(false)}
  }

  return <div className="ops-workspace">
    <p>Ficha compartida de contratistas y sus asignaciones por obra.</p>
    <div className="ops-toolbar">
      <label>Obra<select value={siteId} onChange={event=>{setPreview(null);setImportResult(null);setContractors([]);setWorkers([]);setSelectedId(null);setSiteId(event.target.value);onSiteChange?.(event.target.value)}}>{sites.map(site=><option key={site.id} value={site.id}>{site.name}</option>)}</select></label>
      <span className="ops-toolbar-note">Los registros de esta vista pertenecen a la obra seleccionada.</span>
      <button className="icon-button" title="Actualizar contratistas" onClick={()=>siteId&&void loadContractors(siteId)}><RefreshCcw size={17}/></button>
    </div>
    {error&&<div role="alert" className="alert danger"><XCircle size={18}/>{error}<button onClick={()=>setError("")}>Cerrar</button></div>}
    {notice&&<div role="status" className="alert success"><CheckCircle2 size={18}/>{notice}<button onClick={()=>setNotice("")}>Cerrar</button></div>}
    <div className="ops-summary" aria-label="Resumen de la obra">
      <div><strong>{visibleContractors.length}</strong><span>Contratistas en la obra</span></div>
      <div><strong>{visibleContractors.filter(x=>x.historical_code==="CT").length}</strong><span>Código CT</span></div>
      <div><strong>{visibleContractors.filter(x=>x.historical_code==="CI").length}</strong><span>Código CI</span></div>
      <div><strong>{visibleContractors.reduce((sum,item)=>sum+item.worker_count,0)}</strong><span>Asignaciones activas</span></div>
    </div>
    <section className="results-card ops-card">
      <div className="card-heading ops-card-heading"><div><h2>Contratistas</h2><p>Busca por nombre o RUT y selecciona una empresa para ver sus trabajadores.</p></div><div className="ops-actions">
        {!readOnly&&<button className="secondary" onClick={()=>{if(onImport)onImport();else setImportOpen(!importOpen);setContractorForm(null)}}><FileSpreadsheet size={16}/> Importar Excel o CSV</button>}
        {!readOnly&&<button className="primary" onClick={()=>startContractor("new")}><Plus size={16}/> Nuevo contratista</button>}
      </div></div>
      {importOpen&&<div className="ops-import-panel">
        <div className="ops-import-top"><div><h3>Importación con vista previa</h3><p>La confirmación se valida nuevamente en el servidor. Los estados históricos conservan el origen del archivo Excel o CSV.</p></div><button className="secondary" onClick={()=>{setImportOpen(false);setPreview(null);setImportResult(null)}}>Cerrar</button></div>
        <div className="ops-template-links">Plantillas: <a href={templateUrl("contractors")}><ArrowDownToLine size={14}/> Contratistas</a><a href={templateUrl("workers")}><ArrowDownToLine size={14}/> Trabajadores</a><a href={templateUrl("monthly")}><ArrowDownToLine size={14}/> Registros mensuales</a></div>
        <div className="ops-import-controls"><label>Archivo Excel o CSV<input type="file" accept=".xlsx,.csv" onChange={event=>{setImportFile(event.target.files?.[0]||null);setPreview(null);setImportResult(null)}}/></label><button className="primary" disabled={!importFile||busy} onClick={()=>void previewFile()}>{busy?<LoaderCircle className="spin" size={16}/>:<FileSpreadsheet size={16}/>} Revisar archivo</button></div>
        <details className="ops-column-map"><summary>¿Tu planilla tiene otros encabezados? Asignar columnas</summary><p>Escribe el encabezado exacto de cada columna que quieras asignar. Deja los demás vacíos para usar la detección automática.</p><div>{importColumns.map(column=><label key={column.key}>{column.label}<input value={columnMap[column.key]||""} placeholder="Encabezado en tu archivo" onChange={event=>setColumnMap(current=>({...current,[column.key]:event.target.value}))}/></label>)}</div></details>
        {preview&&<><div className="ops-import-summary"><strong>{preview.rows.length} filas detectadas</strong><span>{preview.summary.contractors} contratistas · {preview.summary.workers} trabajadores · {preview.summary.errors} errores · {preview.summary.warnings} avisos en el archivo original</span></div>
          <details className="ops-detected-columns"><summary>Ver columnas reconocidas</summary>{Object.entries(preview.detected_columns||{}).map(([sheet,columns])=><p key={sheet}><strong>{sheet}:</strong> {Object.entries(columns).map(([field,heading])=>`${field} → ${heading}`).join(" · ")}</p>)}</details>
          <p className="ops-help">Puedes corregir filas aquí. Al confirmar, el servidor vuelve a validar todas las relaciones, RUT y duplicados.</p>
          <div className="table-wrap"><table className="ops-import-table"><thead><tr><th>FILA</th><th>TIPO</th><th>NOMBRE</th><th>RUT</th><th>RUT CONTRATISTA</th><th>CÓDIGO</th><th>NATURALEZA</th><th>FRECUENCIA</th><th>ESTADO CONTRACTUAL</th><th>VALIDACIÓN ORIGINAL</th></tr></thead><tbody>
            {preview.rows.map((row,index)=><tr key={row.row_id||index}><td>{row.sheet}: {row.row_number}</td><td><select aria-label={`Tipo fila ${row.row_number}`} value={row.kind} onChange={event=>editImportRow(index,"kind",event.target.value)}>{row.kind!=="contractor"&&row.kind!=="worker"&&<option value={row.kind}>Sin identificar</option>}<option value="contractor">Empresa</option><option value="worker">Trabajador</option></select></td>
              <td><input aria-label={`Nombre fila ${row.row_number}`} value={row.name} onChange={event=>editImportRow(index,"name",event.target.value)}/></td>
              <td><input aria-label={`RUT fila ${row.row_number}`} value={row.rut||""} onChange={event=>editImportRow(index,"rut",event.target.value)}/></td>
              <td><input aria-label={`RUT contratista fila ${row.row_number}`} value={row.contractor_rut||""} disabled={row.kind==="contractor"} onChange={event=>editImportRow(index,"contractor_rut",event.target.value)}/></td>
              <td><input aria-label={`Código fila ${row.row_number}`} value={row.historical_code||""} disabled={row.kind==="worker"} onChange={event=>editImportRow(index,"historical_code",event.target.value)}/></td>
              <td><select aria-label={`Naturaleza fila ${row.row_number}`} value={row.nature||""} disabled={row.kind==="worker"} onChange={event=>editImportRow(index,"nature",event.target.value)}><option value="">Sin especificar</option>{row.nature&&!natureOptions.some(option=>option.value===row.nature)&&<option value={row.nature}>Valor no reconocido: {row.nature}</option>}{natureOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></td>
              <td><select aria-label={`Frecuencia fila ${row.row_number}`} value={row.frequency||""} disabled={row.kind==="worker"} onChange={event=>editImportRow(index,"frequency",event.target.value)}><option value="">Sin especificar</option>{row.frequency&&!frequencyOptions.some(option=>option.value===row.frequency)&&<option value={row.frequency}>Valor no reconocido: {row.frequency}</option>}{frequencyOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></td>
              <td><select aria-label={`Estado contractual fila ${row.row_number}`} value={row.contract_status||""} disabled={row.kind==="worker"} onChange={event=>editImportRow(index,"contract_status",event.target.value)}><option value="">Sin especificar</option>{row.contract_status&&!statusOptions.some(option=>option.value===row.contract_status)&&<option value={row.contract_status}>Valor no reconocido: {row.contract_status}</option>}{statusOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></td>
              <td>{editedRows.has(index)?<span className="status waiting">Se validará al confirmar</span>:row.errors.length?<span className="status error" title={row.errors.join("; ")}>{row.errors.join("; ")}</span>:row.warnings.length?<span className="status review" title={row.warnings.join("; ")}>{row.warnings.join("; ")}</span>:<span className="status success">Lista</span>}</td></tr>)}
          </tbody></table></div>
          {statusSymbols.length>0&&<div className="ops-mapping"><h3>Confirma el significado de los estados históricos</h3><p>No se equiparan con una verificación documental. Selecciona la regla que corresponde a tus datos antes de importar.</p><div>{statusSymbols.map(symbol=><label key={symbol}><span>{symbol}</span><select value={mapping[symbol]||""} onChange={event=>setMapping(current=>({...current,[symbol]:event.target.value}))}><option value="">Seleccionar significado</option>{historyOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}</div></div>}
          <div className="ops-import-footer"><span>Si alguna fila falla la validación final, no se importará ninguna.</span><button className="primary" disabled={busy||!mappingComplete||readOnly||preview.rows.length===0} onClick={()=>void commitImport()}>Confirmar importación</button></div>
        </>}
        {importResult&&<div className="ops-import-result"><h3>Informe de importación</h3><p>{importResult.created_contractors} empresas creadas · {importResult.linked_contractors} empresas vinculadas · {importResult.created_workers} trabajadores creados · {importResult.assigned_workers} trabajadores asignados · {importResult.skipped} omitidos · {importResult.historical_statuses_count} estados históricos conservados</p><details><summary>Ver detalle de {importResult.imported_rows.length} filas procesadas</summary><div className="table-wrap"><table><thead><tr><th>FILA</th><th>RESULTADO</th><th>ID DEL REGISTRO</th></tr></thead><tbody>{importResult.imported_rows.map((row,index)=><tr key={row.row_id+index}><td>{row.row_id}</td><td>{({created:"Creado",linked:"Vinculado",assigned:"Asignado",updated:"Actualizado",existing:"Sin cambios"} as Record<string,string>)[row.result]||row.result}</td><td>{row.entity_id}</td></tr>)}</tbody></table></div></details></div>}
      </div>}
      {contractorForm&&<form className="ops-form" onSubmit={event=>void saveContractor(event)}><h3>{contractorForm==="new"?"Nuevo contratista":"Editar contratista"}</h3><div className="ops-form-grid">
        <label>Nombre o razón social<input required maxLength={180} value={contractorDraft.name} onChange={event=>setContractorDraft(current=>({...current,name:event.target.value}))}/></label>
        <label>RUT<input placeholder="12.345.678-5" value={contractorDraft.rut||""} onChange={event=>setContractorDraft(current=>({...current,rut:event.target.value}))}/></label>
        <label>Código histórico<input maxLength={20} placeholder="CT, CI u otro" value={contractorDraft.historical_code||""} onChange={event=>setContractorDraft(current=>({...current,historical_code:event.target.value}))}/></label>
        <label>Naturaleza<select value={contractorDraft.nature} onChange={event=>setContractorDraft(current=>({...current,nature:event.target.value}))}>{natureOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>Frecuencia<select value={contractorDraft.frequency} onChange={event=>setContractorDraft(current=>({...current,frequency:event.target.value}))}>{frequencyOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>Estado contractual<select value={contractorDraft.contract_status} onChange={event=>setContractorDraft(current=>({...current,contract_status:event.target.value}))}>{statusOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      </div><div className="ops-form-actions"><button className="secondary" type="button" onClick={()=>setContractorForm(null)}>Cancelar</button><button className="primary" disabled={busy} type="submit">{busy?<LoaderCircle className="spin" size={16}/>:null} Guardar contratista</button></div></form>}
      <div className="ops-filters"><label className="ops-search"><Search size={16}/><input placeholder="Buscar por nombre o RUT" value={search} onChange={event=>setSearch(event.target.value)}/></label><select aria-label="Filtrar por clasificación" value={codeFilter} onChange={event=>setCodeFilter(event.target.value)}><option value="all">Todas las clasificaciones</option><option value="CT">CT</option><option value="CI">CI</option><option value="other">Esporádicos y sin clasificar</option></select><span>{filtered.length} de {visibleContractors.length}</span></div>
      {loading?<div className="ops-empty"><LoaderCircle size={20} className="spin"/> Cargando contratistas…</div>:filtered.length===0?<div className="ops-empty"><Users size={22}/>{visibleContractors.length?"No hay coincidencias":"Aún no hay contratistas en esta obra"}</div>:
      <div className="table-wrap"><table className="ops-list-table"><thead><tr><th>CONTRATISTA</th><th>RUT</th><th>CÓDIGO</th><th>NATURALEZA</th><th>FRECUENCIA</th><th>ESTADO</th><th>TRABAJADORES</th><th></th></tr></thead><tbody>{filtered.map(item=><tr key={item.id} className={selectedId===item.id?"selected-row":""}>
        <td><strong>{item.name}</strong></td><td>{item.rut||"—"}</td><td>{item.historical_code||"—"}</td><td>{label(natureOptions,item.nature)}</td><td>{label(frequencyOptions,item.frequency)}</td><td>{label(statusOptions,item.contract_status)}</td><td>{item.worker_count}</td>
        <td><button className="row-open" aria-label={`Ver trabajadores de ${item.name}`} onClick={()=>{setSelectedId(item.id);setContractorForm(null);setWorkerForm(null)}}><ChevronRight size={18}/></button></td></tr>)}</tbody></table></div>}
    </section>
    {selected&&<section className="results-card ops-card"><div className="card-heading ops-card-heading"><div><span className="eyebrow">CONTRATISTA SELECCIONADO</span><h2>{selected.name}</h2><p>{selected.rut||"Sin RUT"} · {selected.historical_code||"Sin código histórico"} · {label(natureOptions,selected.nature)}</p></div><div className="ops-actions">
      <button className="secondary" onClick={()=>void toggleHistory()}>{historyOpen?"Ocultar historial":"Ver historial"}</button>
      {!readOnly&&<button className="secondary" onClick={()=>startContractor("edit",selected)}>Editar empresa</button>}
      <button className="primary" onClick={()=>onWorkers?.()}>Gestionar trabajadores</button>
    </div></div>
      <MonthlyDocuments key={selected.id} contractor={selected} readOnly={readOnly}/>
      {selected.details&&<dl className="contractor-details">{Object.entries(selected.details).map(([key,value])=><div key={key}><dt>{({external_id:'ID externo',specialty:'Especialidad',phone:'Teléfono',email:'Correo',legal_representative:'Representante legal',legal_representative_rut:'RUT representante legal',contact:'Contacto'} as Record<string,string>)[key]||key}</dt><dd>{value}</dd></div>)}</dl>}
      {historyOpen&&<div className="ops-history"><h3>Historial de cambios</h3>{history===null?<p>Cargando historial…</p>:history.length===0?<p>Aún no hay cambios registrados.</p>:<ul>{history.map(change=><li key={change.id}><time>{new Date(change.created_at).toLocaleString("es-CL")}</time><span>{describeChange(change.changes)}</span><small>Usuario {change.user_id}</small></li>)}</ul>}</div>}
      {workers.length===0?<div className="ops-empty">No hay trabajadores asignados a este contratista en la obra.</div>:<div className="table-wrap"><table className="ops-list-table"><thead><tr><th>NOMBRE</th><th>RUT</th><th>ASIGNACIÓN</th><th></th></tr></thead><tbody>{workers.map(worker=><tr key={worker.id}><td><strong>{worker.name}</strong></td><td>{worker.rut||"—"}</td><td><span className={worker.active?"status success":"status waiting"}>{worker.active?"Activa":"Inactiva"}</span></td><td><button className="secondary ops-small-button" onClick={()=>onWorkers?.(worker.id)}>Ver en Trabajadores</button></td></tr>)}</tbody></table></div>}
    </section>}
  </div>
}
