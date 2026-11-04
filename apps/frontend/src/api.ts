export type Profile = {id:string;org_id:string;email:string;role:string}
export type Dashboard = {total:number;finished:number;queued:number;accredited:number;review:number;errors:number}
export type PaymentControl = {page:number;period:string|null;negative:boolean;receipt:boolean;paid_state:boolean;transaction:boolean;evidence_sufficient:boolean;reasons:string[]}
export type Evidence = {pagina:number;motor:string;confianza_ocr:number|null;extracto:string;palabras:Array<{texto:string;bbox:number[];confianza:number|null}>;control_pago:PaymentControl}
export type DocumentView = {
  id:string;original_name:string;declared_type:string;detected_type:string|null;
  status:"queued"|"processing"|"complete"|"error";payment_status:string|null;
  page_count:number;extracted:{periodo?:string|null;ruts_validos?:string[];verificacion_externa?:boolean;controles_por_pagina?:PaymentControl[];ocr_reutilizado?:boolean;tiempo_ocr_s?:number;tiempo_procesamiento_s?:number;progreso?:{procesadas:number;total:number|null}};
  evidence:Evidence[];warnings:string[];error:string|null;created_at:string;updated_at:string;
}
export type DocumentSummary = Pick<DocumentView,"id"|"original_name"|"declared_type"|"detected_type"|"status"|"payment_status"|"created_at">
const base="/api/v1"
const csrf=()=>document.cookie.split("; ").find(item=>item.startsWith("galant_post_csrf="))?.split("=")[1] || ""

export async function request<T>(url:string,options:RequestInit={}):Promise<T> {
  const headers=new Headers(options.headers)
  const method=(options.method||"GET").toUpperCase()
  if(options.body && !(options.body instanceof FormData))headers.set("Content-Type","application/json")
  if(method!=="GET"&&method!=="HEAD") headers.set("X-CSRF-Token",csrf())
  const response=await fetch(base+url,{...options,headers,credentials:"include",cache:"no-store"})
  if(!response.ok){
    if(response.status===401)window.dispatchEvent(new Event("galant-session-ended"))
    let message="Error HTTP "+response.status
    try {
      const data=await response.json()
      const detail=data.detail
      if(typeof detail==="string")message=detail
      else if(Array.isArray(detail))message=detail.map((item:{loc?:Array<string|number>;msg?:string})=>`${item.loc?.join(".")||"Datos"}: ${item.msg||"inválidos"}`).join("; ")
      else if(detail&&typeof detail==="object"){
        if(Array.isArray(detail.rows))message="Filas inválidas: "+detail.rows.map((row:{row_id?:string;errors?:string[]})=>`${row.row_id||"fila"}: ${(row.errors||[]).join(", ")}`).join("; ")
        else if(typeof detail.error==="string")message=(detail.row_id?detail.row_id+": ":"")+detail.error
      }
    }catch{}
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
export const api={
  version:()=>request<{version:string;commit:string}>("/version"),
  login:(email:string,password:string)=>request<Profile>("/auth/login",{method:"POST",body:JSON.stringify({email,password})}),
  me:()=>request<Profile>("/auth/me"),
  logout:()=>request<{ok:boolean}>("/auth/logout",{method:"POST"}),
  dashboard:()=>request<Dashboard>("/dashboard"),
  list:(category?:string)=>request<DocumentSummary[]>("/documents"+(category?"?category="+encodeURIComponent(category):"")),
  get:(id:string)=>request<DocumentView>("/documents/"+encodeURIComponent(id)),
  upload:(file:File,category:string)=>{
    const data=new FormData()
    data.append("file",file)
    data.append("category",category)
    return request<DocumentView>("/documents",{method:"POST",body:data})
  },
  retry:(id:string)=>request<DocumentView>("/documents/"+encodeURIComponent(id)+"/retry",{method:"POST"}),
  pdf:(id:string)=>base+"/documents/"+encodeURIComponent(id)+"/file",
  excel:(id:string)=>base+"/documents/"+encodeURIComponent(id)+"/report",
  extraction:(id:string)=>base+"/documents/"+encodeURIComponent(id)+"/extraction"
}
