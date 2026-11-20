import { ArrowRight, Clock3, Inbox, Megaphone, Users } from "lucide-react";
import "./facebook-overview.css";

type Counts = {
  contacts: number;
  unread: number;
  published_ads: number;
  pending_ads: number;
};
type Contact = {
  id: string;
  name: string;
  company: string;
  specialty: string;
  trades?: string[];
  unread: boolean;
  last_inbound_at: string | null;
};
type Publication = {
  id: string;
  title: string;
  specialty: string;
  state: string;
  post_url: string | null;
  updated_at?: string;
};

type Props = {
  loading: boolean;
  counts?: Counts;
  leads: Contact[];
  publications: Publication[];
  onOpenConversations: (unreadOnly: boolean) => void;
  onOpenTracking: () => void;
  onOpenPublications: () => void;
  onOpenPending: () => void;
  onOpenContact: (id: string) => void;
};

const validDate = (value?: string | null) => {
  if (!value) return "Sin fecha registrada";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Fecha no disponible";
  return new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeZone: "America/Santiago" }).format(parsed);
};
const postLabels: Record<string, string> = {
  published: "Publicado",
  pending: "En cola",
  sending: "Enviando",
  failed: "Error de publicación",
  uncertain: "Revisar en Meta",
  deleted: "Retirado",
  cancelled: "Cancelado",
  not_queued: "Sin enviar",
};

/** Vista de lectura. No crea estadísticas históricas ni efectúa mutaciones en Meta. */
export default function FacebookOverview({
  loading, counts, leads, publications,
  onOpenConversations, onOpenTracking, onOpenPublications, onOpenPending, onOpenContact,
}: Props) {
  const categoryCounts = new Map<string, number>();
  let classified = 0;
  for (const contact of leads) {
    const trades = [...new Set((contact.trades?.length ? contact.trades : [contact.specialty])
      .map((trade) => trade.trim()).filter((trade) => trade && !/^(sin clasificar|por confirmar|desconocid)/i.test(trade)))];
    if (trades.length) classified += 1;
    trades.forEach((trade) => categoryCounts.set(trade, (categoryCounts.get(trade) || 0) + 1));
  }
  const categories = [...categoryCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const recentContacts = [...leads]
    .filter((lead) => lead.last_inbound_at)
    .sort((a, b) => (b.last_inbound_at || "").localeCompare(a.last_inbound_at || ""))
    .slice(0, 4);
  const recentPosts = [...publications]
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""))
    .slice(0, 4);

  if (loading) return <section className="fbov fbov-empty" role="status">Cargando datos de Facebook…</section>;
  if (!counts) return <section className="fbov fbov-empty" role="status">No se pudo cargar el resumen. Comprueba la conexión e inténtalo nuevamente.</section>;

  return (
    <section className="fbov" aria-label="Resumen de Facebook">
      <header className="fbov-heading">
        <div>
          <h3>Resumen</h3>
        </div>
      </header>

      <div className="fbov-metrics" aria-label="Indicadores de Facebook">
        <button type="button" title="Hasta 100 contactos recientes; no son postulaciones confirmadas" className="fbov-metric fbov-primary" onClick={onOpenTracking}
          aria-label={"Abrir seguimiento de contactos; " + counts.contacts + " contactos en los datos recientes"}>
          <span className="fbov-metric-icon"><Users size={22} /></span>
          <span className="fbov-metric-copy"><span>Contactos recientes</span>
            <strong>{counts.contacts.toLocaleString("es-CL")}</strong>
          </span>
          <ArrowRight size={18} className="fbov-arrow" aria-hidden="true" />
        </button>
        <button type="button" title="Conversaciones sin leer entre contactos recientes" className="fbov-metric" onClick={() => onOpenConversations(true)}>
          <Inbox size={22} className="fbov-blue" />
          <span>Sin leer</span><strong>{counts.unread.toLocaleString("es-CL")}</strong>
        </button>
        <button type="button" title="Hasta 200 envíos recientes" className="fbov-metric" onClick={onOpenPublications}>
          <Megaphone size={22} className="fbov-purple" />
          <span>Publicadas</span><strong>{counts.published_ads.toLocaleString("es-CL")}</strong>
        </button>
        <button type="button" title="Anuncios pendientes de revisión" className="fbov-metric" onClick={onOpenPending}>
          <Clock3 size={22} className="fbov-amber" />
          <span>Por revisar</span><strong>{counts.pending_ads.toLocaleString("es-CL")}</strong>
        </button>
      </div>

      <div className="fbov-layout">
        <section className="fbov-panel fbov-posts" aria-labelledby="fbov-posts-title">
          <div className="fbov-panel-heading">
            <div><h4 id="fbov-posts-title">Publicaciones recientes</h4></div>
            <button type="button" className="fbov-link" onClick={onOpenPublications}>Ver todas <ArrowRight size={15} /></button>
          </div>
          {!recentPosts.length ? <p className="fbov-no-data">Todavía no hay publicaciones registradas.</p> :
            <div className="fbov-rows">
              {recentPosts.map((post) => <div className="fbov-row" key={post.id}>
                <span className="fbov-post-symbol"><Megaphone size={17}/></span>
                <div className="fbov-row-main"><strong>{post.title}</strong>
                  <small>{post.specialty || "Oficio no informado"} · {validDate(post.updated_at)}</small></div>
                <span className={"fbov-pill " + (post.state === "published" ? "ok" :
                  ["failed", "uncertain"].includes(post.state) ? "bad" : "neutral")}>
                  {postLabels[post.state] || post.state}</span>
                <button type="button" className="fbov-row-action" onClick={onOpenPublications}
                  aria-label={"Gestionar publicación " + post.title}><ArrowRight size={17}/></button>
              </div>)}
            </div>}
        </section>
        <section className="fbov-panel" aria-labelledby="fbov-specialties-title">
          <div className="fbov-panel-heading">
            <div><h4 id="fbov-specialties-title">Por especialidad</h4>
              <small>{classified} de {leads.length} contactos con oficio conocido</small></div>
          </div>
          {!categories.length ? <p className="fbov-no-data">Aún no se han identificado oficios.</p> :
            <div className="fbov-bars">
              {categories.map(([category, count]) => <div key={category} className="fbov-bar-item">
                <div className="fbov-bar-label"><span>{category}</span><strong>{count}</strong></div>
                <div className="fbov-bar-track" aria-label={category + ": " + count + " contactos de " + classified + " clasificados"}>
                  <span style={{ width: (classified ? (count / classified) * 100 : 0) + "%" }}/>
                </div>
              </div>)}
              <small>Recuento por oficio declarado; un contacto puede tener varias especialidades.</small>
            </div>}
        </section>
        <section className="fbov-panel fbov-recent" aria-labelledby="fbov-contacts-title">
          <div className="fbov-panel-heading">
            <div><h4 id="fbov-contacts-title">Conversaciones recientes</h4></div>
            <button type="button" className="fbov-link" onClick={() => onOpenConversations(false)}>
              Ver todas <ArrowRight size={15}/>
            </button>
          </div>
          {!recentContacts.length ? <p className="fbov-no-data">No hay mensajes recientes con fecha registrada.</p> :
            <div className="fbov-rows">
              {recentContacts.map((contact) => <button type="button" className="fbov-contact" key={contact.id}
                onClick={() => onOpenContact(contact.id)}>
                <span className="fbov-avatar">{(contact.name && contact.name !== "Interesado de Facebook" ?
                  contact.name : contact.company || "?").slice(0, 1).toUpperCase()}</span>
                <span className="fbov-row-main"><strong>{contact.name && contact.name !== "Interesado de Facebook" ?
                  contact.name : contact.company || "Contacto sin nombre"}</strong>
                  <small>{contact.specialty || "Oficio pendiente"} · {validDate(contact.last_inbound_at)}</small></span>
                {contact.unread && <span className="fbov-unread" title="Mensaje pendiente" aria-label="Mensaje pendiente" />}
                <ArrowRight size={16} aria-hidden="true" />
              </button>)}
            </div>}
        </section>
      </div>
    </section>
  );
}
