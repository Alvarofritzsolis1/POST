import {useEffect,useMemo,useState} from "react"
import {Activity,BarChart3,LoaderCircle} from "lucide-react"
import {opsControlApi,type HistoricalTrend} from "./opsControlApi"

const palette=["#1f649a","#0d9778","#b56b35","#784db1","#384e69"]
const metricName={compliance:"Cumplimiento aprobado",progress:"Avance de revisión"}
type Metric=keyof typeof metricName
const message=(e:unknown)=>e instanceof Error?e.message:"Error de lectura"

function lineSegments(values:(number|null)[],width:number,height:number){
  const step=values.length>1?width/(values.length-1):0
  const paths:string[]=[]
  let path=""
  values.forEach((value,i)=>{
    if(value==null){
      if(path)paths.push(path)
      path=""
    }else{
      const x=55+step*i
      const y=height-20-value/100*(height-40)
      path+=(path?" L":"M")+x.toFixed(1)+","+y.toFixed(1)
    }
  })
  if(path)paths.push(path)
  return paths
}

export default function HistoricalTrends({period,siteId}:{period:string;siteId:string|null}){
  const [months,setMonths]=useState(12)
  const [metric,setMetric]=useState<Metric>("compliance")
  const [data,setData]=useState<HistoricalTrend|null>(null)
  const [error,setError]=useState("")
  const [loading,setLoading]=useState(true)
  useEffect(()=>{
    let active=true
    setLoading(true);setError("")
    void opsControlApi.trends(period,siteId,months).then(value=>{
      if(active){setData(value);setLoading(false)}
    }).catch(e=>{if(active){setError(message(e));setLoading(false)}})
    return()=>{active=false}
  },[period,siteId,months])
  const curves=useMemo(()=>{
    if(!data)return []
    const total={label:"Consolidado",color:palette[0],values:data.series.map(row=>row[metric])}
    const sites=data.sites.map((site,i)=>({
      label:site.name,color:palette[(i+1)%palette.length],
      values:data.series.map(row=>row.site_summaries.find(s=>s.site_id===site.id)?.[metric]??null)
    }))
    return siteId?sites:[total,...sites]
  },[data,metric,siteId])
  const maxRetention=Math.max(0,...(data?.series??[]).map(s=>Number(s.retention_suggested)))
  const sampleCount=data?.series.filter(p=>p.compliance!==null).length??0
  return <section className="control-card control-trends">
    <div className="control-trends-header"><div><h2><Activity size={18}/> Evolución mensual</h2>
      <p>Series por obra y consolidado calculadas sobre registros mensuales reales. Los períodos sin evaluación quedan vacíos.</p></div>
      <div className="control-trends-filters">
        <label>Indicador<select value={metric} onChange={e=>setMetric(e.target.value as Metric)}>
          <option value="compliance">Cumplimiento</option><option value="progress">Avance revisión</option>
        </select></label>
        <label>Período<select value={months} onChange={e=>setMonths(Number(e.target.value))}>
          <option value={6}>6 meses</option><option value={12}>12 meses</option><option value={24}>24 meses</option>
        </select></label>
      </div>
    </div>
    {error&&<p role="alert" className="form-error">{error}</p>}
    {loading?<p><LoaderCircle className="spin" size={18}/> Consultando historial…</p>:data&&<>
      <div className="control-legend">{curves.map(c=><span key={c.label}>
        <i style={{background:c.color}}/>{c.label}</span>)}</div>
      <div className="control-chart-wrap"><svg viewBox="0 0 900 255" role="img"
        aria-label={metricName[metric]+" durante "+months+" meses, con espacios sin datos"}>
        {[0,25,50,75,100].map(value=>{
          const y=215-value/100*185
          return <g key={value}><line x1={55} x2={860} y1={y} y2={y} stroke="#e1e9f3" strokeWidth={1}/>
            <text x={41} y={y+4} fontSize={11} textAnchor="end" fill="#73849b">{value}%</text></g>
        })}
        {data.series.map((d,i)=>{
          const x=55+(data.series.length>1?805*i/(data.series.length-1):0)
          return <text key={d.period} x={x} y={237} textAnchor="middle" fontSize={10} fill="#72849a">
            {months===24&&i%2!==0?"":d.period.slice(2)}</text>
        })}
        {curves.map((curve)=>lineSegments(curve.values,805,235).map((path,i)=>
          <path key={curve.label+i} d={path} fill="none" stroke={curve.color}
            strokeWidth={3} strokeLinecap="round" strokeLinejoin="round"/>))}
        {curves.map(curve=>curve.values.map((val,i)=>val===null?null:
          <circle key={curve.label+i} cx={55+(curve.values.length>1?805*i/(curve.values.length-1):0)}
            cy={215-val/100*185} r={3.6} fill={curve.color}>
            <title>{curve.label+" · "+data.series[i].period+": "+val+"%"}</title>
          </circle>))}
      </svg></div>
      <p className="control-chart-note">{sampleCount} de {months} meses contienen requisitos evaluables. No se reemplazan datos faltantes por 0% ni 100%.</p>
      <h3><BarChart3 size={17}/> Retenciones propuestas y diferencias por mes</h3>
      <div className="control-retention-bars">{data.series.map(record=><div key={record.period} className="control-retention-month">
        <span>{record.period.slice(2)}</span>
        <div className="control-bar" title={"Retenciones sugeridas: "+Number(record.retention_suggested).toLocaleString("es-CL")+" CLP"}>
          <span style={{width:maxRetention?Math.max(2,100*Number(record.retention_suggested)/maxRetention)+"%":"0%"}}/></div>
        <strong>{Number(record.retention_suggested).toLocaleString("es-CL")} CLP</strong>
        <small>{record.missing_days} días faltantes · {record.unverified_payments} pagos sin verificar</small>
      </div>)}</div>
    </>}
  </section>
}
