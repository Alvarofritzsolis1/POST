import {useCallback,useEffect,useMemo,useState,type FormEvent} from "react"
import {Activity,AlertTriangle,BarChart3,CalendarDays,CheckCircle2,ClipboardCheck,
        FileSpreadsheet,FileText,LoaderCircle,RefreshCcw,ShieldCheck,Users} from "lucide-react"
import {opsApi,type Site,type Worker} from "./opsApi"
import {opsControlApi,type Matrix,type Overview,type Contribution,type ContributionInput,
        type MatrixCompany,type WorkTask,type Contract,type CalendarEntry,type Activity as MonthlyActivity,
        type Alert} from "./opsControlApi"
import HistoricalTrends from "./HistoricalTrends"
import AnalyticsCharts from "./AnalyticsCharts"
import ContractImporter from "./ContractImporter"
import "./control.css"

type Tab="overview"|"documents"|"contributions"|"contracts"|"calendar"|"tasks"|"offboarding"
const tabs:Array<{id:Tab;label:string}>=[
  {id:"overview",label:"Resumen y alertas"},{id:"documents",label:"Matriz documental"},
  {id:"contributions",label:"Cotizaciones y asistencia"},{id:"contracts",label:"Contratos"},
  {id:"calendar",label:"Calendario"},{id:"tasks",label:"Tareas"},
  {id:"offboarding",label:"Bajas"}
]
const kinds=[
  {id:"cotizaciones",name:"Cotizaciones"},{id:"f30_1",name:"F30-1"},
  {id:"liquidaciones",name:"Liquidaciones firmadas"},{id:"asistencia",name:"Asistencia"},
  {id:"porteria",name:"Informe de portería"},{id:"declaracion_jurada",name:"Declaración jurada"},
  {id:"anticipos",name:"Listado de anticipos"}
]
const states:Record<string,string>={
 pending:"Pendiente de revisión",approved:"Aprobado",observed:"Observado",
 rejected:"Rechazado",not_applicable:"No aplica",needs_classification:"Confirmar exigibilidad",
 not_yet_required:"No exigible todavía",overdue:"Vencido",
 schedule_not_configured:"Sin fecha configurada"
}
const number=(n:number|null|undefined)=>n==null?"Sin evaluar":n.toLocaleString("es-CL")
const money=(n:string|number|null|undefined)=>n==null?"Sin evaluar":
  new Intl.NumberFormat("es-CL",{style:"currency",currency:"CLP",maximumFractionDigits:0}).format(Number(n))
const errText=(err:unknown)=>err instanceof Error?err.message:"No se completó la operación"
const periodNow=()=>{const d=new Date();return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")}
const emptyContribution=(association_id:string,period:string):ContributionInput=>({
  association_id,period,worker_assignment_id:null,attendance_days:null,
  required_days:null,paid_days:null,payment_confirmed:false,daily_rate:4950,
  justification:"",notes:"",review_status:"pending",retention_status:"none"
})
const isIndependent=(c:MatrixCompany)=>c.nature==="independent"

export default function ControlCenter({readOnly,externalSiteId,externalPeriod,initialTab,onContextChange}:{readOnly:boolean;externalSiteId?:string;externalPeriod?:string;initialTab?:Tab;onContextChange?:(site:string,period:string)=>void}){
  const [sites,setSites]=useState<Site[]>([])
  const [siteId,setSiteId]=useState("")
  const [period,setPeriod]=useState(periodNow)
  const [tab,setTab]=useState<Tab>(initialTab||"overview")
  useEffect(()=>{if(externalSiteId!==undefined)setSiteId(externalSiteId)},[externalSiteId])
  useEffect(()=>{if(externalPeriod)setPeriod(externalPeriod)},[externalPeriod])
  const [overview,setOverview]=useState<Overview|null>(null)
  const [matrix,setMatrix]=useState<Matrix|null>(null)
  const [contributions,setContributions]=useState<Contribution[]>([])
  const [tasks,setTasks]=useState<WorkTask[]>([])
  const [contracts,setContracts]=useState<Contract[]>([])
  const [calendar,setCalendar]=useState<CalendarEntry[]>([])
  const [activities,setActivities]=useState<MonthlyActivity[]>([])
  const [alerts,setAlerts]=useState<Alert[]>([])
  const [offboarding,setOffboarding]=useState<Array<{id:string;association_id:string;stage:string;status:string;letter_decision:string;notes:string}>>([])
  const [selectedAssoc,setSelectedAssoc]=useState("")
  const [workers,setWorkers]=useState<Worker[]>([])
  const [subject,setSubject]=useState("")
  const [form,setForm]=useState<ContributionInput>(emptyContribution("",periodNow()))
  const [selection,setSelection]=useState<Set<string>>(new Set())
  const [busy,setBusy]=useState(false)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const [taskText,setTaskText]=useState("")
  const [contractType,setContractType]=useState("fixed_term")
  const [contractSubject,setContractSubject]=useState("")
  const [contractStart,setContractStart]=useState("")
  const [contractEnd,setContractEnd]=useState("")
  const [calendarKind,setCalendarKind]=useState("cotizaciones")
  const [calendarRequest,setCalendarRequest]=useState("")
  const [calendarDue,setCalendarDue]=useState("")
  const [calendarAlert,setCalendarAlert]=useState("")
  const [offStage,setOffStage]=useState("requested")
  const [letter,setLetter]=useState("pending")
  const [reason,setReason]=useState("")
  const [activityStatus,setActivityStatus]=useState("unconfirmed")
  const [activityReason,setActivityReason]=useState("")

  useEffect(()=>{let active=true;void opsApi.sites().then(res=>{if(active)setSites(res)})
    .catch(e=>{if(active)setError(errText(e))});return()=>{active=false}},[])
  const reload=useCallback(async()=>{
    const [o,m,c,t,contractsRes,cal,act,al,off]=await Promise.all([
      opsControlApi.overview(period,siteId||null),
      siteId?opsControlApi.matrix(siteId,period):Promise.resolve(null),
      opsControlApi.contributions(period,siteId||null),
      opsControlApi.tasks(siteId||null),
      opsControlApi.contracts(siteId||null),
      opsControlApi.calendar(period,siteId||null),
      siteId?opsControlApi.activity(siteId,period):Promise.resolve([]),
      opsControlApi.alerts(siteId||null),
      opsControlApi.offboarding(siteId||null)
    ])
    setOverview(o);setMatrix(m);setContributions(c);setTasks(t)
    setContracts(contractsRes);setCalendar(cal);setActivities(act)
    setAlerts(al.alerts);setOffboarding(off);setError("")
    if(m&&!selectedAssoc&&m.contractors[0])setSelectedAssoc(m.contractors[0].association_id)
  },[siteId,period,selectedAssoc])
  useEffect(()=>{let active=true;setLoading(true);setSelection(new Set())
    void reload().catch(e=>{if(active)setError(errText(e))}).finally(()=>{if(active)setLoading(false)})
    const id=window.setInterval(()=>{if(active)void reload().catch(()=>{})},60000)
    return()=>{active=false;window.clearInterval(id)}
  },[reload])
  const currentCompany=matrix?.contractors.find(x=>x.association_id===selectedAssoc)||null
  useEffect(()=>{let active=true;setWorkers([]);setSubject("")
    if(siteId&&currentCompany)void opsApi.workers(siteId,currentCompany.contractor_id).then(rows=>{
      if(active)setWorkers(rows)
    }).catch(e=>{if(active)setError(errText(e))})
    return()=>{active=false}
  },[siteId,currentCompany?.association_id,currentCompany?.contractor_id])
  useEffect(()=>{
    const base=emptyContribution(selectedAssoc,period)
    const record=contributions.find(x=>x.association_id===selectedAssoc&&
      x.subject_key===(currentCompany&&isIndependent(currentCompany)?"independent":subject))
    if(record){
      setForm({...base,worker_assignment_id:record.worker_assignment_id,
        attendance_days:record.attendance_days,required_days:record.required_days,
        paid_days:record.paid_days,payment_confirmed:record.payment_confirmed,
        daily_rate:Number(record.daily_rate),justification:record.justification,notes:record.notes,
        review_status:record.review_status as ContributionInput["review_status"],
        retention_status:record.retention_status as ContributionInput["retention_status"]})
    }else setForm({...base,worker_assignment_id:currentCompany&&isIndependent(currentCompany)?null:subject||null})
  },[selectedAssoc,subject,period,contributions,currentCompany?.association_id])

  async function perform(action:()=>Promise<unknown>,message:string){
    setBusy(true);setError("");setNotice("")
    try{await action();await reload();setNotice(message)}
    catch(e){setError(errText(e))}
    finally{setBusy(false)}
  }
  function review(association_id:string,kind:string,status:string){
    if(readOnly)return
    let notes=""
    if(status==="observed"||status==="rejected"||status==="not_applicable"){
      const entered=window.prompt("Indica el motivo de "+(states[status]||status).toLowerCase()+":")
      if(entered===null)return
      notes=entered.trim()
      if(!notes){setError("La observación es obligatoria");return}
    }
    void perform(()=>opsControlApi.reviews({association_id,period,kind,status,notes}),
      "Revisión manual registrada y compartida con los demás usuarios.")
  }
  function applicability(association_id:string,kind:string,applicable:boolean){
    if(readOnly)return
    const explanation=window.prompt("Justificación de la exigibilidad de "+kind+":")
    if(explanation===null)return
    if(explanation.trim().length<3){setError("Debes indicar una justificación");return}
    void perform(()=>opsControlApi.applicability({association_id,period,kind,
      applicable,justification:explanation.trim()}),"Regla de exigibilidad guardada.")
  }
  function toggleSelected(key:string,checked:boolean){
    setSelection(previous=>{const next=new Set(previous);checked?next.add(key):next.delete(key);return next})
  }
  function bulkApprove(){
    if(!matrix||!selection.size||readOnly)return
    const confirmed=window.confirm("¿Aprobar manualmente "+selection.size+" requisitos seleccionados? Se registrará tu usuario y fecha.")
    if(!confirmed)return
    const reviews=Array.from(selection).map(key=>{
      const [association_id,kind]=key.split("|")
      return {association_id,period,kind,status:"approved",notes:"Aprobación manual masiva"}
    })
    void perform(()=>opsControlApi.bulk(reviews),"Aprobaciones registradas.").then(()=>setSelection(new Set()))
  }
  async function saveContribution(event:FormEvent){
    event.preventDefault()
    if(!selectedAssoc||!currentCompany||readOnly||(!isIndependent(currentCompany)&&!subject))return
    await perform(()=>opsControlApi.saveContribution({...form,association_id:selectedAssoc,
      worker_assignment_id:currentCompany&&isIndependent(currentCompany)?null:subject,
      required_days:form.attendance_days,period}),
      "Control de cotizaciones y asistencia actualizado.")
  }
  async function saveTask(event:FormEvent){
    event.preventDefault()
    if(!siteId||!taskText.trim())return
    await perform(()=>opsControlApi.createTask({worksite_id:siteId,
      association_id:selectedAssoc||null,period,title:taskText.trim(),
      kind:"manual",priority:"normal",notes:""}),"Tarea agregada.")
    setTaskText("")
  }
  async function saveContract(event:FormEvent){
    event.preventDefault()
    if(!selectedAssoc||!contractStart||readOnly)return
    await perform(()=>opsControlApi.saveContract({association_id:selectedAssoc,
      worker_assignment_id:contractSubject||null,contract_type:contractType,start_date:contractStart,
      end_date:contractType==="indefinite"?null:contractEnd||null,status:"active",notes:""}),
      "Vigencia contractual registrada.")
  }
  async function saveCalendar(event:FormEvent){
    event.preventDefault()
    if(!siteId||!calendarRequest||!calendarDue)return
    await perform(()=>opsControlApi.saveCalendar({worksite_id:siteId,period,kind:calendarKind,
      request_date:calendarRequest,due_date:calendarDue,alert_date:calendarAlert||null}),
      "Calendario actualizado. Las fechas no se generan automáticamente.")
  }
  async function saveOffboarding(event:FormEvent){
    event.preventDefault()
    if(!selectedAssoc)return
    await perform(()=>opsControlApi.saveOffboarding({association_id:selectedAssoc,
      stage:offStage,letter_decision:letter,letter_reason:reason,notes:reason}),
      "Proceso administrativo guardado sin dar de baja automáticamente.")
  }
  const selectedCount=selection.size
  const summary=overview?.totals
  const days=form.attendance_days!=null&&form.paid_days!=null&&currentCompany&&!isIndependent(currentCompany)
    ?Math.max(0,form.attendance_days-form.paid_days):null
  const amount=days==null?null:days*form.daily_rate
  const existingActivity=activities.find(a=>a.association_id===selectedAssoc)
  const siteName=sites.find(s=>s.id===siteId)?.name||"Todas las obras"
  return <div className="control-workspace">
    <header className="control-heading">
      <div><span className="eyebrow">GALANT · CENTRO DE CONTROL OPERATIVO</span>
        <h1>Gestión de contratistas</h1><p>Datos manuales y Excel. La revisión OCR es opcional y no determina tus decisiones administrativas.</p></div>
      <button className="secondary" type="button" disabled={loading||busy} onClick={()=>void reload().catch(e=>setError(errText(e)))}><RefreshCcw size={17}/> Actualizar</button>
    </header>
    <div className="control-toolbar">
      <label>Obra<select value={siteId} onChange={e=>{setSiteId(e.target.value);onContextChange?.(e.target.value,period);setSelectedAssoc("")}}>
        <option value="">Consolidado general · tres obras</option>
        {sites.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
      </select></label>
      <label>Mes auditado<input type="month" value={period} min="2000-01" max="2099-12"
        onChange={e=>{setPeriod(e.target.value);onContextChange?.(siteId,e.target.value)}}/></label>
      <span className="control-context">{siteName} · {period}</span>
      <a className="secondary control-download" href={"/api/v1"+opsControlApi.excelMensual(period,siteId||null)}><FileSpreadsheet size={16}/> Exportar matriz</a>
      <a className="secondary control-download" href={"/api/v1"+opsControlApi.excelCotizaciones(period,siteId||null)}><FileSpreadsheet size={16}/> Informe CT/CI</a>
    </div>
    <nav className="control-tabs" aria-label="Módulos de control">{tabs.map(t=><button key={t.id}
      type="button" className={tab===t.id?"active":""} aria-current={tab===t.id?"page":undefined}
      onClick={()=>setTab(t.id)}>{t.label}</button>)}</nav>
    {error&&<p className="alert danger" role="alert"><AlertTriangle size={18}/>{error}</p>}
    {notice&&<p className="alert success" role="status"><CheckCircle2 size={18}/>{notice}</p>}
    {loading?<div className="control-loading"><LoaderCircle size={24} className="spin"/> Recuperando registros compartidos…</div>:<>
      {tab==="overview"&&<div className="control-stack">
        <div className="control-metrics">
          {[{icon:Users,label:"Contratistas CT",value:summary?.ct??0},
            {icon:Users,label:"Independientes CI",value:summary?.ci??0},
            {icon:Activity,label:"Esporádicos",value:summary?.sporadic??0},
            {icon:ShieldCheck,label:"Cumplimiento",value:overview?.compliance==null?"Sin evaluar":overview.compliance+"%"},
            {icon:ClipboardCheck,label:"Avance de revisión",value:overview?.progress==null?"Sin evaluar":overview.progress+"%"},
            {icon:AlertTriangle,label:"Días faltantes",value:summary?.days_missing??0},
            {icon:FileText,label:"Retenciones sugeridas",value:money(summary?.retention_proposed)},
            {icon:CalendarDays,label:"Contratos por vencer",value:summary?.expiring_contracts??0}
          ].map(metric=><div className="control-metric" key={metric.label}><metric.icon size={18}/>
            <span>{metric.label}</span><strong>{metric.value}</strong></div>)}
        </div>
        <section className="control-card"><h2>Comparación de obras</h2>
          <p>El consolidado suma requisitos evaluables; no promedia los porcentajes de las obras.</p>
          {overview?.sites.map(s=><div key={s.site_id} className="control-site-row">
            <div><strong>{s.site}</strong><span>{s.contractors} contratistas · {s.workers} trabajadores</span></div>
            <div className="control-bar" role="progressbar" aria-valuenow={s.compliance??0} aria-valuemin={0} aria-valuemax={100}>
              <span style={{width:(s.compliance??0)+"%"}}/></div>
            <strong>{s.compliance==null?"Sin evaluar":s.compliance+"%"}</strong>
          </div>)}
        </section>
        <HistoricalTrends period={period} siteId={siteId||null}/>
        <AnalyticsCharts period={period} siteId={siteId||null}/>
        <section className="control-card"><h2>Situaciones que requieren gestión</h2>
          <p>{alerts.length} alertas o actividades abiertas. No se aplican retenciones ni bajas automáticamente.</p>
          {alerts.slice(0,18).map((a,i)=><div className="control-alert" key={a.reference_id+"-"+i}>
            <span className={"control-priority "+a.priority}>{a.priority}</span><strong>{a.message}</strong>
            <small>{a.date||"Sin fecha programada"}</small></div>)}
          {alerts.length===0&&<p>Sin alertas registradas. Esto no confirma que toda la documentación esté aprobada.</p>}
        </section>
      </div>}
      {tab==="documents"&&<section className="control-card">
        <h2>Matriz de siete requisitos</h2><p>Permite registrar aprobaciones manuales sin PDF, con trazabilidad y controles de aplicabilidad.</p>
        {!siteId?<p>Selecciona una obra para revisar y aprobar sus obligaciones.</p>:<>
        {!readOnly&&<div className="control-bulk"><strong>{selectedCount} seleccionados</strong>
          <button className="primary" disabled={!selectedCount||busy} onClick={bulkApprove}>Aprobar seleccionados</button></div>}
        {matrix?.contractors.map(c=><details className="control-company" key={c.association_id}>
          <summary><strong>{c.name}</strong><span>{c.code||"Sin código"} · {c.nature} · {c.rut||"Sin RUT"}</span></summary>
          <div className="table-wrap"><table className="control-table"><thead><tr><th>Seleccionar</th><th>Requisito</th><th>Exigibilidad</th><th>Estado</th><th>Gestión</th></tr></thead><tbody>
          {c.requirements.map(r=><tr key={r.kind}><td><input type="checkbox"
            aria-label={"Seleccionar "+c.name+" "+r.kind} disabled={readOnly||busy||r.applicable!==true}
            checked={selection.has(c.association_id+"|"+r.kind)}
            onChange={e=>toggleSelected(c.association_id+"|"+r.kind,e.target.checked)}/></td>
            <td><strong>{kinds.find(k=>k.id===r.kind)?.name||r.kind}</strong>
              <small>{r.source==="manual_without_pdf"?"Revisión manual sin PDF":r.source==="document"?"Con respaldo digital":""}</small></td>
            <td>{r.applicable===null?"Por confirmar":r.applicable?"Sí":"No"}
              {!readOnly&&r.applicable===null&&<div className="control-cell-actions">
                <button className="secondary" disabled={busy} onClick={()=>applicability(c.association_id,r.kind,true)}>Exigir</button>
                <button className="secondary" disabled={busy} onClick={()=>applicability(c.association_id,r.kind,false)}>No exigir</button>
              </div>}</td>
            <td><span className={"control-state "+r.state}>{states[r.state]||r.state}</span>
              {r.notes&&<small>{r.notes}</small>}{r.due_date&&<small>Vence: {r.due_date}</small>}</td>
            <td>{!readOnly&&r.applicable===true?<div className="control-cell-actions">
              <button type="button" disabled={busy} onClick={()=>review(c.association_id,r.kind,"approved")}>Aprobar</button>
              <button type="button" disabled={busy} onClick={()=>review(c.association_id,r.kind,"observed")}>Observar</button>
              <button type="button" disabled={busy} onClick={()=>review(c.association_id,r.kind,"pending")}>Pendiente</button>
              <button type="button" disabled={busy} onClick={()=>review(c.association_id,r.kind,"not_applicable")}>No aplica</button>
            </div>:"—"}</td></tr>)}
          </tbody></table></div>
        </details>)}
        {matrix?.contractors.length===0&&<p>Aún no hay contratistas en esta obra. Agrégalos desde «Obras y personas».</p>}
        </>}
      </section>}
      {tab==="contributions"&&<section className="control-card"><h2>Control manual de cotizaciones y asistencia</h2>
        <p>Compara asistencia y días cotizados. Registra excepciones justificadas; confirmar manualmente no reemplaza la evidencia de Previred.</p>
        {!siteId?<p>Selecciona una obra para registrar días y cotizaciones.</p>:<>
        <label>Contratista<select value={selectedAssoc} onChange={e=>setSelectedAssoc(e.target.value)}>
          <option value="">Seleccionar</option>{matrix?.contractors.map(c=><option key={c.association_id} value={c.association_id}>{c.name} · {c.code||"Otro"}</option>)}
        </select></label>
        {currentCompany&&<><div className="control-activity">
          <strong>Actividad en el mes</strong>
          <span>{existingActivity?.status==="no_movements"?"Sin movimientos":existingActivity?.status==="with_movements"?"Con movimientos":"Pendiente de confirmar"}</span>
          {!readOnly&&<><select value={activityStatus} onChange={e=>setActivityStatus(e.target.value)}>
            <option value="unconfirmed">Pendiente</option><option value="with_movements">Con movimientos</option>
            <option value="no_movements">Sin movimientos</option></select>
            <input value={activityReason} onChange={e=>setActivityReason(e.target.value)}
              placeholder="Motivo (obligatorio si no hubo movimientos)"/>
            <button className="secondary" disabled={busy} onClick={()=>void perform(()=>
              opsControlApi.saveActivity({association_id:selectedAssoc,period,
              status:activityStatus,reason:activityReason}),"Actividad mensual registrada.")}>Guardar actividad</button></>}
          </div>
          <form className="control-form" onSubmit={event=>void saveContribution(event)}>
            {!isIndependent(currentCompany)?<label>Trabajador
              <select value={subject} required onChange={e=>setSubject(e.target.value)}>
                <option value="">Seleccionar trabajador</option>{workers.map(w=><option key={w.id} value={w.id}>{w.name} · {w.rut||""}</option>)}
              </select></label>:<p><strong>Independiente:</strong> registro directo a nombre del contratista, sin trabajador ficticio ni retención diaria automática.</p>}
            <div className="control-form-grid">
              <label>Días de asistencia<input type="number" min="0" max="31" value={form.attendance_days??""}
                onChange={e=>{const days=e.target.value===""?null:Number(e.target.value);
                  setForm(f=>({...f,attendance_days:days,required_days:days}))}}/></label>
              <label>Días cotizados<input type="number" min="0" max="31" value={form.paid_days??""}
                onChange={e=>setForm(f=>({...f,paid_days:e.target.value===""?null:Number(e.target.value)}))}/></label>
              <label>Tarifa diaria CLP<input type="number" min="0" step="0.01" value={form.daily_rate}
                disabled={isIndependent(currentCompany)} onChange={e=>setForm(f=>({...f,daily_rate:Number(e.target.value)}))}/></label>
              <label>Estado de revisión<select value={form.review_status}
                onChange={e=>setForm(f=>({...f,review_status:e.target.value as ContributionInput["review_status"]}))}>
                <option value="pending">Pendiente</option><option value="approved">Aprobado manualmente</option><option value="observed">Observado</option>
              </select></label>
              <label>Estado de retención<select value={form.retention_status} disabled={isIndependent(currentCompany)}
                onChange={e=>setForm(f=>({...f,retention_status:e.target.value as ContributionInput["retention_status"]}))}>
                <option value="none">Sin acción</option><option value="proposed">Propuesta</option><option value="justified">Justificada</option>
                <option value="confirmed">Confirmada por administrador</option><option value="resolved">Resuelta</option>
              </select></label>
            </div>
            <label className="control-check"><input type="checkbox" checked={form.payment_confirmed}
              onChange={e=>setForm(f=>({...f,payment_confirmed:e.target.checked}))}/> Confirmo manualmente el pago de cotizaciones</label>
            <label>Justificación de la diferencia<input value={form.justification}
              maxLength={2000} onChange={e=>setForm(f=>({...f,justification:e.target.value}))}/></label>
            <label>Observaciones<input value={form.notes} maxLength={2000}
              onChange={e=>setForm(f=>({...f,notes:e.target.value}))}/></label>
            <div className="control-calc"><span>Días faltantes: <strong>{number(days)}</strong></span>
              <span>Retención sugerida: <strong>{money(amount)}</strong></span></div>
            {!readOnly&&<button className="primary" disabled={busy||(!isIndependent(currentCompany)&&!subject)}>Guardar control</button>}
          </form></>}
        </>}
        <div className="table-wrap"><table className="control-table"><thead><tr><th>Contratista / trabajador</th><th>Asistencia</th><th>Pagados</th><th>Faltantes</th><th>Retención sugerida</th><th>Pago</th></tr></thead><tbody>
        {contributions.filter(c=>!siteId||c.site_id===siteId).map(c=><tr key={c.id}>
          <td><strong>{c.contractor}</strong><small>{c.worker||"Independiente"} · {c.code}</small></td>
          <td>{c.attendance_days??"—"}</td><td>{c.paid_days??"—"}</td>
          <td>{c.missing_days??"No comparable"}</td><td>{money(c.retention_suggested)}</td>
          <td>{c.payment_confirmed?"Confirmado manualmente":"Sin confirmar"}</td></tr>)}
        </tbody></table></div>
      </section>}
      {tab==="contracts"&&<><section className="control-card"><h2>Contratos y vigencias</h2>
        <p>Alertas para 30, 15 y 7 días. Los indefinidos no vencen por carecer de fecha de término.</p>
        {siteId&&!readOnly&&<form className="control-form-inline" onSubmit={event=>void saveContract(event)}>
          <label>Contratista<select value={selectedAssoc} onChange={e=>setSelectedAssoc(e.target.value)}>
            <option value="">Seleccionar</option>{matrix?.contractors.map(c=><option key={c.association_id} value={c.association_id}>{c.name}</option>)}</select></label>
          <label>Contrato de<select value={contractSubject} onChange={e=>setContractSubject(e.target.value)}><option value="">Contratista</option>{workers.map(w=><option key={w.id} value={w.id}>Trabajador: {w.name}</option>)}</select></label>
          <label>Tipo<select value={contractType} onChange={e=>setContractType(e.target.value)}>
            <option value="fixed_term">Plazo fijo</option><option value="indefinite">Indefinido</option>
            <option value="project">Por obra</option><option value="services">Servicios</option></select></label>
          <label>Inicio<input required type="date" value={contractStart} onChange={e=>setContractStart(e.target.value)}/></label>
          <label>Término<input type="date" disabled={contractType==="indefinite"} value={contractEnd} onChange={e=>setContractEnd(e.target.value)}/></label>
          <button className="primary" disabled={busy||!selectedAssoc}>Registrar contrato</button></form>}
        <div className="table-wrap"><table className="control-table"><thead><tr><th>Contratista</th><th>Tipo</th><th>Inicio</th><th>Término</th><th>Vigencia</th></tr></thead><tbody>
          {contracts.map(c=><tr key={c.id}><td>{matrix?.contractors.find(x=>x.association_id===c.association_id)?.name||c.association_id.slice(0,8)}</td>
            <td>{c.contract_type}</td><td>{c.start_date}</td><td>{c.end_date||"Indefinido / sin fecha"}</td>
            <td>{c.expiry_alert||c.status}</td></tr>)}
        </tbody></table></div>
      </section>
      {siteId&&tab==="contracts"&&!readOnly&&<ContractImporter siteId={siteId} onImported={()=>{void reload().catch(e=>setError(errText(e)))}}/>}
      </>}
      {tab==="calendar"&&<section className="control-card"><h2>Calendario de exigibilidad</h2>
        <p>La solicitud se activa desde la fecha configurada; antes no se marcará vencido.</p>
        {siteId&&!readOnly&&<form className="control-form-inline" onSubmit={event=>void saveCalendar(event)}>
          <label>Documento<select value={calendarKind} onChange={e=>setCalendarKind(e.target.value)}>
            {kinds.map(k=><option value={k.id} key={k.id}>{k.name}</option>)}</select></label>
          <label>Inicio de solicitud<input type="date" required value={calendarRequest} onChange={e=>setCalendarRequest(e.target.value)}/></label>
          <label>Fecha límite<input type="date" required value={calendarDue} onChange={e=>setCalendarDue(e.target.value)}/></label>
          <label>Alerta desde<input type="date" value={calendarAlert} onChange={e=>setCalendarAlert(e.target.value)}/></label>
          <button className="primary" disabled={busy}>Guardar calendario</button></form>}
        <div className="table-wrap"><table className="control-table"><thead><tr><th>Obra</th><th>Requisito</th><th>Inicio solicitud</th><th>Fecha límite</th><th>Alerta</th></tr></thead><tbody>
          {calendar.map(c=><tr key={c.id}><td>{sites.find(s=>s.id===c.worksite_id)?.name||"Obra"}</td>
            <td>{kinds.find(k=>k.id===c.kind)?.name||c.kind}</td>
            <td>{c.request_date}</td><td>{c.due_date}</td><td>{c.alert_date||"No configurada"}</td></tr>)}
        </tbody></table></div>
      </section>}
      {tab==="tasks"&&<section className="control-card"><h2>Gestión de tareas</h2>
        {siteId&&!readOnly&&<form className="control-form-inline" onSubmit={event=>void saveTask(event)}>
          <label>Descripción<input value={taskText} onChange={e=>setTaskText(e.target.value)}
            required maxLength={240} placeholder="Gestión administrativa pendiente"/></label>
          <button className="primary" disabled={busy||!taskText.trim()}>Crear tarea</button></form>}
        <div className="table-wrap"><table className="control-table"><thead><tr><th>Actividad</th><th>Prioridad</th><th>Responsable</th><th>Fecha límite</th><th>Estado</th><th>Acción</th></tr></thead><tbody>
          {tasks.map(t=><tr key={t.id}><td>{t.title}<small>{t.kind}</small></td>
            <td>{t.priority}</td><td>{t.assigned_to||"Sin asignar"}</td>
            <td>{t.due_date||"Sin fecha"}</td><td>{t.status}</td><td>{!readOnly&&t.status==="open"&&<button className="secondary"
              disabled={busy} onClick={()=>void perform(()=>opsControlApi.updateTask(t.id,{status:"resolved",notes:t.notes,assigned_to:t.assigned_to}),"Tarea resuelta.")}>Resolver</button>}</td></tr>)}
        </tbody></table></div>
      </section>}
      {tab==="offboarding"&&<section className="control-card"><h2>Bajas y cartas de término</h2>
        <p>La ausencia de movimientos crea una tarea de revisión, no una baja ni carta automática.</p>
        {siteId&&!readOnly&&<form className="control-form-inline" onSubmit={event=>void saveOffboarding(event)}>
          <label>Contratista<select value={selectedAssoc} onChange={e=>setSelectedAssoc(e.target.value)}>
            <option value="">Seleccionar</option>{matrix?.contractors.map(c=><option value={c.association_id} key={c.association_id}>{c.name}</option>)}</select></label>
          <label>Etapa<select value={offStage} onChange={e=>setOffStage(e.target.value)}>
            {["requested","background_review","contract_review","letter_decision","preparation","sent","closed"].map(v=><option key={v} value={v}>{v}</option>)}</select></label>
          <label>¿Corresponde carta?<select value={letter} onChange={e=>setLetter(e.target.value)}>
            <option value="pending">Por definir</option><option value="required">Sí</option>
            <option value="not_required">No corresponde</option></select></label>
          <label>Justificación<input value={reason} maxLength={2000} onChange={e=>setReason(e.target.value)}/></label>
          <button className="primary" disabled={busy||!selectedAssoc}>Registrar etapa</button></form>}
        <div className="table-wrap"><table className="control-table"><thead><tr><th>Contratista</th><th>Etapa</th><th>Carta</th><th>Estado</th></tr></thead><tbody>
          {offboarding.map(o=><tr key={o.id}><td>{matrix?.contractors.find(x=>x.association_id===o.association_id)?.name||o.association_id.slice(0,8)}</td>
            <td>{o.stage}</td><td>{o.letter_decision}</td><td>{o.status}</td></tr>)}
        </tbody></table></div>
      </section>}
    </>}
  </div>
}
