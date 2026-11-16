import { useRef, useState, type FormEvent } from "react";
import { Facebook, Check, CalendarDays, BriefcaseBusiness, Users, Send } from "lucide-react";
import { change, type Catalog, type Requirement } from "./networkApi";
import { errorText, todayISO } from "./NetworkUI";

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
  const [siteId, setSiteId] = useState(sites[0]?.id ?? "");
  const [specialty, setSpecialty] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [start, setStart] = useState(todayISO());
  const [workers, setWorkers] = useState(1);
  const [priority, setPriority] = useState("normal");
  const [parts, setParts] = useState<string[]>([]);
  const [publishFacebook, setPublishFacebook] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function togglePart(part: string) {
    setParts((current) => current.includes(part) ? current.filter((item) => item !== part) : [...current, part]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const intent = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") || "published";
    if (!siteId || !specialty.trim() || title.trim().length < 3 || summary.trim().length < 3 || !start) {
      setError("Completa la obra, especialidad, título, resumen y fecha de inicio.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const entries = parts.length ? parts : [specialty.trim()];
      const response = await change<Requirement>("/requirements", {
        site_id: siteId,
        specialty: specialty.trim(),
        title: title.trim(),
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
      <div className="nw-quick-intro">
        <p>Completa lo esencial. La programación y las cantidades específicas se pueden definir después.</p>
      </div>
      <section className="nw-quick-fields" aria-label="Datos de la necesidad">
        <h3>Datos de la necesidad</h3>
        <label>Obra
          {sites.length === 1 ? (
            <span className="nw-site-locked">{sites[0].name}</span>
          ) : (
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)} required>
              <option value="">Selecciona una obra</option>
              {sites.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}
            </select>
          )}
        </label>
        <label>Especialidad
          <input list="network-specialties" value={specialty} onChange={(e) => setSpecialty(e.target.value)}
            minLength={2} maxLength={100} placeholder="Ej. Gasfitería" required />
        </label>
        <label>¿Qué contratista necesitas?
          <input value={title} onChange={(e) => setTitle(e.target.value)}
            minLength={3} maxLength={180} placeholder="Ej. Gasfiter para terminaciones interiores" required />
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
        <h3><BriefcaseBusiness size={18} /> Resumen del trabajo</h3>
        <label>Describe brevemente lo que se necesita
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
            required minLength={3} maxLength={2500} rows={5}
            placeholder="Ej. Instalación de redes sanitarias en departamentos, etapa terminaciones." />
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
        <div className="nw-quick-facebook">
          <label className="nw-quick-facebook-heading">
            <input type="checkbox" checked={publishFacebook} onChange={(e) => setPublishFacebook(e.target.checked)} />
            <Facebook size={24} aria-hidden="true" />
            <strong>Publicar también en Facebook</strong>
          </label>
          <p>Activado por defecto. Puedes desmarcarlo. El anuncio solo se enviará si la página está autorizada y la conexión está habilitada.</p>
          {publishFacebook && (
            <div className="nw-quick-facebook-preview">
              <b><Facebook size={16} /> Vista previa de la difusión</b>
              <span>{title || "Tu necesidad de contratista"} · {specialty || "Especialidad"}</span>
              <small>{sites.find((site) => site.id === siteId)?.name || "Obra"} · Inicio: {start} · {workers} trabajador(es)</small>
              <small>Solo se publican datos del anuncio, sin notas privadas ni documentos.</small>
            </div>
          )}
        </div>
      </section>
      {error && <p className="nw-error nw-quick-error" role="alert">{error}</p>}
      <div className="nw-form-actions nw-quick-actions">
        <p><Send size={15} /> Los detalles de programación y las cantidades se confirman antes de adjudicar.</p>
        <button type="submit" value="draft" className="nw-btn" disabled={busy}>Guardar borrador</button>
        <button type="submit" value="published" className="nw-btn nw-primary" disabled={busy || !sites.length}>
          {busy ? "Guardando..." : "Crear necesidad"}
        </button>
      </div>
    </form>
  );
}
