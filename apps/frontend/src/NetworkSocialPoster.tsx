import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { Camera, ImagePlus, MapPin, RefreshCw } from "lucide-react";
import "./network-social-poster.css";

export type SocialPosterHandle = { exportJpeg: () => Promise<string> };
type Props = {
  specialty: string;
  publicLocation: string;
  workers: number;
  start: string;
  enabled: boolean;
};

// Curated stock-photo slots. Administrators should replace/approve photographs
// for each specialty; a photographed trade must actually match the vacancy.
const PHOTO_SETS: Record<string, string[]> = {
  carpinteria: [
    "photo-1504307651254-35680f356dfd",
    "photo-1531835551805-16d864c8d311",
  ],
  electricidad: [
    "photo-1621905251189-08b45d6a269e",
    "photo-1581091226825-a6a2a5aee158",
  ],
  gasfiteria: [
    "photo-1581092160562-40aa08e78837",
    "photo-1600566753190-17f0baa2a6c3",
  ],
  pintura: [
    "photo-1562259949-e8e7689d7828",
    "photo-1600585154340-be6161a56a0c",
  ],
  construccion: [
    "photo-1504307651254-35680f356dfd",
    "photo-1503387762-592deb58ef4e",
  ],
};
const urlFor = (id: string) => "https://images.unsplash.com/" + id + "?w=1200&q=85&fit=crop&auto=format";

function categoryFor(role: string): string {
  const r = role.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  if (/carpinter|muebl|madera|techumbr/.test(r)) return "carpinteria";
  if (/electri|cable|tablero/.test(r)) return "electricidad";
  if (/gasfit|sanitari|fontan|tuber/.test(r)) return "gasfiteria";
  if (/pint|revestim/.test(r)) return "pintura";
  return "construccion";
}
function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const picture = new Image();
    picture.crossOrigin = "anonymous";
    picture.onload = () => resolve(picture);
    picture.onerror = () => reject(new Error("No se pudo preparar la fotografía. Selecciona otra o sube una propia."));
    picture.src = src;
  });
}
function cover(ctx: CanvasRenderingContext2D, img: HTMLImageElement, zoom: number, vertical: number) {
  const scale = Math.max(1080 / img.naturalWidth, 1350 / img.naturalHeight) * zoom;
  const w = img.naturalWidth * scale, h = img.naturalHeight * scale;
  ctx.drawImage(img, (1080 - w) / 2, (1350 - h) * vertical, w, h);
}
function shrink(ctx: CanvasRenderingContext2D, value: string, max: number, desired: number, min = 38) {
  let size = desired;
  while (size > min) {
    ctx.font = "900 " + size + "px Arial, sans-serif";
    if (ctx.measureText(value).width <= max) break;
    size -= 2;
  }
  return size;
}
function format(date: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "Por confirmar";
  return date.slice(8, 10) + "/" + date.slice(5, 7) + "/" + date.slice(0, 4);
}
export function publicCaption(specialty: string, location: string, workers: number, start: string) {
  return [
    "BUSCAMOS EMPRESAS CONTRATISTAS",
    "",
    "Especialidad: " + (specialty || "Por confirmar"),
    "Sector: " + (location || "Por confirmar"),
    "Dotación estimada: " + (workers || 1) + " trabajadores",
    "Inicio estimado: " + format(start),
    "",
    "¿Tu empresa realiza estos trabajos? Escríbenos por mensaje privado.",
  ].join("\n");
}

const SocialPoster = forwardRef<SocialPosterHandle, Props>(function SocialPoster(
  { specialty, publicLocation, workers, start, enabled }, ref,
) {
  const category = categoryFor(specialty);
  const candidates = useMemo(() => PHOTO_SETS[category].map(urlFor), [category]);
  const [choice, setChoice] = useState(0);
  const [uploaded, setUploaded] = useState("");
  const [tone, setTone] = useState<"teal" | "blue" | "copper">("teal");
  const [zoom, setZoom] = useState(1.12);
  const [vertical, setVertical] = useState(0.48);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [mobile, setMobile] = useState(false);
  const photo = uploaded || candidates[choice % candidates.length];

  useEffect(() => {
    setChoice(0);
    setUploaded("");
  }, [category]);
  useEffect(() => {
    if (!uploaded) return;
    return () => URL.revokeObjectURL(uploaded);
  }, [uploaded]);
  const compose = useCallback(async () => {
    if (!specialty.trim() || !publicLocation.trim()) {
      throw new Error("Completa el oficio y la comuna o sector aproximado.");
    }
    const image = await loadImage(photo);
    const canvas = document.createElement("canvas");
    canvas.width = 1080;
    canvas.height = 1350;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("El navegador no permite crear la imagen.");
    ctx.fillStyle = "#123b45";
    ctx.fillRect(0, 0, 1080, 1350);
    cover(ctx, image, zoom, vertical);
    const gradient = ctx.createLinearGradient(0, 390, 0, 1350);
    const base = tone === "blue" ? "7,27,65" : tone === "copper" ? "48,34,25" : "4,43,48";
    gradient.addColorStop(0, "rgba(" + base + ",0)");
    gradient.addColorStop(0.44, "rgba(" + base + ",0.68)");
    gradient.addColorStop(0.71, "rgba(" + base + ",0.98)");
    gradient.addColorStop(1, "rgba(" + base + ",1)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 390, 1080, 960);
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillStyle = "#fff";
    ctx.font = "800 40px Arial, sans-serif";
    ctx.fillText("CONVOCATORIA A CONTRATISTAS", 76, 810);
    ctx.fillStyle = "#73eee0";
    ctx.fillRect(76, 874, 125, 7);
    ctx.fillStyle = "#fff";
    ctx.font = "900 92px Arial, sans-serif";
    ctx.fillText("BUSCAMOS", 74, 908);
    let role = specialty.trim().toLocaleUpperCase("es-CL");
    const roleSize = shrink(ctx, role, 930, 100, 39);
    ctx.font = "900 " + roleSize + "px Arial, sans-serif";
    if (ctx.measureText(role).width <= 930) {
      ctx.fillText(role, 74, 1014);
    } else {
      // Limit the public artwork to one legible line, without affecting full caption.
      while (role.length > 3 && ctx.measureText(role + "…").width > 900) role = role.slice(0, -1);
      ctx.fillText(role + "…", 74, 1014);
    }
    ctx.fillStyle = "#fff";
    ctx.font = "600 35px Arial, sans-serif";
    const sector = "Sector: " + publicLocation.trim();
    const sectorSize = shrink(ctx, sector, 930, 35, 22);
    ctx.font = "600 " + sectorSize + "px Arial, sans-serif";
    ctx.fillText(sector, 76, 1140);
    ctx.fillStyle = "#61e3d7";
    ctx.fillRect(76, 1234, 929, 2);
    ctx.fillStyle = "#fff";
    ctx.font = "800 31px Arial, sans-serif";
    ctx.fillText("ESCRÍBENOS POR MENSAJE PRIVADO", 76, 1260);
    const data = canvas.toDataURL("image/jpeg", 0.84);
    if (data.length > 3_400_000) throw new Error("La imagen excede el límite, reduce su tamaño.");
    return data;
  }, [photo, specialty, publicLocation, tone, zoom, vertical]);

  useImperativeHandle(ref, () => ({ exportJpeg: compose }), [compose]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void compose().then((value) => {
        if (!cancelled) { setPreview(value); setError(""); }
      }).catch((cause: unknown) => {
        if (!cancelled) { setPreview(""); setError(cause instanceof Error ? cause.message : "No se pudo generar la imagen."); }
      });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [compose, enabled]);

  function upload(file?: File) {
    if (!file) return;
    if (!["image/png", "image/jpeg"].includes(file.type) || file.size > 8_000_000) {
      setError("Usa un JPG o PNG de hasta 8 MB."); return;
    }
    setUploaded(URL.createObjectURL(file));
    setError("");
  }
  if (!enabled) return null;
  return (
    <div className="nsp">
      <div className="nsp-heading">
        <div><strong>Imagen automática</strong><small>Se prepara a partir del oficio y el sector público</small></div>
        <span>1080 × 1350 · 4:5</span>
      </div>
      <div className="nsp-layout">
        <div className="nsp-editor">
          <div className="nsp-gallery">
            {candidates.map((src, index) => (
              <button type="button" key={src} aria-label={"Fotografía " + (index + 1)}
                aria-pressed={!uploaded && choice === index}
                className={!uploaded && choice === index ? "selected" : ""}
                onClick={() => { setChoice(index); setUploaded(""); }}>
                <img src={src} alt={"Fotografía " + (index + 1) + " para la especialidad"} />
              </button>
            ))}
            <label className="nsp-upload"><ImagePlus size={20}/> Subir foto
              <input type="file" accept="image/jpeg,image/png" onChange={(e) => upload(e.target.files?.[0])}/>
            </label>
          </div>
          <label>Estilo de colores
            <select value={tone} onChange={(e) => setTone(e.target.value as "teal" | "blue" | "copper")}>
              <option value="teal">Verde petróleo · recomendado</option>
              <option value="blue">Azul profesional</option>
              <option value="copper">Cobre industrial</option>
            </select>
          </label>
          <label>Acercar fotografía
            <input type="range" min="1" max="1.85" step="0.05" value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}/>
          </label>
          <label>Ajustar encuadre
            <input type="range" min="0" max="1" step="0.05" value={vertical}
              onChange={(e) => setVertical(Number(e.target.value))}/>
          </label>
          <p>La fotografía debe corresponder al oficio y no contener marcas ni rostros sin autorización. Puedes reemplazarla por una propia.</p>
          <button type="button" className="nsp-reset" onClick={() => {
            setChoice(0); setUploaded(""); setZoom(1.12); setVertical(0.48); setTone("teal");
          }}><RefreshCw size={14}/> Restablecer</button>
        </div>
        <div className="nsp-right">
          <div className="nsp-switch">
            <strong>Simulación del feed de Facebook</strong>
            <div><button type="button" className={!mobile ? "active" : ""} onClick={() => setMobile(false)}>Escritorio</button>
              <button type="button" className={mobile ? "active" : ""} onClick={() => setMobile(true)}>Móvil</button></div>
          </div>
          <div className={"nsp-facebook" + (mobile ? " mobile" : "")}>
            <div className="nsp-fbhead"><span className="nsp-profile"><Camera size={16}/></span><span><b>Página de Facebook</b><small>Vista previa · Público</small></span><b className="nsp-more">···</b></div>
            <p className="nsp-caption">{publicCaption(specialty, publicLocation, workers, start)}</p>
            {preview ? <img className="nsp-poster" src={preview} alt={"Anuncio para " + specialty + " en " + publicLocation}/> :
              <div className="nsp-empty">{error || "Generando imagen…"}</div>}
            <div className="nsp-reactions"><span>♡ Me gusta</span><span>▤ Comentar</span><span>↗ Compartir</span></div>
          </div>
          {error && <p role="alert" className="nsp-error">{error}</p>}
          <p className="nsp-disclaimer"><MapPin size={13}/> En Facebook solo aparecerá la ubicación aproximada, nunca el nombre interno de la obra.</p>
        </div>
      </div>
    </div>
  );
});
export default SocialPoster;
