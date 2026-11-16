import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  BadgeCheck, ClipboardCheck, ExternalLink, Eye, Facebook, Info, LoaderCircle,
  MapPin, Plus, RefreshCcw, Send, ShieldCheck, Trash2,
} from "lucide-react";
import { change, net, type Catalog, type Page, type Requirement } from "./networkApi";
import { errorText, todayISO } from "./NetworkUI";
import "./network-facebook.css";

type ContactMode = "messenger" | "email" | "whatsapp";
type Ad = {
  site_id: string; title: string; specialty: string; city: string; region: string;
  workers: number; start_date: string; end_date: string; deadline: string;
  items: string[]; requirements: string; contact_mode: ContactMode; contact_value: string;
};
type Preview = { message: string; preview_hash: string; character_count: number };
type Trial = {
  id: string; kind: "verify" | "publish" | "delete";
  state: string; title: string; page_name: string | null;
  post_url: string | null; error: string | null; created_at: string;
};
type Status = {
  manual_enabled: boolean; automatic_enabled: boolean;
  page_id: string; verified_page_name: string | null; history: Trial[];
};
const stages: Record<string, string> = {
  pending: "En cola", sending: "Enviando a Meta", verified: "Identidad comprobada",
  published: "Publicado", deleted: "Retirado", failed: "Error de Meta",
  uncertain: "Revisar en Facebook", cancelled: "Cancelado",
};
const blank = (): Ad => ({
  site_id: "", title: "", specialty: "", city: "", region: "",
  workers: 1, start_date: todayISO(), end_date: todayISO(),
  deadline: todayISO(), items: [""], requirements: "",
  contact_mode: "messenger", contact_value: "",
});
const cleanPost = (value: string) => value.replace(/\r\n/g, "\n");

export default function NetworkFacebook({ catalog }: { catalog: Catalog }) {
  const [ad, setAd] = useState<Ad>(blank);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewData, setPreviewData] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [opportunities, setOpportunities] = useState<Requirement[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const key = useRef(crypto.randomUUID());
  const currentSnapshot = JSON.stringify(ad);
  const previewReady = !!preview && previewData === currentSnapshot;

  const reload = useCallback(async () => {
    const data = await net<Status>("/facebook/tests");
    setStatus(data);
  }, []);
  useEffect(() => {
    let active = true;
    void reload().catch((err) => { if (active) setError(errorText(err)); });
    void net<Page<Requirement>>("/requirements?limit=100&offset=0")
      .then((result) => { if (active) setOpportunities(result.rows.filter((r) => r.state === "published")); })
      .catch(() => { /* La carga opcional no impide la creación manual. */ });
    const timer = window.setInterval(() => { if (active && !document.hidden) void reload().catch(() => {}); }, 7000);
    return () => { active = false; clearInterval(timer); };
  }, [reload]);
  useEffect(() => {
    if (catalog.sites.length && !ad.site_id)
      setAd((previous) => ({ ...previous, site_id: catalog.sites[0].id }));
  }, [catalog.sites, ad.site_id]);

  function changeAd<K extends keyof Ad>(name: K, value: Ad[K]) {
    setAd((old) => ({ ...old, [name]: value }));
    setPreview(null);
    setAcknowledged(false);
    setError("");
    setNotice("");
  }
  function setItem(index: number, value: string) {
    changeAd("items", ad.items.map((part, idx) => idx === index ? value : part));
  }
  function sourceRequirement(id: string) {
    setSourceId(id);
    const req = opportunities.find((r) => r.id === id);
    if (!req) return;
    setAd((old) => ({
      ...old, site_id: req.site_id, title: req.title, specialty: req.specialty,
      workers: req.workers, start_date: req.start_date, end_date: req.end_date,
      deadline: req.deadline,
      // No importar descripciones internas, notas ni antecedentes de contratistas.
      items: req.items.map((item) => item.name).slice(0, 10),
      requirements: "",
    }));
    setPreview(null);
    setAcknowledged(false);
  }
  async function getPreview(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setWorking("preview"); setError(""); setNotice(""); setAcknowledged(false);
    try {
      const result = await change<Preview>("/facebook/tests/preview", ad);
      setPreview(result);
      setPreviewData(JSON.stringify(ad));
      setNotice("Vista previa validada. Ninguna publicación ha sido enviada.");
    } catch (err) {
      setPreview(null);
      setError(errorText(err));
    } finally {
      setWorking("");
    }
  }
  async function verify() {
    setWorking("verify"); setError(""); setNotice("");
    try {
      await change("/facebook/tests/verify");
      setNotice("Comprobación solicitada. El resultado aparecerá en el historial.");
      await reload();
    } catch (err) { setError(errorText(err)); }
    finally { setWorking(""); }
  }
  async function publish() {
    if (!preview || !previewReady || !acknowledged || !status?.manual_enabled) return;
    if (!window.confirm("Esta prueba SE PUBLICARÁ en tu página real de Facebook y podrá verla cualquier persona. ¿Deseas continuar?")) return;
    setWorking("publish"); setError(""); setNotice("");
    try {
      await change("/facebook/tests/publish", {
        ad, preview_hash: preview.preview_hash,
        confirmation: "PUBLICAR PRUEBA", client_key: key.current,
      });
      setNotice("Envío solicitado. Revisa el historial para confirmar si Meta publicó el anuncio.");
      setAcknowledged(false);
      key.current = crypto.randomUUID();
      await reload();
    } catch (err) { setError(errorText(err)); }
    finally { setWorking(""); }
  }
  async function remove(row: Trial) {
    if (!window.confirm("¿Retirar esta publicación de prueba de tu página de Facebook?")) return;
    setWorking(row.id); setError(""); setNotice("");
    try {
      await change("/facebook/tests/" + row.id + "/remove", { confirmation: "RETIRAR PRUEBA" });
      setNotice("Retiro solicitado. Se confirmará en el historial.");
      await reload();
    } catch (err) { setError(errorText(err)); }
    finally { setWorking(""); }
  }
  const disabled = !!working;
  return (
    <div className="nwf">
      <div className="nwf-head">
        <div>
          <span className="nwf-overline"><Facebook size={15} /> CANAL EXTERNO · SOLO ADMINISTRACIÓN</span>
          <h2>Publicar en Facebook</h2>
          <p>Prepara un anuncio de contratistas, revisa exactamente qué verá el público y realiza una prueba controlada.</p>
        </div>
        <div className="nwf-connected">
          <span className={"nwf-status-dot " + (status?.verified_page_name ? "good" : "")} />
          <span><strong>{status?.verified_page_name || "Identidad sin comprobar"}</strong><small>Página {status?.page_id || "no configurada"} · publicación de prueba</small></span>
        </div>
      </div>
      <div className="nwf-notice nwf-notice-info">
        <Info size={18} />
        <div><strong>Modo de prueba. No es una oferta real.</strong>
          <p>El anuncio llevará la marca «PUBLICACIÓN DE PRUEBA». Previsualizar o comprobar la identidad NO publica nada. Solo el botón «Publicar prueba real», con tu confirmación, envía un post visible a Facebook.</p>
        </div>
      </div>
      <div className="nwf-connection">
        <div className="nwf-connection-main">
          <ShieldCheck size={22} />
          <div><b>Conexión con Facebook</b>
            <p>{status?.manual_enabled
              ? (status.verified_page_name
                ? "Identidad del token y página confirmada. El permiso para publicar se comprueba al enviar una prueba."
                : "Puedes comprobar la identidad de tu página sin publicar contenido.")
              : "El modo de pruebas está apagado en el VPS. Puedes preparar y previsualizar, pero no enviar."}</p>
            {status?.automatic_enabled && <small>La difusión automática también está activada: revisa su configuración antes de publicar.</small>}
          </div>
        </div>
        <button className="nw-btn" type="button" disabled={disabled || !status?.manual_enabled} onClick={() => void verify()}>
          {working === "verify" ? <LoaderCircle size={16} className="nwf-spin" /> : <ShieldCheck size={16} />}
          Comprobar conexión
        </button>
      </div>
      <div className="nwf-main">
        <form className="nwf-form nwf-panel" onSubmit={(event) => void getPreview(event)}>
          <div className="nwf-panel-header">
            <div><span className="nwf-step">01</span><h3>Datos del anuncio</h3></div>
            <small>Los campos con * son obligatorios.</small>
          </div>
          <div className="nwf-form-body">
            <label>Usar información de Red de Obras <span>Opcional</span>
              <select value={sourceId} onChange={(e) => sourceRequirement(e.target.value)}>
                <option value="">Completar manualmente</option>
                {opportunities.map((r) => <option key={r.id} value={r.id}>{r.title} · {r.site}</option>)}
              </select>
              <small>Solo carga datos públicos; no incluye descripciones internas.</small>
            </label>
            <label>Obra <span>*</span>
              <select value={ad.site_id} required onChange={(e) => changeAd("site_id", e.target.value)}>
                <option value="">Selecciona una obra</option>
                {catalog.sites.map((s) => <option value={s.id} key={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label>Nombre del anuncio <span>*</span>
              <input required minLength={5} maxLength={140} value={ad.title} onChange={(e) => changeAd("title", e.target.value)}
                placeholder="Ej. Empresas de carpintería para terminaciones" />
            </label>
            <div className="nwf-grid">
              <label>Especialidad <span>*</span>
                <input required minLength={2} maxLength={100} value={ad.specialty} list="network-specialties" onChange={(e) => changeAd("specialty", e.target.value)} placeholder="Carpintería" />
              </label>
              <label>Dotación estimada <span>*</span>
                <input required type="number" min={1} max={1000} value={ad.workers} onChange={(e) => changeAd("workers", Number(e.target.value))} />
              </label>
              <label>Comuna <span>*</span>
                <input required minLength={2} maxLength={90} value={ad.city} onChange={(e) => changeAd("city", e.target.value)} placeholder="Coronel" />
              </label>
              <label>Región <span>*</span>
                <input required minLength={2} maxLength={90} value={ad.region} onChange={(e) => changeAd("region", e.target.value)} placeholder="Región del Biobío" />
              </label>
              <label>Inicio estimado <span>*</span>
                <input required type="date" value={ad.start_date} onChange={(e) => changeAd("start_date", e.target.value)} />
              </label>
              <label>Término estimado <span>*</span>
                <input required type="date" min={ad.start_date} value={ad.end_date} onChange={(e) => changeAd("end_date", e.target.value)} />
              </label>
              <label>Fecha límite para contactar <span>*</span>
                <input required type="date" max={ad.end_date} value={ad.deadline} onChange={(e) => changeAd("deadline", e.target.value)} />
              </label>
            </div>
            <div className="nwf-items">
              <div className="nwf-row-between"><div><b>Partidas a ejecutar</b><small>Se muestran en la publicación, sin información privada.</small></div>
                <button className="nw-btn" type="button" disabled={ad.items.length >= 10} onClick={() => changeAd("items", [...ad.items, ""])}><Plus size={15} /> Agregar partida</button>
              </div>
              {ad.items.map((item, index) => (
                <div className="nwf-item" key={index}>
                  <span>{index + 1}</span>
                  <input aria-label={"Partida " + (index + 1)} required minLength={2} maxLength={120}
                    value={item} onChange={(e) => setItem(index, e.target.value)} placeholder="Ej. Instalación de puertas interiores" />
                  <button title="Eliminar partida" aria-label={"Eliminar partida " + (index + 1)} disabled={ad.items.length === 1}
                    type="button" onClick={() => changeAd("items", ad.items.filter((_, i) => i !== index))}><Trash2 size={16} /></button>
                </div>
              ))}
            </div>
            <label>Requisitos para empresas <span>Opcional</span>
              <textarea rows={3} maxLength={800} value={ad.requirements} onChange={(e) => changeAd("requirements", e.target.value)}
                placeholder="Ej. Experiencia comprobable, disponibilidad según programa y documentación contractual al día." />
              <small>No incluyas RUT, documentos personales ni información confidencial.</small>
            </label>
            <label>¿Cómo deben contactarte? <span>*</span>
              <select value={ad.contact_mode} onChange={(e) => {
                setAd((old) => ({ ...old, contact_mode: e.target.value as ContactMode, contact_value: "" }));
                setPreview(null); setAcknowledged(false);
              }}>
                <option value="messenger">Mensaje privado a la página (recomendado)</option>
                <option value="email">Correo comercial público</option>
                <option value="whatsapp">WhatsApp comercial público</option>
              </select>
            </label>
            {ad.contact_mode !== "messenger" && (
              <label>{ad.contact_mode === "email" ? "Correo comercial" : "Número de WhatsApp"} <span>*</span>
                <input required type={ad.contact_mode === "email" ? "email" : "tel"} value={ad.contact_value}
                  onChange={(e) => changeAd("contact_value", e.target.value)}
                  placeholder={ad.contact_mode === "email" ? "contacto@empresa.cl" : "+56912345678"} />
                <small>Este dato quedará visible para cualquier persona en Facebook.</small>
              </label>
            )}
            <div className="nwf-form-footer">
              <button className="nw-btn nw-primary" type="submit" disabled={disabled}>
                {working === "preview" ? <LoaderCircle size={16} className="nwf-spin" /> : <Eye size={16} />}
                Generar vista previa
              </button>
              <span>Sin publicar en Facebook</span>
            </div>
          </div>
        </form>
        <aside className="nwf-right">
          <div className="nwf-panel">
            <div className="nwf-panel-header">
              <div><span className="nwf-step">02</span><h3>Vista previa de Facebook</h3></div>
              <small>{previewReady ? "Validada por GALANT" : "Pendiente"}</small>
            </div>
            <div className="nwf-fb">
              <div className="nwf-fb-head"><span className="nwf-fb-icon"><Facebook size={20} /></span>
                <div><strong>{status?.verified_page_name || "Portal Trabajo Contratistas De Construccion"}</strong>
                  <small>Página de Facebook · Publicación de prueba · Pública</small>
                </div>
              </div>
              {previewReady ? (
                <div className="nwf-fb-text">{cleanPost(preview!.message)}</div>
              ) : (
                <div className="nwf-fb-empty"><Eye size={25} /><b>Tu anuncio aparecerá aquí</b><p>Completa el formulario y selecciona «Generar vista previa» para revisar el texto exacto antes de publicarlo.</p></div>
              )}
            </div>
            <div className="nwf-preview-foot">
              <span>{previewReady ? preview!.character_count.toLocaleString("es-CL") + " caracteres" : "Aún no validado"}</span>
              <span><MapPin size={13} /> Solo tu página, no grupos externos</span>
            </div>
          </div>
          <div className="nwf-panel nwf-publish">
            <div className="nwf-panel-header"><div><span className="nwf-step">03</span><h3>Publicación de prueba</h3></div></div>
            <div className="nwf-publish-body">
              <p>{status?.manual_enabled
                ? "El envío de prueba creará una publicación REAL en tu página. Podrás retirarla desde el historial."
                : "La publicación real está bloqueada por configuración del VPS. La vista previa sí funciona."}</p>
              <label className="nwf-confirm">
                <input type="checkbox" checked={acknowledged} disabled={!previewReady || !status?.manual_enabled} onChange={(e) => setAcknowledged(e.target.checked)} />
                Confirmo que revisé el anuncio y entiendo que será público en Facebook.
              </label>
              <button className="nw-btn nw-primary nwf-send" type="button"
                disabled={disabled || !status?.manual_enabled || !previewReady || !acknowledged}
                onClick={() => void publish()}>
                {working === "publish" ? <LoaderCircle size={16} className="nwf-spin" /> : <Send size={16} />}
                Publicar prueba real
              </button>
              <small>Se requiere confirmar antes del envío. Los errores inciertos no se reintentan automáticamente.</small>
            </div>
          </div>
        </aside>
      </div>
      {error && <div className="nwf-feedback nwf-feedback-error" role="alert">{error}</div>}
      {notice && <div className="nwf-feedback" role="status"><BadgeCheck size={17} />{notice}</div>}
      <section className="nwf-history nwf-panel">
        <div className="nwf-panel-header">
          <div><span className="nwf-step"><ClipboardCheck size={17} /></span><h3>Historial y resultados</h3></div>
          <button type="button" className="nw-btn" onClick={() => void reload().catch((err) => setError(errorText(err)))}><RefreshCcw size={15} /> Actualizar</button>
        </div>
        {!status?.history.length ? <div className="nwf-history-empty">Todavía no hay comprobaciones ni publicaciones de prueba.</div> : (
          <div className="nwf-history-list">
            {status.history.map((r) => (
              <div className="nwf-history-row" key={r.id}>
                <div className={"nwf-history-indicator " + (["published", "verified", "deleted"].includes(r.state) ? "ok" : ["failed", "uncertain"].includes(r.state) ? "bad" : "")} />
                <div className="nwf-history-main"><b>{r.title}</b><span>{r.kind === "verify" ? "Comprobación de conexión" : r.kind === "delete" ? "Retiro de prueba" : "Publicación de prueba"} · {new Date(r.created_at).toLocaleString("es-CL")}</span>
                  {r.error && <small role="alert">{r.error}</small>}
                </div>
                <span className="nwf-history-state">{stages[r.state] || r.state}</span>
                {r.post_url && <a href={r.post_url} target="_blank" rel="noopener noreferrer">Ver en Facebook <ExternalLink size={13} /></a>}
                {r.state === "published" && r.kind === "publish" && (
                  <button type="button" className="nw-btn" disabled={disabled} onClick={() => void remove(r)}><Trash2 size={14} /> Retirar prueba</button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <p className="nwf-footer-note">Pruebas para una página que administras. La API oficial de Meta no permite publicar automáticamente en grupos ajenos.</p>
    </div>
  );
}
