export const emptyContract={start:"",end:"",new_end:"",salary:"",hours:"",transfer_date:"",declaration_reason:"",regulation_version:""};
export const emptyEvent={date:"",epp_items:"",pts_version:""};
/** Compare editable facts without relying on JSON/DB key order. */
export function stableFingerprint(value:unknown):string{
 if(Array.isArray(value))return "["+value.map(stableFingerprint).join(",")+"]";
 if(value!==null&&typeof value==="object")return "{"+Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,v])=>JSON.stringify(key)+":"+stableFingerprint(v)).join(",")+"}";
 return JSON.stringify(value)??"null";
}
export function dossierFields(data:Record<string,unknown>){
 const record=(x:unknown):Record<string,unknown>=>x!==null&&typeof x==="object"&&!Array.isArray(x)?x as Record<string,unknown>:{};
 const stringFields=<T extends Record<string,string>>(base:T,x:unknown):T=>Object.fromEntries(Object.keys(base).map(key=>[key,String(record(x)[key]??base[key])])) as T;
 return {role:String(data.role||""),event_type:String(data.event_type||"ingreso"),employment_type:String(data.employment_type||""),contract:stringFields(emptyContract,data.contract),event:stringFields(emptyEvent,data.event),extra:Object.fromEntries(Object.entries(record(data.extra)).map(([k,v])=>[k,String(v??"")]))};
}
