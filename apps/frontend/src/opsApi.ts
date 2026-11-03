import {request} from "./api"

export type Site = {id:string;name:string;initial_period:string}
export type Contractor = {
  id:string;site_id:string;contractor_id:string;name:string;rut:string|null;historical_code:string|null;
  nature:string;frequency:string;contract_status:string;worker_count:number
}
export type Worker = {
  id:string;site_id:string;worker_id:string;contractor_id:string;name:string;rut:string|null;active:boolean
}
export type ContractorInput = {
  site_id:string;name:string;rut:string|null;historical_code:string|null;
  nature:string;frequency:string;contract_status:string
}
export type WorkerInput = {site_id:string;contractor_id:string;name:string;rut:string|null}
export type ImportRow = {
  row_id:string;sheet:string;row_number:number;kind:string;name:string;rut:string;
  contractor_rut:string;historical_code:string;
  nature:string;frequency:string;contract_status:string;
  historical_statuses:Record<string,string>;errors:string[];warnings:string[]
}
export type ImportPreview = {
  rows:ImportRow[];summary:{contractors:number;workers:number;errors:number;warnings:number;historical_marks?:Record<string,number>};
  detected_columns:Record<string,Record<string,string>>;source_format:string;site_id:string;preview_token:string
}
export type ImportResult = {
  created_contractors:number;linked_contractors:number;created_workers:number;
  assigned_workers:number;skipped:number;historical_statuses_count:number;
  imported_rows:Array<{row_id:string;result:string;entity_id:string}>
}
export type OpsChange = {id:string;entity_type:string;entity_id:string;user_id:string;changes:Record<string,unknown>;created_at:string}

export const opsApi = {
  sites:()=>request<Site[]>("/ops/sites"),
  contractors:(siteId:string)=>request<Contractor[]>("/ops/contractors?site_id="+encodeURIComponent(siteId)),
  createContractor:(data:ContractorInput)=>request<Contractor>("/ops/contractors",{method:"POST",body:JSON.stringify(data)}),
  updateContractor:(id:string,data:Partial<Omit<ContractorInput,"site_id">>)=>request<Contractor>("/ops/contractors/"+encodeURIComponent(id),{method:"PATCH",body:JSON.stringify(data)}),
  workers:(siteId:string,contractorId:string)=>request<Worker[]>("/ops/workers?site_id="+encodeURIComponent(siteId)+"&contractor_id="+encodeURIComponent(contractorId)),
  createWorker:(data:WorkerInput)=>request<Worker>("/ops/workers",{method:"POST",body:JSON.stringify(data)}),
  updateWorker:(id:string,data:Partial<Omit<WorkerInput,"site_id"|"contractor_id">>&{active?:boolean})=>request<Worker>("/ops/workers/"+encodeURIComponent(id),{method:"PATCH",body:JSON.stringify(data)}),
  history:(entityType:string,entityId:string)=>request<OpsChange[]>("/ops/history?entity_type="+encodeURIComponent(entityType)+"&entity_id="+encodeURIComponent(entityId)),
  previewImport:(file:File,siteId:string,columnMap:Record<string,string>={})=>{
    const form=new FormData();form.append("file",file);form.append("site_id",siteId)
    if(Object.keys(columnMap).length)form.append("column_map",JSON.stringify(columnMap))
    return request<ImportPreview>("/ops/imports/preview",{method:"POST",body:form})
  },
  commitImport:(siteId:string,rows:ImportRow[],historicalStatusMapping:Record<string,string>,preview:ImportPreview)=>
    request<ImportResult>("/ops/imports/commit",{method:"POST",body:JSON.stringify({site_id:siteId,rows,historical_status_mapping:historicalStatusMapping,source_format:preview.source_format,preview_token:preview.preview_token})})
}
