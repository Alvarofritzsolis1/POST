import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, ChevronRight, ClipboardCheck, Download, FileCheck2, FileText,
  FolderPlus, Info, Printer, Settings2, ShieldCheck, UserPlus, AlertCircle, Eye} from "lucide-react";
import {request} from "./api";
import {opsApi} from "./opsApi";
import "./javiera-workspace.css";

type Relation="contractor"|"subcontractor";
type Group="Zona Subcontratos"|"Prevención de Riesgos";
type Source={sites:{id:string;name:string}[];contractors:{id:string;site_id:string;name:string;rut:string|null;nature:string}[];
  workers:{id:string;name:string;rut:string|null;active:boolean}[]};
type Catalog={code:string;area:string;title:string;required_fields:string[];published_version:number};
type RoleResult={roles:string[];aliases:Record<string,string>;matrix_roles:string[]};
type State={code:string;title:string;status:string;reason:string;missing_fields:string[];blocking_errors:string[];
  completion_percent:number;can_preview:boolean;can_issue:boolean;has_history:boolean;template_version:number};
type Dossier={id:string;revision:number;site_id:string;employer_id:string;worker_id:string|null;parent_id:string|null;
  relationship:Relation;data:Record<string,unknown>;issues:{id:string;code:string;at:string}[];
  historical:{id:string;code:string;state:string}[]};
type OldDossier={id:string;site_id:string;employer_id:string;worker_id:string|null;relationship:string;revision:number};
type FieldMeta={label:string;type?:string;hint?:string;options?:string[]};

const DOC_AREA:Record<string,Group>={
  labor_contract:"Zona Subcontratos", transfer_addendum:"Zona Subcontratos",
  sworn_declaration:"Zona Subcontratos", extension_addendum:"Zona Subcontratos",
  internal_rules_receipt:"Prevención de Riesgos",ppe_delivery:"Prevención de Riesgos",
  irl:"Prevención de Riesgos",pts:"Prevención de Riesgos",
  pts_receipt:"Prevención de Riesgos",induction:"Prevención de Riesgos",
};
const ORDER=["labor_contract","transfer_addendum","sworn_declaration","extension_addendum",
  "internal_rules_receipt","ppe_delivery","irl","pts","pts_receipt","induction"];
const EVENT:Record<string,string>={labor_contract:"ingreso",transfer_addendum:"traslado",
  sworn_declaration:"declaracion",extension_addendum:"prorroga",
  internal_rules_receipt:"reglamento",ppe_delivery:"entrega_epp",irl:"ingreso",
  pts:"ingreso",pts_receipt:"recepcion_pts",induction:"induccion"};
const TITLES:Record<string,string>={labor_contract:"Contrato de trabajo",transfer_addendum:"Anexo de traslado",
  sworn_declaration:"Declaración jurada",extension_addendum:"Anexo de prórroga",
  internal_rules_receipt:"Recepción del Reglamento Interno",ppe_delivery:"Registro de entrega de EPP",
  irl:"Información de riesgos laborales (IRL)",pts:"Procedimiento de trabajo seguro (PTS)",
  pts_receipt:"Recepción de PTS",induction:"Inducción de prevención"};
const F:Record<string,FieldMeta>={
  "employer.name":{label:"Nombre o razón social del empleador"},
  "employer.rut":{label:"RUT del empleador"},
  "worker.name":{label:"Nombre completo del trabajador"},
  "worker.rut":{label:"RUT del trabajador"},
  "site.name":{label:"Obra"},
  "role":{label:"Labor / especialidad",hint:"Escribe Pintura o Pintor: GALANT utilizará el cargo reconocido por la matriz"},
  "extra.representative_name":{label:"Nombre del representante legal"},
  "extra.representative_rut":{label:"RUT del representante legal"},
  "extra.representative_nationality":{label:"Nacionalidad del representante"},
  "extra.employer_phone":{label:"Teléfono del empleador",type:"tel"},
  "extra.employer_address":{label:"Domicilio del empleador"},
  "extra.employer_commune":{label:"Comuna del empleador"},
  "extra.employer_city":{label:"Ciudad del empleador"},
  "extra.employer_email":{label:"Correo del empleador",type:"email"},
  "extra.specialty":{label:"Rubro o labor de la empresa"},
  "extra.worker_nationality":{label:"Nacionalidad del trabajador"},
  "extra.worker_birthdate":{label:"Fecha de nacimiento",type:"date"},
  "extra.worker_marital_status":{label:"Estado civil"},
  "extra.worker_address":{label:"Domicilio del trabajador"},
  "extra.worker_commune":{label:"Comuna del trabajador"},
  "extra.worker_city":{label:"Ciudad de procedencia"},
  "extra.worker_email":{label:"Correo del trabajador",type:"email"},
  "extra.worker_phone":{label:"Teléfono del trabajador",type:"tel"},
  "extra.site_address":{label:"Dirección de la obra / lugar inicial"},
  "extra.destinations":{label:"Obras o destinos autorizados"},
  "extra.transport_allowance":{label:"Asignación de locomoción"},
  "extra.payment_frequency":{label:"Frecuencia de pago",options:["MENSUALMENTE","QUINCENALMENTE","SEMANALMENTE"]},
  "extra.bank_account":{label:"Detalle de cuenta bancaria"},
  "extra.afp":{label:"AFP del trabajador",hint:"AFP y previsión de salud son datos distintos"},
  "extra.health_provider":{label:"Previsión de salud (Fonasa / Isapre)"},
  "extra.salary_words":{label:"Sueldo en palabras (generado desde monto)",hint:"Se calcula automáticamente si se deja vacío"},
  "extra.principal_company":{label:"Empresa mandante / contratista principal"},
  "extra.declaration_period":{label:"Mes declarado (AAAA-MM)",type:"month"},
  "extra.regulation_version":{label:"Versión de Reglamento Interno"},
  "contract.regulation_version":{label:"Versión de Reglamento Interno"},
  "contract.start":{label:"Fecha real de ingreso",type:"date"},
  "contract.end":{label:"Fecha de término del contrato",type:"date"},
  "contract.new_end":{label:"Nueva fecha de término",type:"date"},
  "contract.transfer_date":{label:"Fecha de traslado",type:"date"},
  "contract.salary":{label:"Sueldo base ($ CLP)",type:"number"},
  "contract.hours":{label:"Jornada semanal (horas)",type:"number"},
  "contract.declaration_reason":{label:"Motivo de declaración jurada"},
  "event.date":{label:"Fecha efectiva del documento",type:"date",hint:"No acredita por sí sola una entrega, firma ni capacitación"},
  "event.epp_items":{label:"EPP efectivamente entregados",hint:"Indica elementos y cantidades; no se marcará ninguno por defecto"},
  "event.pts_version":{label:"Versión del PTS efectivamente entregado"},
};
const EXTRA_CONTRACT=["extra.representative_name","extra.representative_rut","extra.employer_phone",
  "extra.employer_address","extra.employer_commune","extra.employer_city","extra.employer_email",
  "extra.worker_nationality","extra.worker_birthdate","extra.worker_marital_status","extra.worker_address",
  "extra.worker_commune","extra.worker_city","extra.worker_email","extra.worker_phone",
  "extra.site_address","extra.payment_frequency","extra.bank_account","extra.afp","extra.health_provider",
  "contract.start","contract.end","contract.salary","contract.hours","event.date"];
const EXCEL_FIELDS:Record<string,string[]>={
  labor_contract:EXTRA_CONTRACT,
  transfer_addendum:["role","extra.site_address","extra.destinations","extra.transport_allowance",
    "extra.employer_city","contract.transfer_date","event.date"],
  extension_addendum:["contract.start","contract.end","contract.new_end","event.date",
    "extra.representative_name","extra.representative_rut"],
  sworn_declaration:["extra.representative_name","extra.representative_rut",
    "extra.representative_nationality","extra.employer_address","extra.employer_city",
    "extra.principal_company","extra.declaration_period","contract.declaration_reason",
    "role","extra.site_address","event.date"],
  internal_rules_receipt:["extra.regulation_version","extra.employer_city","event.date"],
  ppe_delivery:["role","event.epp_items","event.date"],
  irl:["role","event.date"],pts:["role","event.date","extra.representative_name","extra.representative_rut"],
  pts_receipt:["role","event.date","event.pts_version","extra.representative_name","extra.representative_rut"],
  induction:["role","event.date","extra.representative_name","extra.representative_rut",
    "extra.employer_phone","extra.employer_address","extra.site_address","extra.principal_company"],
};
const EMPLOYER_KEYS=["extra.representative_name","extra.representative_rut","extra.representative_nationality",
  "extra.employer_phone","extra.employer_address","extra.employer_commune",
  "extra.employer_city","extra.employer_email","extra.site_address","extra.specialty"];
const WORKER_KEYS=["extra.worker_nationality","extra.worker_birthdate","extra.worker_marital_status",
  "extra.worker_address","extra.worker_commune","extra.worker_city","extra.worker_email",
  "extra.worker_phone","extra.afp","extra.health_provider"];
const LABELS:Record<string,string>={POR_DETERMINAR:"Por determinar",NO_APLICA:"No corresponde",
  FALTAN_DATOS:"Faltan datos",PENDIENTE_REVISION:"Pendiente de aprobar plantilla o matriz",
  LISTO_PARA_EMITIR:"Listo para PDF",PREVISUALIZABLE:"Vista previa disponible",
  EMITIDO:"PDF generado",EXISTENTE_POR_VERIFICAR:"Documento anterior a verificar"};
const label=(key:string)=>F[key]?.label||key.replace(/^extra\./,"").replaceAll("_"," ").replaceAll("."," · ");
const pick=(v:Record<string,string>,key:string)=>v[key]||"";
const origin=(code:string):Group=>DOC_AREA[code]||"Zona Subcontratos";
const canonical=(name:string,aliases:Record<string,string>)=>{
  const k=name.normalize("NFD").replace(/[\u0300-\u036f]/g,"").trim().toUpperCase().replace(/\s+/g," ");
  return aliases[k]||k;
};
const relationshipOnly=(code:string)=>code==="sworn_declaration";
const isEmployerField=(key:string)=>key.startsWith("extra.representative")||key.startsWith("extra.employer")||
  key==="extra.principal_company"||key==="extra.site_address";
const isWorkerField=(key:string)=>key.startsWith("extra.worker")||key==="extra.afp"||key==="extra.health_provider";
const errText=(e:unknown)=>e instanceof Error?e.message:String(e);
const money=(s:string)=>s?new Intl.NumberFormat("es-CL",{maximumFractionDigits:0}).format(Number(s)||0):"";
async function pdfPreview(dossierId:string,code:string){
  const token=document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch("/api/v1/javiera/preview",{method:"POST",
    headers:{"Content-Type":"application/json","X-CSRF-Token":token},
    credentials:"include",cache:"no-store",body:JSON.stringify({dossier_id:dossierId,code})});
  if(!response.ok){const x=await response.json().catch(()=>({detail:"Vista previa no disponible"}));
    throw new Error(typeof x.detail==="string"?x.detail:"La plantilla no está preparada para vista previa");}
  return response.blob();
}
function pdfTab(blob:Blob){
  const link=URL.createObjectURL(blob);
  window.open(link,"_blank","noopener,noreferrer");
  window.setTimeout(()=>URL.revokeObjectURL(link),120000);
}
function buildData(v:Record<string,string>,code:string,siteName:string,aliases:Record<string,string>,workerless:boolean){
  const extra:Record<string,string>={};
  for(const [key,value] of Object.entries(v))if(key.startsWith("extra."))extra[key.slice(6)]=value;
  const role=canonical(pick(v,"role"),aliases);
  extra.specialty=role;
  const c:Record<string,string>={},e:Record<string,string>={};
  for(const [key,value] of Object.entries(v)){
    if(key.startsWith("contract."))c[key.slice(9)]=value;
    if(key.startsWith("event."))e[key.slice(6)]=value;
  }
  return {employer:{name:pick(v,"employer.name"),rut:pick(v,"employer.rut")},
    worker:{name:workerless?"":pick(v,"worker.name"),rut:workerless?"":pick(v,"worker.rut")},
    site:{name:siteName},role,employment_type:pick(v,"employment_type"),
    event_type:EVENT[code]||"ingreso",contract:c,event:e,extra};
}
function flattenData(data:Record<string,unknown>){
  const result:Record<string,string>={};
  for(const [key,obj] of Object.entries(data)){
    if(["employer","worker","contract","event","extra"].includes(key)&&typeof obj==="object"&&obj){
      for(const [child,val] of Object.entries(obj))result[key+"."+child]=String(val??"");
    } else if(["role","employment_type"].includes(key))result[key]=String(obj??"");
  }
  return result;
}

export default function JavieraWorkspace({onConfig}:{onConfig?:()=>void}){
  const [relation,setRelation]=useState<Relation|null>(null);
  const [area,setArea]=useState<Group>("Prevención de Riesgos");
  const [selectedDoc,setSelectedDoc]=useState("");
  const [source,setSource]=useState<Source>({sites:[],contractors:[],workers:[]});
  const [catalog,setCatalog]=useState<Catalog[]>([]);
  const [roles,setRoles]=useState<RoleResult>({roles:[],aliases:{},matrix_roles:[]});
  const [siteId,setSiteId]=useState("");
  const [companyKind,setCompanyKind]=useState<"new"|"existing">("new");
  const [companyId,setCompanyId]=useState("");
  const [workerKind,setWorkerKind]=useState<"new"|"existing">("new");
  const [workerId,setWorkerId]=useState("");
  const [parentId,setParentId]=useState("");
  const [values,setValues]=useState<Record<string,string>>({});
  const [origins,setOrigins]=useState<Record<string,string>>({});
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);
  const [saved,setSaved]=useState<Dossier|null>(null);
  const [storedSignature,setStoredSignature]=useState("");
  const [status,setStatus]=useState<{signature:string;items:State[]}|null>(null);
  const [lastDossiers,setLastDossiers]=useState<OldDossier[]>([]);
  const requestRevision=useRef(0);

  const setField=(key:string,value:string)=>{setValues(prev=>({...prev,[key]:value}));
    setOrigins(prev=>({...prev,[key]:"Ingresado manualmente"}));};
  const currentSite=source.sites.find(s=>s.id===siteId);
  const groupDocs=catalog.filter(c=>origin(c.code)===area).sort((a,b)=>ORDER.indexOf(a.code)-ORDER.indexOf(b.code));
  const workerless=relationshipOnly(selectedDoc);
  const currentData=useMemo(()=>buildData(values,selectedDoc,currentSite?.name||"",roles.aliases,workerless),
    [values,selectedDoc,currentSite?.name,roles.aliases,workerless]);
  const signature=JSON.stringify({siteId,relation,parentId,
    company:companyKind==="new"?"new":companyId,
    worker:workerless?"none":workerKind==="new"?"new":workerId,
    selectedDoc,data:currentData});
  const changed=!saved||signature!==storedSignature;
  const currentCatalog=catalog.find(c=>c.code===selectedDoc);
  const keys=useMemo(()=>{
    if(!selectedDoc)return [];
    const selected=(currentCatalog?.required_fields||[]).concat(EXCEL_FIELDS[selectedDoc]||[]);
    return [...new Set(selected)].filter(k=>!["employer.name","employer.rut","worker.name",
      "worker.rut","site.name","role","extra.specialty","contract.regulation_version"].includes(k));
  },[selectedDoc,currentCatalog?.required_fields]);
  const docs=status?.signature===JSON.stringify(currentData)?status.items:[];
  const chosenStatus=docs.find(c=>c.code===selectedDoc);
  const missing=chosenStatus?.missing_fields||[];
  const errors=chosenStatus?.blocking_errors||[];
  const complete=chosenStatus?.completion_percent||0;

  useEffect(()=>{
    void Promise.all([
      request<Catalog[]>("/javiera/catalog"),
      request<RoleResult>("/javiera/roles"),
      request<Source>("/javiera/sources"),
    ]).then(([c,r,s])=>{setCatalog(c);setRoles(r);setSource(s);})
      .catch(e=>setError(errText(e)));
  },[]);
  useEffect(()=>{
    let active=true;
    request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+
      "&contractor_id="+encodeURIComponent(companyKind==="existing"?companyId:""))
      .then(s=>{if(active)setSource(s);})
      .catch(e=>{if(active)setError(errText(e));});
    return()=>{active=false;};
  },[siteId,companyKind,companyId]);
  useEffect(()=>{
    if(!relation||!selectedDoc)return;
    const controller=new AbortController();
    requestRevision.current+=1;
    const stamp=requestRevision.current;
    const pending=window.setTimeout(()=>{
      request<{documents:State[]}>("/javiera/eligibility/evaluate",{
        method:"POST",signal:controller.signal,body:JSON.stringify({
          data:currentData,dossier_id:saved?.id||null,data_revision:stamp,
        }),
      }).then(r=>{if(stamp===requestRevision.current)setStatus({
        signature:JSON.stringify(currentData),items:r.documents,
      });}).catch(e=>{if(!controller.signal.aborted)setError(errText(e));});
    },240);
    return()=>{controller.abort();window.clearTimeout(pending);};
  },[relation,selectedDoc,currentData,saved?.id,saved?.revision]);

  async function prefillCompany(id:string,site:string){
    if(!id||!site)return;
    try{
      const all=await request<OldDossier[]>("/javiera/dossiers?site_id="+encodeURIComponent(site)+
        "&employer_id="+encodeURIComponent(id));
      setLastDossiers(all);
      if(!all.length)return;
      const record=await request<Dossier>("/javiera/dossiers/"+encodeURIComponent(all[0].id));
      const historical=flattenData(record.data);
      const supplement:Record<string,string>={};
      for(const key of EMPLOYER_KEYS)if(historical[key])supplement[key]=historical[key];
      setValues(previous=>({...supplement,...Object.fromEntries(Object.entries(previous).filter(([,v])=>v))}));
      setOrigins(previous=>({...previous,...Object.fromEntries(Object.keys(supplement).map(k=>[k,"Recuperado de una ficha anterior en esta obra"]))}));
      if(Object.keys(supplement).length)setNotice("Datos de la empresa recuperados de su última ficha. Revisa que sigan vigentes.");
    }catch(e){setError(errText(e));}
  }
  function chooseSite(next:string){
    setSiteId(next);setCompanyId("");setWorkerId("");setParentId("");setSaved(null);setStoredSignature("");
    setValues({});setOrigins({});setLastDossiers([]);setNotice("");
  }
  function chooseCompany(next:string){
    setCompanyId(next);setWorkerId("");setSaved(null);setStoredSignature("");
    const sourceCompany=source.contractors.find(c=>c.id===next);
    setValues({"employer.name":sourceCompany?.name||"","employer.rut":sourceCompany?.rut||""});
    setOrigins({"employer.name":"GALANT","employer.rut":"GALANT"});
    void prefillCompany(next,siteId);
  }
  function chooseWorker(next:string){
    setWorkerId(next);setSaved(null);setStoredSignature("");
    const w=source.workers.find(x=>x.id===next);
    setValues(prev=>({...prev,"worker.name":w?.name||"","worker.rut":w?.rut||""}));
    setOrigins(prev=>({...prev,"worker.name":"GALANT","worker.rut":"GALANT"}));
  }
  async function loadDossier(id:string){
    setBusy(true);setError("");
    try{
      const doc=await request<Dossier>("/javiera/dossiers/"+encodeURIComponent(id));
      const all=flattenData(doc.data);
      const source=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(doc.site_id)+
        "&contractor_id="+encodeURIComponent(doc.employer_id));
      setSource(source);setSiteId(doc.site_id);setCompanyKind("existing");setCompanyId(doc.employer_id);
      setWorkerKind(doc.worker_id?"existing":"new");setWorkerId(doc.worker_id||"");
      setRelation(doc.relationship);setParentId(doc.parent_id||"");
      setValues(all);setOrigins(Object.fromEntries(Object.keys(all).map(key=>[key,"Ficha guardada de GALANT"])));
      const effective=Object.keys(EVENT).find(code=>EVENT[code]===String(doc.data.event_type||"ingreso")&&
        code!=="labor_contract"&&code!=="pts"&&code!=="irl")||"";
      const documentCode=selectedDoc||effective||(doc.data.employment_type==="dependiente"?"labor_contract":"pts");
      setSelectedDoc(documentCode);setArea(origin(documentCode));
      setSaved(doc);
      const built=buildData(all,documentCode,source.sites.find(s=>s.id===doc.site_id)?.name||"",
        roles.aliases,relationshipOnly(documentCode));
      setStoredSignature(JSON.stringify({siteId:doc.site_id,relation:doc.relationship,parentId:doc.parent_id||"",
        company:doc.employer_id,worker:relationshipOnly(documentCode)?"none":doc.worker_id||"new",
        selectedDoc:documentCode,data:built}));
      setNotice("Expediente recuperado. Puedes continuar con sus datos y generar otros documentos.");
    }catch(e){setError(errText(e));}finally{setBusy(false);}
  }

  async function saveDossier():Promise<string>{
    if(!relation||!siteId||!selectedDoc)throw new Error("Selecciona la obra, el tipo de expediente y el documento.");
    if(!pick(values,"employer.name").trim())throw new Error("Escribe o selecciona el empleador.");
    if(relation==="subcontractor"&&!parentId)throw new Error("Selecciona la empresa contratista principal.");
    if(!workerless&&!pick(values,"worker.name").trim())throw new Error("Indica el nombre del trabajador.");
    if(busy)throw new Error("Ya existe una operación en curso.");
    setBusy(true);setError("");setNotice("");
    let employer=companyId,worker=workerId;
    try{
      if(companyKind==="new"){
        const created=await opsApi.createContractor({site_id:siteId,
          name:pick(values,"employer.name").trim(),rut:pick(values,"employer.rut").trim()||null,
          historical_code:"",nature:"unclassified",frequency:"unclassified",contract_status:"active"});
        employer=created.contractor_id;setCompanyId(employer);setCompanyKind("existing");
      }
      if(!workerless&&workerKind==="new"){
        const created=await opsApi.createWorker({site_id:siteId,contractor_id:employer,
          name:pick(values,"worker.name").trim(),rut:pick(values,"worker.rut").trim()||null});
        worker=created.worker_id;setWorkerId(worker);setWorkerKind("existing");
      }
      const savedData=buildData(values,selectedDoc,currentSite?.name||"",roles.aliases,workerless);
      const result=await request<{id:string;revision:number}>("/javiera/dossiers",{
        method:"POST",body:JSON.stringify({site_id:siteId,employer_id:employer,
          worker_id:workerless?null:worker||null,parent_id:relation==="subcontractor"?parentId:null,
          relationship:relation,data:{...savedData,...(saved?.id?{_dossier_id:saved.id}:{})},
          expected_revision:saved?.id?saved.revision:null}),
      });
      const loaded=await request<Dossier>("/javiera/dossiers/"+encodeURIComponent(result.id));
      setSaved(loaded);
      setStoredSignature(JSON.stringify({siteId,relation,parentId,
        company:employer,worker:workerless?"none":worker||"new",selectedDoc,data:savedData}));
      const fresh=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+
        "&contractor_id="+encodeURIComponent(employer));
      setSource(fresh);setNotice("Ficha guardada. Puedes preparar el PDF seleccionado.");
      return result.id;
    }catch(e){setError(errText(e));throw e;}finally{setBusy(false);}
  }
  async function openPreview(){
    if(!selectedDoc)return;
    try{
      const id=!changed&&saved?.id?saved.id:await saveDossier();
      pdfTab(await pdfPreview(id,selectedDoc));
    }catch(e){setError(errText(e));}
  }
  async function issuePdf(action:"print"|"download"){
    if(!selectedDoc)return;
    if(chosenStatus?.status!=="LISTO_PARA_EMITIR"&&chosenStatus?.status!=="EMITIDO"){
      setError("El documento aún no puede emitirse. Revisa los campos y la aprobación de su plantilla.");return;
    }
    let tab:Window|null=null;
    if(action==="print")tab=window.open("about:blank","_blank");
    try{
      const id=!changed&&saved?.id?saved.id:await saveDossier();
      const result=await request<{id:string;reused:boolean}>("/javiera/issue",{
        method:"POST",body:JSON.stringify({dossier_id:id,code:selectedDoc}),
      });
      const endpoint="/api/v1/javiera/issued/"+encodeURIComponent(result.id)+"/pdf";
      if(action==="print"){
        if(tab)tab.location.href=endpoint;else window.open(endpoint,"_blank","noopener,noreferrer");
      }else{
        const response=await fetch(endpoint,{credentials:"include",cache:"no-store"});
        if(!response.ok)throw new Error("No se pudo descargar el PDF.");
        const url=URL.createObjectURL(await response.blob());
        const a=document.createElement("a");a.href=url;a.download="JAVIERA-"+selectedDoc+".pdf";a.click();
        window.setTimeout(()=>URL.revokeObjectURL(url),60000);
      }
      setSaved(await request<Dossier>("/javiera/dossiers/"+encodeURIComponent(id)));
      setNotice(result.reused?"PDF emitido anteriormente recuperado.":"PDF generado. No equivale a firma, entrega ni capacitación.");
    }catch(e){tab?.close();setError(errText(e));}
  }

  function changeDoc(code:string){
    setSelectedDoc(code);setError("");setNotice("");setStatus(null);
    if(relationshipOnly(code)){setWorkerKind("new");setWorkerId("");}
    if(!relationshipOnly(code)&&workerKind==="new"&&!values["worker.name"])setWorkerId("");
  }
  function renderField(key:string){
    const meta=F[key]||{label:label(key)};
    const value=pick(values,key);
    const isRequired=missing.includes(key);
    const valid=!!value.trim();
    const src=origins[key];
    return <label className={"j65-field "+(isRequired?"j65-required":"")} key={key} htmlFor={"jf-"+key.replaceAll(".","-")}>
      <span>{meta.label}{isRequired&&<em> · pendiente</em>}</span>
      {meta.options?<select id={"jf-"+key.replaceAll(".","-")} value={value} onChange={e=>setField(key,e.target.value)}>
        <option value="">Selecciona</option>{meta.options.map(x=><option key={x} value={x}>{x}</option>)}
      </select>:<input id={"jf-"+key.replaceAll(".","-")} type={meta.type||"text"} value={value}
        min={meta.type==="number"?"0":undefined} autoComplete="off"
        onChange={e=>setField(key,e.target.value)} placeholder={meta.type==="date"?"":meta.label}/>}
      {(src||meta.hint)&&<small>{src&&valid?"<span>":"":src&&valid?"Recuperado de "+src+". ":""}{meta.hint||""}</small>}
    </label>;
  }

  if(!relation)return <section className="j65">
    <div className="j65-intro"><small>GALANT · 16.5 · PROYECTO JAVIERA</small><h2>¿Para quién prepararás los documentos?</h2>
      <p>Elige el tipo de empresa. Después seleccionarás el documento; solo pediremos los datos necesarios.</p></div>
    <div className="j65-entry">
      <button onClick={()=>setRelation("contractor")}><FolderPlus size={27}/><strong>Contratistas</strong>
        <span>Empresa nueva o existente. Contratos, anexos, PTS, IRL y prevención.</span><span className="j65-link">Comenzar <ChevronRight size={16}/></span></button>
      <button onClick={()=>setRelation("subcontractor")}><ShieldCheck size={27}/><strong>Subcontratos</strong>
        <span>Empleador directo diferente de la empresa contratista principal.</span><span className="j65-link">Comenzar <ChevronRight size={16}/></span></button>
    </div>
    <p className="j65-footnote"><Info size={15}/> El sistema no copiará nombres, RUT ni sueldos de ejemplo del Excel a empresas nuevas.</p>
  </section>;

  const forms=keys.filter(k=>k.startsWith("contract.")&&k!=="contract.declaration_reason");
  const employerExtra=keys.filter(k=>isEmployerField(k));
  const workerExtra=keys.filter(k=>isWorkerField(k));
  const events=keys.filter(k=>k.startsWith("event.")||k==="extra.regulation_version"||k==="contract.declaration_reason"||
    k==="extra.declaration_period"||k==="extra.destinations"||k==="extra.transport_allowance");
  const other=keys.filter(k=>!forms.includes(k)&&!employerExtra.includes(k)&&!workerExtra.includes(k)&&
    !events.includes(k)&&k!=="role"&&k!=="extra.specialty");
  const noContract=area==="Prevención de Riesgos";
  const fieldCount=keys.length+(!workerless?2:0)+2;
  return <section className="j65">
    <div className="j65-intro">
      <button className="j65-back" onClick={()=>{setRelation(null);setSelectedDoc("");}}><ArrowLeft size={16}/> Volver a Proyecto JAVIERA</button>
      <small>PROYECTO JAVIERA · {relation==="contractor"?"CONTRATISTAS":"SUBCONTRATOS"}</small>
      <div className="j65-heading"><div><h2>Preparar e imprimir documentos</h2>
        <p>Primero elige un documento. La ficha se adapta a lo que necesita y recupera datos ya registrados.</p></div>
        {onConfig&&<button className="j65-settings" onClick={onConfig}><Settings2 size={16}/> Configurar documentos</button>}
      </div>
    </div>
    {error&&<p className="j65-alert" role="alert"><AlertCircle size={18}/>{error}</p>}
    {notice&&<p className="j65-confirm" role="status"><CheckCircle2 size={18}/>{notice}</p>}
    <div className="j65-tabs" role="group" aria-label="Área documental">
      {(["Prevención de Riesgos","Zona Subcontratos"] as Group[]).map(group=>
        <button key={group} aria-pressed={group===area} className={group===area?"selected":""}
          onClick={()=>{setArea(group);setSelectedDoc("");setStatus(null);}}>
          {group==="Prevención de Riesgos"?<ShieldCheck size={17}/>:<FileText size={17}/>}
          {group}</button>)}
    </div>
    <div className="j65-layout">
      <aside className="j65-documents" aria-label="Documentos para preparar">
        <div className="j65-sidebar-head"><strong>1. ¿Qué necesitas generar?</strong><small>{groupDocs.length} tipos de documento</small></div>
        {groupDocs.map(c=>{
          const selected=c.code===selectedDoc;
          const st=selected?chosenStatus:null;
          return <button key={c.code} className={"j65-doc-choice "+(selected?"selected":"")}
            aria-pressed={selected} onClick={()=>changeDoc(c.code)}>
            <FileText size={18}/><span><b>{TITLES[c.code]||c.title}</b>
              <small>{selected&&st?(LABELS[st.status]||st.status):"Seleccionar y preparar"}</small></span>
            <ChevronRight size={15}/></button>;
        })}
        <div className="j65-sidebar-note"><ClipboardCheck size={17}/> La emisión de un PDF no implica que el documento esté firmado ni entregado.</div>
      </aside>
      <div className="j65-editor">
        {!selectedDoc?<div className="j65-empty"><FileCheck2 size={38}/><h3>Selecciona un documento a la izquierda</h3>
          <p>Si necesitas un PTS, por ejemplo, solo pediré empresa, obra, trabajador, labor y datos preventivos. No sueldo ni contrato.</p></div>:<>
          <header className="j65-editor-head"><div><small>DOCUMENTO SELECCIONADO</small>
            <h3>{TITLES[selectedDoc]||currentCatalog?.title}</h3>
            <p>{noContract?"Sin datos contractuales ni bancarios. Solo antecedentes del documento preventivo.":
              "Datos laborales solicitados según la hoja correspondiente del Excel."}</p></div>
            <div className="j65-progress"><strong>{complete}%</strong><span>completado</span></div>
          </header>
          <div className="j65-progress-line"><span style={{width:complete+"%"}}/></div>
          <section className="j65-section"><h4>2. Obra y empresa empleadora</h4>
            <label className="j65-field">Obra<select value={siteId} onChange={e=>chooseSite(e.target.value)}>
              <option value="">Selecciona una obra</option>{source.sites.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
            </select></label>
            <div className="j65-switch" role="group" aria-label="Estado de la empresa">
              <button className={companyKind==="new"?"active":""} aria-pressed={companyKind==="new"} onClick={()=>{
                setCompanyKind("new");setCompanyId("");setWorkerId("");setWorkerKind("new");setSaved(null);
                setValues(prev=>({...prev,"employer.name":"","employer.rut":"","worker.name":"","worker.rut":""}));}}>
                <FolderPlus size={16}/> Empresa nueva</button>
              <button className={companyKind==="existing"?"active":""} aria-pressed={companyKind==="existing"} onClick={()=>{
                setCompanyKind("existing");setCompanyId("");setWorkerId("");setSaved(null);
              }}>Ya existe en GALANT</button>
            </div>
            {companyKind==="existing"?<label className="j65-field">Buscar empresa
              <select disabled={!siteId} value={companyId} onChange={e=>chooseCompany(e.target.value)}>
                <option value="">Selecciona un contratista</option>
                {source.contractors.filter(c=>c.site_id===siteId).map(c=><option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>:<div className="j65-paired">
              {renderField("employer.name")}{renderField("employer.rut")}
            </div>}
            {companyKind==="existing"&&companyId&&<p className="j65-source-tag">Nombre y RUT recuperados de GALANT. Solo se reutilizarán antecedentes previos de la misma empresa y obra.</p>}
            {relation==="subcontractor"&&<label className="j65-field">Contratista principal (no es el empleador directo)
              <select value={parentId} onChange={e=>setParentId(e.target.value)} disabled={!siteId}>
                <option value="">Selecciona el contratista principal</option>
                {source.contractors.filter(c=>c.site_id===siteId&&c.id!==companyId).map(c=>
                  <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>}
            {employerExtra.length>0&&<div className="j65-paired">{employerExtra.map(renderField)}</div>}
          </section>
          {!workerless&&<section className="j65-section"><h4>3. Trabajador y labor</h4>
            <div className="j65-switch" role="group" aria-label="Estado del trabajador">
              <button className={workerKind==="new"?"active":""} aria-pressed={workerKind==="new"}
                onClick={()=>{setWorkerKind("new");setWorkerId("");setSaved(null);
                  setValues(prev=>({...prev,"worker.name":"","worker.rut":""}));}}><UserPlus size={15}/> Trabajador nuevo</button>
              <button className={workerKind==="existing"?"active":""} aria-pressed={workerKind==="existing"}
                onClick={()=>{setWorkerKind("existing");setWorkerId("");setSaved(null);}}>Ya registrado</button>
            </div>
            {workerKind==="existing"?<label className="j65-field">Buscar trabajador
              <select disabled={!companyId} value={workerId} onChange={e=>chooseWorker(e.target.value)}>
                <option value="">Selecciona un trabajador de esta empresa</option>{source.workers.map(w=>
                  <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>:
              <div className="j65-paired">{renderField("worker.name")}{renderField("worker.rut")}</div>}
            {renderField("role")}
            <datalist id="j65-roles">{roles.roles.map(x=><option key={x} value={x}/>)}</datalist>
            <p className="j65-source-tag">Cargo reconocido: <strong>{canonical(pick(values,"role"),roles.aliases)||"Sin seleccionar"}</strong>. El mismo dato determina la labor y la matriz PTS/IRL.</p>
            {noContract&&<p className="j65-source-tag">Prevención de Riesgos: no se solicita sueldo, jornada ni vigencia del contrato.</p>}
            {workerExtra.length>0&&<details className="j65-details" open><summary>Antecedentes personales solicitados</summary>
              <div className="j65-paired">{workerExtra.map(renderField)}</div></details>}
          </section>}
          {workerless&&<section className="j65-section"><h4>3. Declaración de la empresa</h4>
            <p className="j65-source-tag">Este documento corresponde a la empresa, no a un trabajador determinado. Debe verificarse que realmente no existan trabajadores en el período declarado.</p>
            {renderField("role")}
          </section>}
          {forms.length>0&&<section className="j65-section"><h4>{noContract?"Datos específicos":"4. Datos laborales del documento"}</h4>
            <div className="j65-paired">{forms.map(renderField)}</div>
            {forms.includes("contract.salary")&&<p className="j65-source-tag">Sueldo base indicado: {money(pick(values,"contract.salary"))} CLP. GALANT lo convertirá a palabras al generar el PDF.</p>}
          </section>}
          {(events.length>0||other.length>0)&&<section className="j65-section"><h4>{noContract?"4. Constancia y datos preventivos":"5. Datos finales del documento"}</h4>
            <div className="j65-paired">{[...events,...other].map(renderField)}</div>
          </section>}
          {lastDossiers.length>0&&companyKind==="existing"&&<section className="j65-section j65-previous">
            <h4>Continuar una ficha anterior</h4><label className="j65-field">Expedientes guardados
              <select value={saved?.id||""} onChange={e=>{if(e.target.value)void loadDossier(e.target.value);}}>
                <option value="">Selecciona solo si deseas recuperar sus datos</option>
                {lastDossiers.filter(d=>d.relationship===relation).map(d=><option key={d.id} value={d.id}>Ficha {d.id.slice(0,8)} · revisión {d.revision}</option>)}
              </select></label>
          </section>}
          <div className="j65-actions">
            <div><strong>5. ¿Qué quieres hacer con este documento?</strong>
              <small>{chosenStatus?(LABELS[chosenStatus.status]||chosenStatus.status):"Completando evaluación…"} · {missing.length} campos pendientes</small></div>
            <div className="j65-action-buttons">
              <button disabled={busy||!siteId} className="j65-save" onClick={()=>{void saveDossier().catch(()=>{});}}>
                <ClipboardCheck size={16}/> {saved?"Guardar cambios":"Guardar ficha"}</button>
              <button disabled={busy||!chosenStatus?.can_preview} onClick={()=>void openPreview()}><Eye size={17}/> Vista previa</button>
              <button className="j65-print" disabled={busy||!(chosenStatus?.can_issue||chosenStatus?.status==="EMITIDO")}
                onClick={()=>void issuePdf("print")}><Printer size={17}/> Imprimir PDF</button>
              <button disabled={busy||!(chosenStatus?.can_issue||chosenStatus?.status==="EMITIDO")}
                onClick={()=>void issuePdf("download")}><Download size={17}/> Descargar PDF</button>
            </div>
            {missing.length>0&&<div className="j65-missing"><b>Para preparar este documento falta:</b>
              <div>{missing.slice(0,12).map(f=><button key={f} onClick={()=>document.getElementById("jf-"+f.replaceAll(".","-"))?.focus()}>
                {label(f)}</button>)}</div></div>}
            {errors.map((m,i)=><p key={i} className="j65-inline-error">{m}</p>)}
            {chosenStatus?.status==="PENDIENTE_REVISION"&&<p className="j65-inline-error">
              Para emitir, la plantilla del Excel y las matrices pertinentes deben estar publicadas por los revisores responsables.
              {onConfig&&<button onClick={onConfig}> Ir a Configuración de automatización</button>}
            </p>}
            {saved&&<small>Ficha #{saved.id.slice(0,8)} · Revisión {saved.revision}{changed?" · con cambios sin guardar":""}</small>}
            {saved?.issues.filter(x=>x.code===selectedDoc).map(x=><a className="j65-issued" href={"/api/v1/javiera/issued/"+encodeURIComponent(x.id)+"/pdf"} key={x.id} target="_blank" rel="noreferrer">
              <FileCheck2 size={15}/> PDF generado anteriormente · Abrir</a>)}
          </div>
        </>}
      </div>
    </div>
  </section>;
}
