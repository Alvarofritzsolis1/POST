import {useCallback,useEffect,useMemo,useState,type ChangeEvent,type DragEvent} from "react"
import {
  Activity,ArrowDownToLine,ArrowRight,CheckCircle2,ChevronRight,Clock3,
  Eye,EyeOff,FileCheck2,FileSearch,FileText,History,LayoutDashboard,LoaderCircle,
  LogOut,RefreshCcw,ScanLine,ShieldCheck,UploadCloud,XCircle
} from "lucide-react"
import {api,type Dashboard,type DocumentSummary,type DocumentView,type Profile} from "./api"

type Area="dashboard"|"cotizaciones"|"f30_1"|"history"|"review"
const nav=[
  {id:"dashboard" as Area,title:"Vista general",icon:LayoutDashboard},
  {id:"cotizaciones" as Area,title:"Cotizaciones",icon:FileCheck2},
  {id:"f30_1" as Area,title:"Certificados F30-1",icon:FileText},
  {id:"history" as Area,title:"Historial OCR",icon:History},
  {id:"review" as Area,title:"Pendientes de revisión",icon:FileSearch},
]
const labels:Record<string,string>={cotizaciones:"Cotizaciones previsionales",f30_1:"F30-1",independientes:"Cotizaciones previsionales",auto:"Automático",desconocido:"No identificado"}
const formatDate=(value:string)=>new Date(value).toLocaleString("es-CL",{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"})
const statusName=(value:string)=>value==="queued"?"En cola":value==="processing"?"Procesando":value==="complete"?"Procesado":"Error"
const badgeClass=(doc:DocumentSummary)=>{
  if(doc.status==="error")return "status error"
  if(doc.status!=="complete")return "status waiting"
  if(doc.payment_status==="Pago acreditado documentalmente")return "status success"
  if(doc.payment_status==="Documento incorrecto"||doc.payment_status==="Documento ilegible")return "status error"
  return "status review"
}
function Logo(){
  return <div className="logo"><span className="logo-symbol"><ScanLine size={21}/></span><span><strong>GALANT</strong><small>DOCUMENT INTELLIGENCE</small></span></div>
}
function Login({onLogin,version}:{onLogin:(user:Profile)=>void;version:string|null}){
  const [email,setEmail]=useState("")
  const [password,setPassword]=useState("")
  const [showPassword,setShowPassword]=useState(false)
  const [error,setError]=useState("")
  const [pending,setPending]=useState(false)
  async function submit(e:React.FormEvent){
    e.preventDefault();setError("");setPending(true)
    try{onLogin(await api.login(email,password))}
    catch(err){setError(err instanceof Error?err.message:"No fue posible ingresar")}
    finally{setPending(false)}
  }
  return <div className="login-page">
    <div className="login-decoration">
      <div className="login-decoration-inner">
        <div className="login-eyebrow"><span className="login-eyebrow-dot"/> PLATAFORMA DOCUMENTAL · CHILE</div>
        <span className="login-hero-icon"><ScanLine size={31} strokeWidth={1.6}/></span>
        <h1>Más claridad.<br/><em>Mejor control.</em><br/>Un solo lugar.</h1>
        <p>Transforma archivos complejos en evidencia organizada. Analiza cotizaciones y certificados F30-1 con OCR, trazabilidad y revisión humana.</p>
        <div className="login-process" aria-label="Etapas de análisis">
          <span><b>01</b> Carga documental</span>
          <span><b>02</b> Análisis OCR</span>
          <span><b>03</b> Revisión de evidencia</span>
        </div>
        <div className="login-decoration-foot"><span>GALANT POST</span><span>DOCUMENT INTELLIGENCE</span></div>
      </div>
    </div>
    <div className="login-panel">
      <div className="login-box">
        <div className="login-panel-head"><Logo/><span className="login-edition">ACCESO PRIVADO</span></div>
        <span className="login-greeting">TU ESPACIO DE TRABAJO</span>
        <h2>Bienvenido a GALANT<span className="heading-period">.</span></h2>
        <p className="muted">Ingresa con tu cuenta autorizada para acceder a tu espacio documental.</p>
        <div className="login-version"><span className="version-indicator" aria-hidden="true"/> GALANT POST · Versión {version?"v"+version:"no disponible"}</div>
        <form onSubmit={submit}>
          <label>Correo electrónico
            <input type="email" required value={email} onChange={e=>setEmail(e.target.value)} autoComplete="username" placeholder="nombre@empresa.cl"/>
          </label>
          <div className="form-field">
            <label htmlFor="galant-password">Contraseña</label>
            <span className="password-field">
              <input id="galant-password" type={showPassword?"text":"password"} required value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" placeholder="Ingresa tu contraseña"/>
              <button type="button" className="password-toggle" aria-label={showPassword?"Ocultar contraseña":"Mostrar contraseña"} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={17}/>:<Eye size={17}/>}</button>
            </span>
          </div>
          {error&&<p className="form-error" role="alert">{error}</p>}
          <button type="submit" className="primary full" disabled={pending}>{pending?<LoaderCircle size={17} className="spin"/>:null} Ingresar a GALANT <ArrowRight size={17}/></button>
        </form>
        <div className="login-footer"><ShieldCheck size={17}/> Espacio de acceso restringido. Cada resultado requiere evaluación documental responsable.</div>
      </div>
    </div>
  </div>
}
function Metric({title,value,icon:Icon,kind}:{title:string;value:number;icon:typeof Activity;kind?:string}){
  return <div className="metric"><div className="metric-top"><span className={"metric-icon "+(kind||"")}><Icon size={19}/></span><span className="metric-rule" aria-hidden="true"/></div><span className="metric-label">{title}</span><span className="metric-value">{value.toLocaleString("es-CL")}</span></div>
}
function App(){
  const [version,setVersion]=useState<string|null>(null)
  const [user,setUser]=useState<Profile|null>(null)
  const [authReady,setAuthReady]=useState(false)
  const [section,setSection]=useState<Area>("dashboard")
  const [stats,setStats]=useState<Dashboard|null>(null)
  const [list,setList]=useState<DocumentSummary[]>([])
  const [chosen,setChosen]=useState<string|null>(null)
  const [selected,setSelected]=useState<DocumentView|null>(null)
  const [uploading,setUploading]=useState(false)
  const [dragging,setDragging]=useState(false)
  const [error,setError]=useState("")
  const [notice,setNotice]=useState("")
  const [uploadFile,setUploadFile]=useState<File|null>(null)
  useEffect(()=>{void api.me().then(setUser).catch(()=>{}).finally(()=>setAuthReady(true))},[])
  useEffect(()=>{void api.version().then(info=>setVersion(info.version)).catch(()=>{})},[])
  const refresh=useCallback(async()=>{
    if(!user)return
    try{
      const [nextStats,nextDocs]=await Promise.all([api.dashboard(),api.list()])
      setStats(nextStats);setList(nextDocs)
    }catch(err){setError(err instanceof Error?err.message:"No se pudo actualizar")}
  },[user])
  useEffect(()=>{
    if(!user)return
    void refresh()
    const timer=window.setInterval(()=>void refresh(),7000)
    return()=>window.clearInterval(timer)
  },[user,refresh])
  useEffect(()=>{
    if(!user||!chosen)return
    if(selected?.id===chosen&&(selected.status==="complete"||selected.status==="error"))return
    let active=true
    const load=async()=>{
      try{const detail=await api.get(chosen);if(active)setSelected(detail)}
      catch(err){if(active)setError(err instanceof Error?err.message:"No se pudo consultar el documento")}
    }
    void load()
    const timer=window.setInterval(()=>void load(),7000)
    return()=>{active=false;window.clearInterval(timer)}
  },[user,chosen,selected?.id,selected?.status])
  const filtered=useMemo(()=>{
    if(section==="review")return list.filter(d=>d.payment_status==="Pendiente de revisión"||d.status==="error")
    if(section==="cotizaciones")return list.filter(d=>d.declared_type===section||d.detected_type===section||d.detected_type==="independientes")
    if(section==="f30_1")return list.filter(d=>d.declared_type===section||d.detected_type===section)
    return list
  },[list,section])
  const category=(section==="cotizaciones"||section==="f30_1")?section:"auto"
  async function upload(){
    if(!uploadFile)return
    setUploading(true);setError("");setNotice("")
    try{
      const document=await api.upload(uploadFile,category)
      setSelected(document);setChosen(document.id);setUploadFile(null)
      setNotice("Archivo recibido. El motor OCR procesará el documento en segundo plano.")
      await refresh()
    }catch(err){setError(err instanceof Error?err.message:"Error de carga")}
    finally{setUploading(false)}
  }
  const changeFile=(ev:ChangeEvent<HTMLInputElement>)=>setUploadFile(ev.target.files?.[0]||null)
  function dropped(ev:DragEvent<HTMLDivElement>){
    ev.preventDefault();setDragging(false);const doc=ev.dataTransfer.files?.[0];if(doc)setUploadFile(doc)
  }
  async function logout(){try{await api.logout()}catch{}setUser(null);setList([]);setStats(null);setChosen(null);setSelected(null)}
  async function retry(id:string){
    setError("");try{setSelected(await api.retry(id));setNotice("El documento volvió a la cola de procesamiento.");await refresh()}
    catch(err){setError(err instanceof Error?err.message:"No se pudo reprocesar")}
  }
  if(!authReady)return <div className="app-loading"><ScanLine size={28}/> Cargando GALANT…</div>
  if(!user)return <Login onLogin={setUser} version={version}/>
  return <div className="shell">
    <aside className="sidebar"><Logo/><div className="sidebar-label">ESPACIO DE TRABAJO</div><nav aria-label="Navegación principal">
      {nav.map(link=><button key={link.id} type="button" aria-current={section===link.id?"page":undefined} className={"nav-item "+(section===link.id?"active":"")} onClick={()=>{setSection(link.id);setChosen(null);setSelected(null);setError("");setNotice("")}}>
        <link.icon size={18}/><span>{link.title}</span>{section===link.id&&<ChevronRight size={15} className="nav-arrow"/>}
      </button>)}
    </nav><div className="sidebar-bottom"><div className="security-note"><ShieldCheck size={18}/><div><b>Verificación responsable</b><span>La evidencia documental no confirma una transacción oficial.</span></div></div><button className="profile-button" onClick={()=>void logout()} title="Cerrar sesión">
      <span className="avatar">{user.email[0]?.toUpperCase()}</span><span className="profile-copy"><b>{user.email}</b><small>{user.role}</small></span><LogOut size={16}/></button></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumbs"><span>GALANT POST</span><ChevronRight size={15}/><strong>{nav.find(x=>x.id===section)?.title}</strong></div>
      <div className="top-actions"><span className="private-pill"><span className="online-dot"/>Entorno privado</span><button className="icon-button" type="button" aria-label="Actualizar datos" title="Actualizar datos" onClick={()=>void refresh()}><RefreshCcw size={17}/></button><button type="button" className="icon-button mobile-logout" title="Cerrar sesión" aria-label="Cerrar sesión" onClick={()=>void logout()}><LogOut size={17}/></button></div></header>
      <div className="page">
        <div className="intro">
          <div><span className="eyebrow">INTELIGENCIA DOCUMENTAL / CHILE</span>
            <h1>{section==="dashboard"?"Visión general":nav.find(x=>x.id===section)?.title}</h1>
            <p>{section==="dashboard"?"Un espacio para evaluar documentos, identificar evidencias y dar seguimiento a cada revisión.":"Revisa documentos, resultados OCR y evidencia localizada en el archivo original."}</p>
          </div>
          <div className="intro-aside"><span className="intro-context">PANEL DE OPERACIONES</span><span className="version-tag">GALANT · v{version||"—"}</span></div>
        </div>
        {section==="dashboard"&&<section className="overview-banner" aria-label="Descripción de GALANT">
          <div className="overview-banner-copy"><span className="eyebrow">TECNOLOGÍA AL SERVICIO DEL CONTROL</span>
            <h2>De documentos complejos<br/>a información más clara.</h2>
            <p>Centraliza tus análisis de cotizaciones y F30-1. Conserva la evidencia y decide con revisión humana.</p>
          </div>
          <span className="overview-banner-badge"><ShieldCheck size={17}/> Análisis documental responsable</span>
        </section>}
        {error&&<div role="alert" className="alert danger"><XCircle size={18}/>{error}<button onClick={()=>setError("")}>Cerrar</button></div>}
        {notice&&<div role="status" className="alert success"><CheckCircle2 size={18}/>{notice}<button onClick={()=>setNotice("")}>Cerrar</button></div>}
        {section==="dashboard"&&<div className="stats">
          <Metric title="Documentos ingresados" value={stats?.total||0} icon={FileText}/>
          <Metric title="Análisis completados" value={stats?.finished||0} icon={CheckCircle2} kind="good"/>
          <Metric title="Evidencia de pago" value={stats?.accredited||0} icon={ShieldCheck} kind="blue"/>
          <Metric title="Requieren revisión" value={(stats?.review||0)+(stats?.errors||0)} icon={Clock3} kind="amber"/>
        </div>}
        {section!=="history"&&section!=="review"&&<section className="upload-card">
          <div className="card-heading"><div><div className="section-kicker"><span>01</span> NUEVO ANÁLISIS</div><h2>Centro de análisis OCR</h2><p>PDF digitales, escaneados o fotografías. Hasta 20 MB, máximo 50 páginas.</p></div><span className="chip"><Activity size={14}/> Motor híbrido</span></div>
          <div className={"dropzone "+(dragging?"dragging":"")} onDragOver={e=>{e.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={dropped}>
            <span className="upload-icon"><UploadCloud size={25}/></span><strong>{uploadFile?uploadFile.name:"Arrastra tu documento aquí"}</strong>
            <span>{uploadFile?"Archivo preparado para el análisis.":"O selecciona un PDF o imagen desde tu computador"}</span>
            <label className="secondary picker">Seleccionar archivo<input hidden type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" onChange={changeFile}/></label>
          </div>
          <div className="upload-bottom"><div><span className="muted">Tipo seleccionado</span><strong>{labels[category]}</strong></div>
            <button className="primary" disabled={!uploadFile||uploading} onClick={()=>void upload()}>{uploading?<LoaderCircle className="spin" size={16}/>:<ScanLine size={16}/>} Analizar documento <ArrowRight size={16}/></button></div>
          <div className="safety-caption"><ShieldCheck size={14}/> Las conclusiones se basan únicamente en el archivo. Un OCR ilegible o incierto requiere validación humana.</div>
        </section>}
        <section className="results-card"><div className="card-heading"><div><div className="section-kicker"><span>02</span> REGISTRO DOCUMENTAL</div><h2>{section==="dashboard"?"Actividad reciente":"Documentos"}</h2><p>Selecciona un documento para consultar su evidencia y diagnóstico.</p></div><span className="count">{filtered.length} registros</span></div>
          {filtered.length===0?<div className="empty"><FileSearch size={30}/><strong>Sin documentos todavía</strong><span>Los análisis realizados aparecerán en este espacio.</span></div>:
          <div className="table-wrap"><table><thead><tr><th>DOCUMENTO</th><th>TIPO</th><th>FECHA</th><th>RESULTADO</th><th></th></tr></thead>
          <tbody>{filtered.map(doc=><tr key={doc.id} className={chosen===doc.id?"selected-row":""}>
            <td><div className="file-name"><span className="file-icon"><FileText size={17}/></span><div><strong title={doc.original_name}>{doc.original_name}</strong><small>{statusName(doc.status)}</small></div></div></td>
            <td>{labels[doc.detected_type||doc.declared_type]||"Desconocido"}</td><td className="small-date">{formatDate(doc.created_at)}</td>
            <td><span className={badgeClass(doc)}>{doc.status!=="complete"?statusName(doc.status):doc.payment_status||"Sin resultado"}</span></td>
            <td><button className="row-open" onClick={()=>{setSelected(null);setChosen(chosen===doc.id?null:doc.id)}} aria-label={"Ver detalles de "+doc.original_name}><ChevronRight size={18}/></button></td></tr>)}</tbody></table></div>}
        </section>
        {chosen&&!selected&&<section className="detail-card"><div className="card-heading"><LoaderCircle className="spin" size={18}/> Cargando detalle del documento…</div></section>}
        {selected&&<section className="detail-card"><div className="card-heading"><div><div className="section-kicker"><span>03</span> EVIDENCIA Y TRAZABILIDAD</div><h2>Resultado del documento</h2><p className="filename-detail">{selected.original_name}</p></div>
          <button className="secondary close-detail" onClick={()=>{setChosen(null);setSelected(null)}}>Cerrar</button></div>
          <div className="detail-grid"><div className="detail-info">
            <div className="detail-result"><small>ESTADO DOCUMENTAL</small><h3>{selected.payment_status||statusName(selected.status)}</h3><p>Este análisis no constituye una confirmación oficial de Previred, AFP, DT ni entidad bancaria.</p></div>
            <dl className="fields"><div><dt>Período</dt><dd>{selected.extracted.periodo||"Por determinar"}</dd></div>
              <div><dt>Páginas</dt><dd>{selected.status==="processing"&&selected.extracted.progreso?
                `${selected.extracted.progreso.procesadas} de ${selected.extracted.progreso.total??"?"} procesadas`:
                selected.page_count||"Pendiente"}</dd></div>
              <div><dt>Identificadores RUT válidos</dt><dd>{selected.extracted.ruts_validos?.join(", ")||"No identificados"}</dd></div>
              <div><dt>Tipo de archivo</dt><dd>{labels[selected.detected_type||selected.declared_type]||"No identificado"}</dd></div>
              {selected.extracted.tiempo_procesamiento_s!==undefined&&<div><dt>Tiempo de procesamiento</dt><dd>{selected.extracted.tiempo_procesamiento_s.toFixed(2)} s</dd></div>}
              {selected.status==="complete"&&<div><dt>Extracción OCR</dt><dd>{selected.extracted.ocr_reutilizado?"Reutilizada":"Nueva"}</dd></div>}</dl>
            {selected.warnings.length>0&&<div className="observations"><b>Observaciones</b>{selected.warnings.map((w,i)=><p key={i}><Clock3 size={14}/>{w}</p>)}</div>}
            {selected.error&&<p className="form-error">{selected.error}</p>}
            <div className="detail-actions">{selected.status==="complete"&&<a className="primary" href={api.excel(selected.id)}><ArrowDownToLine size={16}/> Descargar Excel</a>}
              {selected.status==="complete"&&<a className="secondary" href={api.extraction(selected.id)}><ArrowDownToLine size={16}/> Extracción JSON</a>}
              {(selected.status==="complete"||selected.status==="error")&&user.role!=="viewer"&&<button className="secondary" onClick={()=>void retry(selected.id)}><RefreshCcw size={16}/> Volver a analizar</button>}</div>
          </div><div className="document-preview"><div className="preview-title"><FileSearch size={16}/> Documento original <span>Acceso privado</span></div>
            {selected.original_name.toLowerCase().endsWith(".pdf")?<iframe title="Vista del documento original" src={api.pdf(selected.id)}/>:
              <img alt={"Documento "+selected.original_name} src={api.pdf(selected.id)}/>}
          </div></div>
          <div className="evidence"><h3>Evidencia por página</h3>{selected.evidence.length?selected.evidence.map(e=><div key={e.pagina} className="evidence-item">
            <div className="evidence-header"><b>Página {e.pagina}</b><span>{e.motor}</span><span>Confianza OCR: {e.confianza_ocr===null?"Texto digital":e.confianza_ocr+"%"}</span></div>
            <p>{e.extracto||"Sin texto recuperado"}</p><div className="evidence-controls">
              {e.control_pago.evidence_sufficient?<span className="status success">Evidencia documental localizada</span>:<span className="status review">Revisión recomendada</span>}
              <span>{e.control_pago.period||"Período por identificar"}</span></div></div>):
            <p className="muted">El motor OCR aún no ha generado evidencia.</p>}</div>
        </section>}
        <footer className="footer">GALANT POST · Document Intelligence · Análisis documental no vinculante <span>Protección de datos y revisión humana</span></footer>
      </div>
    </main>
  </div>
}
export default App
