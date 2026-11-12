import {useEffect,useMemo,useRef,useState} from "react";
import {ArrowLeft,CheckCircle2,Download,Eye,FileSpreadsheet,Loader2,Settings2,ShieldAlert} from "lucide-react";
import {request} from "./api";

import "./javiera-simple.css";

type Origin="operational"|"documentary";
type Company={id:string;site_id:string;name:string;rut:string;origin:Origin;details?:Record<string,string>};
type Person={id:string;name:string;rut:string;origin:Origin;details?:Record<string,string>};
type Sources={sites:{id:string;name:string}[];companies:Company[];
  operational_companies:Company[];people:Person[];operational_people:Person[]};
type Library={engine_available:boolean;documents:{code:string;state:string;ready:boolean;sheet:string}[]};
type RoleList={roles:{cargo:string}[]};
type Catalog={code:string;title:string;required_fields:string[]}[];
type Dossier={id:string;revision:number};
type DocumentStatus={code:string;can_issue:boolean;reason:string;missing_fields:string[];
  blocking_errors:string[];last_issue_id?:string|null};
type Batch={issued:number;results:{code:string;ok:boolean;id?:string;reason?:string}[];pdf_url?:string|null};
type LocalPreview={url:string;signature:string;elapsedMs:number};
const EMPTY:Sources={sites:[],companies:[],operational_companies:[],people:[],operational_people:[]};
const LABELS:Record<string,string>={
  labor_contract:"Contrato de trabajo",transfer_addendum:"Anexo de traslado",
  extension_addendum:"Anexo de prórroga",sworn_declaration:"Declaración jurada",
  internal_rules_receipt:"Recepción de reglamento interno",ppe_delivery:"Entrega de EPP",
  irl:"Información de riesgos laborales (IRL)",pts:"Procedimiento de trabajo seguro",
  pts_receipt:"Recepción de PTS",induction:"Inducción de prevención",
};
const ORDER=Object.keys(LABELS);
// Metadata deliberately kept small: Modo Simple never imports the old editor.
const FIELDS:Record<string,string[]>={
  labor_contract:["contract.start","contract.end","contract.salary","contract.hours",
    "extra.worker_address","extra.afp","extra.health_provider","extra.representative_name",
    "extra.representative_rut","extra.employer_address"],
  transfer_addendum:["contract.transfer_date","extra.destinations","extra.transport_allowance"],
  extension_addendum:["contract.end","contract.new_end"],
  sworn_declaration:["extra.representative_name","extra.representative_rut",
    "extra.declaration_period","contract.declaration_reason"],
  internal_rules_receipt:["extra.regulation_version"],
  ppe_delivery:["event.epp_items"],
  irl:[],pts:["extra.representative_name","extra.representative_rut"],
  pts_receipt:["event.pts_version"],
  induction:["event.induction_topics","extra.employer_phone","extra.employer_address"],
};
const FIELDMETA:Record<string,{label:string;type?:string}>={
  "contract.start":{label:"Fecha de ingreso",type:"date"},
  "contract.end":{label:"Fecha de término",type:"date"},
  "contract.new_end":{label:"Nueva fecha de término",type:"date"},
  "contract.transfer_date":{label:"Fecha de traslado",type:"date"},
  "contract.salary":{label:"Sueldo base",type:"number"},
  "contract.hours":{label:"Jornada semanal",type:"number"},
  "contract.declaration_reason":{label:"Motivo de la declaración"},
  "extra.representative_name":{label:"Nombre del representante legal"},
  "extra.representative_rut":{label:"RUT del representante legal"},
  "extra.representative_nationality":{label:"Nacionalidad del representante"},
  "extra.worker_nationality":{label:"Nacionalidad del trabajador"},
  "extra.worker_address":{label:"Domicilio del trabajador"},
  "extra.worker_commune":{label:"Comuna del trabajador"},
  "extra.worker_birthdate":{label:"Fecha de nacimiento",type:"date"},
  "extra.worker_marital_status":{label:"Estado civil"},
  "extra.worker_phone":{label:"Teléfono del trabajador"},
  "extra.worker_email":{label:"Correo del trabajador"},
  "extra.employer_phone":{label:"Teléfono de la empresa"},
  "extra.employer_address":{label:"Domicilio de la empresa"},
  "extra.employer_commune":{label:"Comuna de la empresa"},
  "extra.employer_city":{label:"Ciudad de la empresa"},
  "extra.site_address":{label:"Dirección de obra"},
  "extra.destinations":{label:"Destinos autorizados"},
  "extra.transport_allowance":{label:"Asignación de transporte"},
  "extra.regulation_version":{label:"Versión del reglamento interno"},
  "extra.declaration_period":{label:"Período de declaración"},
  "extra.afp":{label:"AFP"},
  "extra.health_provider":{label:"Previsión de salud"},
  "extra.payment_frequency":{label:"Frecuencia de pago"},
  "extra.bank_account":{label:"Datos de la cuenta de pago"},
  "event.epp_items":{label:"Elementos de protección personal"},
  "event.pts_version":{label:"Versión del PTS"},
  "event.induction_topics":{label:"Temas de inducción"},
  "event.print_notes":{label:"Observaciones para impresión"},
};
const base="/javiera/v166";
function deep(values:Record<string,string>):Record<string,unknown>{
  const root:Record<string,unknown>={};
  Object.entries(values).forEach(([key,val])=>{
    if(!val.trim())return;
    const parts=key.split(".");
    if(parts.length===2){
      const obj=(root[parts[0]]||{}) as Record<string,string>;
      obj[parts[1]]=val.trim();root[parts[0]]=obj;
    }else root[key]=val.trim();
  });
  return root;
}
const today=()=>{
  const d=new Date();
  return [d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-");
};
function friendly(error:unknown):string{
  if(!(error instanceof Error))return "No pudimos preparar este documento. Revisa los datos.";
  try{
    const value=JSON.parse(error.message) as {detail?:string|{reason?:string;missing_fields?:string[]}};
    if(typeof value.detail==="string")return value.detail;
    if(value.detail?.reason)return value.detail.reason;
  }catch{/* ordinary error */}
  return error.message.replace(/Error HTTP \d+/g,"No se pudo completar la solicitud");
}
function csrf():string{
  return document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
}
async function previewPdf(id:string,code:string):Promise<Blob>{
  const response=await fetch("/api/v1/javiera/v166/preview",{
    method:"POST",credentials:"include",cache:"no-store",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
    body:JSON.stringify({dossier_id:id,code})
  });
  if(!response.ok){
    const body=await response.json().catch(()=>null) as
      {detail?:{reason?:string;missing_fields?:string[]}|string}|null;
    const detail=body?.detail;
    throw new Error(typeof detail==="string"?detail:
      detail?.reason||"Falta completar o aprobar el documento para generar la vista previa.");
  }
  if(!response.headers.get("Content-Type")?.includes("application/pdf"))
    throw new Error("El servidor no devolvió un PDF válido.");
  return response.blob();
}
const token=(x:{origin:string;id:string})=>x.origin+":"+x.id;
function locate<T extends {origin:string;id:string}>(values:T[],key:string):T|undefined{
  return values.find(value=>token(value)===key);
}

export default function JavieraSimple({onConfig,onBack}:{onConfig?:()=>void;onBack?:()=>void}){
  const [source,setSource]=useState<Sources>(EMPTY);
  const [library,setLibrary]=useState<Library|null>(null);
  const [roles,setRoles]=useState<string[]>([]);
  const [catalog,setCatalog]=useState<Catalog>([]);
  const [site,setSite]=useState("");
  const [companyToken,setCompanyToken]=useState("");
  const [companyId,setCompanyId]=useState("");
  const [personToken,setPersonToken]=useState("");
  const [personId,setPersonId]=useState("");
  const [role,setRole]=useState("");
  const [code,setCode]=useState("irl");
  const [date,setDate]=useState(today);
  const [filter,setFilter]=useState("");
  const [extras,setExtras]=useState<Record<string,string>>({});
  const [verifiedNoWorkers,setVerifiedNoWorkers]=useState(false);
  const [missing,setMissing]=useState<string[]>([]);
  const [reasons,setReasons]=useState<string[]>([]);
  const [showExtras,setShowExtras]=useState(false);
  const [busy,setBusy]=useState(false);
  const [booting,setBooting]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [preview,setPreview]=useState<LocalPreview|null>(null);
  const [issued,setIssued]=useState("");
  const current=useRef<{signature:string;dossier:Dossier}|null>(null);
  const generation=useRef(0);
  const previewRef=useRef<LocalPreview|null>(null);
  useEffect(()=>{previewRef.current=preview;},[preview]);
  useEffect(()=>()=>{if(previewRef.current)URL.revokeObjectURL(previewRef.current.url);},[]);
  const companies=useMemo(()=>[...source.companies,...source.operational_companies]
    .filter(x=>x.site_id===site&&(x.name+" "+x.rut).toLowerCase().includes(filter.toLowerCase())),
    [source,site,filter]);
  const people=useMemo(()=>[...source.people,...source.operational_people],[source]);
  const selectedCompany=locate(companies,companyToken);
  const selectedPerson=locate(people,personToken);
  const layout=library?.documents.find(x=>x.code===code);
  const workerless=code==="sworn_declaration";
  const ready=!!site&&!!companyToken&&!!companyId&&
    (!!personToken&&!!personId||workerless)&&!!code&&!!date&&
    (!!role||!["irl","pts","pts_receipt","ppe_delivery","induction"].includes(code))&&
    (workerless?verifiedNoWorkers:true);
  const signature=JSON.stringify({site,companyId,personId:workerless?null:personId,role,code,date,extras,verifiedNoWorkers});
  function resetPreview(){
    setPreview(old=>{if(old)URL.revokeObjectURL(old.url);return null;});
    setIssued("");setMissing([]);setReasons([]);setNotice("");setError("");
  }
  useEffect(()=>{resetPreview();},[signature]);
  useEffect(()=>{
    let active=true;
    void Promise.all([
      request<Sources>(base+"/sources"),
      request<Library>(base+"/templates/status"),
      request<RoleList>("/javiera/v194/roles"),
      request<Catalog>("/javiera/catalog"),
    ]).then(([s,l,r,c])=>{
      if(!active)return;
      setSource(s);setLibrary(l);setRoles(r.roles.map(x=>x.cargo));setCatalog(c);
    }).catch(e=>{if(active)setError(friendly(e));})
      .finally(()=>{if(active)setBooting(false);});
    return ()=>{active=false;};
  },[]);
  async function changeSite(value:string){
    const index=++generation.current;
    setSite(value);setCompanyToken("");setCompanyId("");setPersonToken("");setPersonId("");
    setRole("");setFilter("");setExtras({});setVerifiedNoWorkers(false);
    setSource(old=>({...old,people:[],operational_people:[]}));
    current.current=null;
    try{
      const loaded=await request<Sources>(base+"/sources"+
        (value?"?site_id="+encodeURIComponent(value):""));
      if(index===generation.current)setSource(loaded);
    }catch(e){if(index===generation.current)setError(friendly(e));}
  }
  async function changeCompany(value:string){
    const index=++generation.current;
    setCompanyToken(value);setCompanyId("");setPersonToken("");setPersonId("");
    setExtras({});setRole("");current.current=null;
    if(!value)return;
    const item=locate([...source.companies,...source.operational_companies],value);
    if(!item)return;
    setBusy(true);setError("");
    try{
      const linked=await request<{id:string}>(base+"/companies",{
        method:"POST",body:JSON.stringify({
          site_id:site,origin:item.origin,source_id:item.id
        })
      });
      if(index!==generation.current)return;
      setCompanyId(linked.id);
      const loaded=await request<Sources>(base+"/sources?site_id="+encodeURIComponent(site)+
        "&company_id="+encodeURIComponent(linked.id));
      if(index!==generation.current)return;
      setSource(loaded);
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  async function changePerson(value:string){
    const index=++generation.current;
    setPersonToken(value);setPersonId("");setRole("");current.current=null;
    if(!value)return;
    const item=locate(people,value);
    if(!item||!companyId)return;
    setBusy(true);setError("");
    try{
      const linked=await request<{id:string}>(base+"/people",{
        method:"POST",body:JSON.stringify({
          company_id:companyId,origin:item.origin,source_id:item.id
        })
      });
      if(index!==generation.current)return;
      setPersonId(linked.id);
      if(item.details?.role)setRole(item.details.role);
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  function changeDocument(value:string){
    setCode(value);setExtras({});setShowExtras(false);setVerifiedNoWorkers(false);
    current.current=null;
    if(value==="sworn_declaration"){setPersonToken("");setPersonId("");}
  }
  async function prepare():Promise<Dossier|null>{
    if(!ready){setError("Selecciona una obra, empresa, trabajador, cargo y documento.");return null;}
    if(!library?.documents.some(item=>item.code===code&&item.ready)){
      setError("La plantilla Excel original no está habilitada. Revísala en Administración de plantillas.");return null;
    }
    if(current.current?.signature===signature)return current.current.dossier;
    const shared=deep({...extras,role,"event.date":date});
    const dossier=await request<Dossier>(base+"/dossiers",{
      method:"POST",body:JSON.stringify({
        site_id:site,company_id:companyId,person_id:workerless?null:personId,
        relationship:"contractor",parent_name:null,selected_codes:[code],
        shared,document_data:workerless?{[code]:{verified_no_workers:verifiedNoWorkers}}:{[code]:{}},
        ...(current.current&&{
          dossier_id:current.current.dossier.id,
          expected_revision:current.current.dossier.revision,
        }),
      })
    });
    current.current={signature,dossier};
    return dossier;
  }
  async function check(id:string):Promise<boolean>{
    const result=await request<{documents:DocumentStatus[]}>(base+"/dossiers/"+id+"/eligibility");
    const item=result.documents.find(x=>x.code===code);
    if(!item)return false;
    if(item.can_issue){setMissing([]);setReasons([]);return true;}
    setMissing((item.missing_fields||[]).filter(x=>!["worker.name","worker.rut","employer.name","employer.rut","site.name"].includes(x)));
    setReasons([...new Set([item.reason,...(item.blocking_errors||[])].filter(Boolean))]);
    setShowExtras(true);
    return false;
  }
  async function run(action:"preview"|"issue"){
    if(busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      if(action==="preview"&&preview?.signature===signature){
        setNotice("Vista previa reutilizada: no se volvió a generar el PDF.");return;
      }
      const dossier=await prepare();
      if(!dossier)return;
      if(!await check(dossier.id))return;
      if(action==="preview"){
        const start=performance.now();
        const pdf=await previewPdf(dossier.id,code);
        const elapsed=performance.now()-start;
        if(pdf.size===0)throw new Error("El PDF está vacío.");
        const url=URL.createObjectURL(pdf);
        setPreview(old=>{if(old)URL.revokeObjectURL(old.url);return {url,signature,elapsedMs:elapsed};});
        setNotice("Vista previa lista. La impresión no representa una firma o entrega realizada.");
      }else{
        const result=await request<Batch>(base+"/issue/batch",{
          method:"POST",body:JSON.stringify({dossier_id:dossier.id,codes:[code]})
        });
        if(!result.issued||!result.results[0]?.ok){
          throw new Error(result.results[0]?.reason||"No se pudo emitir este documento.");
        }
        setIssued("/api/v1/javiera/v166/issues/"+encodeURIComponent(result.results[0].id||"")+"/pdf");
        setNotice("Documento generado y guardado en el historial privado.");
      }
    }catch(e){setError(friendly(e));}
    finally{setBusy(false);}
  }
  const fieldKeys=FIELDS[code]||[];
  const auto=new Set(["role","event.date","worker.name","worker.rut","employer.name","employer.rut","site.name"]);
  const requiredCatalog=catalog.find(x=>x.code===code)?.required_fields||[];
  const extraFields=[...new Set([...fieldKeys,...requiredCatalog,...missing])]
    .filter(x=>!auto.has(x)&&x.includes("."));
  return <main className="jsm-shell" aria-label="Proyecto Javiera modo simple">
    <header className="jsm-heading">
      <div>
        {onBack&&<button type="button" className="jsm-back" onClick={onBack}>
          <ArrowLeft size={17}/> Volver</button>}
        <span className="jsm-eyebrow">GALANT 19.6 · MODO SIMPLE</span>
        <h1>Proyecto Javiera</h1>
        <p>Selecciona a la persona y el documento. GALANT utiliza las plantillas originales de Excel.</p>
      </div>
      {onConfig&&<button type="button" className="jsm-settings" onClick={onConfig}>
        <Settings2 size={17}/> Administración de plantillas</button>}
    </header>
    {error&&<div className="jsm-message error" role="alert"><ShieldAlert size={19}/>{error}</div>}
    {notice&&<div className="jsm-message ok" role="status"><CheckCircle2 size={19}/>{notice}</div>}
    {booting?<p className="jsm-loading"><Loader2 size={20} className="jsm-spin"/> Cargando documentos…</p>:
    <section className="jsm-panel">
      <div className="jsm-intro"><FileSpreadsheet size={21}/>
        <div><h2>Nuevo documento</h2><p>Los datos existentes se recuperan automáticamente.</p></div>
      </div>
      <div className="jsm-grid">
        <label>Obra
          <select aria-label="Obra" value={site} onChange={e=>void changeSite(e.target.value)} disabled={busy}>
            <option value="">Selecciona la obra</option>
            {source.sites.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <label>Buscar empresa
          <input aria-label="Buscar empresa" value={filter} onChange={e=>setFilter(e.target.value)}
            placeholder="Razón social o RUT" disabled={!site||busy}/>
        </label>
        <label>Empresa contratista
          <select aria-label="Empresa contratista" value={companyToken} disabled={!site||busy}
            onChange={e=>void changeCompany(e.target.value)}>
            <option value="">Selecciona la empresa</option>
            {companies.map(x=><option key={token(x)} value={token(x)}>{x.name}</option>)}
          </select>
        </label>
        <label>Trabajador
          <select aria-label="Trabajador" value={workerless?"":personToken}
            disabled={!companyId||busy||workerless} onChange={e=>void changePerson(e.target.value)}>
            <option value="">{workerless?"No corresponde a declaración empresarial":"Selecciona un trabajador"}</option>
            {people.map(x=><option key={token(x)} value={token(x)}>{x.name}</option>)}
          </select>
        </label>
        <label>Cargo
          <select aria-label="Cargo" value={role} onChange={e=>setRole(e.target.value)} disabled={busy}>
            <option value="">Selecciona el cargo</option>
            {role&&!roles.includes(role)&&<option value={role}>{role}</option>}
            {roles.map(name=><option value={name} key={name}>{name}</option>)}
          </select>
        </label>
        <label>Documento
          <select aria-label="Documento" value={code} disabled={busy} onChange={e=>changeDocument(e.target.value)}>
            {ORDER.map(key=><option key={key} value={key}>{LABELS[key]}</option>)}
          </select>
        </label>
      </div>
      <div className="jsm-details">
        <label>Fecha del documento <input type="date" value={date} onChange={e=>setDate(e.target.value)}/></label>
        <p>{selectedPerson?.name||"Selecciona el trabajador"} · {selectedCompany?.name||"Empresa por seleccionar"}</p>
      </div>
      {workerless&&<label className="jsm-checkbox"><input type="checkbox"
        checked={verifiedNoWorkers} onChange={e=>setVerifiedNoWorkers(e.target.checked)}/>
        Confirmo que la empresa no tiene trabajadores en el período declarado.
      </label>}
      {!layout?.ready&&<p className="jsm-alert" role="status">
        {layout?.state==="draft"?"La plantilla Excel necesita revisión antes de emitir.":
          layout?.state==="not_imported"?"Importa la plantilla original desde Administración de plantillas.":
          "La plantilla no está habilitada o requiere comprobar el motor PDF."}
      </p>}
      {(extraFields.length>0||missing.length>0)&&<details className="jsm-extras"
        open={showExtras} onToggle={e=>setShowExtras(e.currentTarget.open)}>
        <summary>Completar otros datos del documento {missing.length>0&&"("+missing.length+" pendientes)"}</summary>
        <div className="jsm-extra-grid">
          {extraFields.map(key=>{
            const meta=FIELDMETA[key];
            const required=missing.includes(key);
            return <label key={key}>{meta?.label||key.replaceAll("."," · ")}
              <input type={meta?.type==="date"?"date":meta?.type==="number"?"number":"text"}
                aria-invalid={required&&!extras[key]}
                value={extras[key]||""}
                onChange={e=>setExtras(old=>({...old,[key]:e.target.value}))}
                placeholder={required?"Dato necesario para continuar":""}/>
            </label>;
          })}
        </div>
      </details>}
      {reasons.length>0&&<div className="jsm-alert" role="status">
        <strong>Antes de generar el documento:</strong>
        {reasons.map((reason,i)=><p key={i}>{reason}</p>)}
      </div>}
      <div className="jsm-actions">
        <button type="button" className="jsm-secondary" disabled={!ready||busy||!layout?.ready}
          onClick={()=>void run("preview")}>{busy?<Loader2 className="jsm-spin" size={18}/>:<Eye size={18}/>} Vista previa</button>
        <button type="button" className="jsm-primary" disabled={!ready||busy||!layout?.ready}
          onClick={()=>void run("issue")}>{busy?<Loader2 className="jsm-spin" size={18}/>:<Download size={18}/>} Generar PDF</button>
      </div>
      <p className="jsm-footnote">Las matrices y documentos preventivos sin aprobación siguen bloqueados.
        Los PDF emitidos se guardan de forma privada, sin firmas ficticias.</p>
    </section>}
    {preview&&<section className="jsm-preview" aria-label="Vista previa del PDF">
      <header><div><strong>Vista previa PDF</strong><small>Recepción: {Math.round(preview.elapsedMs)} ms (medición de esta solicitud, no tiempo garantizado)</small></div>
        <a href={preview.url} target="_blank" rel="noreferrer">Abrir en pestaña</a></header>
      <iframe title="Documento PDF de Proyecto Javiera" src={preview.url} loading="eager"/>
    </section>}
    {issued&&<div className="jsm-issued">
      <CheckCircle2 size={20}/><a href={issued} target="_blank" rel="noreferrer">Abrir PDF generado</a>
      <small>Documento guardado; listo para obtener firmas presenciales.</small>
    </div>}
  </main>;
}
