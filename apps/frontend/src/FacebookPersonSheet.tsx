import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertCircle, ArrowRight, BriefcaseBusiness, CalendarClock, CheckCircle2,
  ClipboardList, Clock3, Link2, MapPin, MessageCircle, Phone, Save,
  ShieldCheck, Sparkles, UserRound, Users, X,
} from "lucide-react";
import { change, net } from "./networkApi";
import { errorText } from "./NetworkUI";
import "./facebook-person-sheet.css";

export type TrackingPerson = {
  id: string; name: string; company: string; category: string; stage: string;
  urgency: "high" | "normal" | "none"; next_action: string;
  profile_state?: string; trades?: string[]; needs_support: boolean;
  links?: { id: string; title: string; specialty: string }[];
  matches?: { id: string; title: string; specialty: string; reasons: string[]; linked: boolean }[];
};
type Lead = {
  id: string; name: string; company: string; specialty: string; trades?: string[];
  workers: number | null; availability: string; experience: string; documents_state: string;
  status: string; requirement_id: string | null; linked_needs?: string[];
  entity_type: string; interest_type: string; team_available: boolean | null;
  has_employees: boolean | null; work_area: string; work_communes?: string[];
  follow_up_on: string | null; follow_up_note: string; last_inbound_at: string | null;
  contact_phone?: string | null; phone_source?: string | null; phone_requested_at?: string | null;
  phone_opt_out?: boolean; can_reply: boolean;
  profile: { summary: string; percent: number; missing: string[]; evidence: string };
};
type Detail = { lead: Lead };
type Match = { id:string; title:string; specialty:string; site?:string; reasons:string[]; linked?:boolean };
type Insights = { contact_id:string; next_action:string; matches:Match[] };
type Trace = {event:string; trade:string|null; at:string; source:string};
type Props = {
  person: TrackingPerson;
  onClose: () => void;
  onChanged: () => void;
  onOpenChat: (id:string) => void;
};
const dateText = (v?:string|null) => {
  if (!v) return "Por programar";
  // A date-only value is a calendar date, not UTC midnight (Chile would show the day before).
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) {
    const [year,month,day] = v.split("-");
    return `${day}-${month}-${year}`;
  }
  const date = new Date(v);
  return Number.isNaN(date.getTime()) ? v : new Intl.DateTimeFormat("es-CL", {
    day:"2-digit", month:"short", year:"numeric", timeZone:"America/Santiago",
  }).format(date);
};
const nameOf = (lead:Lead) => lead.name && lead.name !== "Interesado de Facebook" ?
  lead.name : lead.company || "Contacto sin nombre";
const interest = (v:string) => ({employment:"Busca empleo",service_offer:"Ofrece servicios",
  both:"Busca empleo y ofrece servicios"} as Record<string,string>)[v] || "Por confirmar";
const typeLabel = (v:string) => ({company:"Empresa declarada",individual:"Persona natural",
  unknown:"Por confirmar"} as Record<string,string>)[v] || "Por confirmar";
const traceLabel = (value:string) => value==="need_linked" ? "Necesidad vinculada" :
  value==="need_unlinked" ? "Necesidad desvinculada" : value==="trade_added" ?
  "Oficio registrado" : value==="trade_removed" ? "Oficio corregido" : "Ficha actualizada";
const validPhone = (text:string) => !text.trim() ||
  /^(?:\+?56[\s.-]?)?9[\s.-]?\d{4}[\s.-]?\d{4}$/.test(text.trim());
const Cell = ({title,value}:{title:string;value:string|number|null|undefined}) =>
  <div className="fbps-cell"><span>{title}</span><strong>{value===null||value===undefined||value===""?"Por confirmar":value}</strong></div>;

export default function FacebookPersonSheet({person,onClose,onChanged,onOpenChat}:Props) {
  const [data,setData]=useState<Detail|null>(null);
  const [insights,setInsights]=useState<Insights|null>(null);
  const [trace,setTrace]=useState<Trace[]>([]);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [saving,setSaving]=useState(false);
  const [editing,setEditing]=useState(false);
  const [phone,setPhone]=useState("");
  const [date,setDate]=useState("");
  const [notes,setNotes]=useState("");
  const dialog=useRef<HTMLDivElement>(null);
  const closeButton=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    const oldFocus=document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const scroll=document.body.style.overflow;
    document.body.style.overflow="hidden";
    closeButton.current?.focus();
    function keydown(event:KeyboardEvent){
      if(event.key==="Escape"){event.preventDefault();onClose();}
      if(event.key!=="Tab"||!dialog.current)return;
      const controls=Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), summary, a[href]"
      )).filter(el=>el.getClientRects().length>0);
      if(!controls.length)return;
      if(event.shiftKey&&document.activeElement===controls[0]){
        event.preventDefault();controls[controls.length-1].focus();
      }else if(!event.shiftKey&&document.activeElement===controls[controls.length-1]){
        event.preventDefault();controls[0].focus();
      }
    }
    document.addEventListener("keydown",keydown);
    return()=>{document.removeEventListener("keydown",keydown);document.body.style.overflow=scroll;oldFocus?.focus();};
  },[onClose]);
  async function reload(){
    const [detail,insight,history]=await Promise.all([
      net<Detail>("/facebook/leads/"+person.id),
      net<Insights>("/facebook/leads/"+person.id+"/insights").catch(()=>null),
      net<Trace[]>("/facebook/leads/"+person.id+"/trace").catch(()=>[]),
    ]);
    setData(detail);setInsights(insight);setTrace(history);
    setPhone(detail.lead.contact_phone||"");
    setDate(detail.lead.follow_up_on||"");
    setNotes(detail.lead.follow_up_note||"");
  }
  useEffect(()=>{
    let enabled=true;
    Promise.all([
      net<Detail>("/facebook/leads/"+person.id),
      net<Insights>("/facebook/leads/"+person.id+"/insights").catch(()=>null),
      net<Trace[]>("/facebook/leads/"+person.id+"/trace").catch(()=>[]),
    ]).then(([detail,insight,history])=>{
      if(!enabled)return;
      setData(detail);setInsights(insight);setTrace(history);
      setPhone(detail.lead.contact_phone||"");setDate(detail.lead.follow_up_on||"");
      setNotes(detail.lead.follow_up_note||"");
    }).catch(e=>{if(enabled)setError(errorText(e));});
    return()=>{enabled=false;};
  },[person.id]);
  async function save(e:FormEvent){
    e.preventDefault();
    if(saving||!data)return;
    if(!validPhone(phone)){setError("Número inválido. Usa +56 9 1234 5678 o deja vacío.");return;}
    setSaving(true);setError("");setNotice("");
    try{
      await change("/facebook/leads/"+person.id,{
        contact_phone:phone.trim(),follow_up_on:date||null,follow_up_note:notes.trim(),
      },"PATCH");
      await reload();setEditing(false);setNotice("Ficha actualizada.");onChanged();
    }catch(e){setError(errorText(e));}
    finally{setSaving(false);}
  }
  async function link(id:string,unlink:boolean){
    if(saving)return;setSaving(true);setError("");setNotice("");
    try{
      await change("/facebook/leads/"+person.id+"/needs/"+id+(unlink?"/unlink":"/link"),{});
      await reload();setNotice(unlink?"Vínculo retirado.":"Necesidad vinculada para revisión.");onChanged();
    }catch(e){setError(errorText(e));}finally{setSaving(false);}
  }
  async function requestPhone(){
    if(saving)return;setSaving(true);setError("");setNotice("");
    try{
      await change("/facebook/leads/"+person.id+"/request-phone",{});
      setNotice("Solicitud de número puesta en cola de Messenger.");onChanged();
    }catch(e){setError(errorText(e));}finally{setSaving(false);}
  }
  const lead=data?.lead;
  const linked=new Set(lead?.linked_needs || (lead?.requirement_id?[lead.requirement_id]:[]));
  const matches=insights?.matches||person.matches||[];
  return <div className="fbps-overlay" onMouseDown={e=>{if(e.target===e.currentTarget)onClose();}}>
    <div ref={dialog} className="fbps-dialog" role="dialog" aria-modal="true"
      aria-label={"Ficha de "+(lead?nameOf(lead):person.name)}>
      <div className="fbps-titlebar"><span><UserRound size={16}/> Ficha inteligente · Red de Obras</span>
        <button ref={closeButton} type="button" className="fbps-close" onClick={onClose} aria-label="Cerrar ficha">
          <X size={19}/></button></div>
      {!lead?<div className="fbps-loading" role="status">{error||"Cargando ficha…"}</div>:<>
        <header className="fbps-header">
          <div className="fbps-avatar">{nameOf(lead).slice(0,1).toLocaleUpperCase("es-CL")}</div>
          <div className="fbps-person"><h2>{nameOf(lead)}</h2><div className="fbps-tags">
            <span className="fbps-tag trade">{lead.specialty||person.category||"Oficio por confirmar"}</span>
            <span className={"fbps-tag "+(person.needs_support?"amber":person.urgency==="high"?"rose":"mint")}>
              {person.stage}</span>
            <span className="fbps-tag pale">{lead.profile.percent}% ficha</span>
          </div><p>Información declarada · Pendiente de verificación</p></div>
          <div className="fbps-actions">
            <button type="button" className="fbps-button" onClick={()=>setEditing(v=>!v)}>
              <ClipboardList size={16}/>{editing?"Cerrar edición":"Editar ficha"}</button>
            <button type="button" className="fbps-button main" onClick={()=>onOpenChat(person.id)}>
              <MessageCircle size={16}/> Ver chat</button>
          </div>
        </header>
        {error&&<p className="fbps-error" role="alert">{error}</p>}
        {notice&&<p className="fbps-notice" role="status"><CheckCircle2 size={16}/>{notice}</p>}
        <div className="fbps-scroll">
          {editing&&<form className="fbps-editor" onSubmit={save}>
            <div><h3>Editar seguimiento</h3><small>Los cambios solo se guardan en GALANT.</small></div>
            <label>Teléfono voluntario<input type="tel" inputMode="tel" autoComplete="off"
              value={phone} onChange={e=>setPhone(e.target.value)} maxLength={26}
              placeholder="+56 9 1234 5678"/></label>
            <label>Fecha de seguimiento<input type="date" value={date} onChange={e=>setDate(e.target.value)}/></label>
            <label className="fbps-notes-field">Nota interna<textarea rows={2} maxLength={240}
              value={notes} onChange={e=>setNotes(e.target.value)}/></label>
            <button type="submit" disabled={saving} className="fbps-button main"><Save size={16}/>
              {saving?"Guardando…":"Guardar"}</button>
          </form>}
          <div className="fbps-grid">
            <section className="fbps-card"><h3><UserRound size={18}/> Datos generales</h3><div className="fbps-fields">
              <Cell title="Nombre" value={lead.name==="Interesado de Facebook"?"Por confirmar":lead.name}/>
              <Cell title="Perfil" value={typeLabel(lead.entity_type)}/>
              <Cell title="Interés" value={interest(lead.interest_type)}/>
              <Cell title="Empresa declarada" value={lead.company}/>
              <Cell title="Teléfono" value={lead.contact_phone||"No compartido"}/>
              <Cell title="Origen del número" value={lead.phone_source==="message"?"Enviado voluntariamente":
                lead.phone_source==="manual"?"Registrado por administración":"Sin dato"}/>
              {!lead.contact_phone&&!lead.phone_opt_out&&!lead.phone_requested_at&&lead.can_reply&&
                <button type="button" className="fbps-inline-action" onClick={()=>void requestPhone()} disabled={saving}>
                  <Phone size={15}/> Solicitar número para coordinación</button>}
              {!lead.contact_phone && lead.phone_requested_at &&
                <small className="fbps-muted">Solicitud creada · comprobar envío en chat · {dateText(lead.phone_requested_at)}</small>}
              {!lead.contact_phone && lead.phone_opt_out &&
                <small className="fbps-muted">Prefiere continuar sin compartir teléfono</small>}
            </div></section>
            <section className="fbps-card"><h3><BriefcaseBusiness size={18}/> Oficios y experiencia</h3>
              <div className="fbps-tags">{[...new Set(lead.trades?.length?lead.trades:
                (lead.specialty?[lead.specialty]:[]))].map(t=><span key={t} className="fbps-tag trade">{t}</span>)}</div>
              <div className="fbps-fields"><Cell title="Experiencia" value={lead.experience}/>
                <Cell title="Trabaja con equipo" value={lead.team_available===null?"Por confirmar":lead.team_available?"Sí":"No"}/>
                <Cell title="Personas disponibles" value={lead.workers}/>
                <Cell title="Tiene empleados" value={lead.has_employees===null?"Por confirmar":lead.has_employees?"Sí":"No"}/>
              </div></section>
            <section className="fbps-card"><h3><MapPin size={18}/> Disponibilidad y cobertura</h3>
              <div className="fbps-fields"><Cell title="Disponibilidad" value={lead.availability}/>
                <Cell title="Comunas" value={lead.work_communes?.length?lead.work_communes.join(", "):lead.work_area}/>
                <Cell title="Último mensaje" value={dateText(lead.last_inbound_at)}/>
                <Cell title="Próximo seguimiento" value={dateText(lead.follow_up_on)}/></div></section>
            <section className="fbps-card"><h3><ShieldCheck size={18}/> Estado del proceso</h3>
              <div className="fbps-fields"><Cell title="Situación" value={person.stage}/>
                <Cell title="Necesidades vinculadas" value={linked.size}/>
                <Cell title="Documentación" value={lead.documents_state==="verified"?"Revisada":
                  lead.documents_state==="declared"?"Declarada":"Sin revisar"}/>
                <Cell title="Siguiente acción" value={insights?.next_action||person.next_action}/></div></section>
            <section className="fbps-card fbps-ai"><h3><Sparkles size={19}/> Resumen de Galancito
                <span>Datos orientativos</span></h3>
              <p>{lead.profile.summary}</p>
              <div className="fbps-recommendation"><CheckCircle2 size={17}/>
                <div><b>Próximo paso</b><p>{insights?.next_action||person.next_action}</p></div></div>
              <small>{lead.profile.evidence}</small></section>
            <section className="fbps-card"><h3><AlertCircle size={18}/> Por confirmar
              <span className="fbps-count">{lead.profile.missing.length}</span></h3>
              {lead.profile.missing.length?
                <div className="fbps-missing">{lead.profile.missing.map(t=><div key={t}>
                  <AlertCircle size={15}/>{t}</div>)}</div>:
                <p className="fbps-muted">Sin campos básicos pendientes. Los antecedentes requieren validación.</p>}
            </section>
            <section className="fbps-card"><h3><Link2 size={18}/> Necesidades relacionadas</h3>
              {!matches.length&&!(person.links||[]).length&&
                <p className="fbps-muted">No hay necesidades relacionadas con los datos actuales.</p>}
              <div className="fbps-needs">{matches.map(m=><div className="fbps-need" key={m.id}>
                <div><b>{m.title}</b><small>{m.specialty||"Necesidad de obra"}</small></div>
                <button type="button" disabled={saving} onClick={()=>void link(m.id,linked.has(m.id))}>
                  {linked.has(m.id)?"Desvincular":"Vincular"}</button></div>)}
                {(person.links||[]).filter(l=>!matches.some(m=>m.id===l.id)).map(l=>
                  <div className="fbps-need" key={l.id}><div><b>{l.title}</b><small>Vinculada anteriormente</small></div>
                    <button type="button" disabled={saving} onClick={()=>void link(l.id,true)}>Desvincular</button>
                  </div>)}</div><small>La coincidencia no implica contratación.</small></section>
            <section className="fbps-card"><h3><Clock3 size={18}/> Últimos movimientos</h3>
              {!trace.length&&<p className="fbps-muted">Aún no se registran movimientos.</p>}
              <div className="fbps-timeline">{trace.slice(0,8).map((t,i)=><div key={i}>
                <span className="fbps-dot"/><div><b>{traceLabel(t.event)}</b>
                  <small>{t.trade?t.trade+" · ":""}{dateText(t.at)}</small></div></div>)}</div></section>
            <section className="fbps-card"><h3><Users size={18}/> Observaciones</h3>
              <p className="fbps-muted">{lead.follow_up_note||"Sin observaciones registradas."}</p>
              <button type="button" className="fbps-inline-action" onClick={()=>setEditing(true)}>
                <ArrowRight size={15}/> Agregar observación</button>
            </section>
          </div>
        </div>
      </>}
    </div>
  </div>;
}
