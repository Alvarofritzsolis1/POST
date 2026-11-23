import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertCircle, CalendarDays, CheckCircle2, ChevronDown, Facebook, FileText, MapPin, Send, Sparkles } from "lucide-react";
import { change, type Catalog, type Requirement } from "./networkApi";
import { todayISO, errorText } from "./NetworkUI";
import { NetworkSpecialtyPicker } from "./NetworkSpecialtyPicker";
import SocialPoster, { type SocialPosterHandle } from "./NetworkSocialPoster";
import "./network-quick-premium.css";

/** Compact publication flow. Nonessential programming remains in the full editor. */
const TRADES = ["Carpintería", "Electricidad", "Gasfitería", "Albañilería", "Pintura",
  "Enfierradura", "Terminaciones", "Cerámica", "Impermeabilización", "Techumbre",
  "Soldadura", "Ventanas", "Climatización", "Jardinería", "Paisajismo", "Excavaciones"];

const normalize = (s: string) =>
  s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();

const CATEGORY_WORDS: Record<string, RegExp> = {
  electricidad: /electri|tablero|cablead|conexion electrica|luminaria/,
  pintura: /pintur|pintar|pintado|esmalte|latex/,
  carpinteria: /carpinter|puertas de madera|muebl|tabiqueria madera/,
  gasfiteria: /gasfiter|sanitari|alcantarill|tuber|griferia|agua potable/,
  albañileria: /albanil|ladrillo|mortero|mamposteria/,
};
function category(s: string) {
  return Object.entries(CATEGORY_WORDS).find(([, pattern]) => pattern.test(normalize(s)))?.[0] ?? "";
}
/** Only flag a clear one-trade contradiction. Do not silently rewrite either field. */
function contradiction(specialty: string, notes: string) {
  const specified = category(specialty);
  const described = Object.entries(CATEGORY_WORDS)
    .filter(([, re]) => re.test(normalize(notes))).map(([name]) => name);
  return specified && described.length === 1 && described[0] !== specified
    ? described[0] : "";
}
function labelForCategory(name: string) {
  return { electricidad: "electricidad", pintura: "pintura", carpinteria: "carpintería",
    gasfiteria: "gasfitería", albañileria: "albañilería" }[name] || name;
}
function StateMark({ ok, pending }: {ok: boolean; pending?: string}) {
  return <span className={"nq-state " + (ok ? "valid" : "invalid")} aria-label={ok ? "Campo correcto" : "Campo pendiente"}>
    {ok ? <CheckCircle2 size={14} aria-hidden="true"/> : <AlertCircle size={14} aria-hidden="true"/>}
    {ok ? "Correcto" : pending || "Pendiente"}
  </span>;
}

export function NetworkQuickForm({
  catalog,
  done,
}: {
  catalog: Catalog;
  done: (message: string, req?: Requirement) => void;
}) {
  const sites = catalog.sites.filter((s) => s.editable);
  const key = useRef(crypto.randomUUID());
  const posterEditor = useRef<SocialPosterHandle>(null);
  const roleRef = useRef<HTMLDivElement>(null);
  const [siteId, setSiteId] = useState(sites[0]?.id ?? "");
  const [specialty, setSpecialty] = useState("");
  const [summary, setSummary] = useState("");
  const [publicSummary, setPublicSummary] = useState("");
  const [copyEdited, setCopyEdited] = useState(false);
  const [copySource, setCopySource] = useState("");
  const [copyBusy, setCopyBusy] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [copyCycle, setCopyCycle] = useState(0);
  const [start, setStart] = useState("");
  const [workers, setWorkers] = useState(1);
  const [priority, setPriority] = useState("normal");
  const [title, setTitle] = useState("");
  const [publishFacebook, setPublishFacebook] = useState(true);
  const [publicLocation, setPublicLocation] = useState(sites[0]?.public_location ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [confirmedMismatch, setConfirmedMismatch] = useState(false);
  const [mobilePane, setMobilePane] = useState<"fields" | "preview">("fields");
  const [expandedMore, setExpandedMore] = useState(false);

  const tradeOk = specialty.trim().length >= 2;
  const descriptionOk = summary.trim().length >= 8;
  const copyOk = publicSummary.trim().length >= 8 && publicSummary.trim().length <= 400;
  const locationOk = publicLocation.trim().length >= 3 && !/\d/.test(publicLocation);
  const staffOk = Number.isInteger(workers) && workers >= 1 && workers <= 10000;
  const siteOk = Boolean(siteId);
  const mismatch = contradiction(specialty, summary);
  const reviewOk = !mismatch || confirmedMismatch;
  const pending = [!siteOk, !tradeOk, !descriptionOk, !staffOk, publishFacebook && !locationOk,
    publishFacebook && !copyOk, !reviewOk]
    .filter(Boolean).length;
  const canPublish = pending === 0;

  // Debounced, bounded model call. Never overwrite edits made by the resident.
  useEffect(() => {
    if (!publishFacebook || !siteId || !tradeOk || !descriptionOk || copyEdited) return;
    let active = true;
    const timer = window.setTimeout(() => {
      setCopyBusy(true);
      setCopyError("");
      void change<{ suggestion: string; source: string }>("/requirements/summary-suggestion", {
        site_id: siteId, specialty: specialty.trim(), description: summary.trim(),
      }).then((result) => {
        if (!active) return;
        setPublicSummary(result.suggestion);
        setCopySource(result.source === "ia" ? "Mejorado con IA" : "Resumen automático");
      }).catch(() => {
        if (!active) return;
        setPublicSummary(summary.trim().replace(/\s+/g, " ").slice(0, 220));
        setCopySource("Resumen básico · revisa antes de publicar");
        setCopyError("La IA no pudo mejorar el texto. Puedes editarlo directamente.");
      }).finally(() => { if (active) setCopyBusy(false); });
    }, 1000);
    return () => { active = false; window.clearTimeout(timer); };
  }, [publishFacebook, siteId, specialty, summary, copyEdited, copyCycle, tradeOk, descriptionOk]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intent = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") || "published";
    setSubmitted(true);
    setError("");
    if (intent !== "draft" && !canPublish) {
      setError("Revisa los campos marcados en rojo antes de publicar.");
      setMobilePane("fields");
      if (!tradeOk) roleRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (!siteOk || (intent === "draft" && !tradeOk)) {
      setError("Selecciona la obra y escribe al menos el oficio para guardar."); return;
    }
    setBusy(true);
    try {
      const effectiveStart = start || todayISO();
      const poster = publishFacebook && intent === "published"
        ? await posterEditor.current?.exportJpeg() : "";
      if (publishFacebook && intent === "published" && !poster) {
        throw new Error("La fotografía aún no está lista. Cambia de imagen o súbela nuevamente.");
      }
      const response = await change<Requirement>("/requirements", {
        site_id: siteId,
        specialty: specialty.trim(),
        title: (title.trim() || "Contratistas de " + specialty.trim()).slice(0, 180),
        description: summary.trim(),
        public_summary: publishFacebook ? publicSummary.trim() : "",
        priority,
        workers: staffOk ? workers : 1,
        // Existing scheduling and item matching require dates. The pending flag
        // prevents exposing a synthetic date as a confirmed user decision.
        start_date: effectiveStart,
        start_date_pending: !start,
        end_date: effectiveStart,
        deadline: effectiveStart,
        items: [{
          name: specialty.trim(),
          description: summary.trim(),
          quantity: 1,
          unit: "gl",
          start_date: effectiveStart,
          end_date: effectiveStart,
          notes: start
            ? "Partida preliminar: precisar programación antes de adjudicar."
            : "Fecha pendiente: coordinar programación antes de adjudicar.",
        }],
        publish_to_facebook: publishFacebook,
        public_location: publicLocation.trim(),
        poster_data: poster,
        state: intent,
        client_key: key.current,
      });
      done(intent === "draft" ? "Borrador guardado." :
        publishFacebook ? "Necesidad guardada. Revisa el estado de Facebook en su ficha." :
          "Necesidad publicada en Red de Obras.", response);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form noValidate className="nw-form nq-form" onSubmit={(event) => void submit(event)}>
      <div className="nq-mobile-tabs" role="group" aria-label="Secciones de creación">
        <button type="button" className={mobilePane === "fields" ? "active" : ""}
          aria-pressed={mobilePane === "fields"} onClick={() => setMobilePane("fields")}>1. Necesidad</button>
        <button type="button" className={mobilePane === "preview" ? "active" : ""}
          aria-pressed={mobilePane === "preview"} onClick={() => setMobilePane("preview")}>2. Vista previa</button>
      </div>
      <section className={"nq-main" + (mobilePane === "fields" ? " nq-mobile-active" : "")}
        aria-label="Datos de la necesidad">
        <div className="nq-head"><b>Datos de la necesidad</b><span>Lo esencial, sin pasos innecesarios</span></div>
        <div className="nq-field">
          <label htmlFor="nq-site">Obra <StateMark ok={siteOk}/></label>
          {sites.length === 1
            ? <div className="nq-fixed-site">{sites[0].name}</div>
            : <select id="nq-site" value={siteId}
                aria-invalid={!siteOk} onChange={(event) => {
                  setSiteId(event.target.value);
                  setPublicLocation(sites.find((s) => s.id === event.target.value)?.public_location ?? "");
                }}>
              <option value="">Seleccionar obra</option>
              {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
            </select>}
        </div>
        <div ref={roleRef} className="nq-field">
          <NetworkSpecialtyPicker value={specialty}
            onChange={(value) => { setSpecialty(value); setConfirmedMismatch(false); }}
            suggestions={[...TRADES, ...catalog.specialties]} invalid={submitted && !tradeOk}/>
          <div className="nq-field-progress"><StateMark ok={tradeOk}/></div>
        </div>
        <div className="nq-field nq-description">
          <label htmlFor="nq-summary">¿Qué trabajos se realizarán? <StateMark ok={descriptionOk}/></label>
          <textarea id="nq-summary" value={summary} maxLength={2500} rows={2}
            aria-invalid={submitted && !descriptionOk}
            onChange={(e) => {
              setSummary(e.target.value);
              setConfirmedMismatch(false);
              if (!copyEdited) { setPublicSummary(""); setCopySource(""); }
            }}
            placeholder="Ej. Instalación y pintura de fachadas exteriores en edificios."/>
          <small className="nq-soft">Describe las labores reales. La IA creará un resumen más claro.</small>
        </div>
        {publishFacebook && <div className="nq-copy">
          <div className="nq-copy-title">
            <label htmlFor="nq-public-copy"><Sparkles size={15}/> Resumen para Facebook
              <StateMark ok={copyOk} pending="Por revisar"/></label>
            <button type="button" disabled={!tradeOk || !descriptionOk || copyBusy}
              onClick={() => { setPublicSummary(""); setCopyEdited(false); setCopySource(""); setCopyCycle(v => v + 1); }}
              aria-label="Volver a mejorar el resumen con IA">
              <Sparkles size={14}/> {copyBusy ? "Preparando…" : "Mejorar con IA"}
            </button>
          </div>
          <textarea id="nq-public-copy" rows={2} maxLength={400}
            aria-invalid={submitted && !copyOk}
            value={publicSummary}
            onChange={(e) => {
              setPublicSummary(e.target.value); setCopyEdited(true);
              setCopySource("Editado por ti"); setCopyError("");
            }}
            placeholder={copyBusy ? "Analizando las labores…" : "El resumen editable aparecerá aquí"}/>
          <div className="nq-copy-foot">
            <small>{copyError || copySource || "Basado en la descripción, sin inventar datos."}</small>
            <small>{publicSummary.length}/400</small>
          </div>
        </div>}
        <div className="nq-two">
          <div className="nq-field">
            <label htmlFor="nq-workers">Personas aprox. <StateMark ok={staffOk}/></label>
            <div className="nq-count">
              <button type="button" aria-label="Reducir dotación" onClick={() => setWorkers((n) => Math.max(1, n - 1))}>−</button>
              <input id="nq-workers" type="number" value={workers} min="1" max="10000"
                aria-invalid={!staffOk} onChange={(e) => setWorkers(Number(e.target.value))}/>
              <button type="button" aria-label="Aumentar dotación" onClick={() => setWorkers((n) => Math.min(10000, n + 1))}>+</button>
            </div>
          </div>
          <div className="nq-field">
            <label htmlFor="nq-date"><CalendarDays size={14} aria-hidden="true"/> Inicio estimado <span className="nq-optional">Opcional</span></label>
            <input id="nq-date" type="date" value={start} onChange={(e) => setStart(e.target.value)}/>
            {!start && <small className="nq-soft">Por confirmar · no se anuncia fecha</small>}
          </div>
        </div>
        <div className="nq-facebook">
          <label className="nq-facebook-choice">
            <input type="checkbox" checked={publishFacebook} onChange={(e) => setPublishFacebook(e.target.checked)}/>
            <Facebook size={17} aria-hidden="true"/>
            <span>Publicar también en Facebook</span>
          </label>
          {publishFacebook && <div className="nq-field">
            <label htmlFor="nq-location"><MapPin size={14} aria-hidden="true"/> Sector aproximado
              <StateMark ok={locationOk}/></label>
            <input id="nq-location" value={publicLocation} maxLength={120}
              aria-invalid={submitted && !locationOk}
              placeholder="Ej. San Pedro de la Paz, Biobío"
              onChange={(e) => setPublicLocation(e.target.value)}/>
            <small className="nq-soft">Solo comuna o sector; el nombre de la obra es privado.</small>
          </div>}
        </div>
        <details className="nq-extra" open={expandedMore} onToggle={(e) => setExpandedMore(e.currentTarget.open)}>
          <summary><span><FileText size={16}/> Opciones adicionales <small>(opcional)</small></span><ChevronDown size={15}/></summary>
          <div className="nq-extra-body">
            <label htmlFor="nq-title">Título interno personalizado <span className="nq-optional">Opcional</span></label>
            <input id="nq-title" value={title} maxLength={180}
              placeholder="Se genera automáticamente si lo dejas vacío"
              onChange={(e) => setTitle(e.target.value)}/>
            <label htmlFor="nq-priority">Prioridad <span className="nq-optional">Opcional</span></label>
            <select id="nq-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="normal">Normal</option><option value="high">Alta</option>
              <option value="urgent">Urgente</option>
            </select>
          </div>
        </details>
        {mismatch && <div className="nq-mismatch" role="alert">
          <AlertCircle size={18} aria-hidden="true"/>
          <div><strong>Revisa el oficio y la descripción</strong>
            <p>Seleccionaste {specialty}, pero el texto parece corresponder a {labelForCategory(mismatch)}.</p>
            <label><input type="checkbox" checked={confirmedMismatch}
              onChange={(e) => setConfirmedMismatch(e.target.checked)}/>
              Confirmo que ambos datos son correctos.</label>
          </div>
        </div>}
        {error && <p className="nq-error" role="alert">{error}</p>}
      </section>
      <section className={"nq-preview" + (mobilePane === "preview" ? " nq-mobile-active" : "")}
        aria-label="Vista previa de Facebook">
        <SocialPoster ref={posterEditor} compact enabled={publishFacebook} specialty={specialty}
          publicLocation={publicLocation} publicSummary={publicSummary} workers={workers} start={start}/>
        {!publishFacebook && <div className="nq-internal-only"><CheckCircle2 size={18}/> La necesidad solo se compartirá dentro de Red de Obras.</div>}
      </section>
      <div className="nq-footer">
        <div className={"nq-progress " + (canPublish ? "ready" : "pending")} aria-live="polite">
          {canPublish ? <CheckCircle2 size={19} aria-hidden="true"/> : <AlertCircle size={19} aria-hidden="true"/>}
          <div><strong>{canPublish ? "Lista para publicar" : pending + (pending === 1 ? " dato pendiente" : " datos pendientes")}</strong>
            <small>{canPublish ? "Verifica la imagen antes de compartir." : "Completa lo marcado en rojo."}</small></div>
        </div>
        <div className="nq-actions">
          <button type="submit" value="draft" className="nw-btn" disabled={busy}>Guardar borrador</button>
          <button type="submit" value="published" className="nw-btn nw-primary" disabled={busy || !sites.length}>
            <Send size={16}/> {busy ? "Guardando…" : "Publicar necesidad"}
          </button>
        </div>
      </div>
    </form>
  );
}
