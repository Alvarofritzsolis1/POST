import {request} from "./api"

export type Requirement = {
  kind:string;applicable:boolean|null;state:string;source:string|null;
  document_id:string|null;reviewed_by:string|null;reviewed_at:string|null;
  notes:string;request_date:string|null;due_date:string|null;
  name?:string;rule_source?:string;rule_id?:string|null;subject?:string;
  required?:boolean;reviewed_name?:string|null;subjects?:number;worker_level?:boolean;
  required_count?:number;approved_count?:number
}
export type MatrixCompany = {
  association_id:string;contractor_id:string;name:string;rut:string|null;
  code:string;nature:string;frequency:string;status:string;requirements:Requirement[]
}
export type Matrix = {
  site_id:string;period:string;contractors:MatrixCompany[];
  summary:{applicable:number;approved:number;reviewed:number;compliance:number|null;progress:number|null}
}
export type Overview = {
  period:string;site_id:string|null;
  sites:Array<{site_id:string;site:string;contractors:number;workers:number;
    applicable:number;approved:number;reviewed:number;compliance:number|null;progress:number|null}>;
  totals:{ct:number;ci:number;sporadic:number;active:number;workers:number;
    without_movements:number;unique_companies:number;associations:number;unverified_payments:number;
    days_missing:number;retention_proposed:string;expiring_contracts:number;open_tasks:number;offboarding_open:number};
  applicable:number;approved:number;reviewed:number;compliance:number|null;progress:number|null
}
export type Contribution = {
 id:string;association_id:string;site_id:string;contractor:string;contractor_rut:string|null;code:string;
 period:string;subject_key:string;worker_assignment_id:string|null;worker:string|null;
 attendance_days:number|null;required_days:number|null;paid_days:number|null;payment_confirmed:boolean;
 daily_rate:string;missing_days:number|null;retention_suggested:string|null;
 retention_status:string;review_status:string;justification:string;notes:string;reviewer_id:string|null;
 updated_by:string;updated_at:string
}
export type ContributionInput = {
 association_id:string;period:string;worker_assignment_id:string|null;
 attendance_days:number|null;required_days:number|null;paid_days:number|null;
 payment_confirmed:boolean;daily_rate:number;justification:string;notes:string;
 review_status:"pending"|"approved"|"observed";retention_status:"none"|"proposed"|"justified"|"confirmed"|"resolved"
}
export type WorkTask = {
 id:string;worksite_id:string;association_id:string|null;period:string|null;title:string;kind:string;
 priority:string;status:string;due_date:string|null;assigned_to:string|null;notes:string;updated_at:string
}
export type Contract = {id:string;association_id:string;worker_assignment_id:string|null;contract_type:string;
 start_date:string;end_date:string|null;status:string;notes:string;days_until_expiry?:number|null;expiry_alert?:string|null}
export type CalendarEntry = {id:string;worksite_id:string;period:string;kind:string;
 request_date:string;due_date:string;alert_date:string|null}
export type Activity = {id:string;association_id:string;period:string;status:string;reason:string;changed_by:string}
export type Alert = {kind:string;priority:string;association_id:string|null;date:string|null;
 message:string;reference_id:string}
export type OperationalAnalytics = {
  period:string;worksites:Array<{
    site_id:string;site:string;
    distribution:Record<string,number>;document_states:Record<string,number>;
    contract_expiry:Record<string,number>;
    missing_days:number;retention_suggested:string;unverified_payments:number;open_tasks:number
  }>;
  distribution:Record<string,number>;document_states:Record<string,number>;
  contract_expiry:Record<string,number>;
  missing_days:number;retention_suggested:string
}
export type HistoricalTrend = {
  until:string;months:number;sites:Array<{id:string;name:string}>;
  series:Array<{period:string;applicable:number;approved:number;reviewed:number;pending:number;
    compliance:number|null;progress:number|null;retention_suggested:string;
    missing_days:number;unverified_payments:number;
    site_summaries:Array<{site_id:string;site:string;applicable:number;approved:number;
      reviewed:number;compliance:number|null;progress:number|null;pending:number}>}>
}
export type ContractImportRow = {
  row_id:string;kind:string;source_sheet:string;source_row:number;
  contractor_rut:string;worker_rut:string;contract_type:string;
  start_date:string|null;end_date:string|null;amendment_date:string|null;
  reference:string;status:string;notes:string;errors:string[]
}
export type ContractImportPreview = {
  rows:ContractImportRow[];
  detected_columns:Record<string,Record<string,string>>;
  summary:{total:number;contracts:number;amendments:number;errors:number};
  preview_token:string;site_id:string
}
const q=(data:Record<string,string|null|undefined>)=>{
 const p=new URLSearchParams()
 Object.entries(data).forEach(([key,value])=>{if(value)p.set(key,value)})
 return "?"+p.toString()
}
const ROOT="/control"
export const opsControlApi={
 analytics:(period:string,site_id:string|null)=>request<OperationalAnalytics>(ROOT+"/reports/analytics"+q({period,site_id})),
 trends:(period:string,site_id:string|null,months=12)=>request<HistoricalTrend>(ROOT+"/reports/trends"+q({period,site_id,months:String(months)})),
 previewContracts:(file:File,site_id:string)=>{
   const form=new FormData()
   form.append("file",file);form.append("site_id",site_id)
   return request<ContractImportPreview>(ROOT+"/import/contracts/preview",{method:"POST",body:form})
 },
 commitContracts:(site_id:string,rows:ContractImportRow[],preview_token:string)=>request<{created:number;amendments:number;unchanged:number}>(ROOT+"/import/contracts/commit",{method:"POST",body:JSON.stringify({site_id,rows,preview_token})}),
 contractTemplate:()=>"/api/v1"+ROOT+"/import/contracts/template",
 overview:(period:string,site_id:string|null)=>request<Overview>(ROOT+"/reports/overview"+q({period,site_id})),
 matrix:(site_id:string,period:string)=>request<Matrix>(ROOT+"/matrix"+q({site_id,period})),
 reviews:(data:{association_id:string;period:string;kind:string;status:string;notes:string;subject?:string})=>
   request<{id:string;status:string;source:string}>(ROOT+"/reviews",{method:"POST",body:JSON.stringify(data)}),
 bulk:(reviews:Array<{association_id:string;period:string;kind:string;status:string;notes:string;subject?:string}>)=>
   request<{updated:number}>(ROOT+"/reviews/bulk",{method:"POST",body:JSON.stringify({reviews})}),
 applicability:(data:{association_id:string;period:string;kind:string;applicable:boolean;justification:string})=>
   request<{id:string}>(ROOT+"/applicability",{method:"PUT",body:JSON.stringify(data)}),
 contributions:(period:string,site_id:string|null)=>request<Contribution[]>(ROOT+"/contributions"+q({period,site_id})),
 saveContribution:(data:ContributionInput)=>request<Contribution>(ROOT+"/contributions",{method:"PUT",body:JSON.stringify(data)}),
 activity:(site_id:string,period:string)=>request<Activity[]>(ROOT+"/activity"+q({site_id,period})),
 saveActivity:(data:{association_id:string;period:string;status:string;reason:string})=>
   request<Activity>(ROOT+"/activity",{method:"PUT",body:JSON.stringify(data)}),
 tasks:(site_id:string|null,status?:string)=>request<WorkTask[]>(ROOT+"/admin/tasks"+q({site_id,status})),
 createTask:(data:{worksite_id:string;association_id:string|null;period:string|null;title:string;kind:string;priority:string;notes:string})=>
   request<WorkTask>(ROOT+"/admin/tasks",{method:"POST",body:JSON.stringify(data)}),
 updateTask:(id:string,data:{status:string;notes:string;assigned_to:string|null})=>
   request<WorkTask>(ROOT+"/admin/tasks/"+encodeURIComponent(id),{method:"PATCH",body:JSON.stringify(data)}),
 contracts:(site_id:string|null)=>request<Contract[]>(ROOT+"/admin/contracts"+q({site_id})),
 saveContract:(data:{association_id:string;worker_assignment_id:string|null;contract_type:string;start_date:string;end_date:string|null;status:string;notes:string})=>
   request<Contract>(ROOT+"/admin/contracts",{method:"POST",body:JSON.stringify(data)}),
 calendar:(period:string,site_id:string|null)=>request<CalendarEntry[]>(ROOT+"/admin/calendar"+q({period,site_id})),
 saveCalendar:(data:{worksite_id:string;period:string;kind:string;request_date:string;due_date:string;alert_date:string|null})=>
   request<CalendarEntry>(ROOT+"/admin/calendar",{method:"PUT",body:JSON.stringify(data)}),
 alerts:(site_id:string|null)=>request<{date:string;total:number;alerts:Alert[]}>(ROOT+"/admin/alerts"+q({site_id})),
 offboarding:(site_id:string|null)=>request<Array<{id:string;association_id:string;stage:string;status:string;letter_decision:string;notes:string}>>(ROOT+"/admin/offboarding"+q({site_id})),
 saveOffboarding:(data:{association_id:string;stage:string;letter_decision:string;letter_reason:string;notes:string})=>
   request<{id:string;stage:string}>(ROOT+"/admin/offboarding",{method:"PUT",body:JSON.stringify(data)}),
 excelCotizaciones:(period:string,site_id:string|null)=>ROOT+"/reports/cotizaciones.xlsx"+q({period,site_id}),
 excelMensual:(period:string,site_id:string|null)=>ROOT+"/reports/mensual.xlsx"+q({period,site_id})
}
