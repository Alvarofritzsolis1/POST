import { useRef, useState, type FormEvent } from "react";
import { Facebook, Check, CalendarDays, BriefcaseBusiness, Users, Send } from "lucide-react";
import { change, type Catalog, type Requirement } from "./networkApi";
import { errorText, todayISO } from "./NetworkUI";
import SocialPoster, { type SocialPosterHandle } from "./NetworkSocialPoster";

/** Publicación rápida: una fecha y partidas globales, sin alterar expedientes históricos. */
const QUICK_PARTS = ["Instalaciones", "Terminaciones", "Estructura", "Obras exteriores", "Otras"];

export function NetworkQuickForm({
  catalog,
  done,
}: {
  catalog: Catalog;
  done: (message: string, req?: Requirement) => void;
}) {
  const sites = catalog.sites.filter((site) => site.editable);
  const key = useRef(crypto.randomUUID());
  const posterEditor = useRef<SocialPosterHandle>(null);
  const [siteId, setSiteId] = useState(sites[0]?.id ?? "");
  const [specialty, setSpecialty] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [start, setStart] = useState(todayISO());
  const [workers, setWorkers] = useState(1);
  const [priority, setPriority] = useState("normal");
  const [parts, setParts] = useState<string[]>([]);
  const [publishFacebook, setPublishFacebook] = useState(true);
  const [publicLocation, setPublicLocation] = useState(sites[0]?.public_location ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function togglePart(part: string) {
    setParts((current) => current.includes(part) ? current.filter((item) => item !== part) : [...current, part]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intent = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") || "published";
    const suggestedTitle = (title.trim() || `Se necesita contratista de ${specialty.trim()}`).slice(0, 180);
    if (!siteId || specialty.trim().length < 2 || suggestedTitle.length < 3 || summary.trim().length < 3 || !start || !Number.isFinite(workers) || workers < 1) {
      setError("Completa el oficio, la descripción, la fecha y los trabajadores.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const posterData = publishFacebook && intent === "published"
        ? await posterEditor.current?.exportJpeg()
        : "";
      if (publishFacebook && intent === "published" && !posterData) {
        throw new Error("No se pudo preparar la imagen para Facebook.");
      }
      const entries = parts.length ? parts : [specialty.trim()];
      const response = await change<Requirement>("/requirements", {
        site_id: siteId,
        specialty: specialty.trim(),
        title: suggestedTitle,
        description: summary.trim(),
        priority,
        workers,
        start_date: start,
        // Programación preliminar: el periodo se podrá precisar al editar.
        end_date: start,
        deadline: start,
        items: entries.map((name) => ({
          name,
          description: summary.trim(),
          quantity: 1,
          unit: "gl",
          start_date: start,
          end_date: start,
          notes: "Partida global preliminar; confirmar programación y cantidades antes de adjudicar.",
        })),
        publish_to_facebook: publishFacebook,
        public_location: publicLocation.trim(),
        poster_data: posterData,
        state: intent,
        client_key: key.current,
      });
      done(intent === "draft" ? "Borrador guardado." :
        publishFacebook ? "Necesidad guardada. Consulta el estado de difusión en Facebook en el detalle." :
          "Necesidad publicada solo en GALANT.", response);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="nw-form nw-quick-form" onSubmit={(e) => void submit(e)}>
      <div className="nw-quick-intro"><p>Indica el oficio y el trabajo. Completa los detalles después.</p></div>
      <section className="nw-quick-fields" aria-label="Datos de la necesidad">
        <h3>1. ¿Qué necesitas?</h3>
        <label>Obra
          {sites.length === 1 ? (
            <span className="nw-site-locked">{sites[0].name}</span>
          ) : (
            <select value={siteId} onChange={(e) => {
              setSiteId(e.target.value);
              setPublicLocation(sites.find((item) => item.id === e.target.value)?.public_location ?? "");
            }} required>
              <option value="">Selecciona una obra</option>
              {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
            </select>
          )}
        </label>
        <label>Oficio o especialidad
          <input list="network-specialties" value={specialty} onChange={(e) => setSpecialty(e.target.value)}
            minLength={2} maxLength={100} placeholder="Ej. Gasfitería" required />
        </label>
        <div className="nw-form-grid">
          <label><span className="nw-quick-label"><CalendarDays size={16} /> Inicio estimado</span>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
          </label>
          <label><span className="nw-quick-label"><Users size={16} /> Trabajadores aprox.</span>
            <input type="number" min={1} max={10000} value={workers}
              onChange={(e) => setWorkers(Number(e.target.value))} required />
          </label>
        </div>
        <div className="nw-quick-priority">
          <span>Urgencia</span>
          <div className="nw-quick-options" role="group" aria-label="Nivel de urgencia">
            {[["normal", "Normal"], ["high", "Alta"], ["urgent", "Urgente"]].map(([value, label]) => (
              <button key={value} type="button" aria-pressed={priority === value}
                className={"nw-quick-priority-btn " + (priority === value ? "selected" : "")}
                onClick={() => setPriority(value)}>
                <span className={"nw-quick-dot nw-quick-dot-" + value} /> {label}
              </button>
            ))}
          </div>
        </div>
      </section>
      <section className="nw-quick-details" aria-label="Alcance y difusión">
        <h3><BriefcaseBusiness size={18} /> 2. Describe el trabajo</h3>
        <label>¿Qué labores se realizarán?
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
            required minLength={3} maxLength={2500} rows={3}
            placeholder="Ej. Instalación de redes sanitarias en departamentos, etapa terminaciones." />
        </label>
        <details className="nw-quick-more">
          <summary>Más opciones (opcional)</summary>
          <label>Título personalizado
            <input value={title} onChange={(e) => setTitle(e.target.value)}
              minLength={3} maxLength={180} placeholder={`Se necesita contratista de ${specialty || "tu oficio"}`} />
          </label>
          <div className="nw-quick-chips">
          <span>Partidas clave <small>(opcional)</small></span>
          <div className="nw-quick-chip-row">
            {QUICK_PARTS.map((part) => (
              <button className={parts.includes(part) ? "selected" : ""} key={part} type="button"
                aria-pressed={parts.includes(part)} onClick={() => togglePart(part)}>
                {parts.includes(part) ? <Check size={14} /> : <span aria-hidden="true">+</span>} {part}
              </button>
            ))}
          </div>
        </div>
        </details>
        <div className="nw-quick-facebook">
          <label className="nw-quick-facebook-heading">
            <input type="checkbox" checked={publishFacebook} onChange={(e) => setPublishFacebook(e.target.checked)} />
            <Facebook size={24} aria-hidden="true" />
            <strong>Publicar también en Facebook</strong>
          </label>
          <small>El anuncio incluirá la fotografía aprobada. No se mostrará el nombre de la obra.</small>
          {publishFacebook && <label>Ubicación aproximada para Facebook
            <input type="text" value={publicLocation}
              onChange={(e) => setPublicLocation(e.target.value)}
              maxLength={120} placeholder="Ej. Sector San Pedro de la Paz, Biobío"
              aria-describedby="nsp-location-help" />
            <small id="nsp-location-help">Solo comuna o sector. Se reutilizará automáticamente para esta obra en futuras convocatorias.</small>
          </label>}
        </div>
        <SocialPoster ref={posterEditor} enabled={publishFacebook} specialty={specialty}
          publicLocation={publicLocation} workers={workers} start={start} />
      </section>
      {error && <p className="nw-error nw-quick-error" role="alert">{error}</p>}
      <div className="nw-form-actions nw-quick-actions">
        <p><Send size={15} /> Puedes editar la necesidad después.</p>
        <button type="submit" value="draft" className="nw-btn" disabled={busy}>Guardar borrador</button>
        <button type="submit" value="published" className="nw-btn nw-primary" disabled={busy || !sites.length}>
          {busy ? "Publicando..." : "Publicar necesidad"}
        </button>
      </div>
    </form>
  );
}
