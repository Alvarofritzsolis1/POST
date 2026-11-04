import {useCallback,useEffect,useMemo,useRef,useState,type FormEvent} from "react"
import MonthlyDocuments from "./MonthlyDocuments"
import ErrorBoundary from "./ErrorBoundary"
import {ArrowDownToLine,CheckCircle2,ChevronRight,FileSpreadsheet,LoaderCircle,Plus,RefreshCcw,Search,Users,XCircle} from "lucide-react"
import {
  opsApi,type Contractor,type ContractorInput,type ImportPreview,type ImportResult,type WorkerLaborRow,
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
  {value:"inactive",label:"Inactivo"}
]
const isActive=(item:Contractor)=>item.contract_status==="active"
const stateBadge=(status:string)=><span className={"ops-state-badge "+(status==="active"?"is-active":"is-inactive")}>
  <span className="ops-state-dot" aria-hidden="true"/>{status==="active"?"Activo":"Inactivo"}
</span>
const scalar=(value:unknown):string=>{
  if(value===null||value===undefined||value==="")return "—"
  return typeof value==="string"||typeof value==="number"||typeof value==="boolean"?String(value):"—"
}
const detailLabels:Record<string,string>={external_id:"ID externo",specialty:"Especialidad",phone:"Teléfono",email:"Correo",legal_representative:"Representante legal",legal_representative_rut:"RUT representante legal",contact:"Contacto"}
const laborLabels:Record<string,string>={active:"Vigente",ending_soon:"Próximo a vencer",expired_needs_review:"Contrato vencido",ended:"Desvinculado",observed:"Revisar",approved:"Aprobado",missing:"Pendiente",not_applicable:"No aplica"}
const dateCL=(date:string|null)=>date?date.slice(0,10).split("-").reverse().join("/"):"—"
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
  const [statusFilter,setStatusFilter]=useState<"active"|"inactive"|"all">("active")
  const [sortBy,setSortBy]=useState<"name"|"workers"|"status">("name")
  const [selectedTab,setSelectedTab]=useState<"summary"|"workers"|"contracts"|"documents"|"history">("summary")
  const [workerSearch,setWorkerSearch]=useState("")
  const [laborRows,setLaborRows]=useState<WorkerLaborRow[]>([])
  const [laborPage,setLaborPage]=useState(1)
  const [laborHasMore,setLaborHasMore]=useState(false)
  const [laborError,setLaborError]=useState("")
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
    setSelectedId(null);setSelectedTab("summary");setLaborRows([]);setLaborPage(1);setContractors([]);setWorkers([]);setLoading(false);setHistory(null);setHistoryOpen(false);setContractorForm(null);setWorkerForm(null);setPreview(null);setImportResult(null)
    if(siteId)void loadContractors(siteId)
  },[siteId,loadContractors])
  const visibleContractors=contractors.filter(item=>item.site_id===siteId)
  const selected=visibleContractors.find(item=>item.id===selectedId)||null
  useEffect(()=>{setHistory(null);setHistoryOpen(false);setSelectedTab("summary");setWorkerSearch("");setLaborPage(1);setLaborRows([])},[selectedId])
  useEffect(()=>{
    let active=true
    if(!selected){setLaborRows([]);setLaborError("");return}
    const associationId=selected.id
    const companyId=selected.contractor_id
    void opsApi.workerRoster(siteId,companyId,laborPage).then(data=>{
      if(!active||activeSite.current!==siteId||activeSelected.current!==associationId)return
      setLaborRows(prev=>laborPage===1?data.rows:[...prev,...data.rows.filter(row=>!prev.some(existing=>existing.assignment_id===row.assignment_id))])
      setLaborHasMore(data.rows.length>=data.page_size)
      setLaborError("")
    }).catch(err=>{if(active)setLaborError(errorText(err))})
    return()=>{active=false}
  },[siteId,selected?.id,selected?.contractor_id,laborPage])
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
    const kind=item.classification
    return matches&&(statusFilter==="all"||(statusFilter==="active"?isActive(item):!isActive(item)))&&
      (classificationFilter==='all'||kind===classificationFilter)&&(codeFilter==="all"||
      (codeFilter==="other" ? !["CT","CE","CI"].includes(kind) : kind===codeFilter))
  }).sort((a,b)=>sortBy==="workers"?b.worker_count-a.worker_count:
    sortBy==="status"?Number(isActive(b))-Number(isActive(a)):
    a.name.localeCompare(b.name,"es-CL")),[visibleContractors,search,codeFilter,classificationFilter,statusFilter,sortBy])
  const filteredWorkers=laborRows.filter(w=>!workerSearch.trim()||
    w.worker_name.toLocaleLowerCase("es-CL").includes(workerSearch.trim().toLocaleLowerCase("es-CL"))||
    (w.worker_rut||"").includes(workerSearch.trim()))
  const activeWorkers=laborRows.filter(w=>["active","ending_soon"].includes(w.labor_state)).length
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
      <div><strong>{visibleContractors.filter(isActive).length}</strong><span>Contratistas activos</span></div>
      <div><strong>{visibleContractors.filter(x=>!isActive(x)).length}</strong><span>Contratistas inactivos</span></div>
      <div><strong>{visibleContractors.length}</strong><span>Total en la obra</span></div>
      <div><strong>{visibleContractors.filter(isActive).reduce((sum,item)=>sum+item.worker_count,0)}</strong><span>Trabajadores asignados a activos</span></div>
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
        <label>Código histórico<input maxLength={20} placeholder="CT, CE o CI" value={contractorDraft.historical_code||""} onChange={event=>setContractorDraft(current=>({...current,historical_code:event.target.value}))}/></label>
        <label>Naturaleza<select value={contractorDraft.nature} onChange={event=>setContractorDraft(current=>({...current,nature:event.target.value}))}>{natureOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>Frecuencia<select value={contractorDraft.frequency} onChange={event=>setContractorDraft(current=>({...current,frequency:event.target.value}))}>{frequencyOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label>Estado contractual<select value={contractorDraft.contract_status} onChange={event=>setContractorDraft(current=>({...current,contract_status:event.target.value}))}>{statusOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      </div><div className="ops-form-actions"><button className="secondary" type="button" onClick={()=>setContractorForm(null)}>Cancelar</button><button className="primary" disabled={busy} type="submit">{busy?<LoaderCircle className="spin" size={16}/>:null} Guardar contratista</button></div></form>}
      <div className="ops-filters">
        <label className="ops-search"><Search size={16}/><input placeholder="Buscar por nombre o RUT" value={search} onChange={event=>setSearch(event.target.value)}/></label>
        <div className="ops-status-filters" role="group" aria-label="Filtrar contratistas por estado">
          {(["active","inactive","all"] as const).map(value=><button type="button" key={value}
            className={statusFilter===value?"selected":""} aria-pressed={statusFilter===value}
            onClick={()=>setStatusFilter(value)}>{value==="active"?"Activos":value==="inactive"?"Inactivos":"Todos"}</button>)}
        </div>
        <label className="ops-filter-label">Clasificación<select aria-label="Filtrar por clasificación" value={codeFilter} onChange={event=>setCodeFilter(event.target.value)}>
          <option value="all">Todas</option><option value="CT">CT · Fijo</option><option value="CE">CE · Esporádico</option><option value="CI">CI · Independiente</option><option value="other">Sin clasificar</option>
        </select></label>
        <label className="ops-filter-label">Ordenar<select aria-label="Ordenar contratistas" value={sortBy} onChange={event=>setSortBy(event.target.value as "name"|"workers"|"status")}>
          <option value="name">Nombre</option><option value="status">Estado</option><option value="workers">Más trabajadores</option>
        </select></label>
        <span aria-live="polite">{filtered.length} de {visibleContractors.length}</span>
      </div>
      {loading?<div className="ops-empty"><LoaderCircle size={20} className="spin"/> Cargando contratistas…</div>:filtered.length===0?<div className="ops-empty"><Users size={22}/>{visibleContractors.length?"No hay contratistas con estos filtros":"Aún no hay contratistas en esta obra"}</div>:
      <div className="table-wrap"><table className="ops-list-table ops-contractors-table">
        <thead><tr><th>CONTRATISTA</th><th>RUT</th><th>CLASIFICACIÓN</th><th>ESTADO</th><th>TRABAJADORES</th><th>ACCIÓN</th></tr></thead>
        <tbody>{filtered.map(item=><tr key={item.id} className={selectedId===item.id?"selected-row":""}>
          <td><strong>{item.name}</strong></td><td>{item.rut||"—"}</td><td>{item.classification}</td>
          <td>{stateBadge(item.contract_status)}</td><td>{item.worker_count}</td>
          <td><button className="row-open" aria-label={`Abrir ficha de ${item.name}`} onClick={()=>{setSelectedId(item.id);setContractorForm(null);setWorkerForm(null)}}><ChevronRight size={18}/></button></td>
        </tr>)}</tbody></table></div>}
    </section>
    {selected&&<ErrorBoundary key={selected.id} label="la ficha del contratista" onClose={()=>setSelectedId(null)}>
      <section className="results-card ops-card ops-contractor-detail" aria-label="Ficha de contratista">
        <div className="card-heading ops-card-heading"><div>
          <span className="eyebrow">CONTRATISTA SELECCIONADO</span>
          <h2>{selected.name}</h2>
          <p>{selected.rut||"Sin RUT"} · {selected.classification} · {sites.find(site=>site.id===siteId)?.name||"Obra seleccionada"} · {stateBadge(selected.contract_status)}</p>
        </div><div className="ops-actions">
          {!readOnly&&<button className="secondary" onClick={()=>startContractor("edit",selected)}>Editar</button>}
          <button type="button" className="secondary" onClick={()=>setSelectedId(null)}>Cerrar ficha</button>
        </div></div>
        <nav className="ops-detail-tabs" aria-label="Apartados del contratista">
          {([
            ["summary","Resumen"],["workers","Trabajadores"],["contracts","Contratos y finiquitos"],
            ["documents","Documentación"],["history","Historial"]
          ] as const).map(([tab,label])=><button type="button" key={tab}
            aria-current={selectedTab===tab?"page":undefined} className={selectedTab===tab?"active":""}
            onClick={()=>{setSelectedTab(tab);if(tab==="history"&&!historyOpen)void toggleHistory()}}>{label}</button>)}
        </nav>
        {selectedTab==="summary"&&<div className="ops-detail-body">
          <div className="ops-detail-stats">
            <div><strong>{selected.worker_count}</strong><span>Trabajadores asignados</span></div>
            <div><strong>{activeWorkers}</strong><span>Contratos vigentes o próximos a vencer</span></div>
            <div><strong>{laborRows.filter(w=>w.finiquito_state==="missing").length}</strong><span>Finiquitos pendientes</span></div>
          </div>
          {!isActive(selected)&&<p className="ops-inactive-note">Contratista inactivo. No genera nuevas obligaciones mensuales; los antecedentes anteriores siguen disponibles.</p>}
          <h3>Información de la empresa</h3>
          <dl className="contractor-details">{Object.entries(selected.details||{}).filter(([,value])=>value===null||["string","number","boolean"].includes(typeof value)).map(([key,value])=>
            <div key={key}><dt>{detailLabels[key]||key}</dt><dd>{scalar(value)}</dd></div>)}</dl>
          <div className="ops-detail-links">
            <button className="secondary" type="button" onClick={()=>setSelectedTab("workers")}>Ver trabajadores</button>
            <button className="secondary" type="button" onClick={()=>setSelectedTab("contracts")}>Ver contratos y finiquitos</button>
            <button className="secondary" type="button" onClick={()=>setSelectedTab("documents")}>Ver documentos</button>
          </div>
        </div>}
        {(selectedTab==="workers"||selectedTab==="contracts")&&<div className="ops-detail-body">
          <div className="ops-workers-heading"><div><h3>{selectedTab==="contracts"?"Contratos y finiquitos":"Trabajadores asociados"}</h3>
            <p>La información laboral proviene del registro compartido de la obra.</p></div>
            <label className="ops-search"><Search size={15}/><input aria-label="Buscar trabajador" placeholder="Buscar trabajador o RUT" value={workerSearch} onChange={e=>setWorkerSearch(e.target.value)}/></label>
          </div>
          {laborError&&<p role="alert" className="form-error">{laborError}</p>}
          {filteredWorkers.length===0?<p className="ops-empty">No hay trabajadores para esta búsqueda.</p>:
          <div className="table-wrap"><table className="ops-list-table ops-worker-table">
            <thead><tr><th>TRABAJADOR</th><th>RUT</th><th>ESTADO</th><th>CONTRATO</th><th>INGRESO</th><th>TÉRMINO</th><th>FINIQUITO</th><th>ACCIÓN</th></tr></thead>
            <tbody>{filteredWorkers.map(worker=><tr key={worker.assignment_id}>
              <td><strong>{worker.worker_name}</strong></td><td>{worker.worker_rut||"—"}</td>
              <td>{laborLabels[worker.labor_state]||worker.labor_state}</td><td>{worker.contract_type||"—"}</td>
              <td>{dateCL(worker.start_date)}</td><td>{dateCL(worker.end_date)}</td>
              <td>{laborLabels[worker.finiquito_state]||worker.finiquito_state}</td>
              <td><button className="secondary ops-small-button" type="button" onClick={()=>onWorkers?.(worker.assignment_id)}>Abrir ficha</button></td>
            </tr>)}</tbody></table></div>}
          <div className="ops-detail-links">
            {laborHasMore&&<button className="secondary" type="button" onClick={()=>setLaborPage(page=>page+1)}>Cargar más trabajadores</button>}
            <button className="primary" type="button" onClick={()=>onWorkers?.()}>Abrir módulo completo de Trabajadores</button>
          </div>
        </div>}
        {selectedTab==="documents"&&<ErrorBoundary label="el control documental" onClose={()=>setSelectedTab("summary")}>
          <MonthlyDocuments key={selected.id} contractor={selected} readOnly={readOnly}/>
        </ErrorBoundary>}
        {selectedTab==="history"&&<div className="ops-detail-body ops-history">
          <h3>Historial de modificaciones</h3>
          {history===null?<p>Cargando historial…</p>:history.length===0?<p>No hay cambios registrados.</p>:<ul>{history.map(change=><li key={change.id}><time>{new Date(change.created_at).toLocaleString("es-CL")}</time>
            <span>{describeChange(change.changes)}</span><small>Registro auditado</small></li>)}</ul>}
        </div>}
      </section>
    </ErrorBoundary>}
  </div>
}
