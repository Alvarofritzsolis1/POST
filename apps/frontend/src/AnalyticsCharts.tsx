import {useEffect,useState} from "react"
import {BarChart3,CalendarClock,FileCheck2,AlertTriangle,LoaderCircle} from "lucide-react"
import {opsControlApi,type OperationalAnalytics} from "./opsControlApi"

const categories=[
  {key:"approved",label:"Aprobado",color:"#197f5c"},
  {key:"pending",label:"Pendiente",color:"#daa23e"},
  {key:"observed",label:"Observado",color:"#e16c39"},
  {key:"overdue",label:"Vencido",color:"#c83a42"},
  {key:"rejected",label:"Rechazado",color:"#8a2b3f"},
  {key:"not_yet_required",label:"No exigible aún",color:"#688fb2"},
  {key:"needs_classification",label:"Por clasificar",color:"#8e82ad"},
  {key:"schedule_not_configured",label:"Sin calendario",color:"#a5acb9"},
  {key:"not_applicable",label:"No aplica",color:"#d6dce6"}
]
const contractCategories=[
  {key:"expired",label:"Vencido",color:"#c83a42"},
  {key:"7_days",label:"Hasta 7 días",color:"#e16c39"},
  {key:"15_days",label:"Hasta 15 días",color:"#d99c40"},
  {key:"30_days",label:"Hasta 30 días",color:"#6395bc"},
  {key:"not_due",label:"Vigente / futuro",color:"#268569"},
  {key:"no_end_date",label:"Sin término",color:"#859bb1"}
]
const clp=(value:string|number)=>new Intl.NumberFormat("es-CL",{style:"currency",currency:"CLP",maximumFractionDigits:0}).format(Number(value))
const errorText=(error:unknown)=>error instanceof Error?error.message:"No fue posible recuperar las estadísticas"

export default function AnalyticsCharts({period,siteId}:{period:string;siteId:string|null}){
  const [data,setData]=useState<OperationalAnalytics|null>(null)
  const [error,setError]=useState("")
  const [busy,setBusy]=useState(true)
  useEffect(()=>{
    let active=true;setBusy(true);setError("")
    void opsControlApi.analytics(period,siteId).then(result=>{
      if(active){setData(result);setBusy(false)}
    }).catch(err=>{if(active){setBusy(false);setError(errorText(err))}})
    return()=>{active=false}
  },[period,siteId])
  if(busy)return <section className="control-card"><LoaderCircle className="spin" size={18}/> Calculando indicadores por obra…</section>
  if(error)return <section className="control-card" role="alert">{error}</section>
  if(!data)return null
  const filtered=data.worksites
  return <div className="control-analytics">
    <section className="control-card">
      <h2><BarChart3 size={18}/> Distribución de contratistas</h2>
      <p>CT y CI son códigos históricos. Esporádico es una frecuencia que puede coincidir con otro código.</p>
      <div className="control-category-grid">
        {[
          {key:"ct",label:"Fijos CT"},
          {key:"ci",label:"Independientes CI"},
          {key:"other",label:"Otros códigos"},
          {key:"sporadic",label:"Esporádicos"}
        ].map(item=><div className="control-category-stat" key={item.key}>
          <strong>{data.distribution[item.key]??0}</strong><span>{item.label}</span></div>)}
      </div>
    </section>
    <section className="control-card"><h2><FileCheck2 size={18}/> Estados documentales por obra</h2>
      <p>La distribución separa no exigibles, pendientes, observados y documentos aprobados.</p>
      {filtered.map(worksite=>{
        const total=Object.values(worksite.document_states).reduce((sum,value)=>sum+value,0)
        return <div className="control-chart-row" key={worksite.site_id}>
          <div className="control-chart-label"><strong>{worksite.site}</strong><small>{total} requisitos clasificados</small></div>
          <div className="control-stacked" aria-label={"Estados documentales "+worksite.site}>
            {categories.map(cat=><div key={cat.key} style={{width:total?((worksite.document_states[cat.key]??0)*100/total)+"%":"0%",background:cat.color}}
              title={cat.label+": "+(worksite.document_states[cat.key]??0)}/>)}
          </div>
          <strong>{worksite.document_states.approved??0} aprobados</strong>
        </div>
      })}
      <div className="control-legend">{categories.map(x=><span key={x.key}><i style={{background:x.color}}/>{x.label}: {data.document_states[x.key]??0}</span>)}</div>
    </section>
    <section className="control-card"><h2><CalendarClock size={18}/> Contratos y vencimientos</h2>
      {filtered.map(worksite=>{
        const total=Object.values(worksite.contract_expiry).reduce((sum,value)=>sum+value,0)
        return <div key={worksite.site_id} className="control-chart-row">
          <div className="control-chart-label"><strong>{worksite.site}</strong><small>{total} registros de contratos</small></div>
          <div className="control-stacked" aria-label={"Vencimientos "+worksite.site}>
            {contractCategories.map(cat=><div key={cat.key} style={{width:total?((worksite.contract_expiry[cat.key]??0)*100/total)+"%":"0%",background:cat.color}}
              title={cat.label+": "+(worksite.contract_expiry[cat.key]??0)}/>)}
          </div><strong>{worksite.contract_expiry.expired??0} vencidos</strong>
        </div>
      })}
      <div className="control-legend">{contractCategories.map(x=><span key={x.key}><i style={{background:x.color}}/>{x.label}: {data.contract_expiry[x.key]??0}</span>)}</div>
    </section>
    <section className="control-card"><h2><AlertTriangle size={18}/> Excepciones previsionales por obra</h2>
      <div className="control-exception-grid">
        {filtered.map(s=><div className="control-exception-item" key={s.site_id}>
          <strong>{s.site}</strong>
          <div><span>Días faltantes</span><b>{s.missing_days}</b></div>
          <div><span>Retención sugerida</span><b>{clp(s.retention_suggested)}</b></div>
          <div><span>Pagos sin confirmar</span><b>{s.unverified_payments}</b></div>
          <div><span>Tareas abiertas</span><b>{s.open_tasks}</b></div>
        </div>)}
      </div>
    </section>
  </div>
}
