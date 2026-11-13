import {lazy, Suspense, useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, ClipboardList, Download, FileText, FolderOpen, Settings2, ShieldCheck, Upload, AlertCircle} from "lucide-react";
import {request} from "./api";
import {opsApi} from "./opsApi";
import "./javiera.css";
import {dossierFields,emptyContract,emptyEvent,stableFingerprint} from "./javiera-dossier-state";
import {parseEppDraft,serializeEppDraft,type EppChoice} from "./javiera-epp";
const JavieraWorkbookAdmin=lazy(()=>import("./JavieraWorkbookAdmin"));

type Source = {sites: {id:string;name:string}[];contractors:{id:string;site_id:string;name:string;rut:string|null;nature:string;defaults?:Record<string,string>}[];workers:{id:string;name:string;rut:string|null;active:boolean;contract?:{start?:string;end?:string}}[]};
type Catalog = {code:string;area:string;title:string;required_fields:string[];published_version:number};
type Status = {code:string;area:string;title:string;status:string;reason:string;missing_fields:string[];blocking_errors:string[];completion_percent:number;can_preview:boolean;can_issue:boolean;has_history:boolean;template_version:number;source_cells?:string[];cache_hit?:boolean};
type DossierSummary = {id:string;site_id:string;employer_id:string;worker_id:string|null;relationship:string;revision:number;worker_name?:string;employer_name?:string};
type BatchResult = {dossier_id?:string;code:string;ok:boolean;id?:string;reason?:string};
type Dossier = {id:string;revision:number;data:Record<string,unknown>;site_id:string;employer_id:string;worker_id:string|null;parent_id:string|null;relationship:string;issues:{id:string;code:string;at:string;sha256:string;version:number}[];historical:{id:string;code:string;state:string;comment:string}[]};
const emptySource:Source={sites:[],contractors:[],workers:[]};
const statusText:Record<string,string>={
  POR_DETERMINAR:"Por determinar", NO_APLICA:"No aplica", FALTAN_DATOS:"Faltan datos",
  PENDIENTE_REVISION:"Revisar configuración", PREVISUALIZABLE:"Vista previa disponible",
  LISTO_PARA_EMITIR:"Listo para PDF", EXISTENTE_POR_VERIFICAR:"Documento anterior",
  ERROR_TEMPORAL:"Validación no disponible", EMITIDO:"Emitido",
  VALIDANDO_PDF:"Comprobando PDF", BLOQUEADO_PLANTILLA:"Error de plantilla",
  GUARDAR_FICHA:"Guardar para verificar"
};
const validField=(key:string)=>key.replaceAll(".","_");
const formatRutDisplay=(value:string):string=>{
  const raw=(value||"").trim();
  const compact=raw.replace(/[.\\-\\s]/g,"").toUpperCase();
  const match=compact.match(/^(\\d{7,8})([\\dK])$/);
  return match?match[1].replace(/\\B(?=(\\d{3})+(?!\\d))/g,".")+"-"+match[2]:raw;
};
const isRutField=(key:string)=>key.endsWith(".rut")||key.endsWith("_rut");
const extraLabels:Record<string,string>={representative_name:"Nombre del representante legal",representative_rut:"RUT del representante legal",representative_nationality:"Nacionalidad del representante",employer_address:"Domicilio de la empresa",employer_commune:"Comuna de la empresa",employer_city:"Ciudad de la empresa",employer_phone:"Teléfono de la empresa",employer_email:"Correo de la empresa",worker_nationality:"Nacionalidad del trabajador",worker_birthdate:"Fecha de nacimiento",worker_marital_status:"Estado civil",worker_address:"Domicilio del trabajador",worker_commune:"Comuna del trabajador",worker_city:"Ciudad del trabajador",worker_phone:"Teléfono del trabajador",worker_email:"Correo del trabajador",payment_frequency:"Periodicidad de pago",bank_account:"Datos de pago o cuenta bancaria",afp:"AFP",health_provider:"Sistema de salud",principal_company:"Empresa mandante",declaration_period:"Período de la declaración",site_address:"Dirección de la obra",specialty:"Especialidad",destinations:"Obras de destino autorizadas",transport_allowance:"Asignación de traslado"};
const fieldLabel=(key:string)=>extraLabels[key.replace(/^extra\./,"")]||({"employer.name":"empresa","employer.rut":"RUT de empresa","worker.name":"trabajador","worker.rut":"RUT del trabajador","site.name":"obra","role":"cargo","employment_type":"vínculo laboral","event.date":"fecha del evento","event.epp_items":"EPP entregados","event.pts_version":"versión del PTS","contract.start":"fecha de ingreso","contract.end":"fecha de término","contract.new_end":"nueva fecha de término (anexo de prórroga)","contract.transfer_date":"fecha de traslado","contract.salary":"sueldo base","contract.hours":"horas semanales"} as Record<string,string>)[key]||key.replaceAll("_"," ");
const errorMessage=(e:unknown)=>e instanceof Error?e.message:String(e);
async function pdfRequest(url:string,body:unknown){
  const csrf=document.cookie.split("; ").find(c=>c.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch("/api/v1/javiera"+url,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    credentials:"include",cache:"no-store",body:JSON.stringify(body)});
  if(!response.ok){
    const x=await response.json().catch(()=>({detail:"PDF no disponible"}));
    const d=x.detail||x;
    const missing=Array.isArray(d.missing_fields)?d.missing_fields:Array.isArray(d.missing)?d.missing:[];
    const explanation=typeof d==="string"?d:typeof d.reason==="string"&&d.reason?d.reason:typeof d.error==="string"?d.error:"PDF no disponible";
    throw new Error(explanation+(missing.length?" · Faltan: "+missing.map((f:string)=>fieldLabel(f)).join(", "):""));
  }
  return response.blob();
}
function downloadBlob(blob:Blob,fileName:string){
  const url=URL.createObjectURL(blob),link=document.createElement("a");
  link.href=url;link.download=fileName;link.style.display="none";
  document.body.appendChild(link);link.click();link.remove();
  window.setTimeout(()=>URL.revokeObjectURL(url),30000);
}
async function downloadIssuedPdf(id:string,code:string){
  const response=await fetch("/api/v1/javiera/issued/"+encodeURIComponent(id)+"/pdf",{
    method:"GET",credentials:"include",cache:"no-store"});
  if(!response.ok)throw new Error("El PDF está emitido pero no se pudo descargar (HTTP "+response.status+"). Usa la opción Descargar emitido.");
  const blob=await response.blob();
  if(blob.size<8||(await blob.slice(0,5).text())!=="%PDF-")throw new Error("El servidor no devolvió un archivo PDF válido.");
  downloadBlob(blob,"GALANT-JAVIERA-"+code+".pdf");
}

export default function Javiera({configuration=false,onBack,onConfig}:{configuration?:boolean;onBack?:()=>void;onConfig?:()=>void}){
  const [mode,setMode]=useState<"new"|"existing"|null>(null);
  const [source,setSource]=useState<Source>(emptySource);
  const [catalog,setCatalog]=useState<Catalog[]>([]);
  const [siteId,setSiteId]=useState("");
  const [companyId,setCompanyId]=useState("");
  const [parentId,setParentId]=useState("");
  const [relationship,setRelationship]=useState("contractor");
  const [workerId,setWorkerId]=useState("");
  const [role,setRole]=useState("");
  const [extra,setExtra]=useState<Record<string,string>>({});
  const [employmentType,setEmploymentType]=useState("");
  const [eventType,setEventType]=useState("ingreso");
  const [contract,setContract]=useState(emptyContract);
  const [event,setEvent]=useState(emptyEvent);
  const [dossierId,setDossierId]=useState("");
  const [dossierRevision,setDossierRevision]=useState(0);
  const [saved,setSaved]=useState<Dossier|null>(null);
  const [response,setResponse]=useState<{key:string;documents:Status[]}|null>(null);
  const [preflight,setPreflight]=useState<{key:string;documents:Status[]}|null>(null);
  const [issueFailures,setIssueFailures]=useState<Record<string,string>>({});
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);
  const [filter,setFilter]=useState("todos");
  const [selectedCodes,setSelectedCodes]=useState<string[]|null>(null);
  const [documentSearch,setDocumentSearch]=useState("");
  const [batchMode,setBatchMode]=useState(false);
  const [selectedDossiers,setSelectedDossiers]=useState<string[]>([]);
  const [batchProgress,setBatchProgress]=useState("");
  const [nativeRoles,setNativeRoles]=useState<string[]>([]);
  const [eppOptions,setEppOptions]=useState<EppChoice[]>([]);
  const [savedFingerprint,setSavedFingerprint]=useState("");
  const [existingDossiers,setExistingDossiers]=useState<DossierSummary[]>([]);
  const [newContractor,setNewContractor]=useState({name:"",rut:""});
  const [newWorker,setNewWorker]=useState({name:"",rut:""});
  const [showCreate,setShowCreate]=useState<"contractor"|"worker"|null>(null);
  const [reviewComments,setReviewComments]=useState<Record<string,string>>({});
  const [reissueReasons,setReissueReasons]=useState<Record<string,string>>({});
  const [batchReport,setBatchReport]=useState<BatchResult[]>([]);
  useEffect(()=>{
    if(!busy)return;
    const beforeUnload=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue="";};
    const beforeNavigate=(e:Event)=>{e.preventDefault();setError("Hay una operación en curso. Espera su resultado antes de cambiar de módulo.");};
    window.addEventListener("beforeunload",beforeUnload);window.addEventListener("galant-before-navigate",beforeNavigate);
    return()=>{window.removeEventListener("beforeunload",beforeUnload);window.removeEventListener("galant-before-navigate",beforeNavigate);};
  },[busy]);
  const revision=useRef(0);
  const loadingDossier=useRef(0);
  const actionLock=useRef(false);
  useEffect(()=>{if(configuration)return;let active=true;
    request<{current:{id:string}|null}>("/javiera/workbook").then(async result=>{
      if(result.current){const roles=await request<Record<string,unknown>>("/javiera/workbook/"+result.current.id+"/roles");if(active)setNativeRoles(Object.keys(roles).sort());}
    }).catch(()=>{});return()=>{active=false;};
  },[configuration]);
  useEffect(()=>{
    if(configuration)return;
    void request<Catalog[]>("/javiera/catalog").then(setCatalog).catch(e=>setError(errorMessage(e)));
    void request<EppChoice[]>("/javiera/epp/catalog").then(setEppOptions)
      .catch(e=>setError("No se pudo cargar la lista de EPP: "+errorMessage(e)));
  },[configuration]);
  useEffect(()=>{
    if(configuration)return;
    let alive=true;
    request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+"&contractor_id="+encodeURIComponent(companyId))
      .then(x=>{if(alive)setSource(x);}).catch(e=>{if(alive)setError(errorMessage(e));});
    return ()=>{alive=false;};
  },[configuration,siteId,companyId]);
  const employer=source.contractors.find(x=>x.id===companyId);
  const worker=source.workers.find(x=>x.id===workerId);
  const site=source.sites.find(x=>x.id===siteId);
  const chosenCodes=selectedCodes??catalog.map(c=>c.code);
  // Seleccionar un contrato permite preparar el documento; no acredita que ya esté firmado.
  const inferredEmployment=employmentType||(workerId&&chosenCodes.includes("labor_contract")&&employer?.nature!=="independent"?"dependiente":"");
  const data=useMemo(()=>({
    employer:{name:employer?.name||"",rut:employer?.rut||""},worker:{name:worker?.name||"",rut:worker?.rut||""},
    site:{name:site?.name||""},role,event_type:eventType,employment_type:inferredEmployment,
    requested_documents:chosenCodes,contract,event,extra
  }),[employer?.name,employer?.rut,worker?.name,worker?.rut,site?.name,role,eventType,inferredEmployment,chosenCodes.join("|"),contract,event,extra]);
  const fingerprint=stableFingerprint({siteId,companyId,workerId,parentId,relationship,data});
  const unsaved=!dossierId||savedFingerprint!==fingerprint;
  useEffect(()=>{
    if(configuration)return;
    const controller=new AbortController();
    revision.current+=1;const current=revision.current;
    setResponse(null);
    const timer=window.setTimeout(()=>{
      request<{documents:Status[];data_revision:number}>("/javiera/eligibility/evaluate",{
        method:"POST",body:JSON.stringify({data,dossier_id:dossierId||null,data_revision:current}),signal:controller.signal
      }).then(result=>{if(current===revision.current)setResponse({key:fingerprint,documents:result.documents});})
        .catch(e=>{if(!controller.signal.aborted)setError(errorMessage(e));});
    },350);
    return ()=>{window.clearTimeout(timer);controller.abort();};
  },[fingerprint,configuration,dossierId,saved?.issues.length,saved?.historical.length]);
  const allCards:Status[]=response?.key===fingerprint?response.documents:catalog.map(x=>({
    code:x.code,area:x.area,title:x.title,status:"POR_DETERMINAR",reason:"Validando la información…",
    missing_fields:x.required_fields,blocking_errors:[],completion_percent:0,can_preview:false,can_issue:false,
    has_history:false,template_version:x.published_version
  }));
  const preflightCodes=allCards.filter(x=>chosenCodes.includes(x.code)&&x.can_issue).map(x=>x.code);
  const preflightKey=[dossierId,dossierRevision,fingerprint,preflightCodes.join(",")].join("|");
  useEffect(()=>{
    if(configuration||batchMode||!dossierId||unsaved||!preflightCodes.length){setPreflight(null);return;}
    const controller=new AbortController();setPreflight(null);
    void request<{documents:Status[];dossier_revision:number}>("/javiera/eligibility/preflight",{
      method:"POST",body:JSON.stringify({dossier_id:dossierId,codes:preflightCodes}),signal:controller.signal
    }).then(result=>{
      if(!controller.signal.aborted&&result.dossier_revision===dossierRevision){
        setPreflight({key:preflightKey,documents:result.documents});
      }
    }).catch(e=>{
      if(!controller.signal.aborted){
        setPreflight({key:preflightKey,documents:preflightCodes.map(code=>({
          ...allCards.find(x=>x.code===code)!,status:"ERROR_TEMPORAL",can_issue:false,
          reason:"No se pudo comprobar la plantilla. "+errorMessage(e)
        }))});
      }
    });
    return()=>controller.abort();
  },[configuration,batchMode,dossierId,unsaved,preflightKey]);
  useEffect(()=>{setIssueFailures({});},[fingerprint]);
  const cards=allCards.map(item=>{
    if(batchMode||!chosenCodes.includes(item.code))return item;
    if(issueFailures[item.code])return {...item,status:"BLOQUEADO_PLANTILLA",can_issue:false,
      reason:issueFailures[item.code]};
    if(!item.can_issue)return item;
    if(unsaved||!dossierId)return {...item,status:"GUARDAR_FICHA",can_issue:false,
      reason:"Guarda la ficha para comprobar el contenido real del PDF antes de descargar."};
    const result=preflight?.key===preflightKey?preflight.documents.find(x=>x.code===item.code):null;
    return result?{...item,...result}:{
      ...item,status:"VALIDANDO_PDF",can_issue:false,
      reason:"Comprobando la salida real del Excel antes de habilitar la descarga."
    };
  });
  const selectedCatalog=catalog.filter(c=>chosenCodes.includes(c.code));
  const eppDraft=useMemo(()=>parseEppDraft(event.epp_items,eppOptions),[event.epp_items,eppOptions]);
  const neededFields=new Set(selectedCatalog.flatMap(c=>c.required_fields));
  function focusMissingField(field:string){
    const element=document.getElementById(validField(field));
    if(element){
      element.scrollIntoView({behavior:"smooth",block:"center"});
      element.focus();
      setError("");
    }else{
      setError("Este dato no está disponible en el formulario. Revisa la configuración de la plantilla.");
    }
  }
  const fieldInput=(field:string,label:string,value:string,change:(v:string)=>void,type="text")=>
    <label key={field} htmlFor={validField(field)}>{label}<input id={validField(field)} value={isRutField(field)?formatRutDisplay(value):value}
      type={type} onChange={e=>change(e.target.value)} onBlur={()=>{if(isRutField(field))change(formatRutDisplay(value));}}/></label>;
  useEffect(()=>{
    if(!mode||!companyId||!siteId){setExistingDossiers([]);return;}
    let alive=true;
    request<typeof existingDossiers>("/javiera/dossiers?site_id="+encodeURIComponent(siteId)+"&employer_id="+encodeURIComponent(companyId))
      .then(rows=>{if(alive)setExistingDossiers(rows);}).catch(e=>{if(alive)setError(errorMessage(e));});
    return()=>{alive=false;};
  },[mode,siteId,companyId,saved?.issues.length]);
  // Recuperar la ficha anterior del trabajador sin mostrar un selector técnico.
  useEffect(()=>{
    if(mode!=="existing"||batchMode||!workerId||!companyId||!siteId||dossierId||busy)return;
    const previous=existingDossiers.find(d=>d.worker_id===workerId);
    if(previous)void loadDossier(previous.id);
  },[mode,batchMode,workerId,companyId,siteId,dossierId,existingDossiers]);
  async function loadDossier(id:string){
    if(actionLock.current)return;
    const load=++loadingDossier.current;setBusy(true);setError("");
    try{
      const row=await request<Dossier>("/javiera/dossiers/"+encodeURIComponent(id));
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(row.site_id)+"&contractor_id="+encodeURIComponent(row.employer_id));
      if(load!==loadingDossier.current)return;
      const fields=dossierFields(row.data);
      const company=src.contractors.find(c=>c.id===row.employer_id);
      const worker=src.workers.find(w=>w.id===row.worker_id);
      const site=src.sites.find(z=>z.id===row.site_id);
      setBatchReport([]);setSaved(row);setDossierId(row.id);setDossierRevision(row.revision);
      setSource(src);setSiteId(row.site_id);setCompanyId(row.employer_id);setWorkerId(row.worker_id||"");
      setParentId(row.parent_id||"");setRelationship(row.relationship);setMode("existing");
      const requested=Array.isArray(row.data.requested_documents)?
        row.data.requested_documents.filter((code):code is string=>typeof code==="string"&&catalog.some(c=>c.code===code)):chosenCodes;
      setSelectedCodes(requested);
      setRole(fields.role);setExtra(fields.extra);setEventType(fields.event_type);
      setEmploymentType(fields.employment_type);setContract(fields.contract);setEvent(fields.event);
      const effectiveEmployment=fields.employment_type||(row.worker_id&&requested.includes("labor_contract")&&company?.nature!=="independent"?"dependiente":"");
      setSavedFingerprint(stableFingerprint({siteId:row.site_id,companyId:row.employer_id,workerId:row.worker_id||"",parentId:row.parent_id||"",relationship:row.relationship,data:{
        employer:{name:company?.name||"",rut:company?.rut||""},worker:{name:worker?.name||"",rut:worker?.rut||""},site:{name:site?.name||""},
        ...fields,employment_type:effectiveEmployment,requested_documents:requested}}));
      setNotice("Expediente recuperado. Puedes revisar y generar sus documentos.");
    }catch(e){if(load===loadingDossier.current)setError(errorMessage(e));}finally{if(load===loadingDossier.current)setBusy(false);}
  }
  async function createCompany(){
    if(!siteId||!newContractor.name.trim()||!newContractor.rut.trim()){setError("Selecciona la obra e ingresa razón social y RUT de empresa.");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{
      const result=await opsApi.createContractor({site_id:siteId,name:newContractor.name,rut:formatRutDisplay(newContractor.rut)||null,
        historical_code:"",nature:"unclassified",frequency:"unclassified",contract_status:"active"});
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId));
      setSource(src);chooseCompany(result.contractor_id);setShowCreate(null);setNewContractor({name:"",rut:""});
      setNotice("Contratista registrado y vinculado a la obra.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function createWorker(){
    if(!siteId||!companyId||!newWorker.name.trim()){setError("Selecciona empleador e indica el trabajador");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{
      const result=await opsApi.createWorker({site_id:siteId,contractor_id:companyId,name:newWorker.name,rut:formatRutDisplay(newWorker.rut)||null});
      const src=await request<Source>("/javiera/sources?site_id="+encodeURIComponent(siteId)+"&contractor_id="+encodeURIComponent(companyId));
      setSource(src);chooseWorker(result.worker_id);setShowCreate(null);setNewWorker({name:"",rut:""});
      setNotice("Trabajador vinculado al empleador.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function refreshDossier(id:string){
    const result=await request<Dossier>("/javiera/dossiers/"+id);setSaved(result);
  }
  async function saveDossier(){
    if(!mode||!companyId||!siteId){setError("Selecciona obra y empleador antes de guardar.");return;}
    if(dossierId&&!unsaved){setNotice("No hay cambios por guardar. El expediente ya está actualizado.");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");setNotice("");
    try{
      const result=await request<{id:string;revision:number}>("/javiera/dossiers",{
        method:"POST",body:JSON.stringify({site_id:siteId,employer_id:companyId,
          worker_id:workerId||null,parent_id:parentId||null,
          relationship,data:{...(saved?.data||{}),...data,...(dossierId?{_dossier_id:dossierId}:{})},
          expected_revision:dossierId?dossierRevision:null})});
      setDossierId(result.id);setDossierRevision(result.revision);setSavedFingerprint(fingerprint);
      setExistingDossiers(rows=>[{id:result.id,site_id:siteId,employer_id:companyId,worker_id:workerId||null,relationship,revision:result.revision,worker_name:worker?.name},...rows.filter(r=>r.id!==result.id)]);
      await refreshDossier(result.id);
      setNotice("Ficha guardada. Puedes generar los documentos que estén listos.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function openPreview(code:string){
    if(unsaved){setError("Guarda los cambios antes de generar una vista previa.");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    // Reservar la pestaña durante el clic evita que el navegador bloquee la vista previa asíncrona.
    const tab=window.open("about:blank","_blank");
    try{
      const blob=await pdfRequest("/preview",{dossier_id:dossierId,code});
      if(tab&&!tab.closed){const url=URL.createObjectURL(blob);tab.location.href=url;window.setTimeout(()=>URL.revokeObjectURL(url),60000);}
      else{downloadBlob(blob,"GALANT-JAVIERA-VISTA-PREVIA-"+code+".pdf");setNotice("La vista previa se descargó porque el navegador no permitió abrir otra pestaña.");}
    }catch(e){tab?.close();setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function issue(code:string,reissue_reason?:string){
    if(unsaved){setError("Guarda los cambios antes de emitir el PDF.");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{
      const result=await request<{id:string;reused:boolean}>("/javiera/issue",{
        method:"POST",body:JSON.stringify({dossier_id:dossierId,code,reissue_reason})});
      await downloadIssuedPdf(result.id,code);
      await refreshDossier(dossierId);
      setNotice(result.reused?"PDF emitido anteriormente y descargado.":"PDF emitido y descargado; la emisión no equivale a firma ni entrega.");
    }catch(e){
      const reason=errorMessage(e);
      setIssueFailures(old=>({...old,[code]:reason}));
      setError(reason);
    }finally{actionLock.current=false;setBusy(false);}
  }
  async function downloadExisting(id:string,code:string){
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{await downloadIssuedPdf(id,code);setNotice("PDF descargado correctamente.");}
    catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function issueReady(){
    if(actionLock.current||busy)return;
    if(!chosenCodes.length){setError("Selecciona al menos un documento.");return;}
    if(!batchMode&&unsaved){setError("Guarda primero los cambios del expediente.");return;}
    const issuable=batchMode?chosenCodes:cards.filter(c=>chosenCodes.includes(c.code)&&c.can_issue).map(c=>c.code);
    if(!issuable.length){setError("No hay documentos listos. Completa los campos obligatorios indicados en las tarjetas.");return;}
    const targets=batchMode?selectedDossiers:[dossierId];
    if(!targets.length){setError("Selecciona los expedientes que quieres generar.");return;}
    actionLock.current=true;setBusy(true);setError("");setNotice("");setBatchReport([]);
    const results:BatchResult[]=[];
    try{
      for(const [index,id] of targets.entries()){
        setBatchProgress("Procesando expediente "+(index+1)+" de "+targets.length);
        try{
          const result=await request<{results:BatchResult[]}>("/javiera/issue/batch",{method:"POST",body:JSON.stringify({dossier_id:id,codes:issuable})});
          results.push(...result.results.map(item=>({...item,dossier_id:id})));
        }catch(e){results.push(...issuable.map(code=>({dossier_id:id,code,ok:false,reason:errorMessage(e)})));}
        setBatchReport([...results]);
      }
      // La acción «Generar» debe entregar el archivo, no exigir un segundo clic.
      // Un solo documento se descarga como PDF; varios se agrupan en ZIP.
      const issued=results.filter(r=>r.ok&&r.id);
      const failed=results.length-issued.length;
      if(issued.length){
        try{
          if(issued.length===1){
            await downloadIssuedPdf(issued[0].id!,issued[0].code);
          }else{
            const archive=await pdfRequest("/issue/archive",{issue_ids:issued.map(r=>r.id!)});
            downloadBlob(archive,"JAVIERA-documentos.zip");
          }
          setNotice(issued.length+" documento(s) generado(s) y descargado(s)"+(failed?"; "+failed+" con observaciones.":"."));
        }catch(downloadError){
          // La emisión ya se guardó: no se declara que fracasó el documento.
          setError("Documentos generados, pero falló la descarga: "+errorMessage(downloadError)+". Usa «Descargar documentos en ZIP» para reintentar.");
        }
      }else{
        setError("No se generaron documentos. Revisa el motivo dentro de la tarjeta afectada.");
      }
      if(!batchMode){
        const failures=results.filter(row=>!row.ok).reduce<Record<string,string>>((out,row)=>{
          out[row.code]=row.reason||"Documento bloqueado durante la validación.";return out;
        },{});
        if(Object.keys(failures).length)setIssueFailures(old=>({...old,...failures}));
      }
      if(dossierId)await refreshDossier(dossierId);
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);setBatchProgress("");}
  }
  async function downloadBatch(){
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{
      const ids=batchReport.filter(r=>r.ok&&r.id).map(r=>r.id!);
      const blob=await pdfRequest("/issue/archive",{issue_ids:ids});
      downloadBlob(blob,"JAVIERA-documentos.zip");
      setNotice("Archivo ZIP preparado para su descarga.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function reviewHistorical(id:string,verified:boolean){
    const reason=reviewComments[id]?.trim()||"";
    if(reason.length<6){setError("Indica el motivo y evidencia de la revisión del documento histórico.");return;}
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{
      await request("/javiera/admin/history/"+encodeURIComponent(id)+"/verify",{
        method:"POST",body:JSON.stringify({verified,reason})});
      if(dossierId)await refreshDossier(dossierId);
      setNotice(verified?"Documento histórico revisado; comprueba su aplicabilidad actual.":"Documento histórico observado.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  async function uploadHistorical(code:string,file:File){
    if(!dossierId){setError("Guarda el expediente antes de subir documentos anteriores.");return;}
    const csrf=document.cookie.split("; ").find(c=>c.startsWith("galant_post_csrf="))?.split("=")[1]||"";
    const form=new FormData();form.append("file",file);
    if(actionLock.current)return;actionLock.current=true;setBusy(true);setError("");
    try{const res=await fetch("/api/v1/javiera/dossiers/"+encodeURIComponent(dossierId)+"/history/"+encodeURIComponent(code),{
        method:"POST",body:form,credentials:"include",headers:{"X-CSRF-Token":csrf}});
      if(!res.ok)throw new Error("No se pudo cargar el PDF histórico");
      await refreshDossier(dossierId);setNotice("Documento histórico cargado; pendiente de verificación.");
    }catch(e){setError(errorMessage(e));}finally{actionLock.current=false;setBusy(false);}
  }
  function clearPerson(){loadingDossier.current+=1;setBatchReport([]);setReviewComments({});setReissueReasons({});setEventType("ingreso");setContract(emptyContract);setEvent(emptyEvent);setRole("");setEmploymentType("");setDossierId("");setDossierRevision(0);setSaved(null);setSavedFingerprint("");}
  function chooseSite(v:string){setSelectedDossiers([]);setExistingDossiers([]);setRelationship("contractor");setSiteId(v);setCompanyId("");setWorkerId("");setParentId("");setExtra({});clearPerson();}
  function chooseCompany(v:string){setSelectedDossiers([]);setExistingDossiers([]);setRelationship("contractor");setCompanyId(v);setWorkerId("");setParentId("");clearPerson();setExtra(source.contractors.find(c=>c.id===v)?.defaults||{});}
  function chooseWorker(v:string){setWorkerId(v);clearPerson();setContract({...emptyContract,...source.workers.find(w=>w.id===v)?.contract});setExtra(old=>Object.fromEntries(Object.entries(old).filter(([key])=>!key.startsWith("worker_")&&!["salary_words","afp","health_provider","bank_account","payment_frequency","transport_allowance"].includes(key))));}
  function toggleDocument(code:string){
    setSelectedCodes(old=>{const current=old??catalog.map(c=>c.code);return current.includes(code)?current.filter(c=>c!==code):[...current,code];});
    setBatchReport([]);
  }
  if(configuration)return <Suspense fallback={<div className="app-loading">Abriendo el Excel maestro…</div>}><JavieraWorkbookAdmin onBack={onBack||(()=>window.history.back())}/></Suspense>;
  if(!mode)return <section className="jv-module">
    <div className="jv-hero"><small>AUTOMATIZACIÓN DOCUMENTAL · GALANT 20</small><h2>Proyecto JAVIERA</h2>
      <p>Una sola ficha para documentos laborales y prevención de riesgos. Los documentos aparecen conforme completas los datos.</p></div>
    <div className="jv-mode-cards">
      <button onClick={()=>{setMode("new");setSelectedCodes(["labor_contract"]);setShowCreate("contractor");}}><FolderOpen size={28}/><strong>Contratista nuevo</strong>
        <span>Registra la empresa y sus trabajadores para preparar sus documentos de ingreso.</span></button>
      <button onClick={()=>{setMode("existing");setSelectedCodes([]);setShowCreate(null);}}><ClipboardList size={28}/><strong>Contratista existente</strong>
        <span>Busca una empresa registrada, recupera sus antecedentes y prepara los documentos que faltan.</span></button>
    </div>
    {onConfig&&<button type="button" className="jv-inline-action" onClick={()=>{if(!busy)onConfig();}}><Settings2 size={16}/> Editar Excel maestro y plantillas</button>}
    <p className="jv-note">La emisión no certifica por sí sola firma, recepción, capacitación ni entrega real de EPP.</p>
  </section>;
  const selectedCards=cards.filter(c=>chosenCodes.includes(c.code));
  const ready=selectedCards.filter(c=>c.can_issue).length;
  const criticalCards=selectedCards.filter(c=>["BLOQUEADO_PLANTILLA","ERROR_TEMPORAL"].includes(c.status));
  const incompleteCards=selectedCards.filter(c=>["FALTAN_DATOS","PENDIENTE_REVISION","POR_DETERMINAR","GUARDAR_FICHA"].includes(c.status));
  const verifyingCards=selectedCards.filter(c=>c.status==="VALIDANDO_PDF");
  const groups=Array.from(new Set(selectedCards.map(c=>c.area)));
  return <section className="jv-module">
    <div className="jv-hero" style={{display:"grid",gridTemplateColumns:"minmax(0, 1fr)",gridAutoFlow:"row",justifyItems:"start",alignContent:"start",rowGap:9}}>
      <div className="jv-hero-back-row" style={{display:"block",width:"100%",minHeight:31,margin:0}}><button type="button" className="jv-back" disabled={busy} onClick={()=>{setMode(null);chooseSite("");setBatchMode(false);setSelectedDossiers([]);}}><ArrowLeft size={18}/> Proyecto JAVIERA</button></div>
      <small style={{display:"block",gridColumn:1}}>{mode==="new"?"CONTRATISTA NUEVO":"CONTRATISTA EXISTENTE"} · EXPEDIENTE</small>
      {onConfig&&<button type="button" disabled={busy} className="jv-back" onClick={()=>{if(!busy)onConfig();}}><Settings2 size={16}/> Editar Excel maestro y plantillas</button>}
      <h2>Generación documental interactiva</h2><p>Gestiona contratos, anexos, declaraciones, IRL, PTS, EPP, reglamento e inducción desde una misma ficha.</p></div>
    {error&&<p role="alert" className="jv-error"><AlertCircle size={16}/>{error}</p>}
    {!error&&notice&&<p role="status" className="jv-success"><CheckCircle2 size={16}/>{notice}</p>}
    <section className="jv-document-picker" aria-label="Seleccionar documentos">
      <div className="jv-picker-heading"><div><small>PASO 1 · DOCUMENTOS</small><h3>¿Qué necesitas generar?</h3><p>Marca uno o varios documentos. La ficha pedirá los datos que necesitan.</p></div>
        <label>Buscar documento<input type="search" value={documentSearch} onChange={e=>setDocumentSearch(e.target.value)} placeholder="IRL, EPP, contrato…"/></label></div>
      <fieldset disabled={busy} className="jv-flow"><div className="jv-picker-actions">
        <button type="button" onClick={()=>setSelectedCodes(null)}>Seleccionar todos</button>
        <button type="button" onClick={()=>setSelectedCodes(catalog.filter(c=>c.area==="Prevención de Riesgos").map(c=>c.code))}>Solo prevención</button>
        <button type="button" onClick={()=>setSelectedCodes(catalog.filter(c=>c.area!=="Prevención de Riesgos").map(c=>c.code))}>Solo laborales</button>
        <button type="button" onClick={()=>setSelectedCodes([])}>Limpiar selección</button><strong>{chosenCodes.length} seleccionados</strong></div>
      <div className="jv-picker-grid">{catalog.filter(c=>c.title.toLocaleLowerCase("es").includes(documentSearch.toLocaleLowerCase("es"))).map(c=><label className={"jv-picker-card "+(chosenCodes.includes(c.code)?"chosen":"")} key={c.code}>
        <input type="checkbox" checked={chosenCodes.includes(c.code)} onChange={()=>toggleDocument(c.code)}/><span><b>{c.title}</b><small>{c.area==="Zona Subcontratos"?"Laboral":c.area}</small></span></label>)}</div>
      {catalog.length>0&&!catalog.some(c=>c.title.toLocaleLowerCase("es").includes(documentSearch.toLocaleLowerCase("es")))&&<p>No hay documentos con ese nombre.</p>}</fieldset>
    </section>
    <div className="jv-workspace">
      <div className="jv-form"><fieldset disabled={busy} className="jv-flow">
        <div className="jv-section"><h3>{batchMode?"Paso 2 · Obra y empresa del lote":"Paso 2 · Empresa y trabajador"}</h3>
          <label>Obra <select value={siteId} onChange={e=>chooseSite(e.target.value)}><option value="">Selecciona una obra</option>
            {source.sites.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
          {mode==="existing"?<label>Empresa registrada
            <select value={companyId} onChange={e=>chooseCompany(e.target.value)}>
              <option value="">Selecciona una empresa de esta obra</option>
              {source.contractors.filter(c=>c.site_id===siteId).map(c=><option key={c.id} value={c.id}>{c.name}{c.rut?" · "+c.rut:""}</option>)}
            </select>
          </label>:companyId?<div className="jv-new-form jv-company-confirmed" role="status">
            <strong><CheckCircle2 size={16}/> Empresa registrada y vinculada</strong>
            <span>{employer?.name||"Empresa guardada"}{employer?.rut?" · "+employer.rut:""}</span>
            <p>Continúa con los datos del trabajador. No necesitas seleccionar la empresa nuevamente.</p>
          </div>:<div className="jv-new-form">
            <p>Registra la empresa una sola vez para preparar sus documentos.</p>
            <label>Razón social <input required value={newContractor.name} onChange={e=>setNewContractor({...newContractor,name:e.target.value})} placeholder="Nombre completo de la empresa"/></label>
            <label>RUT de empresa <input required value={formatRutDisplay(newContractor.rut)} onChange={e=>setNewContractor({...newContractor,rut:e.target.value})} onBlur={()=>setNewContractor(old=>({...old,rut:formatRutDisplay(old.rut)}))} placeholder="12.345.678-9"/></label>
            <button disabled={busy||!siteId||!newContractor.name.trim()||!newContractor.rut.trim()} type="button" onClick={()=>void createCompany()}>Guardar y continuar</button>
            {!siteId&&<p role="status">Selecciona primero una obra.</p>}
          </div>}
          {relationship==="subcontractor"&&<label>Contratista principal del expediente anterior <select value={parentId} onChange={e=>setParentId(e.target.value)}>
            <option value="">Selecciona el contratista principal</option>{source.contractors.filter(c=>c.id!==companyId&&c.site_id===siteId).map(c=>
              <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>}
          {!batchMode&&<>
          <label>Trabajador <select value={workerId} onChange={e=>chooseWorker(e.target.value)}>
            <option value="">Selecciona trabajador asignado a esta obra</option>
            {source.workers.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
          <button type="button" className="jv-inline-action" onClick={()=>setShowCreate(showCreate==="worker"?null:"worker")}>+ Registrar trabajador nuevo</button>
          {showCreate==="worker"&&<div className="jv-new-form">
            <label>Nombre del trabajador<input value={newWorker.name} onChange={e=>setNewWorker({...newWorker,name:e.target.value})}/></label>
            <label>RUT del trabajador<input value={formatRutDisplay(newWorker.rut)} onChange={e=>setNewWorker({...newWorker,rut:e.target.value})} onBlur={()=>setNewWorker(old=>({...old,rut:formatRutDisplay(old.rut)}))} placeholder="12.345.678-9"/></label>
            <button disabled={busy||!companyId} type="button" onClick={()=>void createWorker()}>Guardar trabajador</button>
          </div>}
          <p className="jv-hint">{workerId?"Trabajador asignado en GALANT":"Selecciona o registra el trabajador sin duplicar su RUT."}</p>
          <label>Cargo o especialidad<input list="javiera-cargos" value={role} onChange={e=>setRole(e.target.value)}/><datalist id="javiera-cargos">{nativeRoles.map(cargo=><option key={cargo} value={cargo}/>)}</datalist></label>
          <p className="jv-hint">GALANT utiliza los documentos elegidos para identificar automáticamente el trámite. No necesitas indicar vínculo laboral ni motivo del expediente.</p>
          </>}
          {batchMode&&<p>El lote utiliza los datos guardados de cada expediente. Selecciona las personas en el panel de generación; para corregir sus datos, vuelve al modo individual.</p>}
        </div>
        {!batchMode&&[...neededFields].some(f=>f.startsWith("contract."))&&<div className="jv-section"><h3>Datos contractuales solicitados</h3>
          <div className="jv-paired">
            {neededFields.has("contract.start")&&fieldInput("contract.start","Fecha de ingreso",contract.start,v=>setContract({...contract,start:v}),"date")}
            {neededFields.has("contract.end")&&fieldInput("contract.end","Término actual",contract.end,v=>setContract({...contract,end:v}),"date")}
            {neededFields.has("contract.new_end")&&fieldInput("contract.new_end","Nueva fecha de término",contract.new_end,v=>setContract({...contract,new_end:v}),"date")}
            {neededFields.has("contract.transfer_date")&&fieldInput("contract.transfer_date","Fecha de traslado",contract.transfer_date,v=>setContract({...contract,transfer_date:v}),"date")}
            {neededFields.has("contract.salary")&&fieldInput("contract.salary","Sueldo base (CLP)",contract.salary,v=>setContract({...contract,salary:v}),"number")}
            {neededFields.has("contract.hours")&&fieldInput("contract.hours","Horas semanales",contract.hours,v=>setContract({...contract,hours:v}),"number")}
          </div>
          {neededFields.has("contract.declaration_reason")&&fieldInput("contract.declaration_reason","Motivo de declaración jurada",contract.declaration_reason,v=>setContract({...contract,declaration_reason:v}))}
          {neededFields.has("contract.regulation_version")&&fieldInput("contract.regulation_version","Versión del Reglamento Interno",contract.regulation_version,v=>setContract({...contract,regulation_version:v}))}
        </div>}
        {!batchMode&&[...neededFields].some(f=>f.startsWith("event."))&&<div className="jv-section"><h3>Datos de prevención y constancias</h3>
          <p>Una fecha rellenada no reemplaza la evidencia de una entrega, firma o inducción real.</p>
          {neededFields.has("event.date")&&fieldInput("event.date","Fecha efectiva del evento",event.date,v=>setEvent({...event,date:v}),"date")}
          {neededFields.has("event.epp_items")&&<div className="jv-epp-editor" id={validField("event.epp_items")}>
            <h4>EPP efectivamente entregados</h4>
            <p>Indica la cantidad real de cada elemento. Deja <strong>0</strong> si no se entregó. La fecha se registra arriba, no aquí.</p>
            {eppDraft.invalid.length>0&&<div className="jv-epp-invalid" role="alert">
              <strong>Hay datos que no corresponden a un EPP</strong>
              <p>{eppDraft.invalid.join("; ")}</p>
              <p>Este valor anterior no se modificará sin tu autorización. Comprueba la fecha y corrige el registro antes de declarar una entrega real.</p>
              <button type="button" disabled={busy} onClick={()=>setEvent(old=>({...old,epp_items:""}))}>
                Quitar dato incorrecto y registrar EPP
              </button>
            </div>}
            {eppOptions.length===0?<p role="status">Cargando la lista de EPP del Excel maestro…</p>:
              <div className="jv-epp-grid">{eppOptions.map((option,index)=><label key={option.name}>
                <span>{option.name}</span>
                <input aria-label={"Cantidad de "+option.name} type="number" min="0"
                  max={option.max_quantity} step="1" inputMode="numeric"
                  disabled={busy||eppDraft.invalid.length>0}
                  value={eppDraft.quantities[index]??0}
                  onChange={e=>{
                    const value=Number(e.target.value);
                    if(!Number.isInteger(value)||value<0||value>option.max_quantity)return;
                    const quantities=eppDraft.quantities.slice();quantities[index]=value;
                    setEvent(old=>({...old,epp_items:serializeEppDraft(eppOptions,quantities)}));
                  }}/>
              </label>)}</div>}
            <p className="jv-hint">El Excel contiene ocho filas de EPP. No se agregarán elementos ni cantidades no acreditados. «Protección Auditiva/Mascarilla» corresponde a una sola fila del formato original.</p>
          </div>}
          {neededFields.has("event.pts_version")&&fieldInput("event.pts_version","Versión del PTS entregado",event.pts_version,v=>setEvent({...event,pts_version:v}))}
        </div>}
        {!batchMode&&selectedCatalog.some(c=>c.required_fields.some(f=>f.startsWith("extra.")))&&<div className="jv-section">
          <h3>Antecedentes del documento</h3><p>Completa solo la información que falta en los registros de GALANT.</p>
          {Array.from(new Set(selectedCatalog.flatMap(c=>c.required_fields.filter(f=>f.startsWith("extra."))))).map(f=>
            fieldInput(f,extraLabels[f.slice(6)]||f.slice(6).replaceAll("_"," "),extra[f.slice(6)]||"",
              value=>setExtra(old=>({...old,[f.slice(6)]:value})),f.endsWith("birthdate")?"date":f.endsWith("declaration_period")?"month":"text"))}
        </div>}
        {!batchMode&&<div className="jv-actions"><button type="button" className="jv-primary" disabled={busy||!siteId||!companyId||!!dossierId&&!unsaved}
          onClick={()=>void saveDossier()}>{busy?"Procesando…":dossierId?"Guardar nueva revisión":"Guardar expediente"}</button>
          {dossierId&&<span>Expediente {dossierId.slice(0,8)} · revisión {dossierRevision}{unsaved?" · cambios sin guardar":""}</span>}
        </div>}
      </fieldset></div>
      <aside className="jv-document-panel" aria-label="Documentos que puedes exportar a PDF">
        {!batchMode&&selectedCards.length>0&&<div className={"jv-validation-panel "+(
          criticalCards.length?"jv-validation-danger":incompleteCards.length?"jv-validation-warning":
          verifyingCards.length?"jv-validation-checking":ready?"jv-validation-ok":"jv-validation-warning"
        )} role="status" aria-live="polite">
          <div className="jv-validation-heading">
            {criticalCards.length||incompleteCards.length||verifyingCards.length?
              <AlertCircle size={20}/>:<CheckCircle2 size={20}/>}
            <div><strong>{criticalCards.length?"Hay documentos bloqueados":
              incompleteCards.length?"Documentos pendientes de completar o guardar":
              verifyingCards.length?"Comprobando el contenido del PDF…":
              ready?"Documentos verificados":"Selecciona documentos"}</strong>
            <p>{criticalCards.length?"No se emitirá ningún PDF con datos del ejemplo.":
              incompleteCards.length?"Revisa la tarjeta de cada documento y guarda la ficha antes de generar.":
              verifyingCards.length?"Revisando las fórmulas y valores de la salida real del Excel.":
              ready?ready+" documento(s) verificados.":"Completa la ficha para generar."}</p></div>
          </div>
          {criticalCards.map(doc=><div key={doc.code} className="jv-validation-item">
            <strong>{doc.title}</strong><span>{doc.reason}</span>
            {!!doc.source_cells?.length&&<small>Origen: Datos Contrato!{doc.source_cells.join(", ")}</small>}
            {onConfig&&doc.status==="BLOQUEADO_PLANTILLA"&&<button type="button" disabled={busy}
              onClick={()=>onConfig()}>Abrir configuración del Excel</button>}
          </div>)}
        </div>}
        {!batchMode&&unsaved&&<p className="jv-note" role="status">Guarda los cambios para habilitar la exportación de PDFs.</p>}
        <div className="jv-panel-head"><div><small>DOCUMENTOS SELECCIONADOS</small><h3>Preparar y generar PDF</h3>
          <p>{batchMode?"Se valida cada expediente con sus propios datos":!companyId?"Primero registra o selecciona la empresa":unsaved?"Guarda el expediente para habilitar la descarga":"Los estados se actualizan automáticamente"}</p></div><strong>{batchMode?selectedDossiers.length+" expedientes":response?.key===fingerprint?ready+" listos":"Validando…"}</strong></div>
        <fieldset disabled={busy} className="jv-flow"><label className="jv-check-line"><input type="checkbox" checked={batchMode} onChange={e=>{setBatchMode(e.target.checked);}}/> Generar para varios expedientes guardados</label>
        {batchMode&&<div className="jv-batch-targets"><p>Usa los datos propios de cada expediente de esta empresa y obra. Para agregar otra persona, completa y guarda su ficha.</p>
          <button type="button" onClick={()=>setSelectedDossiers(existingDossiers.slice(0,20).map(d=>d.id))}>Seleccionar hasta 20 expedientes</button>
          <button type="button" onClick={()=>setSelectedDossiers([])}>Limpiar</button>
          {existingDossiers.map(d=><label className="jv-check-line" key={d.id}><input type="checkbox" checked={selectedDossiers.includes(d.id)} disabled={!selectedDossiers.includes(d.id)&&selectedDossiers.length>=20} onChange={e=>setSelectedDossiers(old=>e.target.checked?[...old,d.id]:old.filter(id=>id!==d.id))}/>
            <span>{d.worker_name||source.workers.find(w=>w.id===d.worker_id)?.name||(d.worker_id?"Trabajador "+d.worker_id.slice(0,8):"Empresa · declaración jurada")} · revisión {d.revision}</span></label>)}
          {!existingDossiers.length&&<p>Selecciona obra y empresa para ver sus expedientes guardados.</p>}</div>}
        <button type="button" className="jv-primary jv-batch" disabled={busy||!chosenCodes.length||(batchMode?!selectedDossiers.length:unsaved||!ready)}
          onClick={()=>void issueReady()}>{busy?"Generando…":"Generar documentos listos"} ({batchMode?chosenCodes.length:ready}{batchMode?" × "+selectedDossiers.length+" expedientes":""})</button>
        {!batchMode&&!ready&&!!chosenCodes.length&&<p className="jv-hint" role="status">Todavía no hay documentos listos. Revisa los datos faltantes en las tarjetas y guarda la ficha.</p>}
        {!chosenCodes.length&&<p className="jv-hint" role="status">Selecciona al menos un documento en el paso 1.</p>}</fieldset>
        {batchProgress&&<p role="status">{batchProgress}</p>}
        {batchReport.length>0&&<div className="jv-batch-report" role="status">
          {batchReport.some(r=>r.ok)&&<button type="button" disabled={busy} onClick={()=>void downloadBatch()}><Download size={15}/> Descargar documentos en ZIP</button>}
          {batchReport.map(item=><p key={(item.dossier_id||"")+item.code}>{item.ok?"✓":"!"} {batchMode?(existingDossiers.find(d=>d.id===item.dossier_id)?.worker_name||"Empresa")+" · ":""}{catalog.find(c=>c.code===item.code)?.title||item.code}
            {item.ok&&item.id?<a target="_blank" rel="noreferrer" href={"/api/v1/javiera/issued/"+encodeURIComponent(item.id)+"/pdf"}>Abrir PDF</a>:<span>{item.reason||"Pendiente de revisión"}</span>}</p>)}
        </div>}
        {!batchMode&&<>
        <div className="jv-filters">{[["todos","Todos"],["listos","Listos"],["pendientes","Pendientes"],["historicos","Existentes"]].map(([v,l])=>
          <button key={v} className={filter===v?"active":""} onClick={()=>setFilter(v)}>{l}</button>)}</div>
        {groups.filter(area=>cards.some(c=>c.area===area)).map(area=><div key={area} className="jv-doc-area">
          <h4>{area==="Zona Subcontratos"?<FolderOpen size={17}/>:<ShieldCheck size={17}/>} {area==="Zona Subcontratos"?"Documentos laborales":area}</h4>
          {cards.filter(c=>chosenCodes.includes(c.code)&&c.area===area && (filter==="todos" || filter==="listos"&&c.can_issue ||
            filter==="pendientes"&&!c.can_issue&&(!c.has_history||["BLOQUEADO_PLANTILLA","ERROR_TEMPORAL"].includes(c.status)) ||
            filter==="historicos"&&c.has_history)).map(c=><article className={"jv-doc-card "+(
             ["BLOQUEADO_PLANTILLA","ERROR_TEMPORAL"].includes(c.status)?"jv-card-danger":
             c.status==="FALTAN_DATOS"?"jv-card-warning":
             c.can_issue?"jv-card-ok":"")} key={c.code}>
            <div className="jv-doc-title"><input type="checkbox" aria-label={"Seleccionar "+c.title} checked={chosenCodes.includes(c.code)} disabled={busy} onChange={()=>toggleDocument(c.code)}/><FileText size={17}/><b>{c.title}</b><span className={"jv-state jv-"+c.status.toLowerCase()}>{statusText[c.status]||c.status}</span></div>
            {!["BLOQUEADO_PLANTILLA","ERROR_TEMPORAL","VALIDANDO_PDF"].includes(c.status)&&
              <div className="jv-progress"><span style={{width:String(c.completion_percent)+"%"}}/></div>}
            {["BLOQUEADO_PLANTILLA","ERROR_TEMPORAL"].includes(c.status)?
              <div className="jv-card-problem" role="alert"><strong>Documento bloqueado</strong>
                <p>{c.reason||"El sistema detectó un error en la plantilla."}</p>
                {!!c.source_cells?.length&&<p><strong>Ubicación exacta:</strong> Datos Contrato!{c.source_cells.join(", ")}</p>}
                {c.source_cells?.includes("C11")&&<button type="button" disabled={busy}
                  onClick={()=>focusMissingField("extra.employer_commune")}>Comprobar comuna de la empresa</button>}
                {onConfig&&c.status==="BLOQUEADO_PLANTILLA"&&<button type="button" disabled={busy}
                  onClick={()=>onConfig()}>Revisar plantilla Excel</button>}
              </div>:
              ["FALTAN_DATOS","PENDIENTE_REVISION","GUARDAR_FICHA"].includes(c.status)?
              <div className="jv-card-missing"><strong>{c.status==="FALTAN_DATOS"?"Completar información":c.status==="GUARDAR_FICHA"?"Guardar ficha":"Revisar configuración"}</strong>
                {c.reason&&<p>{c.reason}</p>}
                {!!c.missing_fields.length&&<><p>Faltan: {c.missing_fields.map(fieldLabel).join(", ")}</p>
                  <button type="button" disabled={busy} onClick={()=>focusMissingField(c.missing_fields[0])}>
                    Completar {fieldLabel(c.missing_fields[0])}
                  </button></>}
                {!!c.blocking_errors.length&&<p>{c.blocking_errors.join("; ")}</p>}
              </div>:c.reason&&<p>{c.reason}</p>}
            <div className="jv-card-actions">
              <button disabled={!c.can_preview||unsaved||busy} onClick={()=>void openPreview(c.code)}>Vista previa</button>
              <button disabled={!c.can_issue||unsaved||busy} onClick={()=>void issue(c.code)}><Download size={14}/> PDF</button>
              {c.status==="EXISTENTE_POR_VERIFICAR"&&c.can_preview&&<div className="jv-reissue">
                <label>Motivo de nueva emisión
                  <textarea rows={2} placeholder="Describe qué cambió y por qué es necesario emitir otra versión"
                    value={reissueReasons[c.code]||""}
                    onChange={e=>setReissueReasons(old=>({...old,[c.code]:e.target.value}))}/>
                </label>
                <button type="button" disabled={unsaved||busy||(reissueReasons[c.code]||"").trim().length<20}
                  onClick={()=>void issue(c.code,reissueReasons[c.code].trim())}>Emitir nueva versión justificada</button>
              </div>}
              {dossierId&&<label className="jv-upload"><Upload size={14}/> Anterior<input type="file" accept=".pdf,application/pdf"
                onChange={e=>{const f=e.target.files?.[0];if(f)void uploadHistorical(c.code,f);e.target.value="";}}/></label>}
              {saved?.historical.filter(x=>x.code===c.code).map(h=><div key={h.id} className="jv-history-review">
                <strong>PDF anterior: {h.state==="verified"?"verificado":h.state==="rejected"?"observado":"pendiente de revisar"}</strong>
                {h.state==="pending"&&<>
                  <input aria-label="Motivo de revisión" placeholder="Evidencia y motivo de revisión" value={reviewComments[h.id]||""}
                    onChange={e=>setReviewComments({...reviewComments,[h.id]:e.target.value})}/>
                  <button disabled={busy} onClick={()=>void reviewHistorical(h.id,true)}>Validar antecedente</button>
                  <button disabled={busy} onClick={()=>void reviewHistorical(h.id,false)}>Observar</button>
                </>}
              </div>)}
              {saved?.issues.filter(x=>x.code===c.code).map(doc=><button type="button" key={doc.id} disabled={busy} onClick={()=>void downloadExisting(doc.id,doc.code)}>
                <Download size={14}/> Descargar emitido v{doc.version}</button>)}
            </div>
          </article>)}
        </div>)}
        </>}
        <p className="jv-note">Documentos anteriores: existencia no equivale a vigencia. Su verificación es independiente.</p>
      </aside>
    </div>
  </section>;
}
