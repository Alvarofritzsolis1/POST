import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileCheck2,
  LayoutDashboard,
  LayoutGrid,
  List,
  MessageSquare,
  Network,
  Plus,
  Search,
  Send,
  Sparkles,
  Users,
  Workflow,
} from "lucide-react";
import type { Profile } from "./api";
import {
  attach,
  change,
  net,
  type Attachment,
  type Award,
  type CalendarEvent,
  type Capacity,
  type Catalog,
  type Conversation,
  type Coordination,
  type Item,
  type Match,
  type Messages,
  type Overview,
  type Page,
  type Requirement,
} from "./networkApi";
import {
  AwardForm,
  AwardProgressForm,
  AwardRevisionForm,
  CapacityForm,
  RequirementForm,
} from "./NetworkForms";
import { NetworkAccountMenu } from "./NetworkAccounts";
import {
  Badge,
  dateText,
  dateTime,
  Drawer,
  Empty,
  errorText,
  labels,
  number,
  todayISO,
} from "./NetworkUI";
import "./network.css";

const tabs = [
  ["home", "Inicio", LayoutDashboard],
  ["requirements", "Necesito contratista", Building2],
  ["capacities", "Contratistas con capacidad", Users],
  ["matches", "Coincidencias", Sparkles],
  ["awards", "Adjudicaciones", FileCheck2],
  ["messages", "Mensajes", MessageSquare],
  ["calendar", "Calendario", CalendarDays],
] as const;
const steps = [
  "interested",
  "contacted",
  "evaluating",
  "confirmed",
  "proposed",
  "approved",
  "documents_pending",
  "documents_complete",
  "finished",
];
type History = Page<{
  id: string;
  kind: string;
  actor: string;
  at: string;
  title: string;
  reason: string;
  details: { label: string; before: string | null; after: string }[];
}>;
const emptyCatalog: Catalog = { sites: [], contractors: [], specialties: [] };

export function ResidentNetwork({
  user,
  version,
  logout,
}: {
  user: Profile;
  version: string | null;
  logout: () => void;
}) {
  return (
    <div className="nw nw-resident-shell">
      <header className="nw-resident-header">
        <div className="nw-brand">
          <span>
            <Network size={23} />
          </span>
          <div>
            <b>GALANT POST</b>
            <small>Red de Obras</small>
          </div>
        </div>
        <NetworkAccountMenu user={user} logout={logout} />
      </header>
      <main>
        <RedDeObras user={user} />
      </main>
      <footer>GALANT POST · Red de Obras · v{version}</footer>
    </div>
  );
}

export default function RedDeObras({ user }: { user: Profile }) {
  const [tab, setTab] = useState("home"),
    [catalog, setCatalog] = useState<Catalog>(emptyCatalog);
  const [overview, setOverview] = useState<Overview | null>(null),
    [reqs, setReqs] = useState<Page<Requirement>>({ rows: [], total: 0 });
  const [caps, setCaps] = useState<Page<Capacity>>({ rows: [], total: 0 }),
    [matches, setMatches] = useState<Page<Match>>({ rows: [], total: 0 });
  const [awards, setAwards] = useState<Page<Award>>({ rows: [], total: 0 }),
    [coords, setCoords] = useState<Page<Coordination>>({ rows: [], total: 0 });
  const [conversations, setConversations] = useState<Page<Conversation>>({
    rows: [],
    total: 0,
  });
  const [site, setSite] = useState(""),
    [specialty, setSpecialty] = useState(""),
    [search, setSearch] = useState(""),
    [priority, setPriority] = useState("");
  const [mode, setMode] = useState("cards"),
    [page, setPage] = useState(0),
    [mine, setMine] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [loading, setLoading] = useState(true);
  const [panel, setPanel] = useState(""),
    [selectedReq, setSelectedReq] = useState<Requirement | null>(null),
    [selectedCap, setSelectedCap] = useState<Capacity | null>(null);
  const [selectedItem, setSelectedItem] = useState<Item | null>(null),
    [selectedAward, setSelectedAward] = useState<Award | null>(null);
  const [conversationId, setConversationId] = useState(""),
    [activeCoord, setActiveCoord] = useState<Coordination | null>(null);
  const [files, setFiles] = useState<Attachment[]>([]),
    [history, setHistory] = useState<History>({ rows: [], total: 0 });
  const generation = useRef(0);
  const canPublish =
    ["admin", "resident", "supervisor", "analyst"].includes(user.role) &&
    catalog.sites.some((s) => s.editable);
  const query = new URLSearchParams({
    ...(site ? { site_id: site } : {}),
    ...(specialty ? { specialty } : {}),
  }).toString();
  const refresh = useCallback(async () => {
    const id = ++generation.current;
    const suffix =
      "?" + query + (query ? "&" : "") + "limit=24&offset=" + page * 24;
    try {
      const data = await Promise.all([
        net<Catalog>("/catalog"),
        net<Overview>("/overview?" + query + (mine ? "&mine=true" : "")),
        ["home", "requirements"].includes(tab)
          ? net<Page<Requirement>>(
              "/requirements" +
                suffix +
                "&q=" +
                encodeURIComponent(search) +
                "&priority=" +
                priority +
                "&mine=" +
                mine,
            )
          : null,
        ["home", "capacities"].includes(tab)
          ? net<Page<Capacity>>(
              "/capacities" + suffix + "&q=" + encodeURIComponent(search),
            )
          : null,
        ["home", "matches"].includes(tab)
          ? net<Page<Match>>("/matches" + suffix)
          : null,
        tab === "awards" ? net<Page<Award>>("/awards" + suffix) : null,
        tab === "matches"
          ? net<Page<Coordination>>("/coordinations?limit=100")
          : null,
        tab === "messages"
          ? net<Page<Conversation>>(
              "/conversations?limit=24&offset=" + page * 24,
            )
          : null,
      ]);
      if (id !== generation.current) return;
      const [cat, o, r, c, m, a, co, conv] = data;
      setCatalog(cat);
      setOverview(o);
      if (r) setReqs(r);
      if (c) setCaps(c);
      if (m) setMatches(m);
      if (a) setAwards(a);
      if (co) setCoords(co);
      if (conv) setConversations(conv);
      setError("");
    } catch (err) {
      if (id === generation.current) setError(errorText(err));
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }, [tab, query, page, search, priority, mine]);
  useEffect(() => {
    let active = true;
    const sync = () => {
      if (!document.hidden)
        void change("/sync").catch((err) => {
          if (active) setError(errorText(err));
        });
    };
    sync();
    const timer = window.setInterval(sync, 30000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    setLoading(true);
    void refresh();
    const update = () => {
      if (!document.hidden) void refresh();
    };
    const timer = window.setInterval(update, 7000);
    window.addEventListener("focus", update);
    window.addEventListener("galant-network-changed", update);
    return () => {
      generation.current++;
      clearInterval(timer);
      window.removeEventListener("focus", update);
      window.removeEventListener("galant-network-changed", update);
    };
  }, [refresh]);
  async function openReq(id: string) {
    try {
      setSelectedReq(
        await net<Requirement>("/requirements/" + encodeURIComponent(id)),
      );
      setPanel("detail");
      setFiles([]);
      setHistory({ rows: [], total: 0 });
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function openCap(id: string) {
    try {
      setSelectedCap(
        await net<Capacity>("/capacities/" + encodeURIComponent(id)),
      );
      setPanel("capacity-detail");
    } catch (err) {
      setError(errorText(err));
    }
  }
  useEffect(() => {
    const handle = () => {
      const [prefix, kind, id] = window.location.hash.slice(1).split("/");
      if (prefix !== "red" || !id) return;
      if (kind === "requirement") {
        setTab("requirements");
        void openReq(id);
      } else if (kind === "capacity") {
        setTab("capacities");
        void openCap(id);
      } else if (kind === "conversation") {
        setTab("messages");
        setConversationId(id);
      } else {
        setTab("matches");
      }
    };
    handle();
    window.addEventListener("hashchange", handle);
    return () => window.removeEventListener("hashchange", handle);
  }, []);
  useEffect(() => {
    if (panel !== "detail" || !selectedReq?.editable) return;
    let active = true;
    const id = selectedReq.id;
    void Promise.all([
      net<Attachment[]>("/attachments?requirement_id=" + id),
      net<History>("/history/" + id),
    ])
      .then(([f, h]) => {
        if (active) {
          setFiles(f);
          setHistory(h);
        }
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    const timer = window.setInterval(() => {
      if (!document.hidden)
        void net<Requirement>("/requirements/" + id)
          .then((r) => {
            if (active) setSelectedReq(r);
          })
          .catch((err) => {
            if (active) setError(errorText(err));
          });
    }, 7000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [panel, selectedReq?.id, selectedReq?.editable]);
  function go(next: string) {
    setTab(next);
    setPage(0);
    setError("");
  }
  function saved(message: string, req?: Requirement) {
    setNotice(message);
    setPanel("");
    void refresh();
    window.dispatchEvent(new Event("galant-network-changed"));
    if (req) void openReq(req.id);
  }
  async function interest(m: Match, contact = true) {
    try {
      const coord = await change<Coordination>("/coordinations", {
        match_id: m.id,
      });
      setNotice(
        "Interés registrado y coordinación vinculada a la oportunidad.",
      );
      if (contact && coord.conversation_id) {
        go("messages");
        setConversationId(coord.conversation_id);
        setPanel("");
      } else {
        go("matches");
        setActiveCoord(coord);
        setPanel("coordination");
      }
      window.dispatchEvent(new Event("galant-network-changed"));
    } catch (err) {
      setError(errorText(err));
    }
  }
  async function contactCap(c: Capacity) {
    try {
      const list = await net<Page<Match>>(
        "/matches?capacity_id=" + c.id + "&limit=100",
      );
      const match = list.rows.find((m) => m.requirement.editable);
      if (match) await interest(match);
      else {
        setNotice(
          "Para contactar sobre esta capacidad, publica un requerimiento compatible en una de tus obras. La conversación quedará vinculada a ambos registros.",
        );
        setPanel("");
        go("requirements");
      }
    } catch (err) {
      setError(errorText(err));
    }
  }
  const total =
    tab === "requirements"
      ? reqs.total
      : tab === "capacities"
        ? caps.total
        : tab === "matches"
          ? matches.total
          : tab === "awards"
            ? awards.total
            : conversations.total;
  const pageControls = (
    <div className="nw-pagination">
      <span>
        {total} registros · Página {page + 1}
      </span>
      <button
        className="nw-icon"
        aria-label="Página anterior"
        disabled={!page}
        onClick={() => setPage((p) => p - 1)}
      >
        <ChevronLeft size={18} />
      </button>
      <button
        className="nw-icon"
        aria-label="Página siguiente"
        disabled={(page + 1) * 24 >= total}
        onClick={() => setPage((p) => p + 1)}
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
  const reqCard = (r: Requirement) => (
    <article className="nw-card" key={r.id}>
      <div className="nw-row">
        <span className="nw-site">
          <Building2 size={13} />
          {r.site}
        </span>
        <Badge value={r.priority} />
      </div>
      <span className="nw-specialty">{r.specialty}</span>
      <h3>
        <button className="nw-text-button" onClick={() => void openReq(r.id)}>
          {r.title}
        </button>
      </h3>
      <div className="nw-card-meta">
        <span>
          <CalendarDays size={14} />
          {dateText(r.start_date)}
        </span>
        <span>
          <Users size={14} />
          {r.workers} trabajadores
        </span>
        <span>{r.item_count} partidas</span>
      </div>
      <div className="nw-progress-heading">
        <span>{r.coverage}% adjudicado</span>
        <Badge value={r.state === "draft" ? "draft" : r.allocation_state} />
      </div>
      <progress
        max={100}
        value={r.coverage}
        aria-label="Porcentaje adjudicado"
      />
      {r.items.flatMap((i) => i.awards).length > 0 && (
        <p className="nw-awarded-label">
          Adjudicado a:{" "}
          {[
            ...new Set(
              r.items.flatMap((i) => i.awards.map((a) => a.contractor)),
            ),
          ].join(", ")}
        </p>
      )}
      <div className="nw-card-footer">
        <span>{r.resident}</span>
        <button className="nw-text-button" onClick={() => void openReq(r.id)}>
          Ver detalle <ArrowRight size={14} />
        </button>
      </div>
    </article>
  );
  const capCard = (c: Capacity) => (
    <article className="nw-card nw-capacity-card" key={c.id}>
      <div className="nw-row">
        <span className="nw-site">
          <Building2 size={13} />
          {c.site}
        </span>
        {c.expired ? (
          <Badge value="Caducada" />
        ) : c.stale ? (
          <Badge value="Requiere actualización" />
        ) : (
          <Badge value={c.availability} />
        )}
      </div>
      <span className="nw-specialty">{c.specialty}</span>
      <h3>
        <button className="nw-text-button" onClick={() => void openCap(c.id)}>
          {c.contractor}
        </button>
      </h3>
      <p className="nw-muted">
        {labels[c.situation]} · {labels[c.mode]}
      </p>
      <div className="nw-capacity-number">
        <strong>{c.workers}</strong>
        <span>
          trabajadores estimados
          <br />
          <b>Desde {dateText(c.available_date)}</b>
        </span>
      </div>
      <p className="nw-muted">
        Vigencia hasta {dateText(c.expires_on)}
        {c.confirmed_at
          ? " · Última confirmación " + dateText(c.confirmed_at)
          : " · Sujeta a confirmación"}
      </p>
      <div className="nw-card-footer">
        <span>{c.resident}</span>
        <button className="nw-text-button" onClick={() => void contactCap(c)}>
          Contactar residente <ArrowRight size={14} />
        </button>
      </div>
    </article>
  );
  const matchCard = (m: Match) => (
    <article className="nw-card nw-match-card" key={m.id}>
      <div className="nw-row">
        <span className="nw-specialty">
          <Sparkles size={14} />
          Posible contratista para tu requerimiento
        </span>
        <span className="nw-score">{m.score}%</span>
      </div>
      <h3>{m.capacity.contractor}</h3>
      <p className="nw-muted">{m.requirement.title}</p>
      <div className="nw-match-route">
        <span>{m.capacity.site}</span>
        <ArrowRight size={16} />
        <span>{m.requirement.site}</span>
      </div>
      <Badge value={m.capacity.availability} />
      <ul className="nw-reasons">
        {m.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <div className="nw-row nw-wrap">
        <button className="nw-btn nw-primary" onClick={() => void interest(m)}>
          <MessageSquare size={15} />
          Contactar residente
        </button>
        <button className="nw-btn" onClick={() => void interest(m, false)}>
          Solicitar coordinación
        </button>
        <button className="nw-btn" onClick={() => void openCap(m.capacity.id)}>
          Ver detalles
        </button>
      </div>
    </article>
  );
  return (
    <section className="nw nw-portal">
      <div className="nw-heading">
        <div>
          <span className="nw-eyebrow">
            <span className="nw-live-dot" />
            COLABORACIÓN ENTRE OBRAS
          </span>
          <h1>
            Red de Obras<span>.</span>
          </h1>
          <p>
            Conecta necesidades, comparte capacidad y coordina cada partida.
          </p>
        </div>
        {canPublish && (
          <div className="nw-row nw-wrap">
            <button
              className="nw-btn"
              onClick={() => {
                setSelectedCap(null);
                setPanel("capacity-form");
              }}
            >
              <Users size={16} />
              Tengo contratista con capacidad
            </button>
            <button
              className="nw-btn nw-primary"
              onClick={() => {
                setSelectedReq(null);
                setPanel("request-form");
              }}
            >
              <Plus size={17} />
              Necesito contratista
            </button>
          </div>
        )}
      </div>
      <nav className="nw-tabs" aria-label="Red de Obras">
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            aria-current={tab === id ? "page" : undefined}
            className={tab === id ? "active" : ""}
            onClick={() => go(id)}
          >
            <Icon size={16} />
            {label}
            {id === "messages" && !!overview?.unread_messages && (
              <span className="nw-tab-count">{overview.unread_messages}</span>
            )}
          </button>
        ))}
      </nav>
      <div className="nw-filters">
        <label>
          <Building2 size={16} />
          <select
            aria-label="Filtrar por obra"
            value={site}
            onChange={(e) => {
              setSite(e.target.value);
              setPage(0);
            }}
          >
            <option value="">Todas las obras</option>
            {catalog.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <Workflow size={16} />
          <select
            aria-label="Filtrar por especialidad"
            value={specialty}
            onChange={(e) => {
              setSpecialty(e.target.value);
              setPage(0);
            }}
          >
            <option value="">Todas las especialidades</option>
            {catalog.specialties.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        {["requirements", "capacities"].includes(tab) && (
          <label className="nw-search">
            <Search size={16} />
            <input
              aria-label="Buscar publicaciones"
              placeholder="Buscar en la red…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
            />
          </label>
        )}
        {tab === "requirements" && (
          <>
            <select
              aria-label="Filtrar prioridad"
              value={priority}
              onChange={(e) => {
                setPriority(e.target.value);
                setPage(0);
              }}
            >
              <option value="">Todas las prioridades</option>
              {["low", "normal", "high", "urgent"].map((p) => (
                <option key={p} value={p}>
                  {labels[p]}
                </option>
              ))}
              <option value="attention">Alta o urgente</option>
            </select>
            <label className="nw-check">
              <input
                type="checkbox"
                checked={mine}
                onChange={(e) => {
                  setMine(e.target.checked);
                  setPage(0);
                }}
              />
              Solo mis obras
            </label>
          </>
        )}
        {tab === "home" && user.role === "resident" && (
          <label className="nw-check">
            <input
              type="checkbox"
              checked={mine}
              onChange={(e) => {
                setMine(e.target.checked);
                setPage(0);
              }}
            />
            Solo mis obras
          </label>
        )}
        {["requirements", "capacities"].includes(tab) && (
          <div className="nw-view-toggle">
            {[
              ["cards", LayoutGrid, "Tarjetas"],
              ["list", List, "Lista compacta"],
              ["kanban", Workflow, "Kanban"],
            ].map(([value, Icon, title]) => {
              const I = Icon as typeof LayoutGrid;
              return (
                <button
                  className={mode === value ? "active" : ""}
                  aria-label={String(title)}
                  aria-pressed={mode === value}
                  key={String(value)}
                  onClick={() => setMode(String(value))}
                >
                  <I size={16} />
                </button>
              );
            })}
          </div>
        )}
      </div>
      {error && (
        <div role="alert" className="nw-error">
          {error}
          <button className="nw-btn" onClick={() => void refresh()}>
            Reintentar
          </button>
        </div>
      )}
      {notice && (
        <div role="status" className="nw-success">
          <CheckCheck size={17} />
          {notice}
          <button className="nw-text-button" onClick={() => setNotice("")}>
            Cerrar
          </button>
        </div>
      )}
      {loading && (
        <p className="nw-muted" role="status">
          Actualizando información compartida…
        </p>
      )}
      {tab === "home" && overview && (
        <>
          <div className="nw-kpis">
            {(
              [
                [
                  "requirements",
                  "Requerimientos abiertos",
                  overview.requirements,
                  Building2,
                ],
                [
                  "requirements",
                  "Partidas pendientes",
                  overview.pending_items,
                  Workflow,
                ],
                [
                  "urgent",
                  "Requerimientos prioritarios",
                  overview.urgent,
                  Clock3,
                ],
                [
                  "capacities",
                  "Contratistas con capacidad",
                  overview.capacities,
                  Users,
                ],
                [
                  "messages",
                  "Mensajes sin leer",
                  overview.unread_messages,
                  MessageSquare,
                ],
              ] as const
            ).map(([destination, label, value, Icon]) => (
              <button
                className="nw-kpi"
                key={label}
                onClick={() => {
                  if (destination === "urgent") {
                    setPriority("attention");
                    go("requirements");
                  } else go(destination);
                }}
              >
                <span>
                  <Icon size={18} />
                  {label}
                </span>
                <strong>{number(value)}</strong>
                <small>
                  Ver registros <ArrowRight size={13} />
                </small>
              </button>
            ))}
          </div>
          <div className="nw-section-title">
            <h2>Necesidades que conectan obras</h2>
            <button
              className="nw-text-button"
              onClick={() => go("requirements")}
            >
              Ver todas <ArrowRight size={15} />
            </button>
          </div>
          {reqs.rows.length ? (
            <div className="nw-cards">{reqs.rows.slice(0, 6).map(reqCard)}</div>
          ) : (
            <Empty title="La red está lista para conectar tus obras">
              Publica el primer requerimiento o comparte la capacidad de un
              contratista registrado.
            </Empty>
          )}
          <div className="nw-dashboard-grid">
            <div className="nw-surface">
              <h3>Necesidades por especialidad</h3>
              <Bars values={overview.by_specialty} />
            </div>
            <div className="nw-surface">
              <h3>Actividad por obra</h3>
              <Bars values={overview.by_site} />
            </div>
          </div>
          <div className="nw-operational-strip">
            <button className="nw-text-button" onClick={() => go("awards")}>
              <b>{overview.awarded_items}</b> partidas adjudicadas
            </button>
            <button className="nw-text-button" onClick={() => go("matches")}>
              <b>{overview.matches}</b> coincidencias posibles
            </button>
            <span><b>{overview.active_coordinations}</b> coordinaciones activas</span>
            <span>
              <b>{overview.partial_items}</b> partidas parciales
            </span>
            <span>
              <b>{overview.awards}</b> adjudicaciones confirmadas
            </span>
            <span>
              <b>{overview.pending_clearance}</b> habilitaciones pendientes
            </span>
            <span>
              <b>{overview.enabled_awards}</b> adjudicaciones habilitadas
            </span>
            <span>
              <b>{overview.average_award_days ?? "—"}</b> días promedio para
              adjudicar
            </span>
          </div>
          {!!matches.rows.length && (
            <>
              <div className="nw-section-title">
                <h2>Oportunidades para coordinar</h2>
              </div>
              <div className="nw-cards">
                {matches.rows.slice(0, 3).map(matchCard)}
              </div>
            </>
          )}
        </>
      )}
      {tab === "requirements" && (
        <>
          <div className="nw-section-title">
            <h2>
              Necesito contratista <span>{reqs.total}</span>
            </h2>
            {canPublish && (
              <button
                className="nw-btn"
                onClick={() => {
                  setSelectedReq(null);
                  setPanel("request-form");
                }}
              >
                <Plus size={16} />
                Publicar requerimiento
              </button>
            )}
          </div>
          {reqs.rows.length ? (
            mode === "kanban" ? (
              <div className="nw-kanban">
                {[
                  "none",
                  "partial",
                  "full",
                  "in_progress",
                  "completed",
                  "cancelled",
                ].map((state) => (
                  <section key={state}>
                    <h3>{labels[state] || state}</h3>
                    {reqs.rows
                      .filter((r) => r.allocation_state === state)
                      .map(reqCard)}
                  </section>
                ))}
              </div>
            ) : (
              <div
                className={
                  "nw-cards " + (mode === "list" ? "nw-list-view" : "")
                }
              >
                {reqs.rows.map(reqCard)}
              </div>
            )
          ) : (
            <Empty title="No hay requerimientos con estos filtros" />
          )}
          {pageControls}
        </>
      )}
      {tab === "capacities" && (
        <>
          <div className="nw-section-title">
            <h2>
              Contratistas con capacidad <span>{caps.total}</span>
            </h2>
            {canPublish && (
              <button
                className="nw-btn"
                onClick={() => {
                  setSelectedCap(null);
                  setPanel("capacity-form");
                }}
              >
                <Plus size={16} />
                Publicar capacidad
              </button>
            )}
          </div>
          <p className="nw-help">
            <CircleHelp size={16} />
            Las publicaciones expresan capacidad estimada. Confirma fechas y
            disponibilidad con la obra de origen.
          </p>
          {caps.rows.length ? (
            mode === "kanban" ? (
              <div className="nw-kanban">
                {[
                  "estimated",
                  "pending",
                  "confirmed",
                  "committed",
                  "discarded",
                ].map((state) => (
                  <section key={state}>
                    <h3>{labels[state]}</h3>
                    {caps.rows
                      .filter((c) => c.availability === state)
                      .map(capCard)}
                  </section>
                ))}
              </div>
            ) : (
              <div
                className={
                  "nw-cards " + (mode === "list" ? "nw-list-view" : "")
                }
              >
                {caps.rows.map(capCard)}
              </div>
            )
          ) : (
            <Empty title="Aún no hay capacidad publicada" />
          )}
          {pageControls}
        </>
      )}
      {tab === "matches" && (
        <>
          <div className="nw-section-title">
            <h2>Coincidencias y coordinación</h2>
            <span className="nw-muted">
              Sugerencias explicables · Disponibilidad sujeta a confirmación
            </span>
          </div>
          {matches.rows.length ? (
            <div className="nw-cards">{matches.rows.map(matchCard)}</div>
          ) : (
            <Empty title="No se encontraron coincidencias vigentes">
              GALANT compara especialidad, fechas, partidas y capacidad libre
              entre obras diferentes.
            </Empty>
          )}
          {pageControls}
          <h2 className="nw-section-title">Coordinaciones en curso</h2>
          <div className="nw-cards">
            {coords.rows.map((c) => (
              <article className="nw-card" key={c.id}>
                <Badge value={c.state} />
                <h3>{c.requirement}</h3>
                <b>{c.contractor}</b>
                <p className="nw-muted">
                  {c.origin} → {c.site}
                </p>
                <div className="nw-row nw-wrap">
                  <button
                    className="nw-btn"
                    onClick={() => {
                      setActiveCoord(c);
                      setPanel("coordination");
                    }}
                  >
                    Ver coordinación
                  </button>
                  {c.conversation_id && (
                    <button
                      className="nw-btn"
                      onClick={() => {
                        go("messages");
                        setConversationId(c.conversation_id!);
                      }}
                    >
                      Abrir conversación
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
      {tab === "awards" && (
        <>
          <div className="nw-section-title">
            <h2>Adjudicaciones y partidas</h2>
            <a className="nw-btn" href={"/api/v1/network/report?" + query}>
              Exportar adjudicaciones CSV
            </a>
          </div>
          <p className="nw-help">
            <FileCheck2 size={16} />
            Cada cantidad adjudicada conserva su contratista, responsable,
            estado y habilitación en destino.
          </p>
          {awards.rows.length ? (
            <div className="nw-cards">
              {awards.rows.map((a) => (
                <article className="nw-card" key={a.id}>
                  <div className="nw-row">
                    <span className="nw-site">{a.site}</span>
                    <Badge value={a.state} />
                  </div>
                  <h3>{a.item_name}</h3>
                  <p className="nw-awarded-label">
                    ADJUDICADO A: {a.contractor}
                  </p>
                  <div className="nw-award-quantity">
                    <b>
                      {number(a.quantity)} {a.unit}
                    </b>
                    <span>{number(a.executed)} ejecutadas</span>
                  </div>
                  <p className="nw-muted">{a.clearance?.label}</p>
                  <button
                    className="nw-btn"
                    onClick={() => void openReq(a.requirement_id)}
                  >
                    Ver partida e historial
                  </button>
                </article>
              ))}
            </div>
          ) : (
            <Empty title="Las adjudicaciones aparecerán aquí" />
          )}
          {pageControls}
        </>
      )}
      {tab === "messages" && (
        <div className="nw-messaging">
          <aside>
            <h2>Mensajes</h2>
            {conversations.rows.map((c) => (
              <button
                key={c.id}
                className={conversationId === c.id ? "active" : ""}
                onClick={() => setConversationId(c.id)}
              >
                <b>{c.title}</b>
                <small>{c.site}</small>
                {c.unread > 0 && <span>{c.unread} sin leer</span>}
              </button>
            ))}
            {!conversations.rows.length && (
              <p className="nw-muted">
                Contacta a un residente desde una coincidencia para iniciar una
                conversación.
              </p>
            )}
            {pageControls}
          </aside>
          {conversationId ? (
            <ConversationView
              key={conversationId}
              id={conversationId}
              user={user}
              changed={() => {
                void refresh();
                window.dispatchEvent(new Event("galant-network-changed"));
              }}
            />
          ) : (
            <Empty title="Selecciona una conversación" />
          )}
        </div>
      )}
      {tab === "calendar" && (
        <CalendarView
          query={query}
          open={(ev) => {
            if (ev.kind === "capacity") void openCap(ev.id);
            else void openReq(ev.requirement_id || ev.id);
          }}
        />
      )}
      <datalist id="network-specialties">
        {[
          ...new Set([
            "Carpintería",
            "Electricidad",
            "Gasfitería",
            "Albañilería",
            "Pintura",
            "Enfierradura",
            "Terminaciones",
            ...catalog.specialties,
          ]),
        ].map((s) => (
          <option value={s} key={s} />
        ))}
      </datalist>
      <datalist id="network-units">
        {["un", "m", "m²", "m³", "kg", "gl", "jornada"].map((u) => (
          <option value={u} key={u} />
        ))}
      </datalist>
      {panel && (
        <Drawer
          title={
            panel === "detail"
              ? "Detalle del requerimiento"
              : panel === "request-form"
                ? selectedReq
                  ? "Editar requerimiento"
                  : "Publicar requerimiento"
                : panel === "capacity-form"
                  ? "Publicar contratista con capacidad"
                  : panel === "capacity-detail"
                    ? "Capacidad del contratista"
                    : panel === "award"
                      ? "Adjudicar partida"
                      : panel === "award-progress"
                        ? "Seguimiento de adjudicación"
                        : panel === "amend"
                          ? "Ampliación formal de partida"
                          : "Coordinación entre obras"
          }
          onClose={() => setPanel("")}
        >
          {panel === "request-form" && (
            <RequirementForm
              catalog={catalog}
              current={selectedReq || undefined}
              done={saved}
            />
          )}
          {panel === "capacity-form" && (
            <CapacityForm
              catalog={catalog}
              current={selectedCap || undefined}
              done={saved}
            />
          )}
          {panel === "award" && selectedReq && selectedItem && (
            <AwardForm
              req={selectedReq}
              item={selectedItem}
              catalog={catalog}
              done={(message) => {
                saved(message);
                void openReq(selectedReq.id);
              }}
            />
          )}
          {panel === "award-progress" && selectedAward && (
            <AwardProgressForm
              award={selectedAward}
              done={(message) => {
                saved(message);
                void openReq(selectedAward.requirement_id);
              }}
            />
          )}
          {panel === "award-revision" && selectedAward && selectedItem && (
            <AwardRevisionForm
              award={selectedAward}
              item={selectedItem}
              done={(message) => {
                saved(message);
                void openReq(selectedAward.requirement_id);
              }}
            />
          )}
          {panel === "amend" && selectedReq && selectedItem && (
            <AmendmentForm
              item={selectedItem}
              done={(message) => {
                saved(message);
                void openReq(selectedReq.id);
              }}
            />
          )}
          {panel === "detail" && selectedReq && (
            <div className="nw-detail">
              <div className="nw-row nw-wrap">
                <Badge value={selectedReq.priority} />
                <Badge value={selectedReq.state} />
                <Badge value={selectedReq.allocation_state} />
              </div>
              <h2>{selectedReq.title}</h2>
              <p className="nw-muted">
                {selectedReq.site} · {selectedReq.specialty} ·{" "}
                {selectedReq.resident}
              </p>
              <p>
                {selectedReq.description ||
                  (!selectedReq.editable
                    ? "Vista colaborativa limitada. Los adjuntos y antecedentes privados corresponden a la obra responsable."
                    : "Sin descripción adicional.")}
              </p>
              <p>
                {dateText(selectedReq.start_date)} →{" "}
                {dateText(selectedReq.end_date)} · {selectedReq.workers}{" "}
                trabajadores
              </p>
              {selectedReq.editable && (
                <button
                  className="nw-btn"
                  onClick={() => setPanel("request-form")}
                >
                  Editar y reprogramar
                </button>
              )}
              <h3>Partidas y contratistas adjudicados</h3>
              {selectedReq.items.map((i) => (
                <div className="nw-detail-item" key={i.id}>
                  <div className="nw-row">
                    <h3>{i.name}</h3>
                    <Badge value={i.state} />
                  </div>
                  <div className="nw-item-totals">
                    <span>
                      <b>{number(i.quantity)}</b> solicitadas
                    </span>
                    <span>
                      <b>{number(i.awarded)}</b> adjudicadas
                    </span>
                    <span>
                      <b>{number(i.pending)}</b> pendientes
                    </span>
                    <span>
                      <b>{number(i.executed)}</b> ejecutadas
                    </span>
                  </div>
                  <p className="nw-muted">Unidad: {i.unit}</p>
                  {i.awards.map((a) => (
                    <div className="nw-award-line" key={a.id}>
                      <b>ADJUDICADO A: {a.contractor}</b>
                      <p>
                        {number(a.quantity)} {a.unit} ·{" "}
                        <Badge value={a.state} />
                      </p>
                      <small>{a.clearance?.label}</small>
                      <p className="nw-muted">
                        {dateText(a.start_date)} → {dateText(a.end_date)} ·
                        Responsable: {a.awarded_by}
                      </p>
                      {selectedReq.can_award &&
                        !["revoked", "completed"].includes(a.state) && (
                          <div className="nw-row nw-wrap">
                            <button
                              className="nw-btn"
                              onClick={() => {
                                setSelectedAward(a);
                                setPanel("award-progress");
                              }}
                            >
                              Actualizar seguimiento
                            </button>
                            <button
                              className="nw-btn"
                              onClick={() => {
                                setSelectedAward(a);
                                setSelectedItem(i);
                                setPanel("award-revision");
                              }}
                            >
                              Modificar cantidad o fechas
                            </button>
                          </div>
                        )}
                    </div>
                  ))}
                  {!i.awards.length && (
                    <p className="nw-muted">
                      {selectedReq.editable
                        ? "Sin contratista adjudicado"
                        : "Las adjudicaciones detalladas se consultan desde la obra responsable."}
                    </p>
                  )}
                  {selectedReq.can_award && (
                    <div className="nw-row nw-wrap">
                      {i.pending > 0 && selectedReq.state === "published" && (
                        <button
                          className="nw-btn nw-primary"
                          onClick={() => {
                            setSelectedItem(i);
                            setPanel("award");
                          }}
                        >
                          Adjudicar partida
                        </button>
                      )}
                      {user.role === "admin" && (
                        <button
                          className="nw-btn"
                          onClick={() => {
                            setSelectedItem(i);
                            setPanel("amend");
                          }}
                        >
                          Ampliar cantidad
                        </button>
                      )}
                    </div>
                  )}
                </div>
              ))}
              {selectedReq.editable && (
                <>
                  <h3>Documentación complementaria</h3>
                  <AttachmentList files={files} />
                  <FileUpload
                    kind="requirement_id"
                    id={selectedReq.id}
                    done={() =>
                      void net<Attachment[]>(
                        "/attachments?requirement_id=" + selectedReq.id,
                      ).then(setFiles)
                    }
                  />
                  <div className="nw-history-heading">
                    <h3>Historial y trazabilidad</h3>
                    <span>{history.total} movimientos</span>
                  </div>
                  <div className="nw-timeline" aria-label="Historial del requerimiento">
                    {history.rows.map((h) => (
                      <details className="nw-history" key={h.id}>
                        <summary>
                          <span className="nw-history-marker" aria-hidden="true">
                            <Clock3 size={14} />
                          </span>
                          <span className="nw-history-summary">
                            <strong>{h.title}</strong>
                            <span>{h.actor} · {dateTime(h.at)}</span>
                          </span>
                        </summary>
                        <div className="nw-history-content">
                          {h.reason && <p><b>Motivo:</b> {h.reason}</p>}
                          {h.details.map((detail, i) => (
                            <div className="nw-history-change" key={detail.label + i}>
                              <b>{detail.label}</b>
                              {detail.before !== null && (
                                <span>Antes: {detail.before}</span>
                              )}
                              <span>{detail.before === null ? "Valor: " : "Ahora: "}{detail.after}</span>
                            </div>
                          ))}
                          {!h.details.length && !h.reason && (
                            <p>Actividad registrada correctamente.</p>
                          )}
                        </div>
                      </details>
                    ))}
                    {!history.rows.length && (
                      <p className="nw-muted">Todavía no hay movimientos registrados.</p>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
          {panel === "capacity-detail" && selectedCap && (
            <div className="nw-detail">
              <Badge value={selectedCap.availability} />
              <h2>{selectedCap.contractor}</h2>
              <p>
                {selectedCap.site} · {selectedCap.specialty}
              </p>
              <p>RUT: {selectedCap.rut || "Sin registro"}</p>
              <p>{labels[selectedCap.situation]}</p>
              <div className="nw-capacity-number">
                <strong>{selectedCap.workers}</strong>
                <span>
                  trabajadores estimados
                  <br />
                  Desde {dateText(selectedCap.available_date)}
                </span>
              </div>
              <p>{selectedCap.notes}</p>
              <p className="nw-callout">
                {selectedCap.expired
                  ? "Publicación caducada. Renueva su vigencia antes de coordinar."
                  : "La capacidad publicada requiere confirmación y coordinación. No constituye una asignación."}
              </p>
              <h3>Partidas pendientes</h3>
              {selectedCap.pending_items.map((i, index) => (
                <p key={index}>
                  {i.name} · {number(i.quantity)} {i.unit} ·{" "}
                  {dateText(i.end_date)}
                </p>
              ))}
              <div className="nw-row nw-wrap">
                <button
                  className="nw-btn nw-primary"
                  onClick={() => void contactCap(selectedCap)}
                >
                  Contactar residente
                </button>
                {selectedCap.editable && (
                  <>
                    <button
                      className="nw-btn"
                      onClick={() => setPanel("capacity-form")}
                    >
                      Actualizar capacidad
                    </button>
                    <RenewButton cap={selectedCap} done={saved} />
                  </>
                )}
              </div>
            </div>
          )}
          {panel === "coordination" && activeCoord && (
            <CoordinationForm
              current={activeCoord}
              openCapacity={() => void openCap(activeCoord.capacity_id)}
              done={saved}
            />
          )}
        </Drawer>
      )}
    </section>
  );
}

function Bars({ values }: { values: Record<string, number> }) {
  const max = Math.max(...Object.values(values), 1);
  return Object.keys(values).length ? (
    <div className="nw-bars">
      {Object.entries(values).map(([label, value]) => (
        <div key={label}>
          <div>
            <span>{label}</span>
            <b>{value}</b>
          </div>
          <progress max={max} value={value} aria-label={label} />
        </div>
      ))}
    </div>
  ) : (
    <p className="nw-muted">Sin requerimientos activos para estos filtros.</p>
  );
}
function AttachmentList({ files }: { files: Attachment[] }) {
  return (
    <div className="nw-attachments">
      {files.map((f) => (
        <a href={"/api/v1/network/attachments/" + f.id + "/file"} key={f.id}>
          {f.filename}
          <small>{number(Math.ceil(f.size / 1024))} KB</small>
        </a>
      ))}
      {!files.length && <p className="nw-muted">Sin archivos adjuntos.</p>}
    </div>
  );
}
function FileUpload({
  kind,
  id,
  done,
}: {
  kind: "requirement_id" | "conversation_id";
  id: string;
  done: () => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  return (
    <div className="nw-upload">
      <label>
        Adjuntar PDF, JPG o PNG
        <input
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            const input = e.target;
            if (!file) return;
            setBusy(true);
            setError("");
            setNotice("");
            void attach(file, kind, id)
              .then(() => {
                done();
                setNotice("Archivo adjuntado.");
              })
              .catch((err) => setError(errorText(err)))
              .finally(() => {
                setBusy(false);
                input.value = "";
              });
          }}
        />
      </label>
      {busy && <p role="status">Adjuntando archivo…</p>}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="nw-error">
          {error}
        </p>
      )}
    </div>
  );
}
function ConversationView({
  id,
  user,
  changed,
}: {
  id: string;
  user: Profile;
  changed: () => void;
}) {
  const [data, setData] = useState<Messages | null>(null),
    [files, setFiles] = useState<Attachment[]>([]),
    [draft, setDraft] = useState("");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [admins, setAdmins] = useState<
      { id: string; name: string; role: string }[]
    >([]);
  const clientKey = useRef(crypto.randomUUID()),
    scroll = useRef<HTMLDivElement>(null),
    first = useRef(true);
  const refresh = useCallback(async () => {
    const [next, f] = await Promise.all([
      net<Messages>("/conversations/" + id + "/messages"),
      net<Attachment[]>("/attachments?conversation_id=" + id),
    ]);
    setData((old) =>
      old && old.rows.length > 50
        ? {
            ...next,
            rows: [
              ...old.rows.filter((r) => !next.rows.some((n) => n.id === r.id)),
              ...next.rows,
            ],
          }
        : next,
    );
    setFiles(f);
    const last = next.rows.at(-1);
    if (last && !document.hidden)
      await change("/conversations/" + id + "/read?last_message_id=" + last.id);
  }, [id]);
  useEffect(() => {
    let active = true;
    const update = () => {
      if (!document.hidden)
        void refresh().catch((err) => {
          if (active) setError(errorText(err));
        });
    };
    update();
    const timer = window.setInterval(update, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    if (first.current && data?.rows.length) {
      scroll.current?.scrollTo({ top: scroll.current.scrollHeight });
      first.current = false;
    }
  }, [data]);
  useEffect(() => {
    if (user.role === "admin")
      void net<typeof admins>("/users")
        .then((a) => setAdmins(a.filter((p) => p.role === "admin")))
        .catch((err) => setError(errorText(err)));
  }, [user.role]);
  async function send(e: FormEvent) {
    e.preventDefault();
    if (!draft.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await change("/conversations/" + id + "/messages", {
        body: draft.trim(),
        client_key: clientKey.current,
      });
      setDraft("");
      clientKey.current = crypto.randomUUID();
      await refresh();
      changed();
      scroll.current?.scrollTo({
        top: scroll.current.scrollHeight,
        behavior: "smooth",
      });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="nw-chat">
      <header>
        <h3>Conversación de coordinación</h3>
        <p className="nw-muted">
          {data?.participants
            .map(
              (p) =>
                p.name +
                (p.sites.length
                  ? " · " + p.sites.join(", ")
                  : " · Administración"),
            )
            .join(" / ")}
        </p>
        {user.role === "admin" && (
          <label>
            Incorporar coordinador
            <select
              aria-label="Incorporar coordinador"
              value=""
              onChange={(e) => {
                if (e.target.value)
                  void change("/conversations/" + id + "/participants", {
                    user_id: e.target.value,
                  })
                    .then(() => refresh())
                    .catch((err) => setError(errorText(err)));
              }}
            >
              <option value="">Seleccionar administrador</option>
              {admins
                .filter((a) => !data?.participants.some((p) => p.id === a.id))
                .map((a) => (
                  <option value={a.id} key={a.id}>
                    {a.name}
                  </option>
                ))}
            </select>
          </label>
        )}
      </header>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <div
        className="nw-chat-history"
        ref={scroll}
        aria-label="Historial de mensajes"
      >
        {data?.next_before && (
          <button
            className="nw-btn"
            onClick={() =>
              void net<Messages>(
                "/conversations/" + id + "/messages?before=" + data.next_before,
              )
                .then((older) =>
                  setData((old) =>
                    old
                      ? {
                          ...old,
                          rows: [...older.rows, ...old.rows],
                          next_before: older.next_before,
                        }
                      : older,
                  ),
                )
                .catch((err) => setError(errorText(err)))
            }
          >
            Cargar mensajes anteriores
          </button>
        )}
        {data?.rows.map((m) => (
          <article
            className={"nw-message " + (m.sender_id === user.id ? "mine" : "")}
            key={m.id}
          >
            <b>{m.sender}</b>
            <p>{m.body}</p>
            <small>{dateTime(m.created_at)}</small>
          </article>
        ))}
        {data && !data.rows.length && (
          <Empty title="Inicia la coordinación">
            Confirma fechas, capacidad y las partidas con el residente de
            origen.
          </Empty>
        )}
      </div>
      <form className="nw-chat-compose" onSubmit={(e) => void send(e)}>
        <label className="nw-sr-only" htmlFor="network-message">
          Escribir mensaje
        </label>
        <textarea
          id="network-message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Escribe un mensaje al residente…"
          required
          maxLength={10000}
          rows={2}
        />
        <button
          className="nw-btn nw-primary"
          disabled={busy || !draft.trim()}
          aria-label="Enviar mensaje"
        >
          <Send size={18} />
          {busy ? "Enviando…" : "Enviar"}
        </button>
      </form>
      <details className="nw-chat-files">
        <summary>Archivos de la conversación ({files.length})</summary>
        <AttachmentList files={files} />
        <FileUpload
          kind="conversation_id"
          id={id}
          done={() => void refresh().catch((err) => setError(errorText(err)))}
        />
      </details>
    </section>
  );
}
function CoordinationForm({
  current,
  openCapacity,
  done,
}: {
  current: Coordination;
  openCapacity: () => void;
  done: (message: string) => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const next = steps[steps.indexOf(current.state) + 1];
  return (
    <form
      className="nw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const d = new FormData(e.currentTarget);
        setBusy(true);
        setError("");
        void change(
          "/coordinations/" + current.id,
          {
            state: d.get("state"),
            version: current.version,
            reason: d.get("reason"),
          },
          "PATCH",
        )
          .then(() => done("Coordinación actualizada y notificada."))
          .catch((err) => setError(errorText(err)))
          .finally(() => setBusy(false));
      }}
    >
      <Badge value={current.state} />
      <h3>{current.requirement}</h3>
      <p>{current.contractor}</p>
      <p>
        {current.origin} → {current.site}
      </p>
      <ol className="nw-timeline">
        {steps.map((s, i) => (
          <li
            className={i <= steps.indexOf(current.state) ? "done" : ""}
            key={s}
          >
            {labels[s]}
          </li>
        ))}
      </ol>
      <button type="button" className="nw-btn" onClick={openCapacity}>
        Ver o confirmar capacidad en origen
      </button>
      {next &&
        !["rejected", "cancelled", "finished"].includes(current.state) && (
          <>
            <label>
              Próximo estado
              <select name="state">
                <option value={next}>{labels[next]}</option>
                <option value="rejected">Rechazar propuesta</option>
                <option value="cancelled">Cancelar coordinación</option>
              </select>
            </label>
            <label>
              Motivo u observaciones
              <textarea name="reason" maxLength={2000} />
            </label>
            <p className="nw-muted">
              La confirmación corresponde a la obra de origen. La aprobación e
              habilitación requieren autorización administrativa.
            </p>
            {error && (
              <p className="nw-error" role="alert">
                {error}
              </p>
            )}
            <button className="nw-btn nw-primary" disabled={busy}>
              {busy ? "Guardando…" : "Actualizar coordinación"}
            </button>
          </>
        )}
    </form>
  );
}
function AmendmentForm({
  item,
  done,
}: {
  item: Item;
  done: (message: string) => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <form
      className="nw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const d = new FormData(e.currentTarget);
        setBusy(true);
        void change("/items/" + item.id + "/amend", {
          quantity: Number(d.get("quantity")),
          reason: d.get("reason"),
        })
          .then(() => done("Ampliación formal registrada."))
          .catch((err) => setError(errorText(err)))
          .finally(() => setBusy(false));
      }}
    >
      <h3>{item.name}</h3>
      <p>
        Cantidad actual: {number(item.quantity)} {item.unit}
      </p>
      <label>
        Nueva cantidad total
        <input
          name="quantity"
          type="number"
          min={item.quantity + 0.001}
          step="0.001"
          required
        />
      </label>
      <label>
        Motivo de la ampliación
        <textarea name="reason" minLength={5} maxLength={2000} required />
      </label>
      {error && (
        <p role="alert" className="nw-error">
          {error}
        </p>
      )}
      <button className="nw-btn nw-primary" disabled={busy}>
        {busy ? "Guardando…" : "Confirmar ampliación"}
      </button>
    </form>
  );
}
function RenewButton({
  cap,
  done,
}: {
  cap: Capacity;
  done: (message: string) => void;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <>
      <button
        className="nw-btn"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void change("/capacities/" + cap.id + "/renew", {
            version: cap.version,
            validity_days: 14,
          })
            .then(() => done("Vigencia renovada por 14 días."))
            .catch((err) => setError(errorText(err)))
            .finally(() => setBusy(false));
        }}
      >
        {busy ? "Renovando…" : "Renovar 14 días"}
      </button>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
function CalendarView({
  query,
  open,
}: {
  query: string;
  open: (event: CalendarEvent) => void;
}) {
  const [cursor, setCursor] = useState(todayISO()),
    [weekly, setWeekly] = useState(false),
    [events, setEvents] = useState<CalendarEvent[]>([]),
    [error, setError] = useState("");
  const selected = new Date(cursor + "T12:00:00");
  const firstDay = weekly
    ? new Date(selected)
    : new Date(selected.getFullYear(), selected.getMonth(), 1, 12);
  firstDay.setDate(firstDay.getDate() - ((firstDay.getDay() + 6) % 7));
  const iso = (d: Date) =>
    d.getFullYear() +
    "-" +
    String(d.getMonth() + 1).padStart(2, "0") +
    "-" +
    String(d.getDate()).padStart(2, "0");
  const days = Array.from({ length: weekly ? 7 : 42 }, (_, i) => {
    const d = new Date(firstDay);
    d.setDate(d.getDate() + i);
    return iso(d);
  });
  const start = days[0],
    end = days.at(-1)!;
  useEffect(() => {
    let active = true;
    const load = () =>
      void net<CalendarEvent[]>(
        "/calendar?start=" + start + "&end=" + end + (query ? "&" + query : ""),
      )
        .then((r) => {
          if (active) {
            setEvents(r);
            setError("");
          }
        })
        .catch((err) => {
          if (active) setError(errorText(err));
        });
    load();
    const timer = setInterval(() => {
      if (!document.hidden) load();
    }, 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [query, start, end]);
  function move(dir: number) {
    const d = new Date(selected);
    if (weekly) d.setDate(d.getDate() + 7 * dir);
    else {
      d.setDate(1);
      d.setMonth(d.getMonth() + dir);
    }
    setCursor(iso(d));
  }
  return (
    <div className="nw-calendar">
      <div className="nw-section-title">
        <h2>
          {selected.toLocaleDateString("es-CL", {
            month: "long",
            year: "numeric",
          })}
        </h2>
        <div className="nw-row nw-wrap">
          <button
            className="nw-icon"
            aria-label="Período anterior"
            onClick={() => move(-1)}
          >
            <ChevronLeft size={18} />
          </button>
          <button className="nw-btn" onClick={() => setCursor(todayISO())}>
            Hoy
          </button>
          <button
            className="nw-icon"
            aria-label="Período siguiente"
            onClick={() => move(1)}
          >
            <ChevronRight size={18} />
          </button>
          <select
            aria-label="Vista de calendario"
            value={weekly ? "week" : "month"}
            onChange={(e) => setWeekly(e.target.value === "week")}
          >
            <option value="month">Mes</option>
            <option value="week">Semana</option>
          </select>
        </div>
      </div>
      <p className="nw-muted">
        Selecciona un evento para ver su detalle y reprogramar desde la obra
        autorizada.
      </p>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <div className="nw-calendar-scroll">
        <div className="nw-calendar-grid">
          {[
            "Lunes",
            "Martes",
            "Miércoles",
            "Jueves",
            "Viernes",
            "Sábado",
            "Domingo",
          ].map((d) => (
            <b className="nw-calendar-weekday" key={d}>
              {d}
            </b>
          ))}
          {days.map((day) => (
            <div
              className={
                "nw-calendar-day " + (day === todayISO() ? "today" : "")
              }
              key={day}
            >
              <time dateTime={day}>{Number(day.slice(-2))}</time>
              {events
                .filter((e) => e.date <= day && e.end_date >= day)
                .map((ev) => (
                  <button
                    key={ev.kind + ev.id}
                    className={"nw-calendar-event " + ev.kind}
                    onClick={() => open(ev)}
                  >
                    <span>
                      {ev.kind === "capacity"
                        ? "Capacidad"
                        : ev.kind === "award"
                          ? "Adjudicación"
                          : "Necesidad"}
                      {ev.overdue ? " · Revisar plazo" : ""}
                    </span>
                    {ev.title}
                  </button>
                ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
