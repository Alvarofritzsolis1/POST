import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {ArrowLeft, CheckCircle2, ChevronRight, Download, Eye, FileText,
  FolderOpen, Printer, Save, Search, ShieldCheck, AlertCircle} from "lucide-react";
import {request} from "./api";
import {JAVIERA_EXCEL_FIELDS, JAVIERA_FIELD_META} from "./JavieraWorkspace";
import "./javiera-v166.css";

type Origin="new"|"operational"|"documentary";
type Company={id:string;name:string;rut:string;site_id:string;origin:Origin};
type Person={id:string;name:string;rut:string;origin:Origin};
type Source={sites:{id:string;name:string}[];companies:Company[];operational_companies:Company[];
  people:Person[];operational_people:Person[]};
type Catalog={code:string;area:string;title:string;required_fields:string[];published_version:number};
type TemplateLink={code:string;sheet:string;linked:boolean;imported:boolean;
  latest_revision:number|null;approved_revision:number|null;
  state:"not_imported"|"draft"|"missing_storage"|"engine_unavailable"|"published";
  message:string;ready:boolean;source_sha256:string|null};
type LibraryStatus={engine_available:boolean;documents:TemplateLink[]};
type NativeFormat={code:string;status:"ready"|"requires_review"|"requires_published_text";editable_in:string;source_revision:number|null};
type NativeCatalog={mode:string;formats:NativeFormat[];message:string};
type DocState={code:string;status:string;reason:string;missing_fields:string[];blocking_errors:string[];
  completion_percent:number;can_issue:boolean;has_history:boolean;requires_reissue_reason?:boolean;last_issue_id?:string};
type Dossier={id:string;revision:number;company_id:string;person_id:string|null;site_id:string;
  company_name:string;company_rut:string;person_name:string|null;person_rut:string;site_name:string;selected_codes:string[];
  shared:Record<string,unknown>;document_data:Record<string,Record<string,unknown>>;
  relationship:string;parent_name:string|null;updated_at:string};
type Result={code:string;ok:boolean;id?:string;reused?:boolean;reason?:string;missing_fields?:string[]};
type Batch={id:string;results:Result[];issued:number;failed:number;pdf_url:string|null;package_error?:string|null};
type History={legacy_issues:{id:string;code:string;issued_at:string;sha256:string}[];issues:{id:string;dossier_id:string;code:string;issued_at:string;sha256:string;reissue_reason:string|null}[];
  batches:{id:string;dossier_id:string;created_at:string;has_pdf:boolean;results:Result[]}[]};
const BASE="/javiera/v166";
const API="/api/v1/javiera/v166";
const EMPTY:Source={sites:[],companies:[],operational_companies:[],people:[],operational_people:[]};
const TITLES:Record<string,string>={
  labor_contract:"Contrato de trabajo",transfer_addendum:"Anexo de traslado",
  sworn_declaration:"Declaración jurada de empresa",extension_addendum:"Anexo de prórroga",
  internal_rules_receipt:"Recepción de Reglamento Interno",ppe_delivery:"Entrega de EPP",
  irl:"Información de Riesgos Laborales (IRL)",pts:"Procedimiento de Trabajo Seguro (PTS)",
  pts_receipt:"Recepción de PTS",induction:"Inducción de prevención",
};
const ORDER=Object.keys(TITLES);
const DOC_ONLY=new Set(["event.date","event.epp_items","event.pts_version","event.induction_topics","event.print_notes",
  "extra.regulation_version","extra.declaration_period","contract.declaration_reason",
  "contract.transfer_date","contract.new_end","extra.destinations",
  "extra.transport_allowance"]);
const AUTO=new Set(["employer.name","employer.rut","worker.name","worker.rut","site.name"]);
const errorText=(error:unknown)=>{
  if(!(error instanceof Error))return String(error);
  try{const parsed=JSON.parse(error.message) as {detail?:{reason?:string;missing_fields?:string[]}};
    return parsed.detail?.reason||error.message;}catch{return error.message;}
};
function nestedFromFields(values:Record<string,string>){
  const out:Record<string,unknown>={};
  for(const [key,value] of Object.entries(values)){
    if(!value.trim())continue;
    const parts=key.split(".");
    if(parts.length===2){
      const obj=(out[parts[0]]||{}) as Record<string,string>;
      obj[parts[1]]=value;
      out[parts[0]]=obj;
    }else out[key]=value;
  }
  return out;
}
const formatTime=(iso:string)=>new Date(iso).toLocaleString("es-CL");
async function previewRequest(dossier_id:string,code:string){
  const csrf=document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch(API+"/preview",{method:"POST",credentials:"include",cache:"no-store",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    body:JSON.stringify({dossier_id,code})});
  if(!response.ok){
    const detail=await response.json().catch(()=>({detail:"PDF no disponible"}));
    throw new Error(typeof detail.detail==="string"?detail.detail:detail.detail?.reason||"Documento bloqueado");
  }
  return response.blob();
}
async function nativeBatchRequest(dossier_id:string,codes:string[]){
  const csrf=document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch("/api/v1/javiera/v19/preview/batch",{
    method:"POST",credentials:"include",cache:"no-store",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    body:JSON.stringify({dossier_id,codes})
  });
  if(!response.ok){
    const body=await response.json().catch(()=>({detail:"No fue posible preparar el paquete HTML."}));
    throw new Error(typeof body.detail==="string"?body.detail:"Faltan datos o formatos HTML habilitados.");
  }
  return response.blob();
}
async function nativePreviewRequest(dossier_id:string,code:string){
  const csrf=document.cookie.split("; ").find(x=>x.startsWith("galant_post_csrf="))?.split("=")[1]||"";
  const response=await fetch("/api/v1/javiera/v19/preview",{
    method:"POST",credentials:"include",cache:"no-store",
    headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},
    body:JSON.stringify({dossier_id,code})
  });
  if(!response.ok){
    const body=await response.json().catch(()=>({detail:"No fue posible preparar el PDF nativo."}));
    throw new Error(typeof body.detail==="string"?body.detail:"Revisa los datos requeridos para este documento.");
  }
  return response.blob();
}
function pdfTab(){try{return window.open("about:blank","_blank");}catch{return null;}}

export default function JavieraV166({onConfig,onTextEditor}:{onConfig?:()=>void;onTextEditor?:()=>void}){
  const [step,setStep]=useState(1);
  const [origin,setOrigin]=useState<Origin>("new");
  const [siteId,setSiteId]=useState("");
  const [source,setSource]=useState<Source>(EMPTY);
  const [catalog,setCatalog]=useState<Catalog[]>([]);
  const [library,setLibrary]=useState<TemplateLink[]>([]);
  const [nativeFormats,setNativeFormats]=useState<NativeFormat[]>([]);
  const [nativeLoading,setNativeLoading]=useState(true);
  const [companyChoice,setCompanyChoice]=useState("");
  const [companyName,setCompanyName]=useState("");
  const [companyRut,setCompanyRut]=useState("");
  const [companyId,setCompanyId]=useState("");
  const [relation,setRelation]=useState("contractor");
  const [parentName,setParentName]=useState("");
  const [checked,setChecked]=useState<string[]>([]);
  const [personOrigin,setPersonOrigin]=useState<Origin>("new");
  const [personChoice,setPersonChoice]=useState("");
  const [personName,setPersonName]=useState("");
  const [personRut,setPersonRut]=useState("");
  const [personId,setPersonId]=useState("");
  const [shared,setShared]=useState<Record<string,string>>({});
  const [specific,setSpecific]=useState<Record<string,Record<string,string>>>({});
  const [dossier,setDossier]=useState<Dossier|null>(null);
  const [states,setStates]=useState<DocState[]>([]);
  const [batch,setBatch]=useState<Batch|null>(null);
  const [history,setHistory]=useState<History>({legacy_issues:[],issues:[],batches:[]});
  const [reasons,setReasons]=useState<Record<string,string>>({});
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [saving,setSaving]=useState(false);
  const [lookup,setLookup]=useState("");
  const savingRef=useRef(false);
  const identityGeneration=useRef(0);
  const snapshotRef=useRef("");
  const identityRef=useRef({companyId:"",companyRut:"",personId:"",personRut:"",personName:""});
  const dossierRef=useRef<Dossier|null>(null);
  const stepNames=["Empresa","Documentos","Antecedentes","Revisión e impresión","Historial"];
  const workerless=checked.length===1&&checked[0]==="sworn_declaration";
  const requiredPerson=checked.length>0&&!workerless;
  const title=(code:string)=>TITLES[code]||catalog.find(c=>c.code===code)?.title||code;
  const templateInfo=(code:string)=>library.find(x=>x.code===code);
  const libraryLabel=(code:string)=>{
    const item=nativeFormats.find(f=>f.code===code);
    if(!item)return "Consultando diseño HTML…";
    if(item.status==="ready")return "Formato HTML disponible para vista previa";
    if(item.status==="requires_review")return "HTML editado · pendiente de habilitación";
    return "Falta revisar el contenido HTML";
  };

  useEffect(()=>{void Promise.all([request<Source>(BASE+"/sources"),
    request<Catalog[]>("/javiera/catalog")]).then(([s,c])=>{setSource(s);setCatalog(c);})
    .catch(e=>setError(errorText(e)));
    void request<LibraryStatus>(BASE+"/templates/status")
      .then(result=>setLibrary(result.documents))
      .catch(()=>setLibrary([]));
    void request<NativeCatalog>("/javiera/v19/formats")
      .then(result=>setNativeFormats(result.formats))
      .catch(()=>setNativeFormats([]))
      .finally(()=>setNativeLoading(false));
  },[]);
  const refreshSources=useCallback(async(company:string,site:string)=>{
    const r=await request<Source>(BASE+"/sources?site_id="+encodeURIComponent(site)+
      "&company_id="+encodeURIComponent(company));
    setSource(r);
  },[]);
  useEffect(()=>{void refreshSources(companyId,siteId).catch(e=>setError(errorText(e)));},
    [siteId,companyId,refreshSources]);

  const options=useMemo(()=>[...source.companies,...source.operational_companies]
    .filter(c=>c.site_id===siteId&&(c.name+" "+c.rut).toLowerCase().includes(lookup.toLowerCase())),[source,siteId,lookup]);
  const people=useMemo(()=>[...source.people,...source.operational_people],[source]);

  const fieldsByCode=useMemo(()=>Object.fromEntries(checked.map(code=>{
    const item=catalog.find(c=>c.code===code);
    return [code,[...new Set([...(item?.required_fields||[]),...(JAVIERA_EXCEL_FIELDS[code]||[]),...(code==="labor_contract"?["employment_type"]:[])])]];
  })) as Record<string,string[]>,[checked,catalog]);
  const commonKeys=useMemo(()=>[...new Set(Object.values(fieldsByCode).flat())]
    .filter(k=>!AUTO.has(k)&&!DOC_ONLY.has(k)&&!k.startsWith("event.")),[fieldsByCode]);
  const uniqueKeys=useMemo<Record<string,string[]>>(()=>{
    const result:Record<string,string[]>={};
    for(const code of checked){
      result[code]=(fieldsByCode[code]||[]).filter(key=>!AUTO.has(key)&&!commonKeys.includes(key));
    }
    return result;
  },[checked,fieldsByCode,commonKeys]);
  // A shared field is counted once across all selected documents.
  const requirements=useMemo(()=>{
    const entries=new Map<string,{key:string;code:string}>();
    for(const code of checked){
      for(const key of fieldsByCode[code]||[]){
        const privateField=DOC_ONLY.has(key)||key.startsWith("event.");
        const identifier=privateField?code+"|"+key:key;
        if(!entries.has(identifier))entries.set(identifier,{key,code});
      }
    }
    return [...entries.values()];
  },[checked,fieldsByCode]);
  const missingLocal=useMemo(()=>requirements.filter(({key,code})=>{
    if(key==="employer.name")return !companyName.trim();
    if(key==="employer.rut")return !companyRut.trim();
    if(key==="worker.name")return !personName.trim();
    if(key==="worker.rut")return !personRut.trim();
    if(key==="site.name")return !siteId;
    const byDocument=DOC_ONLY.has(key)||key.startsWith("event.");
    return !(byDocument?specific[code]?.[key]:shared[key])?.trim();
  }),[requirements,companyName,companyRut,personName,personRut,siteId,specific,shared]);
  const total=requirements.length;
  const filled=total-missingLocal.length;
  const ready=states.filter(x=>x.can_issue);
  const invalid=states.filter(x=>!x.can_issue);
  const fingerprint=JSON.stringify({siteId,companyId,personId,companyRut,personName,personRut,personChoice,personOrigin,checked,shared,specific,relation,parentName});
  const showFailure=(e:unknown)=>{setError(errorText(e));setNotice("");};

  function chooseCode(code:string){
    if(code==="sworn_declaration"){
      setChecked(old=>old.includes(code)?[]:[code]);return;
    }
    setChecked(old=>old.includes(code)?old.filter(x=>x!==code):[...old.filter(x=>x!=="sworn_declaration"),code]);
  }
  function resetPersonContext(){
    identityGeneration.current+=1;
    // Keep employer-wide details, but never carry worker, contract or event fields across people.
    setPersonId("");setPersonName("");setPersonRut("");setPersonChoice("");
    setDossier(null);dossierRef.current=null;setBatch(null);setStates([]);
    snapshotRef.current="";
    identityRef.current={...identityRef.current,personId:"",personRut:"",personName:""};
    setSpecific({});
    setShared(old=>Object.fromEntries(Object.entries(old).filter(([key])=>
      key.startsWith("extra.representative")||key.startsWith("extra.employer")||
      key==="extra.site_address"||key==="extra.principal_company"||
      key==="extra.specialty"
    )));
  }
  function resetIdentity(){
    identityGeneration.current+=1;
    setCompanyId("");setPersonId("");setDossier(null);dossierRef.current=null;
    setBatch(null);setStates([]);setChecked([]);setShared({});setSpecific({});
    setPersonChoice("");setCompanyChoice("");setCompanyName("");setCompanyRut("");
    setPersonName("");setPersonRut("");setLookup("");setReasons({});
    snapshotRef.current="";
    identityRef.current={companyId:"",companyRut:"",personId:"",personRut:"",personName:""};
  }
  async function startCompany(){
    setError("");setNotice("");
    if(!siteId){setError("Selecciona la obra antes de continuar.");return;}
    if(relation==="subcontractor"&&!parentName.trim()){setError("Indica el contratista principal.");return;}
    setSaving(true);
    try{
      let result:Company;
      if(origin==="new"){
        if(companyName.trim().length<2)throw new Error("Escribe el nombre de la empresa.");
        result=await request<Company>(BASE+"/companies",{method:"POST",body:JSON.stringify({
          site_id:siteId,origin:"new",name:companyName,rut:companyRut})});
      }else{
        if(!companyChoice)throw new Error("Selecciona una empresa para continuar.");
        const option=options.find(x=>x.origin+":"+x.id===companyChoice);
        if(!option)throw new Error("La empresa seleccionada no está disponible en esta obra.");
        result=await request<Company>(BASE+"/companies",{method:"POST",body:JSON.stringify({
          site_id:siteId,origin:option.origin,source_id:option.id})});
      }
      if(dossierRef.current&&result.id!==companyId){
        dossierRef.current=null;setDossier(null);setChecked([]);
        setShared({});setSpecific({});setBatch(null);setStates([]);
        snapshotRef.current="";
      }
      setCompanyId(result.id);setCompanyName(result.name);setCompanyRut(result.rut);
      identityRef.current={companyId:result.id,companyRut:result.rut,personId:"",personRut:"",personName:""};
      setStep(2);setNotice("Empresa preparada exclusivamente para Proyecto Javiera.");
    }catch(e){showFailure(e);}finally{setSaving(false);}
  }
  async function ensurePerson(){
    if(!requiredPerson)return null;
    if(personId)return personId;
    let result:Person;
    const generation=identityGeneration.current;
    if(personOrigin==="new"){
      if(personName.trim().length<2)throw new Error("Indica el nombre de la persona.");
      result=await request<Person>(BASE+"/people",{method:"POST",body:JSON.stringify({
        company_id:companyId,origin:"new",name:personName,rut:personRut})});
    }else{
      const option=people.find(x=>x.origin+":"+x.id===personChoice);
      if(!option)throw new Error("Selecciona una persona de la empresa.");
      result=await request<Person>(BASE+"/people",{method:"POST",body:JSON.stringify({
        company_id:companyId,origin:option.origin,source_id:option.id})});
    }
    if(generation!==identityGeneration.current)return null;
    setPersonId(result.id);setPersonName(result.name);setPersonRut(result.rut);
    identityRef.current={...identityRef.current,personId:result.id,personRut:result.rut,personName:result.name};
    return result.id;
  }

  async function saveDraft(force=false,personOverride?:string|null){
    if(savingRef.current)return null;
    if(!companyId||!siteId||!checked.length)return null;
    savingRef.current=true;setSaving(true);setError("");
    const generation=identityGeneration.current;
    try{
      if(generation!==identityGeneration.current)return null;
      const current=dossierRef.current;
      const targetPerson=personOverride===undefined?(workerless?null:personId||null):personOverride;
      const last=identityRef.current;
      let identityChanged=false;
      // Persist edits to local documentary identities only, never to operational GALANT.
      if(last.companyId===companyId&&last.companyRut!==companyRut){
        await request(BASE+"/companies/"+companyId,{method:"PATCH",
          body:JSON.stringify({rut:companyRut})});
        identityRef.current={...identityRef.current,companyRut};
        identityChanged=true;
      }
      if(targetPerson&&personId===targetPerson&&last.personId===targetPerson&&
         (last.personRut!==personRut||last.personName!==personName)){
        await request(BASE+"/people/"+targetPerson,{method:"PATCH",body:JSON.stringify({
          rut:personRut,name:personName})});
        identityRef.current={...identityRef.current,personRut,personName};
        identityChanged=true;
      }
      const data={site_id:siteId,company_id:companyId,
        person_id:targetPerson,
        relationship:relation,parent_name:relation==="subcontractor"?parentName:null,
        selected_codes:checked,shared:nestedFromFields(shared),
        document_data:Object.fromEntries(checked.map(code=>[code,{
          ...nestedFromFields(specific[code]||{}),
          ...(code==="sworn_declaration"&&specific[code]?.["verified_no_workers"]==="true"?
            {verified_no_workers:true}:{}),
        }])), // Preparar el PDF no confirma que el evento ocurrió.
        ...(current?{dossier_id:current.id,expected_revision:current.revision}:{})};
      const signature=JSON.stringify(data);
      // Volver a previsualizar sin cambios no debe incrementar la revisión,
      // duplicar documentos, ni bloquear la interfaz por escrituras evitables.
      if(current&&signature===snapshotRef.current){
        if(identityChanged){
          const check=await request<{documents:DocState[]}>(BASE+"/dossiers/"+current.id+"/eligibility");
          setStates(check.documents);
        }
        return current;
      }
      const result=await request<Dossier>(BASE+"/dossiers",{method:"POST",body:JSON.stringify(data)});
      if(generation!==identityGeneration.current)return null;
      dossierRef.current=result;setDossier(result);snapshotRef.current=JSON.stringify({
        ...data,dossier_id:result.id,expected_revision:result.revision});
      const eligibility=await request<{documents:DocState[]}>(BASE+"/dossiers/"+result.id+"/eligibility");
      if(generation!==identityGeneration.current)return null;
      setStates(eligibility.documents);
      if(force)setNotice("Expediente documental guardado correctamente.");
      return result;
    }catch(e){showFailure(e);return null;}finally{savingRef.current=false;setSaving(false);}
  }
  async function goReview(){
    if(!checked.length){setError("Selecciona al menos un documento.");return;}
    try{
      const generation=identityGeneration.current;
      const resolved=await ensurePerson();
      if(generation!==identityGeneration.current||(requiredPerson&&!resolved))return;
      const result=await saveDraft(true,requiredPerson?resolved:null);
      if(result){setStep(4);setError("");}
    }catch(e){showFailure(e);}
  }

  useEffect(()=>{
    if(step!==3||!companyId||!checked.length)return;
    if(requiredPerson&&!personId&&(
       personOrigin==="new"?personName.trim().length<2:!personChoice))return;
    const timeout=window.setTimeout(()=>{
      void (async()=>{
        try{
          const generation=identityGeneration.current;
          const resolved=requiredPerson?await ensurePerson():null;
          if(generation!==identityGeneration.current||(requiredPerson&&!resolved))return;
          await saveDraft(false,requiredPerson?resolved:null);
        }catch(e){showFailure(e);}
      })();
    },1600);
    return()=>window.clearTimeout(timeout);
  // Debounced autosave starts as soon as there is a valid documentary identity.
  },[fingerprint,step]);

  async function generate(){
    if(!dossierRef.current)return;
    const current=await saveDraft(true);
    if(!current)return;
    const available=states.filter(s=>s.can_issue).map(s=>s.code);
    if(!available.length){setError("No hay documentos listos. Revisa los datos y las aprobaciones.");return;}
    setSaving(true);setError("");
    try{
      const result=await request<Batch>(BASE+"/issue/batch",{method:"POST",body:JSON.stringify({
        dossier_id:current.id,codes:available,reissue_reasons:reasons})});
      setBatch(result);
      const record=await request<History>(BASE+"/history?dossier_id="+encodeURIComponent(current.id));
      setHistory(record);
      setNotice(result.issued+" PDF disponibles. "+(result.failed?result.failed+" no emitidos.":"Puedes imprimir el paquete."));
    }catch(e){showFailure(e);}finally{setSaving(false);}
  }
  async function openNativeBatch(){
    const tab=pdfTab();
    try{
      if(!checked.length){tab?.close();setError("Selecciona los documentos que quieres imprimir.");return;}
      const record=await saveDraft(true);
      if(!record){tab?.close();return;}
      const blob=await nativeBatchRequest(record.id,checked);
      const url=URL.createObjectURL(blob);
      if(tab)tab.location.replace(url);
      else setError("El navegador bloqueó el PDF. Permite las ventanas emergentes para imprimir.");
      window.setTimeout(()=>URL.revokeObjectURL(url),120000);
      setNotice(checked.length+" documentos preparados en PDF A4 sin convertir Excel. "+
        "Deben firmarse físicamente después.");
    }catch(e){tab?.close();showFailure(e);}
  }
  async function openNativePreview(code:string){
    const tab=pdfTab();
    try{
      const record=await saveDraft(true);
      if(!record){tab?.close();return;}
      const blob=await nativePreviewRequest(record.id,code);
      const url=URL.createObjectURL(blob);
      if(tab)tab.location.replace(url);
      else setNotice("El navegador bloqueó la pestaña del PDF. Permite ventanas emergentes para revisarlo.");
      window.setTimeout(()=>URL.revokeObjectURL(url),120000);
    }catch(e){tab?.close();showFailure(e);}
  }
  async function openPreview(code:string){
    const tab=pdfTab();
    try{
      const result=await saveDraft(true);
      if(!result){tab?.close();return;}
      const blob=await previewRequest(result.id,code);
      const url=URL.createObjectURL(blob);
      if(tab)tab.location.replace(url);
      else setNotice("El navegador bloqueó la pestaña. Puedes utilizar los documentos emitidos desde Historial.");
      window.setTimeout(()=>URL.revokeObjectURL(url),120000);
    }catch(e){tab?.close();showFailure(e);}
  }
  async function openHistory(){
    try{
      setHistory(await request<History>(BASE+"/history"+(dossierRef.current?
        "?dossier_id="+encodeURIComponent(dossierRef.current.id):"")));
      setStep(5);
    }catch(e){showFailure(e);}
  }
  async function loadDossier(id:string){
    const generation=++identityGeneration.current;
    try{
      const d=await request<Dossier>(BASE+"/dossiers/"+id);
      if(generation!==identityGeneration.current)return;
      setSiteId(d.site_id);setCompanyId(d.company_id);setCompanyName(d.company_name);setCompanyRut(d.company_rut||"");
      setPersonId(d.person_id||"");setPersonName(d.person_name||"");setPersonRut(d.person_rut||"");
      setRelation(d.relationship);setParentName(d.parent_name||"");
      setChecked(d.selected_codes);
      function flatten(o:Record<string,unknown>){
        const data:Record<string,string>={};
        for(const [key,value] of Object.entries(o)){
          if(value&&typeof value==="object"&&!Array.isArray(value)){
            for(const [nested,val] of Object.entries(value as Record<string,unknown>))
              if(typeof val==="string"||typeof val==="number")data[key+"."+nested]=String(val);
          }else if(typeof value==="string"||typeof value==="number")data[key]=String(value);
        }
        return data;
      }
      setShared(flatten(d.shared));
      setSpecific(Object.fromEntries(Object.entries(d.document_data).map(([code,obj])=>[
        code,{...flatten(obj),...(obj.verified_no_workers?{verified_no_workers:"true"}:{})}])));
      identityRef.current={companyId:d.company_id,companyRut:d.company_rut||"",
        personId:d.person_id||"",personRut:d.person_rut||"",personName:d.person_name||""};
      setDossier(d);dossierRef.current=d;setBatch(null);setStep(3);setNotice("Expediente recuperado sin modificar módulos operativos.");
    }catch(e){showFailure(e);}
  }

  const field=(key:string,code?:string)=>{
    const meta:{label:string;type?:string;options?:string[];hint?:string}=key==="employment_type"?{label:"Vínculo laboral",options:["dependiente","independiente"]}:JAVIERA_FIELD_META[key]||{label:key.replaceAll("."," · ").replaceAll("_"," ")};
    const value=code?specific[code]?.[key]||"":shared[key]||"";
    const label=meta.label;
    const type=meta.type||"text";
    return <label className="j166-field" key={(code||"common")+key}>
      <span>{label}</span>
      {meta.options?<select value={value} onChange={e=>changeField(key,e.target.value,code)}>
        <option value="">Seleccionar</option>{meta.options.map(o=><option key={o}>{o}</option>)}
      </select>:type==="textarea"?<textarea rows={6} value={value}
        onChange={e=>changeField(key,e.target.value,code)} placeholder={label}/>:
        <input type={type} value={value} onChange={e=>changeField(key,e.target.value,code)}
        min={type==="number"?"0":undefined} placeholder={label}/>}
      {meta.hint&&<small>{meta.hint}</small>}
    </label>;
  };
  function changeField(key:string,value:string,code?:string){
    if(code)setSpecific(old=>({...old,[code]:{...old[code],[key]:value}}));
    else setShared(old=>({...old,[key]:value}));
  }

  return <main className="j166">
    <header className="j166-head">
      <div><small>PROYECTO JAVIERA · DOCUMENTOS HTML</small><h2>Generador de documentos PDF A4</h2>
        <p>Prepara documentos sin incorporar personas ni empresas a los módulos operativos de GALANT.</p></div>
      {onConfig&&<button className="j166-light" onClick={onConfig}>Configurar plantillas</button>}
    </header>
    <nav className="j166-steps" aria-label="Progreso">
      {stepNames.map((name,i)=><button key={name} className={step===i+1?"active":""}
        disabled={i+1>step||saving} onClick={()=>setStep(i+1)}>{i+1}. {name}</button>)}
    </nav>
    {error&&<p className="j166-error" role="alert"><AlertCircle size={17}/>{error}</p>}
    {notice&&<p className="j166-notice" role="status"><CheckCircle2 size={17}/>{notice}</p>}
    {step===1&&<section className="j166-panel">
      <h3>¿La empresa es nueva o ya existe?</h3>
      <div className="j166-two">
        <button className={"j166-pick "+(origin==="new"?"selected":"")} onClick={()=>{setOrigin("new");resetIdentity();}}>
          <FolderOpen size={23}/><b>Empresa nueva</b><span>Crear una ficha exclusivamente documental.</span></button>
        <button className={"j166-pick "+(origin!=="new"?"selected":"")} onClick={()=>{setOrigin("documentary");resetIdentity();}}>
          <Search size={23}/><b>Empresa existente</b><span>Recuperar de GALANT o de Javiera sin modificar su origen.</span></button>
      </div>
      <div className="j166-fields">
        <label className="j166-field"><span>Obra</span><select value={siteId} onChange={e=>{setSiteId(e.target.value);resetIdentity();}}>
          <option value="">Selecciona una obra</option>{source.sites.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
        </select></label>
        <label className="j166-field"><span>Tipo de relación</span><select value={relation} onChange={e=>setRelation(e.target.value)}>
          <option value="contractor">Contratista</option><option value="subcontractor">Subcontrato</option></select></label>
        {relation==="subcontractor"&&<label className="j166-field"><span>Contratista principal</span>
          <input value={parentName} onChange={e=>setParentName(e.target.value)} placeholder="Nombre de la empresa principal"/></label>}
        {origin==="new"?<>
          <label className="j166-field"><span>Razón social</span><input value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label>
          <label className="j166-field"><span>RUT de empresa (si se conoce)</span><input value={companyRut} onChange={e=>setCompanyRut(e.target.value)}/></label>
        </>:<>
          <label className="j166-field"><span>Buscar por nombre o RUT</span><input value={lookup} onChange={e=>setLookup(e.target.value)}/></label>
          <label className="j166-field"><span>Empresa existente</span><select value={companyChoice} onChange={e=>setCompanyChoice(e.target.value)}>
            <option value="">Seleccionar empresa</option>{options.map(c=><option key={c.origin+":"+c.id} value={c.origin+":"+c.id}>
              {c.name} · {c.rut||"Sin RUT"} · {c.origin==="operational"?"GALANT":"Javiera"}</option>)}
          </select></label>
        </>}
      </div>
      <div className="j166-actions"><button disabled={saving} className="j166-primary" onClick={()=>void startCompany()}>
        Continuar a documentos <ChevronRight size={17}/></button>
        <button className="j166-light" onClick={()=>void openHistory()}>Consultar documentos emitidos</button></div>
    </section>}
    {step===2&&<section className="j166-panel">
      <button className="j166-back" onClick={()=>setStep(1)}><ArrowLeft size={16}/> Volver</button>
      <h3>¿Qué documentos quieres preparar?</h3>
      <p>Selecciona varios mediante las casillas. La declaración de ausencia de trabajadores necesita un expediente empresarial separado.</p>
      {["Zona Subcontratos","Prevención de Riesgos"].map(area=><div key={area}>
        <div className="j166-group"><h4>{area}</h4>
          <button className="j166-light" onClick={()=>{
            const codes=catalog.filter(c=>c.area===area&&c.code!=="sworn_declaration").map(c=>c.code);
            setChecked(old=>[...new Set([...old.filter(x=>x!=="sworn_declaration"),...codes])]);}}>Seleccionar área</button></div>
        <div className="j166-doc-grid">{catalog.filter(c=>c.area===area).map(c=>
          <label key={c.code} className={"j166-doc "+(checked.includes(c.code)?"checked":"")}>
            <input type="checkbox" checked={checked.includes(c.code)} onChange={()=>chooseCode(c.code)}/>
            <FileText size={17}/><span><b>{title(c.code)}</b><small>{
              library.length?libraryLabel(c.code):
                c.published_version?"Plantilla publicada · revisión "+c.published_version:
                "Comprobar biblioteca de plantillas"}</small></span>
          </label>)}</div>
      </div>)}
      {checked.length>0&&<div className="j166-sub" aria-live="polite">
        <h4>Datos que necesitarás completar</h4>
        <p>{total} antecedentes distintos para los documentos marcados · {missingLocal.length} pendientes.</p>
        <div className="j166-needed">{missingLocal.slice(0,6).map(({key,code},index)=>
          <span key={code+":"+key+":"+index}>
            {key==="employment_type"?"Vínculo laboral":JAVIERA_FIELD_META[key]?.label||key}
            {DOC_ONLY.has(key)||key.startsWith("event.")?" · "+title(code):""}
          </span>)}
          {missingLocal.length>6&&<small>y {missingLocal.length-6} más, organizados en el siguiente paso</small>}
        </div>
      </div>}
      <div className="j166-actions"><strong>{checked.length} documentos seleccionados</strong>
        <button className="j166-light" onClick={()=>setChecked([])}>Quitar selección</button>
        <button disabled={!checked.length} className="j166-primary" onClick={()=>setStep(3)}>Continuar <ChevronRight size={17}/></button></div>
    </section>}
    {step===3&&<section className="j166-panel">
      <button className="j166-back" onClick={()=>setStep(2)}><ArrowLeft size={16}/> Volver a documentos</button>
      <h3>Completar antecedentes una sola vez</h3>
      <p>{checked.length} documentos · {filled} de {total} requisitos cubiertos. Los datos compartidos se reutilizan donde corresponden.</p>
      <div className="j166-meter"><div style={{width:(total?100*filled/total:0)+"%"}}/></div>
      <section className="j166-sub"><h4>Datos documentales de la empresa</h4>
        <div className="j166-fields">
          <label className="j166-field"><span>Razón social</span><input value={companyName} readOnly/></label>
          <label className="j166-field"><span>RUT de empresa (ficha Javiera)</span>
            <input value={companyRut} onChange={e=>setCompanyRut(e.target.value)}/></label>
        </div><small>Modificar este RUT no altera Contratistas de GALANT.</small>
      </section>
      {requiredPerson&&<section className="j166-sub">
        <h4>Persona documental</h4>
        <div className="j166-switch"><button className={personOrigin==="new"?"active":""}
          onClick={()=>{resetPersonContext();setPersonOrigin("new");}}>Nueva</button>
          <button className={personOrigin!=="new"?"active":""}
          onClick={()=>{resetPersonContext();setPersonOrigin("documentary");}}>Existente</button></div>
        {personOrigin==="new"?<div className="j166-fields">
          <label className="j166-field"><span>Nombre completo</span><input value={personName} onChange={e=>setPersonName(e.target.value)}/></label>
          <label className="j166-field"><span>RUT</span><input value={personRut} onChange={e=>setPersonRut(e.target.value)}/></label></div>
          :<label className="j166-field"><span>Seleccionar persona</span><select value={personChoice} onChange={e=>{resetPersonContext();setPersonChoice(e.target.value);}}>
            <option value="">Seleccionar</option>{people.map(p=><option key={p.origin+":"+p.id} value={p.origin+":"+p.id}>{p.name} · {p.origin==="operational"?"GALANT":"Javiera"}</option>)}</select></label>}
        {personId&&<label className="j166-field"><span>RUT de persona (ficha Javiera)</span>
          <input value={personRut} onChange={e=>setPersonRut(e.target.value)}/></label>}
        <small>Este registro no modificará el módulo Trabajadores.</small>
      </section>}
      <section className="j166-sub"><h4>Datos compartidos</h4>
        <div className="j166-fields">{commonKeys.map(key=>field(key))}</div></section>
      <p className="j166-native-help">Abre solo el documento que necesitas completar.
        Los datos comunes se reutilizan automáticamente en los demás.</p>
      {checked.map((code,index)=><details key={code} className="j166-sub j166-doc-accordion" open={index===0}>
        <summary><strong>{title(code)}</strong>
          <small>{(uniqueKeys[code]||[]).length} campos propios · se puede editar después</small>
        </summary>
        {["ppe_delivery","pts_receipt","induction","internal_rules_receipt"].includes(code)&&
          <p>Este formulario se prepara para imprimir y obtener firma en papel después. No es necesario indicar que la entrega o recepción ya ocurrió.</p>}
        {code==="sworn_declaration"&&<label className="j166-confirm"><input type="checkbox"
          checked={specific[code]?.verified_no_workers==="true"}
          onChange={e=>changeField("verified_no_workers",e.target.checked?"true":"",code)}/>
          Confirmo que la ausencia de trabajadores se verificará para el período declarado, con respaldo documental.</label>}
        {uniqueKeys[code]?.length?<div className="j166-fields">{uniqueKeys[code].map(key=>field(key,code))}</div>:
          <p>Este documento utiliza únicamente los antecedentes compartidos.</p>}
        <label className="j166-field">
          <span>Observaciones opcionales para este documento</span>
          <textarea rows={3} value={specific[code]?.["event.print_notes"]||""}
            maxLength={2000} placeholder="Solo agrega información verificable; no modifica el texto aprobado."
            onChange={e=>changeField("event.print_notes",e.target.value,code)}/>
          <small>Se imprimen en un apartado separado. No reemplazan cláusulas ni certifican una firma.</small>
        </label>
      </details>)}
      <div className="j166-actions"><span>{saving?"Guardando cambios…":dossier?"Borrador recuperable · revisión "+dossier.revision:"Pendiente de guardar"}</span>
        <button disabled={saving} className="j166-light" onClick={()=>void (async()=>{
          try{const resolved=await ensurePerson();await saveDraft(true,requiredPerson?resolved:null);}
          catch(e){showFailure(e);}})()}><Save size={17}/> Guardar borrador</button>
        <button disabled={saving} className="j166-primary" onClick={()=>void goReview()}>Revisar documentos <ChevronRight size={17}/></button></div>
    </section>}
    {step===4&&<section className="j166-panel">
      <button className="j166-back" onClick={()=>setStep(3)}><ArrowLeft size={16}/> Corregir antecedentes</button>
      <h3>Revisión e impresión</h3>
      <p className="j166-native-help">Elige <strong>Vista previa A4</strong> para revisar cada formato
        o <strong>Preparar paquete PDF A4</strong> para imprimir todos los seleccionados.
        Si falta contenido, abre <strong>Editar HTML</strong>. Ya no necesitas importar Excel.
        Puedes corregir los datos antes de imprimir; el PDF no registra firmas físicas.</p>
      <p>{checked.length} documentos seleccionados · {checked.filter(c=>nativeFormats.find(f=>f.code===c)?.status==="ready").length} con formato HTML habilitado</p>
      {states.map(s=><div className="j166-status" key={s.code}>
        <div><strong>{title(s.code)}</strong><small>{s.can_issue?"Listo para emitir":
          s.status+" · "+(s.reason||s.missing_fields.length+" datos pendientes")}</small>
          {s.missing_fields.length>0&&<small>Faltan: {s.missing_fields.map(x=>JAVIERA_FIELD_META[x]?.label||x).join(", ")}</small>}
          {s.blocking_errors.map(x=><small key={x}>{x}</small>)}
          {!s.can_issue&&templateInfo(s.code)&&<small>
            {templateInfo(s.code)?.message} · Hoja: {templateInfo(s.code)?.sheet}
          </small>}
        </div><div className="j166-status-actions">
          {s.can_issue&&<details className="j166-legacy-preview"><summary>Versión Excel histórica</summary>
            <button className="j166-light" onClick={()=>void openPreview(s.code)}><Eye size={16}/> Vista previa Excel</button>
          </details>}
          {nativeLoading&&<small>Consultando formatos A4…</small>}
          {nativeFormats.find(f=>f.code===s.code)?.status==="ready"&&
            <button className="j166-light" disabled={saving}
              onClick={()=>void openNativePreview(s.code)}
              title="PDF A4 para revisar e imprimir. No acredita firma ni recepción.">
              <Eye size={16}/> Vista previa A4
            </button>}
          {["requires_published_text","requires_review"].includes(
              nativeFormats.find(f=>f.code===s.code)?.status||"")&&
            <button className="j166-light" disabled={!onTextEditor} onClick={onTextEditor}
              title="Editar la versión HTML, guardar y habilitar su vista previa">
              <FileText size={16}/> Editar HTML
            </button>}
          {s.last_issue_id&&<a href={API+"/issues/"+s.last_issue_id+"/pdf"} target="_blank" rel="noreferrer">PDF anterior</a>}
        </div>
        {s.has_history&&<label className="j166-field"><span>Motivo de reemisión (mínimo 20 caracteres si cambian los datos)</span>
          <input value={reasons[s.code]||""} onChange={e=>setReasons(old=>({...old,[s.code]:e.target.value}))}/></label>}
      </div>)}
      <div className="j166-actions">
        <button disabled={saving||!checked.length} className="j166-primary" onClick={()=>void openNativeBatch()}>
          <Printer size={18}/> Preparar paquete PDF A4 ({checked.length})
        </button>
        <button className="j166-light" onClick={()=>void openHistory()}>Historial</button>
      </div>
      <details className="j166-excel-legacy">
        <summary>Compatibilidad: emisión antigua desde Excel</summary>
        <p>Disponible para revisar documentos históricos mientras completas la migración.
           Este proceso puede requerir las plantillas Excel originales.</p>
        <button disabled={saving||!ready.length} className="j166-light" onClick={()=>void generate()}>
          <Printer size={18}/> Generar {ready.length} documentos elegibles (Excel)
        </button>
      </details>
      {batch&&<div className="j166-sub"><h4>Resultado del paquete</h4>
        <p>{batch.issued} documentos disponibles · {batch.failed} no emitidos.</p>
        {batch.package_error&&<p role="alert" className="j166-error">{batch.package_error}</p>}
        {batch.results.map(x=><div key={x.code} className="j166-result">
          <span>{title(x.code)} — {x.ok?"Disponible":x.reason}</span>
          {x.ok&&<a href={API+"/issues/"+x.id+"/pdf"} target="_blank" rel="noreferrer">Abrir individual</a>}</div>)}
        {batch.pdf_url&&<div className="j166-actions">
          <a className="j166-primary" href={batch.pdf_url} target="_blank" rel="noreferrer"><Printer size={17}/> Imprimir paquete PDF</a>
          <a className="j166-light" href={batch.pdf_url} download="JAVIERA-paquete.pdf"><Download size={17}/> Descargar paquete</a></div>}
      </div>}
    </section>}
    {step===5&&<section className="j166-panel">
      <button className="j166-back" onClick={()=>setStep(dossier?4:1)}><ArrowLeft size={16}/> Volver</button>
      <h3>Documentos emitidos</h3>
      <p>Los PDF originales se conservan sin modificaciones. Abrir o descargar no equivale a una firma o entrega.</p>
      <h4>Paquetes de emisión</h4>
      {history.batches.length===0&&<p>No hay paquetes registrados para esta búsqueda.</p>}
      {history.batches.map(b=><div className="j166-result" key={b.id}><span>{formatTime(b.created_at)} · {b.results.filter(x=>x.ok).length} documentos</span>
        {b.has_pdf&&<a href={API+"/batches/"+b.id+"/pdf"} target="_blank" rel="noreferrer">Abrir paquete</a>}</div>)}
      <h4>Documentos individuales</h4>
      {history.issues.map(i=><div className="j166-result" key={i.id}>
        <span>{title(i.code)} · {formatTime(i.issued_at)} {i.reissue_reason?"· Reemisión":""}</span>
        <a href={API+"/issues/"+i.id+"/pdf"} target="_blank" rel="noreferrer">Abrir PDF</a></div>)}
      <h4>Documentos históricos (versión 16.5)</h4>
      {history.legacy_issues?.map(i=><div className="j166-result" key={i.id}>
        <span>{title(i.code)} · {formatTime(i.issued_at)} · Archivo original</span>
        <a href={"/api/v1/javiera/issued/"+i.id+"/pdf"} target="_blank" rel="noreferrer">Abrir PDF histórico</a>
      </div>)}
      <h4>Continuar expediente documental</h4>
      <DossierPicker onPick={id=>void loadDossier(id)}/>
    </section>}
    <footer className="j166-foot">Proyecto JAVIERA no da de alta trabajadores ni contratistas operativos.
      La emisión de un PDF no acredita firma, entrega de EPP ni capacitación.</footer>
  </main>;
}

function DossierPicker({onPick}:{onPick:(id:string)=>void}){
  const [records,setRecords]=useState<Dossier[]>([]);
  const [error,setError]=useState("");
  useEffect(()=>{void request<Dossier[]>(BASE+"/dossiers").then(setRecords)
    .catch(e=>setError(errorText(e)));},[]);
  return <div><p>{error}</p><div className="j166-history-list">
    {records.map(d=><button key={d.id} onClick={()=>onPick(d.id)}>
      {d.company_name} · {d.person_name||"Sin persona"} · {d.site_name} · {formatTime(d.updated_at)}
    </button>)}</div></div>;
}
