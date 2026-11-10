import {useCallback, useEffect, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, Eye, FileText, Save, ShieldCheck} from "lucide-react";
import {request} from "./api";
import "./javiera-native-editor.css";
import JavieraVisualCanvas from "./JavieraVisualCanvas";
import JavieraIRLStructure from "./JavieraIRLStructure";

type Format={code:string;title:string;status:"ready"|"requires_review"|"requires_published_text";
  source_kind:string;source_revision:number|null};
type FormatList={formats:Format[];message:string};
type EditorDocument={code:string;title:string;html:string;revision:number|null;
  state:string;mode:"supplement"|"main_body";preview_only:boolean;needs_review:boolean};
type EditorSave={code:string;revision:number;state:string;message:string};
type EditorHistoryItem={revision:number;state:string;reason:string;created_at:string;html:string};
type EditorHistory={code:string;revisions:EditorHistoryItem[];restoration_policy:string};
type PreviewDossier={id:string;selected_codes:string[];company_name:string;person_name:string|null;site_name:string;revision:number};

const sampleCsp="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; connect-src 'none';";
const previewCss=`
body{margin:0;font:11pt/1.5 Arial,sans-serif;color:#1d2939}
h2,h3{font-size:12pt;color:#183b5b;border-bottom:1px solid #bccbd8;padding-bottom:6px}
p{margin:8px 0}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #b7c6d4;padding:6px;font-size:10pt;vertical-align:top}
th{background:#edf2f6}blockquote{border-left:3px solid #abbdd1;margin:10px 0;padding:6px 12px}
`;
const previewFields:Record<string,string>={
  "worker.name":"Nombre del trabajador","worker.rut":"RUT del trabajador",
  "employer.name":"Empresa","employer.rut":"RUT de la empresa",
  "site.name":"Obra","role":"Cargo","event.date":"Fecha del documento",
};
function designPreview(html:string){
  const text=html.replace(/\{\{\s*([A-Za-z0-9_.]+)\s*\}\}/g,
    (_full:string,key:string)=>'<strong class="document-variable">'+
      (previewFields[key]||"Dato automático")+'</strong>');
  return '<!doctype html><html lang="es"><head><meta charset="utf-8">'+
    '<meta http-equiv="Content-Security-Policy" content="'+sampleCsp+'">'+
    '<style>'+previewCss+'.document-variable{background:#e8f2fc;color:#215278;border-radius:3px;padding:2px 4px}'+'</style></head><body>'+text+'</body></html>';
}
const insertions=[
  {label:"Párrafo",source:"<p>Escribe aquí el texto oficial.</p>\n"},
  {label:"Título",source:"<h2>Título de sección</h2>\n"},
  {label:"Subtítulo",source:"<h3>Subtítulo</h3>\n"},
  {label:"Negrita",source:"<strong>Texto destacado</strong>"},
  {label:"Casilla",source:"<p>☐ Punto por verificar</p>\n"},
  {label:"Tabla",source:"<table><thead><tr><th>Concepto</th><th>Detalle</th></tr></thead>"+
    "<tbody><tr><td>Escribe aquí</td><td>Dato correspondiente</td></tr></tbody></table>\n"},
] as const;

export default function JavieraNativeEditor({onBack,onOpenMatrices,initialCode="internal_rules_receipt"}:{
  onBack:()=>void;onOpenMatrices?:()=>void;initialCode?:string
}){
  const [formats,setFormats]=useState<Format[]>([]);
  const [selected,setSelected]=useState(initialCode);
  const [document,setDocument]=useState<EditorDocument|null>(null);
  const [html,setHtml]=useState("");
  const [savedHtml,setSavedHtml]=useState("");
  const [reason,setReason]=useState("Ajuste de diseño para impresión A4");
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [sourceView,setSourceView]=useState(true);
  const [expertHtml,setExpertHtml]=useState(false);
  const [history,setHistory]=useState<EditorHistoryItem[]>([]);
  const [historyOpen,setHistoryOpen]=useState(false);
  const [canvasSeed,setCanvasSeed]=useState(0);
  const [sampleDossiers,setSampleDossiers]=useState<PreviewDossier[]>([]);
  const [sampleId,setSampleId]=useState("");
  const [actualPdf,setActualPdf]=useState<string|null>(null);
  const [pdfLoading,setPdfLoading]=useState(false);
  const [showIrlSupplement,setShowIrlSupplement]=useState(false);
  const input=useRef<HTMLTextAreaElement|null>(null);
  const dirty=html!==savedHtml;
  const availableExamples=sampleDossiers.filter(d=>d.selected_codes.includes(selected));
  useEffect(()=>()=>{if(actualPdf)URL.revokeObjectURL(actualPdf);},[actualPdf]);
  useEffect(()=>{setActualPdf(null);},[html,selected]);

  const refreshFormats=useCallback(async()=>{
    const result=await request<FormatList>("/javiera/v19/formats");
    setFormats(result.formats);
  },[]);
  const openDocument=useCallback(async(code:string)=>{
    setLoading(true);setError("");setNotice("");setActualPdf(null);setSampleId("");setShowIrlSupplement(false);
    try{
      const [current,versions]=await Promise.all([
        request<EditorDocument>("/javiera/v19/editor/"+code),
        request<EditorHistory>("/javiera/v19/editor/"+code+"/history"),
      ]);
      setHistory(versions.revisions);
      setCanvasSeed(seed=>seed+1);
      setHistoryOpen(false);
      setDocument(current);
      setHtml(current.html);
      setSavedHtml(current.html);
      setConfirmed(false);
      setSelected(code);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{
    void Promise.all([refreshFormats(),openDocument(initialCode)])
      .catch(e=>setError(e instanceof Error?e.message:String(e)));
    void request<PreviewDossier[]>("/javiera/v166/dossiers")
      .then(setSampleDossiers)
      .catch(()=>setSampleDossiers([]));
  },[refreshFormats,openDocument]);

  function choose(code:string){
    if(busy||code===selected)return;
    if(dirty&&!window.confirm("Hay cambios sin guardar. ¿Cambiar de documento y descartarlos?"))return;
    void openDocument(code);
  }
  function goBack(){
    if(dirty&&!window.confirm("Hay cambios sin guardar. ¿Salir sin guardarlos?"))return;
    onBack();
  }
  function recoverVersion(item:EditorHistoryItem){
    if(dirty&&!window.confirm("Hay cambios sin guardar. ¿Descartarlos para cargar otra revisión?"))return;
    setHtml(item.html);
    setReason("Recuperación de la revisión "+item.revision);
    setConfirmed(false);
    setCanvasSeed(seed=>seed+1);
    setHistoryOpen(false);
    setNotice("Se cargó la revisión "+item.revision+" para editarla. Guarda un nuevo borrador; la versión histórica permanece intacta.");
  }
  function insert(fragment:string){
    const field=input.current;
    if(!field){setHtml(old=>old+"\n"+fragment);return;}
    const from=field.selectionStart;
    const to=field.selectionEnd;
    const updated=html.slice(0,from)+fragment+html.slice(to);
    setHtml(updated);
    window.requestAnimationFrame(()=>{
      field.focus();
      field.setSelectionRange(from+fragment.length,from+fragment.length);
    });
  }
  async function save(){
    if(!html.trim())return setError("Completa el documento antes de guardarlo.");
    setBusy(true);setError("");setNotice("");
    try{
      const result=await request<EditorSave>("/javiera/v19/editor/"+selected,{
        method:"PUT",body:JSON.stringify({html,reason:reason.trim()})
      });
      await openDocument(selected);
      await refreshFormats();
      setNotice("Borrador visual guardado · revisión "+result.revision+
        ". Comprueba la vista y habilita el PDF A4 cuando corresponda.");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function enable(){
    if(!document?.revision)return setError("Guarda primero el documento.");
    if(dirty)return setError("Guarda los cambios antes de habilitar la vista previa.");
    if(!confirmed)return setError("Confirma que verificaste el contenido y su distribución.");
    setBusy(true);setError("");setNotice("");
    try{
      await request("/javiera/v19/editor/"+selected+"/enable-preview",{
        method:"POST",body:JSON.stringify({
          revision:document.revision,confirmed_content:true
        })
      });
      await openDocument(selected);
      await refreshFormats();
      setNotice("Diseño habilitado para vista previa PDF A4. No equivale a firma ni entrega.");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const active=formats.find(f=>f.code===selected);
  async function previewWithDossier(){
    if(!sampleId){setError("Selecciona un expediente documental para mostrar su PDF A4.");return;}
    if(dirty){setError("Guarda los cambios y habilita su revisión antes de comprobar el PDF definitivo.");return;}
    if(active?.status!=="ready"){
      setError("El formato todavía no está habilitado para impresión; revisa su contenido primero.");return;
    }
    setPdfLoading(true);setError("");
    try{
      const csrf=window.document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
      const response=await fetch("/api/v1/javiera/v19/preview",{
        method:"POST",credentials:"include",cache:"no-store",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
        body:JSON.stringify({dossier_id:sampleId,code:selected}),
      });
      if(!response.ok){
        const body=await response.json().catch(()=>({detail:"Vista previa PDF no disponible."}));
        throw new Error(typeof body.detail==="string"?body.detail:"El expediente aún no cumple los requisitos de impresión.");
      }
      const blob=await response.blob();
      if(!blob.size||blob.type!=="application/pdf")throw new Error("El servicio no devolvió un PDF A4 válido.");
      setActualPdf(URL.createObjectURL(blob));
      setNotice("PDF A4 real del expediente seleccionado. Es el mismo archivo que se abrirá para imprimir.");
    }catch(e){setActualPdf(null);setError(e instanceof Error?e.message:String(e));}
    finally{setPdfLoading(false);}
  }
  return <main className="jne-shell">
    <header className="jne-heading">
      <button type="button" className="jne-back" onClick={goBack}>
        <ArrowLeft size={17}/> Volver a documentos
      </button>
      <div><small>PROYECTO JAVIERA · EDITOR VISUAL 19.3</small>
        <h2><FileText size={25}/> Editor visual de documentos</h2>
        <p>Revisa la estructura del IRL y sus matrices. El texto complementario se edita por separado.</p>
      </div>
    </header>
    {error&&<p role="alert" className="jne-alert">{error}</p>}
    {notice&&<p role="status" className="jne-ok"><CheckCircle2 size={17}/>{notice}</p>}
    <div className="jne-layout">
      <aside className="jne-list" aria-label="Seleccionar formato de documento">
        <h3>Documentos <span>{formats.length}/10</span></h3>
        {formats.map(f=><button key={f.code} type="button"
          className={selected===f.code?"selected":""}
          aria-current={selected===f.code?"page":undefined}
          onClick={()=>choose(f.code)}>
          <FileText size={17}/>
          <span>{f.title}<small>{f.status==="ready"?"Vista previa disponible":
            f.status==="requires_review"?"Borrador por revisar":"Falta contenido verificado"}</small></span>
        </button>)}
      </aside>
      <div className="jne-workspace">
        {loading?<p>Consultando la última revisión del documento…</p>:document&&<>
          <div className="jne-context">
            <div><h3>{document.title}</h3>
              <p>{selected==="irl"
                ?"La matriz IRL y los apartados obligatorios se muestran abajo; selecciona el cargo para consultar sus riesgos reales."
                :document.mode==="supplement"
                ?"Este contenido se añade al formulario original. Las matrices y casillas obligatorias se conservan."
                :"Este contenido reemplaza el texto del formato en el PDF. Copia las cláusulas originales sin modificar su significado."}</p>
            </div>
            <div className="jne-history-control">
              <span className="jne-version">{document.revision?"Revisión "+document.revision:"Sin revisión"}</span>
              <button type="button" onClick={()=>setHistoryOpen(!historyOpen)}>
                {historyOpen?"Cerrar historial":"Ver versiones anteriores"}
              </button>
            </div>
          </div>
          {historyOpen&&<section className="jne-history" aria-label="Historial del documento">
            <h4>Historial de versiones</h4>
            <p>Cada revisión se conserva. Recuperar una versión solo la carga en el editor:
              al guardar se crea un borrador nuevo, sin modificar los PDF históricos.</p>
            {history.length===0?<p>Este documento aún no tiene revisiones visuales.</p>:
              <div className="jne-history-list">{history.map(item=>
                <div key={item.revision}>
                  <span>Revisión {item.revision} · {item.state==="pilot_print"?"Vista previa habilitada":"Borrador"}
                    <small>{item.reason}</small></span>
                  <button type="button" onClick={()=>recoverVersion(item)}>Recuperar en el editor</button>
                </div>)}</div>}
          </section>}
          <div className={"jne-panels"+(selected==="irl"?" jne-panels-irl":"")}>
            <section className="jne-editor-panel">
              <div className="jne-panel-heading"><h4><FileText size={17}/>
                {selected==="irl"?"Formato IRL y matriz":"Editar documento"}</h4>
                {selected!=="irl"&&<small>{dirty?"Cambios sin guardar":"Sin cambios pendientes"}</small>}</div>
              {selected==="irl"&&<>
                <JavieraIRLStructure onEditMatrices={onOpenMatrices}/>
                <button type="button" className="jne-supplement-toggle"
                  aria-expanded={showIrlSupplement}
                  onClick={()=>setShowIrlSupplement(!showIrlSupplement)}>
                  {showIrlSupplement?"Ocultar texto complementario":"Editar texto complementario del IRL (opcional)"}
                </button>
              </>}
              {(selected!=="irl"||showIrlSupplement)&&<>
              <div className="jne-visual-mode">
                <strong>Edición visual</strong>
                <button type="button" onClick={()=>setExpertHtml(!expertHtml)}>
                  {expertHtml?"Volver al editor visual":"Edición HTML avanzada (solo administradores)"}
                </button>
              </div>
              {expertHtml?<div>
                <div className="jne-toolbar" role="group" aria-label="Insertar elementos del documento">
                  {insertions.map(item=><button type="button" key={item.label}
                    onClick={()=>insert(item.source)}>{item.label}</button>)}
                </div>
                <label className="jne-label" htmlFor="native-html-source">Código HTML avanzado</label>
                <textarea id="native-html-source" ref={input} spellCheck={false}
                  value={html} rows={22}
                  onChange={e=>setHtml(e.target.value)}/>
                <p className="jne-help">Modo avanzado: se mantiene la validación de seguridad del servidor.
                  El HTML nunca aparece en el documento impreso.</p>
              </div>:<JavieraVisualCanvas html={html} onChange={setHtml}
                resetKey={selected+":"+(document.revision||"base")+":"+canvasSeed}/>}
              <label className="jne-label" htmlFor="native-change-reason">Motivo del cambio</label>
              <input id="native-change-reason" value={reason} maxLength={500}
                onChange={e=>setReason(e.target.value)}/>
              <div className="jne-actions">
                <button type="button" className="jne-primary" disabled={busy||!dirty||reason.trim().length<6}
                  onClick={()=>void save()}><Save size={17}/> {busy?"Procesando…":"Guardar borrador"}</button>
              </div>
              </>}
            </section>
            <section className="jne-preview-panel">
              <div className="jne-panel-heading"><h4><Eye size={17}/> Vista del diseño</h4>
                <button type="button" onClick={()=>setSourceView(!sourceView)}>
                  {sourceView?"Ocultar ayuda":"Mostrar ayuda"}</button></div>
              <p className="jne-help">Elige un expediente guardado para generar el <strong>PDF A4 auténtico</strong>,
                con sus matrices, datos y distribución de impresión. Debes guardar y habilitar antes el formato.</p>
              <div className="jne-pdf-controls">
                <label htmlFor="jne-preview-dossier">Expediente para comprobar el diseño</label>
                <select id="jne-preview-dossier" value={sampleId}
                  onChange={e=>{setSampleId(e.target.value);setActualPdf(null);}}>
                  <option value="">Seleccionar expediente documental</option>
                  {availableExamples.map(d=><option key={d.id} value={d.id}>
                    {d.company_name} · {d.person_name||"Empresa"} · {d.site_name} · rev. {d.revision}
                  </option>)}
                </select>
                <button type="button" className="jne-primary"
                  disabled={busy||pdfLoading||dirty||!sampleId||active?.status!=="ready"}
                  onClick={()=>void previewWithDossier()}>
                  <Eye size={16}/>{pdfLoading?"Generando PDF…":"Ver PDF A4 real"}
                </button>
                {!availableExamples.length&&<small>No hay expedientes recientes que incluyan este formato.
                  Crea uno en «Rellenar documentos» y vuelve para comprobar el PDF.</small>}
              </div>
              {actualPdf?<div className="jne-real-pdf">
                <iframe title={"PDF A4 real "+document.title} src={actualPdf}/>
                <a href={actualPdf} target="_blank" rel="noreferrer">
                  Abrir exactamente este PDF para imprimir
                </a>
              </div>:selected==="irl"?<div className="jne-irl-real-hint">
                <FileText size={22}/>
                <strong>El formato IRL y su matriz están visibles a la izquierda.</strong>
                <p>Para obtener el PDF A4 idéntico al que imprimirás, elige un expediente
                  guardado que incluya IRL. Sus datos sustituyen los campos visuales y
                  el PDF utiliza la matriz aprobada del cargo del expediente.</p>
                {!availableExamples.length&&<p>Si no tienes un expediente guardado,
                  créalo en «Rellenar documentos» y selecciona IRL.</p>}
              </div>:<>
                {sourceView&&<p className="jne-help">
                  Esta es solo una <strong>maqueta de texto</strong>, no el documento imprimible.
                  Las matrices y los datos definitivos están en el PDF real.</p>}
                <div className="jne-paper">
                  <iframe title={"Borrador HTML ilustrativo "+document.title}
                    sandbox="" referrerPolicy="no-referrer" srcDoc={designPreview(html)}/>
                </div>
              </>}
              <div className="jne-enable">
                <label><input type="checkbox" checked={confirmed}
                  onChange={e=>setConfirmed(e.target.checked)}/>
                  <span>Revisé que este texto corresponde al documento original y que no faltan cláusulas.</span></label>
                <button type="button" disabled={busy||dirty||!confirmed||document.state!=="draft"}
                  onClick={()=>void enable()}><ShieldCheck size={17}/> Habilitar vista previa PDF A4</button>
                {active?.status==="ready"&&<p className="jne-ok"><CheckCircle2 size={15}/>
                  El formato está habilitado. Abre un expediente para comprobar e imprimir su PDF A4.</p>}
                <small>Habilitar una vista previa no constituye aprobación profesional,
                  firma, capacitación ni recepción del documento.</small>
              </div>
            </section>
          </div>
        </>}
      </div>
    </div>
  </main>;
}
