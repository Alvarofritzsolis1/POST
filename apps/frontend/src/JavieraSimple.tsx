import {useEffect,useMemo,useRef,useState} from "react";
import {ArrowLeft,CheckCircle2,ClipboardList,Download,Eye,FileSpreadsheet,FileText,FolderOpen,Loader2,Settings2,ShieldAlert,ShieldCheck} from "lucide-react";
import {request} from "./api";
import {parseEppDraft,serializeEppDraft,type EppChoice} from "./javiera-epp";

import "./javiera.css";
import "./javiera-simple.css";

type Origin="operational"|"documentary";
type Company={id:string;site_id:string;name:string;rut:string;origin:Origin;details?:Record<string,string>;source_contractor_id?:string|null};
type Person={id:string;name:string;rut:string;origin:Origin;details?:Record<string,string>;source_worker_id?:string|null};
type Sources={sites:{id:string;name:string}[];companies:Company[];
  operational_companies:Company[];people:Person[];operational_people:Person[]};
type Library={engine_available:boolean;documents:{code:string;state:string;ready:boolean;sheet:string}[]};
type RoleList={roles:{cargo:string}[]};
type Catalog={code:string;title:string;area:string;required_fields:string[]}[];
type Dossier={id:string;revision:number;shared?:Record<string,unknown>;selected_codes?:string[];document_data?:Record<string,Record<string,unknown>>};
type DossierLookup={found:boolean;dossier:Dossier|null;legacy_shared?:Record<string,unknown>|null};
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
  const [eppOptions,setEppOptions]=useState<EppChoice[]>([]);
  const [mode,setMode]=useState<"new"|"existing"|null>(null);
  const [documentSearch,setDocumentSearch]=useState("");
  const [verified,setVerified]=useState<DocumentStatus[]>([]);
  const [site,setSite]=useState("");
  const [companyToken,setCompanyToken]=useState("");
  const [companyId,setCompanyId]=useState("");
  const [personToken,setPersonToken]=useState("");
  const [personId,setPersonId]=useState("");
  const [role,setRole]=useState("");
  const [showNewCompany,setShowNewCompany]=useState(false);
  const [showNewPerson,setShowNewPerson]=useState(false);
  const [newCompany,setNewCompany]=useState({name:"",rut:""});
  const [newPerson,setNewPerson]=useState({name:"",rut:""});
  const [code,setCode]=useState("irl");
  const [selectedCodes,setSelectedCodes]=useState<string[]>(["irl"]);
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
  const [history,setHistory]=useState<{issues:{id:string;code:string;issued_at:string}[];
    legacy_issues:{id:string;code:string;issued_at:string}[]}|null>(null);
  const [historyLoading,setHistoryLoading]=useState(false);
  const current=useRef<{signature:string;dossier:Dossier}|null>(null);
  const generation=useRef(0);
  const previewRef=useRef<LocalPreview|null>(null);
  useEffect(()=>{previewRef.current=preview;},[preview]);
  useEffect(()=>()=>{if(previewRef.current)URL.revokeObjectURL(previewRef.current.url);},[]);
  const companies=useMemo(()=>{
    const linked=new Set(source.companies.map(c=>c.source_contractor_id).filter(Boolean));
    return [...source.companies,...source.operational_companies.filter(c=>!linked.has(c.id))]
      .filter(c=>c.site_id===site&&(c.name+" "+c.rut).toLocaleLowerCase("es").includes(filter.toLocaleLowerCase("es")));
  },[source,site,filter]);
  const people=useMemo(()=>{
    const linked=new Set(source.people.map(p=>p.source_worker_id).filter(Boolean));
    return [...source.people,...source.operational_people.filter(p=>!linked.has(p.id))];
  },[source]);
  const selectedCompany=locate(companies,companyToken);
  const selectedPerson=locate(people,personToken);
  const layout=library?.documents.find(x=>x.code===code);
  const eppDraft=useMemo(()=>parseEppDraft(extras["event.epp_items"]||"",eppOptions),[extras,eppOptions]);
  const workerless=code==="sworn_declaration";
  const ready=!!site&&!!companyToken&&!!companyId&&selectedCodes.length>0&&
    (!!personToken&&!!personId||workerless)&&!!code&&!!date&&
    (!!role||!["irl","pts","pts_receipt","ppe_delivery","induction"].includes(code))&&
    (workerless?verifiedNoWorkers:true);
  const signature=JSON.stringify({site,companyId,personId:workerless?null:personId,role,code,selectedCodes,date,extras,verifiedNoWorkers});
  function resetPreview(){
    setPreview(old=>{if(old)URL.revokeObjectURL(old.url);return null;});
    setIssued("");setMissing([]);setReasons([]);setVerified([]);setNotice("");setError("");
  }
  // Al cambiar una ficha se invalidan pruebas PDF anteriores; NO se borra
  // el aviso de guardado que acaba de mostrar la acción de alta o corrección.
  useEffect(()=>{
    setPreview(old=>{if(old)URL.revokeObjectURL(old.url);return null;});
    setIssued("");setMissing([]);setReasons([]);setVerified([]);setError("");
  },[signature]);
  useEffect(()=>{
    let active=true;
    void Promise.all([
      request<Sources>(base+"/sources"),
      request<Library>(base+"/templates/status"),
      request<RoleList>("/javiera/v194/roles"),
      request<Catalog>("/javiera/catalog"),
      request<EppChoice[]>("/javiera/epp/catalog"),
    ]).then(([s,l,r,c,epp])=>{
      if(!active)return;
      setSource(s);setLibrary(l);setRoles(r.roles.map(x=>x.cargo));setCatalog(c);
      setEppOptions(epp);
    }).catch(e=>{if(active)setError(friendly(e));})
      .finally(()=>{if(active)setBooting(false);});
    return ()=>{active=false;};
  },[]);
  function chooseMode(next:"new"|"existing"){
    generation.current+=1;
    setMode(next);setSite("");setFilter("");setSource(old=>({...old,people:[],operational_people:[]}));
    setCompanyToken("");setCompanyId("");setPersonToken("");setPersonId("");
    setNewCompany({name:"",rut:""});setNewPerson({name:"",rut:""});
    setShowNewCompany(next==="new");setShowNewPerson(false);setRole("");
    setCode(next==="new"?"labor_contract":"irl");
    setSelectedCodes(next==="new"?["labor_contract"]:[]);
    setDocumentSearch("");setExtras({});setVerifiedNoWorkers(false);
    current.current=null;resetPreview();
  }
  function fillShared(shared:Record<string,unknown>|null|undefined){
    if(!shared)return;
    const filled:Record<string,string>={};
    for(const section of ["extra","event","contract"]){
      const values=shared[section];
      if(values&&typeof values==="object"&&!Array.isArray(values))
        for(const [key,value] of Object.entries(values as Record<string,unknown>))
          if(value!==undefined&&value!==null&&typeof value!=="object")
            filled[section+"."+key]=String(value);
    }
    setExtras(filled);
    if(typeof shared.role==="string")setRole(shared.role);
    const event=shared.event as Record<string,unknown>|undefined;
    if(event&&typeof event.date==="string")setDate(event.date.slice(0,10));
  }
  async function recoverExisting(siteId:string,contractorId:string,workerId:string|null,index:number){
    const params=new URLSearchParams({site_id:siteId,company_id:contractorId});
    if(workerId)params.set("person_id",workerId);
    const data=await request<DossierLookup>(base+"/dossiers/lookup?"+params);
    if(index!==generation.current)return;
    current.current=null;
    if(data.found&&data.dossier){
      fillShared(data.dossier.shared);
      const codes=(data.dossier.selected_codes||[]).filter(code=>ORDER.includes(code));
      if(codes.length){setSelectedCodes(codes);setCode(codes[0]);}
      const sworn=data.dossier.document_data?.sworn_declaration;
      setVerifiedNoWorkers(sworn?.verified_no_workers===true);
      current.current={signature:"",dossier:data.dossier};
      setNotice("Ficha anterior recuperada. Revisa los datos antes de emitir documentos.");
    }else if(data.legacy_shared){
      fillShared(data.legacy_shared);
      setNotice("Datos anteriores recuperados para esta empresa y trabajador. Se conservarán al preparar el expediente.");
    }else{
      setNotice("Empresa y trabajador seleccionados. Completa solo los datos que falten.");
    }
  }
  async function changeSite(value:string){
    const index=++generation.current;
    setSite(value);setCompanyToken("");setCompanyId("");setPersonToken("");setPersonId("");
    setRole("");setFilter("");setExtras({});setVerifiedNoWorkers(false);
    setShowNewCompany(mode==="new");setShowNewPerson(false);
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
    setExtras({});setRole("");setVerifiedNoWorkers(false);
    current.current=null;setShowNewPerson(false);setVerified([]);
    if(!value)return;
    const item=locate([...source.companies,...source.operational_companies],value);
    if(!item)return;
    setBusy(true);setError("");
    try{
      const linked=await request<Company>(base+"/companies",{
        method:"POST",body:JSON.stringify({
          site_id:site,origin:item.origin,source_id:item.id
        })
      });
      if(index!==generation.current)return;
      setCompanyId(linked.id);
      const loaded=await request<Sources>(base+"/sources?site_id="+encodeURIComponent(site)+
        "&company_id="+encodeURIComponent(linked.id));
      if(index!==generation.current)return;
      setSource(loaded);setCompanyToken(token(linked));
      if(linked.details)fillShared({extra:linked.details});
      await recoverExisting(site,linked.id,null,index);
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  async function changePerson(value:string){
    const index=++generation.current;
    setPersonToken(value);setPersonId("");setRole("");setExtras({});
    setVerifiedNoWorkers(false);current.current=null;setVerified([]);
    if(!value)return;
    const item=locate(people,value);
    if(!item||!companyId)return;
    setBusy(true);setError("");
    try{
      const linked=await request<Person>(base+"/people",{
        method:"POST",body:JSON.stringify({
          company_id:companyId,origin:item.origin,source_id:item.id
        })
      });
      if(index!==generation.current)return;
      setPersonId(linked.id);setPersonToken(token(linked));
      if(linked.details?.role)setRole(linked.details.role);
      await recoverExisting(site,companyId,linked.id,index);
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  async function createCompany(){
    if(!site||!newCompany.name.trim()||!newCompany.rut.trim()){
      setError("Indica la obra, razón social y RUT para preparar documentos.");return;
    }
    const index=++generation.current;
    setBusy(true);setError("");
    try{
      const company=await request<Company>(base+"/companies",{
        method:"POST",body:JSON.stringify({
          site_id:site,origin:"new",name:newCompany.name.trim(),rut:newCompany.rut.trim()
        })
      });
      const loaded=await request<Sources>(base+"/sources?site_id="+encodeURIComponent(site)+
        "&company_id="+encodeURIComponent(company.id));
      if(index!==generation.current)return;
      setSource(loaded);setCompanyToken(token(company));setCompanyId(company.id);
      setPersonToken("");setPersonId("");setRole("");setShowNewCompany(false);
      setShowNewPerson(true);setNewCompany({name:"",rut:""});
      current.current=null;
      setNotice("Empresa guardada solo en Proyecto Javiera. No se registró en GALANT operativo.");
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  async function createPerson(){
    if(!companyId||!newPerson.name.trim()||!newPerson.rut.trim()){
      setError("Indica nombre y RUT del trabajador para su ficha documental.");return;
    }
    const index=++generation.current;
    setBusy(true);setError("");
    try{
      const person=await request<Person>(base+"/people",{
        method:"POST",body:JSON.stringify({
          company_id:companyId,origin:"new",name:newPerson.name.trim(),rut:newPerson.rut.trim()
        })
      });
      const loaded=await request<Sources>(base+"/sources?site_id="+encodeURIComponent(site)+
        "&company_id="+encodeURIComponent(companyId));
      if(index!==generation.current)return;
      setSource(loaded);setPersonToken(token(person));setPersonId(person.id);
      setRole("");setShowNewPerson(false);setNewPerson({name:"",rut:""});
      current.current=null;
      setNotice("Trabajador guardado solo en Proyecto Javiera. No se asignó a una obra operativa.");
    }catch(e){if(index===generation.current)setError(friendly(e));}
    finally{if(index===generation.current)setBusy(false);}
  }
  async function refreshIdentity(kind:"company"|"person"){
    const id=kind==="company"?companyId:personId;
    if(!id)return;
    setBusy(true);setError("");
    try{
      await request(base+"/"+(kind==="company"?"companies":"people")+"/"+
        encodeURIComponent(id)+"/refresh-source",{method:"POST"});
      const loaded=await request<Sources>(base+"/sources?site_id="+encodeURIComponent(site)+
        "&company_id="+encodeURIComponent(companyId));
      setSource(loaded);
      current.current=null;
      resetPreview();
      setNotice("Datos documentales actualizados desde GALANT. La siguiente vista previa será recalculada.");
    }catch(e){setError(friendly(e));}
    finally{setBusy(false);}
  }
  async function loadHistory(){
    setHistoryLoading(true);setError("");
    try{
      setHistory(await request<{issues:{id:string;code:string;issued_at:string}[];
        legacy_issues:{id:string;code:string;issued_at:string}[]}>(base+"/history"));
    }catch(e){setError(friendly(e));}
    finally{setHistoryLoading(false);}
  }
  function changeDocument(value:string){
    setCode(value);setSelectedCodes([value]);setShowExtras(false);
    if(value==="sworn_declaration"){setPersonToken("");setPersonId("");}
  }
  function toggleDocument(value:string,checked:boolean){
    setSelectedCodes(old=>{
      if(value==="sworn_declaration")return checked?["sworn_declaration"]:[];
      const others=old.filter(code=>code!=="sworn_declaration");
      return checked?[...new Set([...others,value])]:others.filter(code=>code!==value);
    });
    if(checked)setCode(value);
  }
  async function prepare():Promise<Dossier|null>{
    if(!ready){setError("Completa empresa, trabajador, cargo cuando corresponda y selecciona un documento.");return null;}
    if(!library?.documents.some(item=>item.code===code&&item.ready)){
      setError("La plantilla Excel original no está habilitada. Revísala en Administración de plantillas.");return null;
    }
    if(current.current?.signature===signature)return current.current.dossier;
    const shared=deep({...extras,role,"event.date":date});
    const dossier=await request<Dossier>(base+"/dossiers",{
      method:"POST",body:JSON.stringify({
        site_id:site,company_id:companyId,person_id:workerless?null:personId,
        relationship:"contractor",parent_name:null,selected_codes:selectedCodes,
        shared,document_data:Object.fromEntries(selectedCodes.map(selected=>[
          selected,selected==="sworn_declaration"?{verified_no_workers:verifiedNoWorkers}:{}
        ])),
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
  async function verifyDocuments(){
    if(busy)return;
    setBusy(true);setError("");setNotice("");
    try{
      const dossier=await prepare();
      if(!dossier)return;
      const result=await request<{documents:DocumentStatus[]}>(base+"/dossiers/"+
        encodeURIComponent(dossier.id)+"/eligibility");
      setVerified(result.documents);
      const unavailable=result.documents.filter(item=>!item.can_issue);
      setReasons(unavailable.map(item=>
        (LABELS[item.code]||item.code)+": "+(item.reason||"Completa la ficha")));
      setMissing([...new Set(unavailable.flatMap(item=>item.missing_fields||[]))
        ].filter(key=>!["worker.name","worker.rut","employer.name","employer.rut","site.name"].includes(key)));
      if(unavailable.length)setShowExtras(true);
      setNotice(unavailable.length?
        "Ficha guardada. Revisa los campos indicados en los documentos pendientes.":
        "Ficha guardada. Los documentos seleccionados están listos para generar.");
    }catch(e){setError(friendly(e));}
    finally{setBusy(false);}
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
          method:"POST",body:JSON.stringify({dossier_id:dossier.id,codes:selectedCodes})
        });
        if(!result.issued){
          throw new Error(result.results.map(item=>item.reason).filter(Boolean).join(" · ")
            ||"No se pudo emitir ninguno de los documentos.");
        }
        const first=result.results.find(item=>item.ok&&item.id);
        setIssued(result.pdf_url||"/api/v1/javiera/v166/issues/"+
          encodeURIComponent(first?.id||"")+"/pdf");
        const failures=result.results.filter(item=>!item.ok);
        if(failures.length)setReasons(failures.map(item=>
          (LABELS[item.code]||item.code)+": "+(item.reason||"Documento pendiente")));
        setNotice(result.issued+" documento(s) generados y guardados en el historial privado."
          +(failures.length?" Otros "+failures.length+" no se pudieron generar; revisa sus errores.":""));
      }
    }catch(e){setError(friendly(e));}
    finally{setBusy(false);}
  }
  const fieldKeys=[...new Set(selectedCodes.flatMap(item=>FIELDS[item]||[]))];
  const auto=new Set(["role","event.date","worker.name","worker.rut","employer.name","employer.rut","site.name"]);
  const requiredCatalog=[...new Set(selectedCodes.flatMap(item=>
    catalog.find(x=>x.code===item)?.required_fields||[]))];
  const extraFields=[...new Set([...fieldKeys,...requiredCatalog,...missing])]
    .filter(x=>!auto.has(x)&&x.includes("."));
  if(!mode)return <section className="jv-module" aria-label="Proyecto Javiera">
    <div className="jv-hero">
      <small>AUTOMATIZACIÓN DOCUMENTAL · GALANT</small>
      <h2>Proyecto JAVIERA</h2>
      <p>Una sola ficha para documentos laborales y prevención de riesgos. Primero indica si el contratista es nuevo o existente.</p>
    </div>
    {error&&<p role="alert" className="jv-error"><ShieldAlert size={16}/>{error}</p>}
    <div className="jv-mode-cards" aria-label="Tipo de contratista">
      <button type="button" disabled={busy} onClick={()=>chooseMode("new")}>
        <FolderOpen size={28}/>
        <strong>Contratista nuevo</strong>
        <span>Ingresa la empresa y el trabajador para preparar su documentación. No los registra en el módulo operativo de GALANT.</span>
      </button>
      <button type="button" disabled={busy} onClick={()=>chooseMode("existing")}>
        <ClipboardList size={28}/>
        <strong>Contratista existente</strong>
        <span>Elige una empresa registrada y recupera los datos anteriores de sus trabajadores y documentos.</span>
      </button>
    </div>
    {onConfig&&<button type="button" className="jv-inline-action" onClick={onConfig}>
      <Settings2 size={16}/> Editar Excel maestro y plantillas
    </button>}
    {onBack&&<button type="button" className="jv-back" onClick={onBack}><ArrowLeft size={16}/> Volver a GALANT</button>}
    <p className="jv-note">Los documentos preparados aquí no crean contratistas ni asignaciones operativas. La impresión no acredita firmas o entregas reales.</p>
  </section>;
  const selectedCatalog=catalog.filter(item=>selectedCodes.includes(item.code));
  const verifiedReady=verified.filter(item=>item.can_issue).length;
  return <section className="jv-module" aria-label="Proyecto Javiera">
    <div className="jv-hero" style={{display:"grid",gridTemplateColumns:"minmax(0,1fr)",gridAutoFlow:"row",justifyItems:"start",alignContent:"start",rowGap:9}}>
      <div className="jv-hero-back-row">
        <button className="jv-back" type="button" disabled={busy} onClick={()=>chooseMode(mode==="new"?"new":"existing")}>
          <ArrowLeft size={17}/> {mode==="new"?"Contratista nuevo":"Contratista existente"}
        </button>
        <button className="jv-back" type="button" disabled={busy} onClick={()=>{
          generation.current+=1;setMode(null);setSite("");setCompanyId("");setPersonId("");
          setCompanyToken("");setPersonToken("");setExtras({});current.current=null;resetPreview();
        }}><ArrowLeft size={17}/> Proyecto JAVIERA</button>
      </div>
      <small>{mode==="new"?"CONTRATISTA NUEVO":"CONTRATISTA EXISTENTE"} · EXPEDIENTE</small>
      {onConfig&&<button type="button" disabled={busy} className="jv-back" onClick={onConfig}>
        <Settings2 size={16}/> Editar Excel maestro y plantillas
      </button>}
      <h2>Generación documental interactiva</h2>
      <p>Gestiona contratos, anexos, declaraciones, IRL, PTS, EPP, reglamento e inducción desde una misma ficha.</p>
    </div>
    {error&&<p role="alert" className="jv-error"><ShieldAlert size={16}/>{error}</p>}
    {!error&&notice&&<p role="status" className="jv-success"><CheckCircle2 size={16}/>{notice}</p>}
    {booting?<div className="jv-document-picker" role="status"><Loader2 size={18} className="jsm-spin"/> Cargando obras y plantillas…</div>:<>
      <section className="jv-document-picker" aria-label="Seleccionar documentos">
        <div className="jv-picker-heading">
          <div><small>PASO 1 · DOCUMENTOS</small><h3>¿Qué necesitas generar?</h3>
            <p>Marca uno o varios documentos. La ficha pedirá únicamente los datos correspondientes.</p>
          </div>
          <label>Buscar documento
            <input aria-label="Buscar documento" type="search" value={documentSearch}
              placeholder="IRL, EPP, contrato…" onChange={e=>setDocumentSearch(e.target.value)}/>
          </label>
        </div>
        <fieldset disabled={busy} className="jv-flow">
          <div className="jv-picker-actions">
            <button type="button" onClick={()=>{setSelectedCodes(ORDER.filter(x=>x!=="sworn_declaration"));setCode("irl");}}>
              Seleccionar todos</button>
            <button type="button" onClick={()=>{setSelectedCodes(["irl","pts","pts_receipt","ppe_delivery","induction"]);setCode("irl");}}>
              Solo prevención</button>
            <button type="button" onClick={()=>{setSelectedCodes(ORDER.filter(x=>!["sworn_declaration","irl","pts","pts_receipt","ppe_delivery","induction"].includes(x)));setCode("labor_contract");}}>
              Solo laborales</button>
            <button type="button" onClick={()=>setSelectedCodes([])}>Limpiar selección</button>
            <strong>{selectedCodes.length} seleccionados</strong>
          </div>
          <div className="jv-picker-grid">
            {catalog.filter(item=>(item.title+" "+item.code).toLocaleLowerCase("es").includes(documentSearch.toLocaleLowerCase("es")))
              .map(item=><label key={item.code} className={"jv-picker-card "+(selectedCodes.includes(item.code)?"chosen":"")}>
                <input type="checkbox" checked={selectedCodes.includes(item.code)}
                  onChange={e=>toggleDocument(item.code,e.target.checked)}/>
                <span><b>{item.title}</b><small>{item.area||"Documento"}</small></span>
              </label>)}
          </div>
          {!catalog.length&&<p className="jv-hint" role="status">No se pudieron cargar los documentos disponibles.</p>}
        </fieldset>
      </section>
      <div className="jv-workspace">
        <div className="jv-form">
          <fieldset disabled={busy} className="jv-flow">
            <div className="jv-section">
              <h3>Paso 2 · Empresa y trabajador</h3>
              <label>Obra
                <select aria-label="Obra" value={site} onChange={e=>void changeSite(e.target.value)}>
                  <option value="">Selecciona una obra</option>
                  {source.sites.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              {mode==="new"?(
                !companyId?<div className="jv-new-form">
                  <p>Completa la empresa para generar sus documentos. Este registro es exclusivo de Proyecto Javiera.</p>
                  <label>Razón social
                    <input required value={newCompany.name} placeholder="Nombre completo de la empresa"
                      onChange={e=>setNewCompany(old=>({...old,name:e.target.value}))}/>
                  </label>
                  <label>RUT de empresa
                    <input required value={newCompany.rut} placeholder="12.345.678-9"
                      onChange={e=>setNewCompany(old=>({...old,rut:e.target.value}))}/>
                  </label>
                  <button type="button" disabled={!site||!newCompany.name.trim()||!newCompany.rut.trim()}
                    onClick={()=>void createCompany()}>Guardar y continuar</button>
                  {!site&&<p role="status">Selecciona primero una obra.</p>}
                </div>:<div className="jv-new-form jv-company-confirmed" role="status">
                  <strong><CheckCircle2 size={16}/> Empresa registrada solo en Proyecto Javiera</strong>
                  <span>{selectedCompany?.name||"Empresa guardada"} · {selectedCompany?.rut||""}</span>
                  <p>Continúa con el trabajador. No necesitas crear la empresa en GALANT operativo.</p>
                </div>
              ):<>
                <label>Buscar empresa
                  <input aria-label="Buscar empresa" type="search" placeholder="Razón social o RUT"
                    value={filter} onChange={e=>setFilter(e.target.value)} disabled={!site}/>
                </label>
                <label>Empresa registrada
                  <select aria-label="Empresa registrada" value={companyToken} disabled={!site}
                    onChange={e=>void changeCompany(e.target.value)}>
                    <option value="">Selecciona una empresa de esta obra</option>
                    {companies.map(item=><option value={token(item)} key={token(item)}>
                      {item.name}{item.rut?" · "+item.rut:""}
                    </option>)}
                  </select>
                </label>
                {selectedCompany&&companyId&&<div className="jv-new-form jv-company-confirmed">
                  <strong><CheckCircle2 size={16}/> Datos de la empresa recuperados</strong>
                  <span>{selectedCompany.name} · {selectedCompany.rut||"RUT pendiente"}</span>
                </div>}
              </>}
              {companyId&&!workerless&&<>
                <label>Trabajador
                  <select aria-label="Trabajador" value={personToken} onChange={e=>void changePerson(e.target.value)}>
                    <option value="">Selecciona un trabajador de esta empresa</option>
                    {people.map(item=><option key={token(item)} value={token(item)}>
                      {item.name}{item.rut?" · "+item.rut:""}</option>)}
                  </select>
                </label>
                <button type="button" className="jv-inline-action"
                  onClick={()=>setShowNewPerson(old=>!old)}>
                  {showNewPerson?"Cerrar registro de trabajador":"+ Registrar trabajador nuevo"}
                </button>
                {showNewPerson&&<div className="jv-new-form">
                  <label>Nombre del trabajador
                    <input value={newPerson.name} placeholder="Nombre completo"
                      onChange={e=>setNewPerson(old=>({...old,name:e.target.value}))}/>
                  </label>
                  <label>RUT del trabajador
                    <input value={newPerson.rut} placeholder="12.345.678-9"
                      onChange={e=>setNewPerson(old=>({...old,rut:e.target.value}))}/>
                  </label>
                  <button type="button" disabled={!newPerson.name.trim()||!newPerson.rut.trim()}
                    onClick={()=>void createPerson()}>Guardar trabajador</button>
                </div>}
                <p className="jv-hint">{selectedPerson?"Trabajador: "+selectedPerson.name+" · "+(selectedPerson.rut||"RUT pendiente"):
                  "Selecciona o registra al trabajador. No se crean asignaciones en GALANT operativo."}</p>
              </>}
              {companyId&&workerless&&<p className="jv-hint">La declaración jurada se prepara a nivel de empresa, sin seleccionar trabajador.</p>}
              {companyId&&(selectedCompany?.source_contractor_id||selectedCompany?.origin==="operational")&&
                <button type="button" className="jv-inline-action" onClick={()=>void refreshIdentity("company")}>
                  Actualizar empresa desde GALANT</button>}
              {personId&&(selectedPerson?.source_worker_id||selectedPerson?.origin==="operational")&&
                <button type="button" className="jv-inline-action" onClick={()=>void refreshIdentity("person")}>
                  Actualizar trabajador desde GALANT</button>}
              {companyId&&!workerless&&<label>Cargo o especialidad
                <input aria-label="Cargo o especialidad" list="javiera-cargos" value={role}
                  onChange={e=>setRole(e.target.value)} placeholder="Ej. TECHUMBRE"/>
                <datalist id="javiera-cargos">
                  <option value="TECHUMBRE"/>
                  {roles.map(item=><option value={item} key={item}/>)}
                </datalist>
              </label>}
              <p className="jv-hint">El expediente utiliza los documentos seleccionados. No exige vínculo laboral ni motivo adicional.</p>
            </div>
            <div className="jv-section">
              <h3>Datos de prevención y constancias</h3>
              <p>Una fecha rellenada no reemplaza una firma, capacitación o entrega real.</p>
              <label>Fecha efectiva del evento
                <input aria-label="Fecha efectiva del evento" type="date" value={date}
                  onChange={e=>setDate(e.target.value)}/>
              </label>
              {workerless&&<label className="jv-check-line">
                <input type="checkbox" checked={verifiedNoWorkers}
                  onChange={e=>setVerifiedNoWorkers(e.target.checked)}/>
                Confirmo que la empresa no tiene trabajadores en el período declarado
              </label>}
            </div>
            {extraFields.length>0&&<div className="jv-section">
              <h3>Antecedentes de los documentos</h3>
              <p>Los antecedentes recuperados aparecen completados y puedes corregirlos aquí.</p>
              <div className="jv-paired">
              {extraFields.map(key=>{
                if(key==="event.epp_items")return <div key={key} className="jv-epp-editor">
                  <h4>EPP efectivamente entregados</h4>
                  {eppDraft.invalid.length>0&&<p className="jv-error">
                    Corrige el registro anterior: {eppDraft.invalid.join("; ")}
                    <button type="button" onClick={()=>setExtras(old=>({...old,"event.epp_items":""}))}>
                      Limpiar registro incorrecto</button>
                  </p>}
                  {eppOptions.map((item,i)=><label key={item.name}>
                    {item.name}
                    <input aria-label={"Cantidad de "+item.name} type="number" min={0}
                      max={item.max_quantity} step={1}
                      value={eppDraft.quantities[i]||0} disabled={!!eppDraft.invalid.length}
                      onChange={e=>{
                        const value=Number(e.target.value);
                        if(!Number.isInteger(value)||value<0||value>item.max_quantity)return;
                        const values=[...eppDraft.quantities];values[i]=value;
                        setExtras(old=>({...old,"event.epp_items":serializeEppDraft(eppOptions,values)}));
                      }}/>
                  </label>)}
                </div>;
                const meta=FIELDMETA[key];
                return <label key={key}>{meta?.label||key.replaceAll("."," · ")}
                  <input aria-invalid={missing.includes(key)&&!extras[key]}
                    type={meta?.type==="date"?"date":meta?.type==="number"?"number":"text"}
                    placeholder={missing.includes(key)?"Dato requerido para generar":""}
                    value={extras[key]||""}
                    onChange={e=>setExtras(old=>({...old,[key]:e.target.value}))}/>
                </label>;
              })}
              </div>
            </div>}
            {reasons.length>0&&<div className="jv-section" role="alert">
              <h3>Datos pendientes por corregir</h3>
              {reasons.map((reason,i)=><p className="jv-error" key={i}>{reason}</p>)}
            </div>}
            <div className="jv-actions">
              <button type="button" className="jv-primary" disabled={!ready||busy}
                onClick={()=>void verifyDocuments()}>
                {busy?"Comprobando…":"Guardar ficha y verificar"}
              </button>
              <span>{selectedCompany?.name||"Empresa pendiente"} · {selectedPerson?.name||"Sin trabajador seleccionado"}</span>
            </div>
          </fieldset>
        </div>
        <aside className="jv-document-panel" aria-label="Documentos que puedes exportar a PDF">
          <div className="jv-panel-head">
            <small>DOCUMENTOS SELECCIONADOS</small>
            <h3>Preparar y generar PDF</h3>
            <p>{!companyId?"Primero registra o selecciona la empresa":
              !personId&&!workerless?"Selecciona o registra el trabajador":
              "Guarda y verifica la ficha para conocer los datos pendientes."}</p>
          </div>
          {verified.length>0&&<div className="jv-validation-panel" role="status">
            <strong>{verifiedReady} de {selectedCodes.length} documentos listos</strong>
            <p>{verifiedReady===selectedCodes.length?"Puedes generar los documentos seleccionados.":
              "Revisa los campos que se indican en cada documento."}</p>
          </div>}
          <button type="button" className="jv-primary jv-batch"
            disabled={!ready||busy||selectedCodes.length===0}
            onClick={()=>void run("issue")}>
            {busy?"Generando…":"Generar documentos listos"} ({verifiedReady})
          </button>
          {!verified.length&&selectedCodes.length>0&&<p className="jv-hint">
            Guarda y verifica la ficha para actualizar la disponibilidad de cada PDF.
          </p>}
          {!selectedCodes.length&&<p className="jv-hint">Selecciona al menos un documento en el paso 1.</p>}
          <div className="jv-doc-groups">
            {selectedCatalog.map(item=>{
              const state=verified.find(x=>x.code===item.code);
              const errors=[...(state?.blocking_errors||[]),...(state?.missing_fields||[])];
              const downloadable=state?.can_issue===true&&item.code===code;
              return <div className="jv-doc-card" key={item.code}>
                <div className="jv-doc-title">
                  <input type="checkbox" aria-label={"Seleccionar "+item.title}
                    checked={selectedCodes.includes(item.code)}
                    onChange={e=>toggleDocument(item.code,e.target.checked)}/>
                  <FileText size={16}/><b>{item.title}</b>
                </div>
                <p>{item.area||"Documento"}</p>
                <p className={state?.can_issue?"jv-card-ready":"jv-hint"}>
                  {state?(state.can_issue?"Listo para PDF":"Faltan datos"):
                    "Pendiente de verificación"}</p>
                {state&&!state.can_issue&&<div className="jv-card-problem" role="alert">
                  <strong>Completar información</strong>
                  <p>{state.reason||"Falta información para generar este documento."}</p>
                  {errors.slice(0,5).map((reason,i)=><p key={i}>{reason}</p>)}
                </div>}
                <div className="jv-actions jv-card-actions">
                  <button type="button" onClick={()=>setCode(item.code)}>
                    {code===item.code?"Documento seleccionado":"Ver este documento"}
                  </button>
                  {downloadable&&<button type="button" onClick={()=>void run("preview")}>
                    <Eye size={14}/> Vista previa</button>}
                </div>
              </div>;
            })}
          </div>
          <p className="jv-note">Los documentos anteriores conservan su historial. Generar no equivale a firma o recepción real.</p>
          <details className="jsm-extras">
            <summary>Historial de documentos emitidos</summary>
            <button type="button" disabled={historyLoading} onClick={()=>void loadHistory()}>
              {historyLoading?"Consultando…":"Consultar historial"}
            </button>
            {history&&<div className="jsm-history">
              {[...history.legacy_issues.map(item=>({...item,legacy:true})),
                ...history.issues.map(item=>({...item,legacy:false}))].map(item=><p key={item.id}>
                {LABELS[item.code]||item.code} · {item.issued_at.slice(0,10)} ·
                <a target="_blank" rel="noreferrer" href={(item.legacy?
                  "/api/v1/javiera/issued/":"/api/v1/javiera/v166/issues/")+
                  encodeURIComponent(item.id)+"/pdf"}> Abrir PDF</a>
              </p>)}
              {!history.legacy_issues.length&&!history.issues.length&&<p>No existen documentos emitidos.</p>}
            </div>}
          </details>
        </aside>
      </div>
      {preview&&<section className="jsm-preview" aria-label="Vista previa del PDF">
        <header><div><strong>Vista previa PDF</strong><small>{Math.round(preview.elapsedMs)} ms en esta solicitud</small></div>
          <a href={preview.url} target="_blank" rel="noreferrer">Abrir PDF</a></header>
        <iframe title="Documento PDF Proyecto Javiera" src={preview.url} loading="eager"/>
      </section>}
      {issued&&<div className="jsm-issued" role="status">
        <CheckCircle2 size={19}/>
        <a target="_blank" rel="noreferrer" href={issued}>Abrir PDF generado</a>
        <small>Documento guardado en el historial privado.</small>
      </div>}
    </>}
  </section>;
}
