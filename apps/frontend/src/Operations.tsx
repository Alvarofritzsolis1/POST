import {useCallback,useEffect,useMemo,useRef,useState,type FormEvent} from "react"
import MonthlyDocuments from "./MonthlyDocuments"
import {summarizeRequirements,statusLabel} from "./documentUX"
import {opsControlApi,type Requirement} from "./opsControlApi"
import {read} from "./platformApi"
import {ArrowDownToLine,ArrowLeft,CheckCircle2,ChevronRight,FileSpreadsheet,LoaderCircle,Plus,RefreshCcw,Search,Users,XCircle} from "lucide-react"
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
  {value:"inactive",label:"Inactivo"}
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
const blankContractor=(siteId:string):ContractorInput=>({site_id:siteId,name:"",rut:null,historical_code:"CT",nature:"with_workers",frequency:"fixed",contract_status:"active"})
const blankWorker=(siteId:string,contractorId:string):WorkerInput=>({site_id:siteId,contractor_id:contractorId,name:"",rut:null})
type LaborRow={assignment_id:string;worker_name:string;worker_rut:string;contract_type:string|null;start_date:string|null;end_date:string|null;labor_state:string;finiquito_state:string}
const laborStates:Record<string,string>={active:"Vigente",ended:"Terminado",ending_soon:"Próximo a vencer",expired_needs_review:"Vencido",observed:"Observado",missing:"Pendiente",approved:"Aprobado",delivered:"Entregado",not_applicable:"No aplica"}
const laborDate=(value:string|null)=>value?value.slice(0,10).split("-").reverse().join("/"):"—"
const errorText=(err:unknown)=>err instanceof Error?err.message:"No fue posible completar la operación"
const contractorFromUrl=()=>{const match=window.location.pathname.match(/^\/contratistas\/([^/]+)\/?$/);if(!match)return null;try{return decodeURIComponent(match[1])}catch{return null}}
const documentNames:Record<string,string>={cotizaciones:"Pago de cotizaciones",f30_1:"F30-1",asistencia:"Registro de asistencia",liquidaciones:"Liquidaciones de sueldo",porteria:"Informe de portería",declaracion_jurada:"Declaración jurada",anticipos:"Listado de anticipos"}
const templateUrl=(kind:string)=>"/api/v1/ops/imports/templates/"+encodeURIComponent(kind)+"?format=xlsx"

export default function Operations({readOnly,externalSiteId,mode,onImport,onSiteChange,onWorkers,classificationFilter="all",period=""}:{readOnly:boolean;externalSiteId?:string;mode?:string;onImport?:()=>void;onSiteChange?:(id:string)=>void;onWorkers?:(assignmentId?:string)=>void;classificationFilter?:string;period?:string}){
  const [sites,setSites]=useState<Site[]>([])
  const [siteId,setSiteId]=useState(externalSiteId||"")
  useEffect(()=>{if(externalSiteId)setSiteId(externalSiteId)},[externalSiteId])
  const [contractors,setContractors]=useState<Contractor[]>([])
  const [selectedId,setSelectedId]=useState<string|null>(contractorFromUrl)
  const [docOverview,setDocOverview]=useState<Requirement[]|null>(null)
  const [documentPeriod,setDocumentPeriod]=useState(period)
  const [documentRevision,setDocumentRevision]=useState(0)
  useEffect(()=>setDocumentPeriod(period),[period,selectedId])
  const [docIssue,setDocIssue]=useState("")
  const [listCompliance,setListCompliance]=useState<Record<string,ReturnType<typeof summarizeRequirements>>|null>(null)
  const [complianceFilter,setComplianceFilter]=useState("all")
  const [listPage,setListPage]=useState(1)
  const listScroll=useRef(0)
  const restoreListScroll=useRef(false)
  const [workers,setWorkers]=useState<Worker[]>([])
  const [laborRows,setLaborRows]=useState<LaborRow[]>([])
  const [laborError,setLaborError]=useState("")
  const [laborTotal,setLaborTotal]=useState(0)
  const [history,setHistory]=useState<OpsChange[]|null>(null)
  const [historyOpen,setHistoryOpen]=useState(false)
  const [search,setSearch]=useState("")
  const [codeFilter,setCodeFilter]=useState("all")
  const [statusFilter,setStatusFilter]=useState<"active"|"inactive"|"all">("active")
  const [detailTab,setDetailTab]=useState<"summary"|"workers"|"documents"|"contracts"|"severance"|"history">("documents")
  const [workerSearch,setWorkerSearch]=useState("")
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
    const routeId=contractorFromUrl()
    const routeSite=new URLSearchParams(window.location.search).get("obra")
    if(routeId&&routeSite&&siteId&&routeSite!==siteId){
      const url=new URL(window.location.href)
      url.pathname="/contratistas"
      url.searchParams.set("obra",siteId)
      window.history.replaceState({},"",url)
    }
    setSelectedId(routeId && (!routeSite || routeSite===siteId) ? routeId : null);setContractors([]);setWorkers([]);setLoading(false);setHistory(null);setHistoryOpen(false);setContractorForm(null);setWorkerForm(null);setPreview(null);setImportResult(null)
    if(siteId)void loadContractors(siteId)
  },[siteId,loadContractors])
  const visibleContractors=contractors.filter(item=>item.site_id===siteId)
  const selected=visibleContractors.find(item=>item.id===selectedId)||null
  useEffect(()=>{setHistory(null);setHistoryOpen(false);setDetailTab("documents");setWorkerSearch("")},[selectedId])
  useEffect(()=>{
    let valid=true
    setLaborRows([]);setLaborError("");setLaborTotal(0)
    if(!selected||!siteId)return()=>{valid=false}
    const params=new URLSearchParams({site_id:siteId,contractor_id:selected.contractor_id,page_size:"100"})
    void read<{rows:LaborRow[];summary:Record<string,number>}>("/labor/workers?"+params.toString())
      .then(result=>{if(valid){setLaborRows(result.rows);setLaborTotal(result.summary.total||result.rows.length)}})
      .catch(error=>{if(valid)setLaborError(errorText(error))})
    return()=>{valid=false}
  },[siteId,selected?.id,selected?.contractor_id])
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
  useEffect(()=>{
    const onPop=()=>{
      const routeId=contractorFromUrl()
      if(!routeId&&activeSelected.current)restoreListScroll.current=true
      setSelectedId(routeId)
      setContractorForm(null)
      setWorkerForm(null)
    }
    window.addEventListener("popstate",onPop)
    return()=>window.removeEventListener("popstate",onPop)
  },[])
  useEffect(()=>{
    if(selectedId){window.scrollTo({top:0,behavior:"instant"})}
    else if(restoreListScroll.current){
      restoreListScroll.current=false
      window.requestAnimationFrame(()=>window.scrollTo({top:listScroll.current,behavior:"instant"}))
    }
  },[selectedId])
  useEffect(()=>{
    let active=true
    setDocOverview(null);setDocIssue("")
    if(!selected||!documentPeriod)return()=>{active=false}
    void opsControlApi.matrix(siteId,documentPeriod).then(matrix=>{
      if(active)setDocOverview(matrix.contractors.find(c=>c.association_id===selected.id)?.requirements||[])
    }).catch(err=>{if(active)setDocIssue(errorText(err))})
    return()=>{active=false}
  },[siteId,documentPeriod,selected?.id,documentRevision])
  // Una matriz de cumplimiento por obra/período para el listado, sin peticiones por fila.
  useEffect(()=>{
    let active=true
    setListCompliance(null)
    if(!siteId||!period)return()=>{active=false}
    void opsControlApi.matrix(siteId,period).then(matrix=>{
      if(active)setListCompliance(Object.fromEntries(matrix.contractors.map(row=>[row.association_id,summarizeRequirements(row.requirements||[])])))
    }).catch(()=>{if(active)setListCompliance(null)})
    return()=>{active=false}
  },[siteId,period,documentRevision])
  function changeDocumentPeriod(next:string){
    setDocumentPeriod(next)
    if(!selectedId||!next)return
    const url=new URL(window.location.href)
    url.searchParams.set("periodo",next)
    window.history.replaceState(window.history.state,"",url)
  }
  function openContractor(id:string){
    listScroll.current=window.scrollY
    const url=new URL(window.location.href)
    url.pathname="/contratistas/"+encodeURIComponent(id)
    url.searchParams.set("obra",siteId)
    if(period)url.searchParams.set("periodo",period)
    window.history.pushState({galantContractorsDetail:true},"",url)
    setSelectedId(id);setContractorForm(null);setWorkerForm(null)
  }
  function closeContractor(){
    restoreListScroll.current=true
    if(window.history.state?.galantContractorsDetail){window.history.back();return}
    const url=new URL(window.location.href)
    url.pathname="/contratistas"
    url.searchParams.delete("attendance_contractor")
    window.history.replaceState({},"",url)
    setSelectedId(null)
  }
  useEffect(()=>{
    if(!selectedId||contractorFromUrl()!==selectedId||!period)return
    const url=new URL(window.location.href)
    if(url.searchParams.get("periodo")!==period){
      url.searchParams.set("periodo",period)
      window.history.replaceState(window.history.state,"",url)
    }
  },[period,selectedId])
  const docSummary=summarizeRequirements(docOverview||[])
  const pendingDocs=docSummary.pending
  const criticalDocs=docSummary.urgent.length
  const pendingDocsPreview=pendingDocs.slice(0,5)
  const requiredUnits=docSummary.required
  const approvedUnits=docSummary.approved
  const compliance=docSummary.percent
  const filtered=useMemo(()=>visibleContractors.filter(item=>{
    const term=search.trim().toLocaleLowerCase("es-CL")
    const matches=!term||item.name.toLocaleLowerCase("es-CL").includes(term)||(item.rut||"").toLocaleLowerCase("es-CL").includes(term)
    const kind=item.classification
    const active=item.contract_status==="active"
    const summary=listCompliance?.[item.id]
    const statusMatches=complianceFilter==="all" ||
      (complianceFilter==="missing"&&summary!==undefined&&summary.pending.length>0) ||
      (complianceFilter==="critical"&&summary!==undefined&&summary.urgent.length>0) ||
      (complianceFilter==="complete"&&summary!==undefined&&summary.required>0&&summary.pending.length===0) ||
      (complianceFilter==="unevaluable"&&listCompliance!==null&&(summary===undefined||summary.percent===null))
    return matches&&statusMatches&&(statusFilter==="all"||(statusFilter==="active"&&active)||(statusFilter==="inactive"&&!active))&&
      (classificationFilter==='all'||kind===classificationFilter)&&(codeFilter==="all"||
      (codeFilter==="other" ? !["CT","CE","CI"].includes(kind) : kind===codeFilter))
  }).sort((a,b)=>a.name.localeCompare(b.name,"es-CL")),[visibleContractors,search,codeFilter,classificationFilter,statusFilter,complianceFilter,listCompliance])
  useEffect(()=>setListPage(1),[siteId,search,codeFilter,classificationFilter,statusFilter,complianceFilter])
  const totalPages=Math.max(1,Math.ceil(filtered.length/25))
  const safePage=Math.min(listPage,totalPages)
  const currentList=filtered.slice((safePage-1)*25,safePage*25)
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
      nature:item.nature,frequency:item.frequency,contract_status:item.contract_status==="active"?"active":"inactive"
    }:blankContractor(siteId))
    setContractorForm(mode)
  }
  async function saveContractor(event:FormEvent){
    event.preventDefault();if(readOnly||!siteId)return
    setBusy(true);setError("");setNotice("")
    const code=contractorDraft.historical_code?.trim().toUpperCase()||"CT"
    const payload={...contractorDraft,name:contractorDraft.name.trim(),rut:contractorDraft.rut?.trim()||null,
      historical_code:code,
      nature:contractorForm==="new"?(code==="CI"?"independent":"with_workers"):contractorDraft.nature,
      frequency:code==="CE"?"sporadic":code==="CT"?"fixed":contractorDraft.frequency}
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

  const contractorEditor=contractorForm&&<form className="ops-form" onSubmit={event=>void saveContractor(event)}><h3>{contractorForm==="new"?"Nuevo contratista":"Editar contratista"}</h3><div className="ops-form-grid">
        <label>Nombre o razón social<input required maxLength={180} value={contractorDraft.name} onChange={event=>setContractorDraft(current=>({...current,name:event.target.value}))}/></label>
        <label>RUT<input placeholder="12.345.678-5" value={contractorDraft.rut||""} onChange={event=>setContractorDraft(current=>({...current,rut:event.target.value}))}/></label>
        <label>Clasificación (COD)<select value={contractorDraft.historical_code||"CT"} onChange={event=>setContractorDraft(current=>({...current,historical_code:event.target.value}))}><option value="CT">CT · Fijo</option><option value="CE">CE · Esporádico</option><option value="CI">CI · Independiente</option></select></label>
        <label>Estado contractual<select value={contractorDraft.contract_status} onChange={event=>setContractorDraft(current=>({...current,contract_status:event.target.value}))}>{statusOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
      </div><div className="ops-form-actions"><button className="secondary" type="button" onClick={()=>setContractorForm(null)}>Cancelar</button><button className="primary" disabled={busy} type="submit">{busy?<LoaderCircle className="spin" size={16}/>:null} Guardar contratista</button></div></form>;
  return <div className={"ops-workspace"+(selectedId?" ops-isolated-detail":"")}>
    {selectedId ? <div className="ops-focus-header">
      <button type="button" className="secondary ops-back" onClick={closeContractor}><ArrowLeft size={18}/> Volver a contratistas</button>
      {error&&<div className="alert danger" role="alert">{error}</div>}
      {notice&&<div className="alert success" role="status">{notice}</div>}
      {contractorEditor}
      {!selected&&<div className="results-card ops-card ops-focus-loading">{loading?"Cargando ficha del contratista…":"Contratista no disponible en esta obra o sin autorización."}</div>}
      {selected&&<div className="ops-focus-summary ops-v15-summary" aria-label="Resumen documental del contratista">
        <div className="ops-focus-summary-top">
          <div className="ops-v15-identity">
            <span className="eyebrow">FICHA DE CONTRATISTA · {documentPeriod||"Período actual"}</span>
            <h2>{selected.name}</h2>
            <p>{sites.find(site=>site.id===siteId)?.name||"Obra actual"} · {selected.rut||"RUT pendiente"} · {selected.classification} · {String(selected.details?.specialty||"Especialidad sin registrar")}</p>
            <span className={"ops-lifecycle "+(selected.contract_status==="active"?"active":"inactive")}>{selected.contract_status==="active"?"Activo":"Inactivo"}</span>
          </div>
          <div className="ops-v15-head-actions">
            {!readOnly&&<button className="secondary" type="button" onClick={()=>startContractor("edit",selected)}>Editar empresa</button>}
            {detailTab!=="documents"&&<button className="primary" type="button" onClick={()=>setDetailTab("documents")}>Ver documentación <ChevronRight aria-hidden="true" size={16}/></button>}
          </div>
        </div>
        {docIssue&&<p role="alert" className="ops-help">No se pudo consultar el cumplimiento: {docIssue}</p>}
        <div className="ops-focus-metrics ops-v15-metrics" aria-label="Indicadores documentales">
          <div className="ops-v15-compliance">
            <span>Cumplimiento documental</span>
            <strong>{compliance===null?"No evaluable":compliance+"%"}</strong>
            <small>{docOverview?(requiredUnits?approvedUnits+" de "+requiredUnits+" obligaciones aprobadas":"No hay obligaciones evaluables"):"Consultando requisitos…"}</small>
            {compliance!==null&&<div className="ops-v15-progress" role="progressbar" aria-label="Cumplimiento documental" aria-valuenow={compliance} aria-valuemin={0} aria-valuemax={100}><span style={{width:compliance+"%"}}/></div>}
          </div>
          <div className={pendingDocs.length?"warning":"ops-v15-count"}>
            <span>Requisitos por resolver</span>
            <strong>{docOverview?pendingDocs.length:"—"}</strong>
            <small>{docOverview?(criticalDocs?criticalDocs+" con observaciones o vencimientos":"Sin alertas críticas confirmadas"):"Consultando prioridades…"}</small>
          </div>
        </div>
      </div>}
    </div> : <>
    <p>Ficha compartida de contratistas y sus asignaciones por obra.</p>
    {externalSiteId ? <div className="ops-context-bar" aria-label="Contexto de obra actual">
      <span>Obra seleccionada: <strong>{sites.find(site=>site.id===siteId)?.name || "Obra actual"}</strong></span>
      <button type="button" className="secondary" aria-label="Actualizar lista de contratistas" onClick={()=>siteId&&void loadContractors(siteId)}><RefreshCcw size={15}/> Actualizar</button>
    </div> : <div className="ops-toolbar">
      <label>Obra<select aria-label="Seleccionar obra de contratistas" value={siteId} onChange={event=>{setPreview(null);setImportResult(null);setContractors([]);setWorkers([]);setSelectedId(null);setSiteId(event.target.value);onSiteChange?.(event.target.value)}}>{sites.map(site=><option key={site.id} value={site.id}>{site.name}</option>)}</select></label>
      <span className="ops-toolbar-note">Los registros de esta vista pertenecen a la obra seleccionada.</span>
      <button type="button" className="icon-button" aria-label="Actualizar contratistas" title="Actualizar contratistas" onClick={()=>siteId&&void loadContractors(siteId)}><RefreshCcw size={17}/></button>
    </div>}
    {error&&<div role="alert" className="alert danger"><XCircle size={18}/>{error}<button onClick={()=>setError("")}>Cerrar</button></div>}
    {notice&&<div role="status" className="alert success"><CheckCircle2 size={18}/>{notice}<button onClick={()=>setNotice("")}>Cerrar</button></div>}
    <div className="ops-summary" aria-label="Resumen de contratistas y trabajadores">
      <div><strong>{visibleContractors.filter(c=>c.contract_status==="active").length}</strong><span>Contratistas activos</span></div>
      <div><strong>{visibleContractors.filter(c=>c.contract_status!=="active").length}</strong><span>Contratistas inactivos</span></div>
      <div><strong>{visibleContractors.length}</strong><span>Total en la obra</span></div>
      <div><strong>{visibleContractors.filter(c=>c.contract_status==="active").reduce((sum,c)=>sum+c.worker_count,0)}</strong><span>Asignaciones vigentes (activos)</span></div>
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
      {contractorEditor}
      <div className="ops-filters"><label className="ops-search"><Search size={16}/><input placeholder="Buscar por nombre o RUT" value={search} onChange={event=>setSearch(event.target.value)}/></label><div className="ops-status-filters" role="group" aria-label="Filtrar contratistas por estado">{(["active","inactive","all"] as const).map(status=><button type="button" key={status} aria-pressed={statusFilter===status} className={statusFilter===status?"selected":""} onClick={()=>{setStatusFilter(status);setSelectedId(null)}}>{status==="active"?"Activos":status==="inactive"?"Inactivos":"Todos"}</button>)}</div><select aria-label="Filtrar por clasificación" value={codeFilter} onChange={event=>setCodeFilter(event.target.value)}><option value="all">Todas las clasificaciones</option><option value="CT">CT · Fijo</option><option value="CE">CE · Esporádico</option><option value="CI">CI · Independiente</option><option value="other">Sin clasificación válida</option></select>
      <select aria-label="Filtrar por cumplimiento" value={complianceFilter} onChange={event=>setComplianceFilter(event.target.value)} disabled={!listCompliance}><option value="all">Todo cumplimiento</option><option value="critical">Observados o críticos</option><option value="missing">Pendientes de revisión</option><option value="complete">Sin pendientes</option><option value="unevaluable">No evaluables</option></select>
      <span aria-live="polite">{filtered.length} de {visibleContractors.length}</span></div>
      {loading?<div className="ops-empty"><LoaderCircle size={20} className="spin"/> Cargando contratistas…</div>:filtered.length===0?<div className="ops-empty"><Users size={22}/>{visibleContractors.length?"No hay coincidencias":"Aún no hay contratistas en esta obra"}</div>:
      <><div className="table-wrap ops-desktop-list"><table className="ops-list-table ops-contractor-table"><thead><tr><th>CONTRATISTA</th><th>RUT</th><th>COD</th><th>ESTADO</th><th>CUMPLIMIENTO</th><th>PENDIENTES</th><th>TRABAJADORES</th><th>DETALLE</th></tr></thead><tbody>{currentList.map(item=><tr key={item.id} className={selectedId===item.id?"selected-row":""}>
        <td><strong>{item.name}</strong></td><td>{item.rut||"—"}</td><td>{item.classification==="CT"?"CT · Fijo":item.classification==="CE"?"CE · Esporádico":item.classification==="CI"?"CI · Independiente":"Por regularizar"}</td><td><span className={"ops-lifecycle "+(item.contract_status==="active"?"active":"inactive")}>{item.contract_status==="active"?"Activo":"Inactivo"}</span></td><td><span className="ops-v15-list-compliance">{listCompliance?.[item.id]?.percent==null?"No evaluable":listCompliance[item.id].percent+"%"}</span>{listCompliance?.[item.id]?.percent!=null&&<span className="ops-v15-list-track"><span style={{width:listCompliance[item.id].percent+"%"}} /></span>}</td>
        <td><span className={"ops-v15-count-badge "+(listCompliance?.[item.id]?.urgent.length?"urgent":listCompliance?.[item.id]?.pending.length?"pending":"")}>{listCompliance?.[item.id]?listCompliance[item.id].pending.length:"—"}</span></td>
        <td>{item.worker_count}</td>
        <td><button className="row-open" aria-label={`Abrir ficha de ${item.name}`} onClick={()=>openContractor(item.id)}><ChevronRight size={18}/></button></td></tr>)}</tbody></table></div>
      <div className="ops-mobile-list" role="list" aria-label="Contratistas de la obra">
        {currentList.map(item => (
          <article className="ops-mobile-contractor" role="listitem" key={item.id}>
            <div className="ops-mobile-contractor-head">
              <strong>{item.name}</strong>
              <span className={"ops-lifecycle " + (item.contract_status === "active" ? "active" : "inactive")}>
                {item.contract_status === "active" ? "Activo" : "Inactivo"}
              </span>
            </div>
            <p className="ops-mobile-contractor-rut"><span>RUT</span> {item.rut || "Sin registrar"}</p>
            <div className="ops-mobile-contractor-meta">
              <span>{item.classification==="CT"?"CT · Fijo":item.classification==="CE"?"CE · Esporádico":item.classification==="CI"?"CI · Independiente":"Clasificación pendiente"}</span>
              <span>{item.worker_count} {item.worker_count === 1 ? "trabajador" : "trabajadores"}</span>
              <span>Documentación: {listCompliance?.[item.id]?.percent==null?"No evaluable":listCompliance[item.id].percent+"%"}</span>
              <span>Pendientes: {listCompliance?.[item.id]?.pending.length??"—"}</span>
            </div>
            <button type="button" className="ops-mobile-contractor-action" aria-label={`Abrir ficha de ${item.name}`} onClick={() => openContractor(item.id)}>
              Ver ficha <ChevronRight size={17}/>
            </button>
          </article>
        ))}
      </div>
      {totalPages>1&&<nav className="ops-v15-pager" aria-label="Páginas de contratistas">
        <span>Página {safePage} de {totalPages} · {filtered.length} contratistas</span>
        <button type="button" className="secondary" disabled={safePage<=1} onClick={()=>setListPage(p=>Math.max(1,p-1))}>Anterior</button>
        <button type="button" className="secondary" disabled={safePage>=totalPages} onClick={()=>setListPage(p=>Math.min(totalPages,p+1))}>Siguiente</button>
      </nav>}</>}
    </section>
    </>}
    {selected&&<section className="results-card ops-card ops-detail-panel" aria-label="Ficha del contratista">
      <div className="ops-detail-tabs" role="group" aria-label="Secciones de la ficha">
        {(["documents","summary","workers","contracts","severance","history"] as const).map(tab=><button type="button" key={tab} aria-pressed={detailTab===tab} className={detailTab===tab?"selected":""} onClick={()=>{setDetailTab(tab);if(tab==="history"&&!historyOpen)void toggleHistory()}}>{({documents:"Documentación",summary:"Resumen",workers:"Trabajadores",contracts:"Contratos",severance:"Finiquitos",history:"Historial"} as const)[tab]}</button>)}
      </div>
      {detailTab==="summary"&&<div className="ops-detail-content">
        <div className="ops-detail-overview"><div><b>Clasificación</b><span>{selected.classification}</span></div><div><b>Estado</b><span>{selected.contract_status==="active"?"Activo":"Inactivo"}</span></div><div><b>Trabajadores vigentes</b><span>{selected.worker_count}</span></div></div>
        <h3>Información de la empresa y obra</h3>
        {selected.details&&Object.keys(selected.details).length>0?<dl className="contractor-details">{Object.entries(selected.details).filter(([,value])=>value!==null&&value!==undefined&&typeof value!=="object").map(([key,value])=><div key={key}><dt>{({external_id:"ID externo",specialty:"Especialidad",phone:"Teléfono",email:"Correo",legal_representative:"Representante legal",legal_representative_rut:"RUT representante legal",contact:"Contacto"} as Record<string,string>)[key]||key}</dt><dd>{String(value)}</dd></div>)}</dl>:<p className="ops-help">Sin antecedentes adicionales registrados.</p>}
        <button className="secondary" onClick={()=>setDetailTab("workers")}>Ver trabajadores de esta empresa</button>
      </div>}
      {detailTab==="workers"&&<div className="ops-detail-content">
        <div className="ops-detail-toolbar"><h3>Trabajadores y situación laboral</h3><input aria-label="Buscar trabajador" placeholder="Buscar nombre o RUT" value={workerSearch} onChange={e=>setWorkerSearch(e.target.value)}/><button className="secondary" onClick={()=>onWorkers?.()}>Abrir gestión laboral</button></div>
        {laborError&&<p className="ops-help" role="status">No fue posible cargar el estado laboral: {laborError}. Puedes abrir el módulo Trabajadores.</p>}
        {laborTotal>laborRows.length&&<p className="ops-help">Se muestran los primeros {laborRows.length} trabajadores. Consulta el módulo Trabajadores para ver el listado completo.</p>}
        {laborRows.length>0?<div className="table-wrap"><table className="ops-list-table"><thead><tr><th>TRABAJADOR</th><th>RUT</th><th>CONTRATO</th><th>INGRESO</th><th>TÉRMINO</th><th>ESTADO</th><th>FINIQUITO</th><th>FICHA</th></tr></thead><tbody>{laborRows.filter(w=>w.worker_name.toLowerCase().includes(workerSearch.toLowerCase())||(w.worker_rut||"").includes(workerSearch)).map(worker=><tr key={worker.assignment_id}><td><strong>{worker.worker_name}</strong></td><td>{worker.worker_rut}</td><td>{worker.contract_type||"Sin contrato"}</td><td>{laborDate(worker.start_date)}</td><td>{laborDate(worker.end_date)}</td><td>{laborStates[worker.labor_state]||worker.labor_state}</td><td>{laborStates[worker.finiquito_state]||worker.finiquito_state}</td><td><button className="secondary ops-small-button" onClick={()=>onWorkers?.(worker.assignment_id)}>Ver ficha</button></td></tr>)}</tbody></table></div>:
        workers.length===0?<div className="ops-empty">No hay trabajadores asociados a esta empresa en la obra.</div>:<div className="table-wrap"><table className="ops-list-table"><thead><tr><th>TRABAJADOR</th><th>RUT</th><th>ASIGNACIÓN</th><th>FICHA</th></tr></thead><tbody>{workers.filter(w=>w.name.toLowerCase().includes(workerSearch.toLowerCase())||(w.rut||"").includes(workerSearch)).map(worker=><tr key={worker.id}><td><strong>{worker.name}</strong></td><td>{worker.rut||"—"}</td><td>{worker.active?"Vigente":"Inactiva"}</td><td><button className="secondary ops-small-button" onClick={()=>onWorkers?.(worker.id)}>Ver ficha</button></td></tr>)}</tbody></table></div>}
      </div>}
      {(detailTab==="contracts"||detailTab==="severance")&&<div className="ops-detail-content ops-v15-labor-detail">
        <div className="ops-v15-labor-heading">
          <div><h3>{detailTab==="contracts"?"Contratos laborales":"Finiquitos y términos de contrato"}</h3>
          <p>Información laboral registrada del contratista. Las modificaciones se realizan en la ficha del trabajador para conservar trazabilidad.</p></div>
          <button type="button" className="secondary" onClick={()=>onWorkers?.()}>Abrir gestión laboral</button>
        </div>
        {laborError&&<p className="ops-help" role="alert">No fue posible consultar la información laboral: {laborError}</p>}
        {laborTotal>laborRows.length&&<p className="ops-help">Listado parcial: se muestran {laborRows.length} de {laborTotal} registros. Abre Gestión Laboral para consultar todos.</p>}
        <div className="table-wrap"><table className="ops-list-table">
          <thead><tr><th>TRABAJADOR</th><th>RUT</th><th>{detailTab==="contracts"?"TIPO DE CONTRATO":"ESTADO LABORAL"}</th><th>INICIO</th><th>TÉRMINO</th><th>FINIQUITO</th><th>FICHA</th></tr></thead>
          <tbody>{laborRows.filter(row=>detailTab==="contracts"||row.labor_state==="ended"||row.finiquito_state!=="not_applicable").map(row=><tr key={row.assignment_id}>
            <td><strong>{row.worker_name}</strong></td><td>{row.worker_rut||"—"}</td>
            <td>{detailTab==="contracts"?row.contract_type||"Por verificar":laborStates[row.labor_state]||row.labor_state}</td>
            <td>{laborDate(row.start_date)}</td><td>{laborDate(row.end_date)}</td>
            <td>{laborStates[row.finiquito_state]||row.finiquito_state||"Por verificar"}</td>
            <td><button type="button" className="secondary ops-small-button" onClick={()=>onWorkers?.(row.assignment_id)}>Ver ficha</button></td>
          </tr>)}</tbody>
        </table></div>
        {!laborRows.length&&<p className="ops-empty">No hay información laboral registrada para este contratista.</p>}
      </div>}
      {detailTab==="documents"&&<div className="ops-v15-document-layout">
        <div className="ops-v15-document-main"><MonthlyDocuments
          key={selected.id+"-"+period}
          contractor={selected}
          readOnly={readOnly}
          initialPeriod={documentPeriod||period||undefined}
          onPeriodChange={changeDocumentPeriod}
          onReviewed={()=>setDocumentRevision(n=>n+1)}
        /></div>
        <aside className="ops-v15-priorities" aria-label="Prioridades documentales">
          <div className="ops-v15-priority-head"><h3>Requieren atención</h3><span>{docOverview?pendingDocs.length:"—"}</span></div>
          {!docOverview&&<p role="status">Consultando prioridades del período…</p>}
          {docOverview&&pendingDocs.length===0&&<p>No hay requisitos pendientes evaluables en este período.</p>}
          {pendingDocsPreview.map(item=><button type="button" key={item.kind+"|"+(item.subject||"contractor")}
            className={["overdue","observed","rejected"].includes(item.state)?"urgent":""}
            onClick={()=>document.getElementById("monthly-req-"+encodeURIComponent(item.kind)+"-"+encodeURIComponent(item.subject||"contractor"))?.scrollIntoView({behavior:"smooth",block:"center"})}>
            <strong>{item.name||documentNames[item.kind]||item.kind}</strong>
            <small>{statusLabel(item.state)}</small>
            <span>Ver requisito <ChevronRight aria-hidden="true" size={14}/></span>
          </button>)}
          {pendingDocs.length>5&&<p className="ops-v15-priority-more">Y {pendingDocs.length-5} requisito(s) adicional(es) en la tabla.</p>}
        </aside>
      </div>}
      {detailTab==="history"&&<div className="ops-history"><h3>Historial de cambios</h3>{history===null?<p>Cargando historial…</p>:history.length===0?<p>Sin cambios registrados.</p>:<ul>{history.map(change=><li key={change.id}><time>{new Date(change.created_at).toLocaleString("es-CL")}</time><span>{describeChange(change.changes)}</span><small>Registro auditable</small></li>)}</ul>}</div>}
    </section>}
  </div>
}
