import {useCallback, useEffect, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, Code2, Eye, FileCode2, FileText, Save, ShieldCheck, Type} from "lucide-react";
import {request} from "./api";
import "./javiera-native-editor.css";

type Format={code:string;title:string;status:"ready"|"requires_review"|"requires_published_text";
  source_kind:string;source_revision:number|null};
type FormatList={formats:Format[];message:string};
type EditorDocument={code:string;title:string;html:string;revision:number|null;
  state:string;mode:"supplement"|"main_body";preview_only:boolean;needs_review:boolean};
type EditorSave={code:string;revision:number;state:string;message:string};

const sampleCsp="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; connect-src 'none';";
const previewCss=String.raw\`
body{margin:0;font:11pt/1.5 Arial,sans-serif;color:#1d2939}
h2,h3{font-size:12pt;color:#183b5b;border-bottom:1px solid #bccbd8;padding-bottom:6px}
p{margin:8px 0}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #b7c6d4;padding:6px;font-size:10pt;vertical-align:top}
th{background:#edf2f6}blockquote{border-left:3px solid #abbdd1;margin:10px 0;padding:6px 12px}
\`;
function designPreview(html:string){
  return '<!doctype html><html lang="es"><head><meta charset="utf-8">'+
    '<meta http-equiv="Content-Security-Policy" content="'+sampleCsp+'">'+
    '<style>'+previewCss+'</style></head><body>'+html+'</body></html>';
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

export default function JavieraNativeEditor({onBack}:{onBack:()=>void}){
  const [formats,setFormats]=useState<Format[]>([]);
  const [selected,setSelected]=useState("internal_rules_receipt");
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
  const input=useRef<HTMLTextAreaElement|null>(null);
  const dirty=html!==savedHtml;

  const refreshFormats=useCallback(async()=>{
    const result=await request<FormatList>("/javiera/v19/formats");
    setFormats(result.formats);
  },[]);
  const openDocument=useCallback(async(code:string)=>{
    setLoading(true);setError("");setNotice("");
    try{
      const current=await request<EditorDocument>("/javiera/v19/editor/"+code);
      setDocument(current);
      setHtml(current.html);
      setSavedHtml(current.html);
      setConfirmed(false);
      setSelected(code);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLoading(false);}
  },[]);
  useEffect(()=>{
    void Promise.all([refreshFormats(),openDocument("internal_rules_receipt")])
      .catch(e=>setError(e instanceof Error?e.message:String(e)));
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
    if(!html.trim())return setError("Completa el documento en HTML antes de guardarlo.");
    setBusy(true);setError("");setNotice("");
    try{
      const result=await request<EditorSave>("/javiera/v19/editor/"+selected,{
        method:"PUT",body:JSON.stringify({html,reason:reason.trim()})
      });
      await openDocument(selected);
      await refreshFormats();
      setNotice("Borrador HTML guardado · revisión "+result.revision+
        ". Comprueba la vista y habilita el PDF A4 cuando corresponda.");
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function enable(){
    if(!document?.revision)return setError("Guarda primero el formato HTML.");
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
  return <main className="jne-shell">
    <header className="jne-heading">
      <button type="button" className="jne-back" onClick={goBack}>
        <ArrowLeft size={17}/> Volver a documentos
      </button>
      <div><small>PROYECTO JAVIERA · NUEVO GENERADOR</small>
        <h2><FileCode2 size={25}/> Editor de formatos HTML</h2>
        <p>Edita el documento aquí, revisa su aspecto y prepara el PDF A4 sin modificar Excel.</p>
      </div>
    </header>
    {error&&<p role="alert" className="jne-alert">{error}</p>}
    {notice&&<p role="status" className="jne-ok"><CheckCircle2 size={17}/>{notice}</p>}
    <div className="jne-layout">
      <aside className="jne-list" aria-label="Seleccionar formato HTML">
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
              <p>{document.mode==="supplement"
                ?"Este contenido HTML se añade al formulario original. Las matrices y casillas obligatorias se conservan."
                :"Este contenido HTML reemplaza el texto visual del formato en el PDF nativo. Copia las cláusulas originales sin modificar su significado."}</p>
            </div>
            <span className="jne-version">{document.revision?"Revisión "+document.revision:"Sin revisión HTML"}</span>
          </div>
          <div className="jne-panels">
            <section className="jne-editor-panel">
              <div className="jne-panel-heading"><h4><Code2 size={17}/> Editar contenido</h4>
                <small>{dirty?"Cambios sin guardar":"Sin cambios pendientes"}</small></div>
              <div className="jne-toolbar" role="group" aria-label="Insertar elementos del documento">
                {insertions.map(item=><button type="button" key={item.label}
                  onClick={()=>insert(item.source)}>{item.label}</button>)}
              </div>
              <label className="jne-label" htmlFor="native-html-source">
                Texto y estructura HTML
              </label>
              <textarea id="native-html-source" ref={input} spellCheck={false}
                value={html} rows={22}
                placeholder={"<h2>Título original</h2>\n<p>Escribe o pega aquí el contenido real del documento.</p>"}
                onChange={e=>setHtml(e.target.value)}/>
              <p className="jne-help">Usa los botones para insertar títulos, párrafos, casillas y tablas.
                Los campos automáticos mantienen la sintaxis {"{{worker.name}}"}.
                No se permiten scripts, enlaces, imágenes externas ni estilos inseguros.</p>
              <label className="jne-label" htmlFor="native-change-reason">Motivo del cambio</label>
              <input id="native-change-reason" value={reason} maxLength={500}
                onChange={e=>setReason(e.target.value)}/>
              <div className="jne-actions">
                <button type="button" className="jne-primary" disabled={busy||!dirty||reason.trim().length<6}
                  onClick={()=>void save()}><Save size={17}/> {busy?"Procesando…":"Guardar HTML"}</button>
              </div>
            </section>
            <section className="jne-preview-panel">
              <div className="jne-panel-heading"><h4><Eye size={17}/> Vista del diseño</h4>
                <button type="button" onClick={()=>setSourceView(!sourceView)}>
                  {sourceView?"Ocultar ayuda":"Mostrar ayuda"}</button></div>
              {sourceView&&<p className="jne-help">Esta es una maqueta del texto HTML, no el PDF definitivo.
                Comprueba el resultado con <strong>Vista previa A4</strong> después de completar un expediente.</p>}
              <div className="jne-paper">
                <iframe title={"Vista preliminar HTML "+document.title}
                  sandbox="" referrerPolicy="no-referrer" srcDoc={designPreview(html)}/>
              </div>
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
