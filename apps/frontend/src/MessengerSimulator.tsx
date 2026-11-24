import { useEffect, useRef, useState, type FormEvent } from "react";
import { Download, MessageCircle, RotateCcw, Send } from "lucide-react";
import { ApiError, request } from "./api";
import "./messenger-simulator.css";

const path = "/admin/ai/messenger-simulator";
type Mode = "rules" | "local" | "qwen";
type Settings = {local_model: string | null; max_turns: number; qwen_ready?: boolean; release?:string; revision?:string; qwen_settings?:Record<string,number>};
type TurnResult = {
  state: string;
  reply: string | null;
  intent: string;
  source: string | null;
  elapsed_ms: number | null;
  profile: Record<string, string | string[] | boolean | number | null>;
  field_states: Record<string, string>;
  changed_fields: string[];
  checks: {safe: boolean; repeated_fields: string[]; repeated_intro: boolean;
           numbered_menu: boolean; question_displaced: boolean} | null;
  review_required: boolean;
  diagnostics?: {protocol:string;instruction_sha256:string;context_sha256:string;context_chars:number;history_available:number;history_included:number;profile_before:TurnResult["profile"];updates:{field:string;status:string;reason:string;value?:unknown;quote?:string}[];same_as_previous_reply:boolean;reply_sanitized?:boolean;semantic_correctness:string};
  model_evidence?: {model:string; calls:number; output_tokens:number; thinking:boolean; budget_tokens:number; load_ms?:number; prompt_ms?:number; generation_ms?:number; ollama_total_ms?:number; prompt_eval_count?:number};
};
type Exchange = {
  message: string;
  result: Omit<TurnResult, "state">;
  natural?: boolean;
  useful?: boolean;
  note?: string;
  expected?: string;
  attempt: number;
};
type FailedAttempt = {attempt:number;message:string;code:string;http_status:number|null;elapsed_ms:number;at:string};

const fields: Record<string,string> = {
  display_name:"Nombre", specialty:"Oficio principal", trades:"Oficios declarados",
  interest_type:"Interés", entity_type:"Tipo de postulante", team_available:"Cuadrilla",
  workers:"Personas que pueden ir", employee_count:"Personas contratadas", has_employees:"Personal contratado",
  experience:"Experiencia", work_communes:"Comunas", availability:"Disponibilidad",
  contact_phone:"Teléfono", contact_email:"Correo",
};
const values: Record<string,string> = {
  both:"Busca trabajo y ofrece servicios", employment:"Busca trabajo", service_offer:"Ofrece servicios",
  company:"Empresa", individual:"Independiente", unknown:"Pendiente",
};
const sources: Record<string,string> = {
  qwen_direct:"Qwen 4B · inferencia directa", local:"Reglas de Messenger", consent:"Solicitud de permiso", ai:"Modelo local",
  knowledge:"Guía aprobada", local_recovery:"Respuesta local", fallback:"Derivación",
};
const intents: Record<string,string> = {
  apply:"Postulación a un aviso", job_seeker:"Busca trabajo", trade_offer:"Ofrece un oficio",
  company_offer:"Ofrece servicios como empresa", greeting:"Saludo", capacity:"Capacidad de cuadrilla",
  about:"Consulta sobre Red de Obras", documents:"Consulta de documentos", human:"Atención humana",
  requirements:"Consulta de obras", restricted:"Solicitud restringida", unknown:"Por aclarar",
};

function display(value: TurnResult["profile"][string]) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "boolean") return value ? "Sí" : "No";
  return value == null ? "" : values[String(value)] ?? String(value);
}

export default function MessengerSimulator() {
  const [config, setConfig] = useState<Settings | null>(null);
  const [mode, setMode] = useState<Mode>("qwen");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [failedAttempts,setFailedAttempts]=useState<FailedAttempt[]>([]);
  const attemptCounter=useRef(0);
  const [selected, setSelected] = useState(-1);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const transcript = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const state = useRef<string | null>(null);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void request<Settings>(path, {signal:controller.signal}).then(setConfig).catch((problem: unknown) => {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : "No se pudo abrir el simulador.");
    });
    return () => {
      controller.abort();
      pending.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [exchanges.length, sending]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = input.trim();
    if (!message || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setSending(true);
    setError("");
    const attempt=++attemptCounter.current;
    const started=performance.now();
    try {
      const {state: nextState, ...result} = await request<TurnResult>(path + "/turn", {
        method:"POST", body:JSON.stringify({message, mode, state:state.current}), signal:controller.signal,
      });
      if (controller.signal.aborted) return;
      state.current = nextState;
      setSelected(exchanges.length);
      setExchanges(current => [...current, {message, result, attempt}]);
      setInput("");
    } catch (problem) {
      if (!controller.signal.aborted) {
        const detail=problem instanceof Error ? problem.message : "No se pudo responder.";
        setError(detail);
        if(mode==="qwen"){
          const code=/^[a-z_]+:/.test(detail)?detail.split(":")[0]:"request_failed";
          setFailedAttempts(current=>[...current,{attempt,message:code==="private_input_rejected"?"[mensaje privado excluido]":message,
              code,http_status:problem instanceof ApiError?problem.status:null,elapsed_ms:Math.round(performance.now()-started),
              at:new Date().toISOString()}]);
        }
      }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        if (!controller.signal.aborted) {
          setSending(false);
          inputRef.current?.focus();
        }
      }
    }
  }

  function reset() {
    if(mode==="qwen" && (exchanges.length || failedAttempts.length) && !window.confirm("¿Borrar esta práctica? Exporta el balance primero si quieres conservarlo.")) return;
    setFailedAttempts([]);
    attemptCounter.current=0;
    state.current = null;
    setExchanges([]);
    setSelected(-1);
    setInput("");
    setError("");
    inputRef.current?.focus();
  }

  function rate(criterion: "natural" | "useful", value: boolean) {
    setExchanges(current => current.map((item, index) => index === selected ? {...item, [criterion]:value} : item));
  }

  function annotate(field:"note"|"expected",value:string){
    setExchanges(current=>current.map((item,index)=>index===selected?{...item,[field]:value}:item));
  }

  const balance=exchanges.map((item,index)=>{
    const r=item.result;
    const alerts:string[]=[];
    if(r.checks?.repeated_fields.length) alerts.push("repeated_known_field");
    if(r.checks?.question_displaced) alerts.push("question_displaced");
    if(r.checks?.repeated_intro) alerts.push("repeated_intro");
    if(r.checks?.numbered_menu) alerts.push("numbered_menu");
    if(r.checks?.safe===false) alerts.push("safety_check_failed");
    if(r.diagnostics?.same_as_previous_reply) alerts.push("identical_previous_reply");
    if(r.diagnostics?.reply_sanitized) alerts.push("model_reply_sanitized");
    if(r.diagnostics?.updates.some(x=>x.status==="rejected"||x.status==="reverted")) alerts.push("profile_proposal_rejected");
    if(item.natural===false) alerts.push("reviewer_unnatural");
    if(item.useful===false) alerts.push("reviewer_unhelpful");
    if(item.note?.trim()||item.expected?.trim()) alerts.push("reviewer_annotation");
    return {turn:index+1,attempt:item.attempt,alerts};
  });
  const durations=exchanges.map(x=>x.result.elapsed_ms).filter((x):x is number=>typeof x==="number"&&Number.isFinite(x)).sort((a,b)=>a-b);
  const percentile=(p:number)=>durations.length?durations[Math.max(0,Math.ceil(durations.length*p)-1)]:null;
  const report={
    schema:"galant-messenger-practice-v1",generated_at:new Date().toISOString(),scope:"synthetic_qwen_direct_only",
    release:config?.release??null,revision:config?.revision??null,configured_model:config?.local_model??null,
    settings:config?.qwen_settings??null,
    summary:{successful_turns:exchanges.length,failed_attempts:failedAttempts.length,
      verified_model_turns:exchanges.filter(x=>x.result.source==="qwen_direct"&&x.result.model_evidence?.calls===1).length,
      turns_with_alerts:balance.filter(x=>x.alerts.length).length,
      rated_turns:exchanges.filter(x=>x.natural!==undefined||x.useful!==undefined).length,
      latency_ms:{samples:durations.length,p50:percentile(.5),p95:percentile(.95),max:durations.at(-1)??null},
      alert_counts:Object.fromEntries([...new Set(balance.flatMap(x=>x.alerts))].map(code=>[code,balance.filter(x=>x.alerts.includes(code)).length])),
      quality_score:null,quality_status:"partial_controls_and_user_review_not_an_independent_quality_score"},
    turns:exchanges.map((item,index)=>({turn:index+1,...item,alerts:balance[index].alerts})),
    failed_attempts:failedAttempts
  };
  function downloadBalance(){
    if(mode!=="qwen"||(!exchanges.length&&!failedAttempts.length)) return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"}));
    const anchor=document.createElement("a");
    anchor.href=url;
    anchor.download="galant-qwen-practica-"+new Date().toISOString().replace(/[:.]/g,"-")+".json";
    document.body.appendChild(anchor);
    anchor.click();anchor.remove();
    window.setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  const current = exchanges[selected];
  const result = current?.result;
  const checks = result?.checks;
  const latest = exchanges.at(-1)?.result;
  const maxTurns = config?.max_turns ?? 24;
  const reachedLimit = exchanges.length >= maxTurns;

  return <section className="messenger-lab" aria-label="Simulador Messenger">
    <header className="messenger-lab-header">
      <div><h2><MessageCircle size={22} aria-hidden="true"/> Simulador Messenger</h2>
        <p>Escribe como postulante y revisa la respuesta y la ficha. Usa datos de prueba.</p></div>
      <button type="button" className="messenger-lab-reset" onClick={downloadBalance}
        disabled={sending||mode!=="qwen"||(!exchanges.length&&!failedAttempts.length)}>
        <Download size={16} aria-hidden="true"/> Descargar balance JSON
      </button>
      <button type="button" className="messenger-lab-reset" onClick={reset} disabled={sending || (!exchanges.length && !failedAttempts.length)}>
        <RotateCcw size={16} aria-hidden="true"/> Nueva conversación
      </button>
    </header>
    <div className="messenger-lab-grid">
      <article className="messenger-lab-chat">
        <header>
          <div><strong>Galancito</strong><small>Entrega simulada</small></div>
          <label>Modo
            <select value={mode} disabled={sending || exchanges.length > 0 || failedAttempts.length > 0}
              onChange={event => setMode(event.target.value as Mode)}>
              <option value="qwen">Qwen 4B · IA directa</option>
              <option value="local" disabled={!config?.local_model}>Flujo actual de Messenger con IA</option>
              <option value="rules">Solo reglas (diagnóstico)</option>
            </select>
          </label>
        </header>
        {mode === "qwen" && <p className="messenger-lab-empty">Práctica aislada con Qwen 4B: usa datos ficticios. Una llamada por turno, sin respuestas de reglas. {config && !config.qwen_ready ? "El 4B no está configurado en este servidor." : ""}</p>}
        <div className="messenger-lab-transcript" role="log" aria-label="Conversación de prueba" ref={transcript}>
          {!exchanges.length && <p className="messenger-lab-empty">Escribe un mensaje para comenzar.</p>}
          {exchanges.map(({message, result: reply}, index) => <div className="messenger-lab-exchange" key={index}>
            <p className="messenger-lab-bubble incoming">{message}</p>
            {reply.reply && <p className="messenger-lab-bubble outgoing">{reply.reply}</p>}
            <button type="button" className="messenger-lab-inspect" aria-pressed={index === selected}
              onClick={() => setSelected(index)}>{reply.reply ? "Revisar respuesta" : "Revisar turno"}</button>
          </div>)}
          {sending && <p className="messenger-lab-empty" role="status">Galancito está preparando la respuesta…</p>}
        </div>
        <form ref={formRef} className="messenger-lab-compose" onSubmit={send}>
          <textarea ref={inputRef} aria-label="Mensaje de prueba" rows={2} maxLength={1500}
            placeholder="Vi una postulación de trabajo" value={input} disabled={reachedLimit || sending}
            onChange={event => setInput(event.target.value)} onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (input.trim() && !sending) formRef.current?.requestSubmit();
              }
            }}/>
          <button type="submit" disabled={!input.trim() || sending || reachedLimit} aria-label="Enviar mensaje de prueba">
            <Send size={18} aria-hidden="true"/>
          </button>
        </form>
        {error && <p className="messenger-lab-error" role="alert">{error}</p>}
        {reachedLimit && <p className="messenger-lab-empty">La conversación llegó a {maxTurns} turnos. Puedes iniciar una nueva.</p>}
      </article>
      <aside className="messenger-lab-side">
        {mode==="qwen" && <article><h3>Balance de práctica</h3><dl className="messenger-lab-facts">
          <div><dt>Turnos con Qwen verificado</dt><dd>{report.summary.verified_model_turns}/{exchanges.length}</dd></div>
          <div><dt>Turnos con alertas</dt><dd>{report.summary.turns_with_alerts}</dd></div>
          <div><dt>Intentos fallidos</dt><dd>{failedAttempts.length}</dd></div>
          <div><dt>Latencia mediana</dt><dd>{percentile(.5)===null?"Sin datos":(percentile(.5)!/1000).toFixed(2)+" s"}</dd></div>
          <div><dt>Latencia p95</dt><dd>{percentile(.95)===null?"Sin datos":(percentile(.95)!/1000).toFixed(2)+" s"}</dd></div>
          </dl><p>Los controles son parciales; no equivalen a una nota de inteligencia. El JSON incluye conversación, ficha, diagnóstico y tus observaciones.</p>
          {failedAttempts.length>0 && <ul className="messenger-lab-checks">{failedAttempts.slice(-5).map(a=><li key={a.attempt}>Intento {a.attempt}: {a.code} ({a.elapsed_ms} ms)</li>)}</ul>}
        </article>}
        <article>
          <h3>Evaluación del turno</h3>
          {result ? <>
            <dl className="messenger-lab-facts">
              <div><dt>Intención</dt><dd>{intents[result.intent] ?? "Consulta general"}</dd></div>
              <div><dt>Respuesta</dt><dd>{result.source ? sources[result.source] ?? "Respuesta de Messenger" : "Sin respuesta en este turno"}</dd></div>
              {result.elapsed_ms != null && <div><dt>Tiempo de respuesta</dt><dd>{result.elapsed_ms} ms</dd></div>}
            </dl>
            {result.model_evidence && <dl className="messenger-lab-facts">
              <div><dt>Modelo devuelto por Ollama</dt><dd>{result.model_evidence.model}</dd></div>
              <div><dt>Llamadas reales</dt><dd>{result.model_evidence.calls}</dd></div>
              <div><dt>Tokens generados</dt><dd>{result.model_evidence.output_tokens}</dd></div>
              {result.model_evidence.ollama_total_ms != null && <div><dt>Tiempo Ollama</dt><dd>{(result.model_evidence.ollama_total_ms/1000).toFixed(2)} s</dd></div>}
              {result.model_evidence.load_ms != null && <div><dt>Carga del modelo</dt><dd>{(result.model_evidence.load_ms/1000).toFixed(2)} s</dd></div>}
            </dl>}
            {result.diagnostics && <><p>Contexto: {result.diagnostics.history_included} de {result.diagnostics.history_available} mensajes incluidos. {result.diagnostics.same_as_previous_reply?"Repitió exactamente la respuesta anterior.":""}</p>
              {result.diagnostics.updates.length>0 && <ul className="messenger-lab-checks">{result.diagnostics.updates.map((u,i)=><li key={i}>{fields[u.field]??u.field}: {u.status} · {u.reason}</li>)}</ul>}
              <div className="messenger-lab-annotation"><label>¿Qué falló?<textarea maxLength={1000} rows={2} value={current.note??""} onChange={e=>annotate("note",e.target.value)} placeholder="Ej.: no comprendió que quiero ofrecer servicios"/></label>
              <label>¿Qué debía entender o responder?<textarea maxLength={1000} rows={2} value={current.expected??""} onChange={e=>annotate("expected",e.target.value)} placeholder="Ej.: registrar interés y preguntar si tengo equipo"/></label></div></>}
            {result.review_required && <p>Derivación al equipo en este turno de prueba.</p>}
            {checks && <>
              <ul className="messenger-lab-checks">
                {checks.repeated_fields.length > 0 && <li>Volvió a pedir {checks.repeated_fields.map(field => fields[field] ?? field).join(", ")}.</li>}
                {checks.repeated_intro && <li>Repitió su presentación.</li>}
                {checks.numbered_menu && <li>Respondió con un menú numerado.</li>}
                {checks.question_displaced && <li>Pidió un dato de ficha antes de resolver la consulta.</li>}
                {!checks.safe && <li>El control de privacidad o promesas detectó un problema.</li>}
                {checks.safe && checks.repeated_fields.length === 0 && !checks.repeated_intro &&
                  !checks.numbered_menu && !checks.question_displaced && <li>Sin alertas en los controles automáticos.</li>}
              </ul>
              <div className="messenger-lab-rating" role="group" aria-label="Naturalidad">
                <strong>¿Cómo sonó?</strong>
                <button type="button" aria-pressed={current.natural === true} onClick={() => rate("natural", true)}>Natural</button>
                <button type="button" aria-pressed={current.natural === false} onClick={() => rate("natural", false)}>Suena a bot</button>
              </div>
              <div className="messenger-lab-rating" role="group" aria-label="Utilidad">
                <strong>¿Te orientó?</strong>
                <button type="button" aria-pressed={current.useful === true} onClick={() => rate("useful", true)}>Sí</button>
                <button type="button" aria-pressed={current.useful === false} onClick={() => rate("useful", false)}>Puede mejorar</button>
              </div>
            </>}
          </> : <p>La evaluación aparece después del primer mensaje.</p>}
        </article>
        <article>
          <h3>Ficha de prueba</h3>
          <dl className="messenger-lab-facts">{Object.entries(fields).map(([key,label]) => {
            const value = latest ? display(latest.profile[key]) : "";
            const status = latest?.field_states[key];
            const missing = status === "ambiguo" ? "Por aclarar" : status === "rechazado_por_usuario" ? "Prefirió omitirlo" : "Pendiente";
            return <div key={key}><dt>{label}</dt><dd>{value || missing}{latest?.changed_fields.includes(key) && <small> Actualizado</small>}</dd></div>;
          })}</dl>
        </article>
      </aside>
    </div>
  </section>;
}
