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

