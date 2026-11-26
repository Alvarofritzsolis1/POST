/** Shared presentation catalog for Red de Obras, not a change to Galancito or database taxonomy.
 * The 26 defaults are the reviewed proposal; existing organization-specific trades remain available.
 * Photo assets may be installed at assets/recruitment/<id>-<number>.jpg/webp/png.
 */
type TradeGroup = "Obra gruesa" | "Terminaciones" | "Instalaciones" | "Exteriores";
type Trade = { id: string; label: string; group: TradeGroup; glyph: string; aliases: string[]; };
const trade = (id: string, label: string, group: TradeGroup, glyph: string, aliases: string[] = []): Trade => ({ id, label, group, glyph, aliases });
export const RECRUITMENT_TRADES: readonly Trade[] = [
  trade("albanileria","Albañilería","Obra gruesa","🧱",["albañil","ladrillos","mampostería"]),
  trade("carpinteria","Carpintería","Terminaciones","🪚",["carpintero","madera","mueblista"]),
  trade("pintura","Pintura","Terminaciones","🎨",["pintor","pintar"]),
  trade("gasfiteria","Gasfitería","Instalaciones","🔧",["gasfiter","gafiter","fontanería","sanitario"]),
  trade("electricidad","Electricidad","Instalaciones","⚡",["eléctrico","electricista","cableado"]),
  trade("ceramica","Cerámica","Terminaciones","▦",["ceramista","azulejos","porcelanato"]),
  trade("enfierradura","Enfierradura","Obra gruesa","▥",["enfierrador","fierrero","acero"]),
  trade("hormigon","Hormigón","Obra gruesa","🏗",["hormigonado","hormigonero","concreto"]),
  trade("moldajes","Moldajes","Obra gruesa","▤",["encofrado","moldaje"]),
  trade("tabiqueria","Tabiquería","Terminaciones","▧",["tabique","tabiquero","metalcon","volcanita"]),
  trade("yeso","Yeso","Terminaciones","◩",["yesero","enyesado"]),
  trade("estuco","Estuco","Terminaciones","◪",["estuquero","estucado"]),
  trade("techumbre","Techumbre","Obra gruesa","⌂",["techumbres","techero","cubiertas"]),
  trade("impermeabilizacion","Impermeabilización","Terminaciones","💧",["impermeabilizar","membrana"]),
  trade("soldadura","Soldadura","Obra gruesa","✶",["soldador","sodadura"]),
  trade("estructuras-metalicas","Estructuras metálicas","Obra gruesa","⊞",["estructura metálica","montaje metálico"]),
  trade("ventanas","Ventanas","Terminaciones","⊟",["ventanero","vidrios","ventanería","aluminio"]),
  trade("puertas","Puertas","Terminaciones","🚪",["instalador puertas","puerta"]),
  trade("pisos","Pisos","Terminaciones","▨",["piso flotante","pavimentos interiores"]),
  trade("climatizacion","Climatización","Instalaciones","❄",["aire acondicionado","clima","hvac"]),
  trade("excavaciones","Excavaciones","Exteriores","⛏",["excavación","excavador"]),
  trade("movimiento-tierra","Movimiento de tierra","Exteriores","🚜",["movimiento de tierras","nivelación"]),
  trade("pavimentacion","Pavimentación","Exteriores","▰",["pavimentador","pavimentos"]),
  trade("jardineria","Jardinería","Exteriores","🌿",["jardinero","áreas verdes"]),
  trade("paisajismo","Paisajismo","Exteriores","🌳",["paisajista","paisaje"]),
  trade("terminaciones","Terminaciones","Terminaciones","✓",["acabados","remates"]),
];
export const normalizeTrade = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
export function tradeFor(value: string): Trade | undefined {
  const key = normalizeTrade(value);
  return RECRUITMENT_TRADES.find(t => normalizeTrade(t.label) === key)
    ?? RECRUITMENT_TRADES.find(t => t.aliases.some(a => normalizeTrade(a) === key));
}
export function matchesTrade(label: string, query: string): boolean {
  const needle = normalizeTrade(query);
  const item = tradeFor(label);
  return !needle || [label, ...(item?.aliases ?? []), item?.group ?? ""].some(s => normalizeTrade(s).includes(needle));
}
export function recruitmentOptions(extra: string[]): string[] {
  const seen = new Set<string>();
  return [...RECRUITMENT_TRADES.map(t => t.label), ...extra.map(s => tradeFor(s)?.label ?? s.trim())].filter(label => {
    const key = normalizeTrade(label);
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  });
}
// Existing stock slots are retained only for the corresponding trade. New trades
// must never silently inherit an unrelated construction photograph.
const existing: Record<string, string[]> = {
  carpinteria: ["photo-1531835551805-16d864c8d311"],
  electricidad: ["photo-1621905251189-08b45d6a269e","photo-1581091226825-a6a2a5aee158"],
  gasfiteria: ["photo-1581092160562-40aa08e78837","photo-1600566753190-17f0baa2a6c3"],
  pintura: ["photo-1562259949-e8e7689d7828","photo-1600585154340-be6161a56a0c"],
};
const installed = import.meta.glob<string>("./assets/recruitment/*.{jpg,jpeg,webp,png}", { eager: true, query: "?url", import: "default" });
export function recruitmentPhotos(label: string): string[] {
  const item = tradeFor(label);
  if (!item) return [];
  const prefix = "./assets/recruitment/" + item.id + "-";
  const local = Object.entries(installed).filter(([path]) => path.startsWith(prefix)).sort(([a],[b]) => a.localeCompare(b)).map(([,url]) => url);
  return local.length ? local : (existing[item.id] ?? []).map(id => "https://images.unsplash.com/" + id + "?w=1200&q=85&fit=crop&auto=format");
}
export function recruitmentTone(label: string): "teal" | "blue" | "copper" {
  const group = tradeFor(label)?.group;
  return group === "Obra gruesa" ? "copper" : group === "Instalaciones" ? "blue" : "teal";
}
export function initialRecruitmentSummary(label: string): string {
  const specialty = label.trim();
  return specialty.length >= 2 ? "Trabajos de " + specialty.toLocaleLowerCase("es-CL") + "." : "";
}
