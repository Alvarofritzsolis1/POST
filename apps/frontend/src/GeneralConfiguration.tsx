import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  ArrowLeft,
  ArrowUpRight,
  Building2,
  CalendarRange,
  CheckCircle2,
  ChevronRight,
  FileCheck2,
  History,
  LayoutDashboard,
  ListChecks,
  RefreshCcw,
  Settings2,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { Profile } from "./api";
import { api } from "./api";
import { NetworkAccountMenu } from "./NetworkAccounts";
import { net, type Account } from "./networkApi";
import {
  configurationApi as cfg,
  type AuditRow,
  type ConfigurationBootstrap,
  type ConfigurationSummary,
  type ContractorDetail,
  type Counts,
  type Obligation,
  type ReviewState,
  type RuleInput,
  type RulePreview,
} from "./configurationApi";
import "./configuration.css";

const ROOT = "/admin/configuracion";
const sections = [
  ["", "Vista general", LayoutDashboard],
  ["contratistas", "Contratistas", Building2],
  ["documentos", "Configuración documental", FileCheck2],
  ["periodos", "Configuración por períodos", CalendarRange],
  ["obras", "Configuración de obras", ListChecks],
  ["alertas", "Alertas y vencimientos", Activity],
  ["usuarios", "Usuarios y permisos", Users],
  ["auditoria", "Auditoría y trazabilidad", History],
] as const;
const states: Record<string, string> = {
  approved: "Aprobado",
  submitted: "Entregado, pendiente de revisión",
  missing: "No entregado",
  incomplete: "Entregado incompleto",
  rejected: "Rechazado",
  overdue: "Fuera de plazo",
  not_applicable: "No aplica",
  exempt: "Exento",
  no_movements: "Sin movimientos",
  not_required: "No exigible",
  pending: "Pendiente de revisión",
  observed: "Entregado incompleto",
  inactive: "Inactivo",
  unknown: "Sin información suficiente",
};
const frequencies: Record<string, string> = {
  monthly: "Mensual",
  quarterly: "Trimestral",
  annual: "Anual",
  once: "Una vez",
  on_event: "Por evento",
};
const sources: Record<string, string> = {
  general: "Regla general",
  category: "Plantilla de categoría",
  site: "Regla de obra",
  association: "Regla individual",
  exception: "Excepción autorizada",
  default: "Configuración predeterminada",
  legacy: "Configuración histórica",
};
const nowMonth = () =>
  new Intl.DateTimeFormat("sv-SE", {
    timeZone: "America/Santiago",
    year: "numeric",
    month: "2-digit",
  }).format(new Date());
const periodName = (value: string) =>
  /^\d{4}-\d{2}$/.test(value)
    ? new Intl.DateTimeFormat("es-CL", {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      }).format(new Date(value + "-01T12:00:00Z"))
    : value;
const dateName = (value?: string | null) =>
  value
    ? new Intl.DateTimeFormat("es-CL", {
        dateStyle: "medium",
        timeZone: "America/Santiago",
      }).format(new Date(value.length === 10 ? value + "T12:00:00Z" : value))
    : "Sin registrar";
const dateTimeName = (value: string) =>
  new Intl.DateTimeFormat("es-CL", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Santiago",
  }).format(new Date(value));
const percent = (value?: number | null) =>
  value == null
    ? "Sin obligaciones aplicables"
    : value.toLocaleString("es-CL", { maximumFractionDigits: 1 }) + "%";
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "No fue posible completar la operación";
function monthsBetween(start: string, end: string) {
  if (
    !/^20\d{2}-(0[1-9]|1[0-2])$/.test(start) ||
    !/^20\d{2}-(0[1-9]|1[0-2])$/.test(end) ||
    end < start
  )
    return [];
  const values: string[] = [];
  let [year, month] = start.split("-").map(Number);
  while (values.length < 61) {
    const value = year + "-" + String(month).padStart(2, "0");
    if (value > end) break;
    values.push(value);
    if (++month > 12) {
      month = 1;
      year++;
    }
  }
  return values;
}
function Status({ value }: { value: string }) {
  return (
    <span className={"gc-status gc-state-" + value}>
      <span aria-hidden="true">
        {value === "approved"
          ? "✓"
          : ["rejected", "overdue"].includes(value)
            ? "!"
            : "·"}
      </span>
      {states[value] || value}
    </span>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="gc-empty">
      <FileCheck2 size={28} aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}
function Metrics({ counts }: { counts: Counts }) {
  return (
    <div className="gc-metrics">
      <article className="gc-metric gc-main-metric">
        <span>Cumplimiento documental</span>
        <strong>{percent(counts.compliance)}</strong>
        <p>
          {counts.approved} aprobadas de {counts.required} obligaciones
          exigibles
        </p>
      </article>
      <article className="gc-metric">
        <span>Entrega registrada</span>
        <strong>{percent(counts.delivery)}</strong>
        <p>La entrega requiere revisión para aprobarse</p>
      </article>
      <article className="gc-metric">
        <span>Documentos pendientes</span>
        <strong>{counts.missing + counts.submitted}</strong>
        <p>
          {counts.missing} sin entregar · {counts.submitted} por revisar
        </p>
      </article>
      <article className="gc-metric">
        <span>Requieren atención</span>
        <strong>{counts.incomplete + counts.rejected + counts.overdue}</strong>
        <p>
          {counts.incomplete} incompletos · {counts.overdue} fuera de plazo
        </p>
      </article>
    </div>
  );
}
function PeriodTable({ rows }: { rows: ConfigurationSummary["by_period"] }) {
  return rows.length ? (
    <div className="gc-table-wrap">
      <table className="gc-period-table">
        <caption className="gc-sr-only">
          Evolución del cumplimiento por período
        </caption>
        <thead>
          <tr>
            <th>Período</th>
            <th>Exigibles</th>
            <th>Aprobados</th>
            <th>Sin entregar</th>
            <th>Por revisar</th>
            <th>Cumplimiento</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.period}>
              <th scope="row">{periodName(row.period)}</th>
              <td data-label="Exigibles">{row.required}</td>
              <td data-label="Aprobados">{row.approved}</td>
              <td data-label="Sin entregar">{row.missing}</td>
              <td data-label="Por revisar">{row.submitted}</td>
              <td data-label="Cumplimiento">
                <strong>{percent(row.compliance)}</strong>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty>No hay períodos para consultar.</Empty>
  );
}
function AuditTable({ rows }: { rows: AuditRow[] }) {
  return rows.length ? (
    <div className="gc-audit-list">
      {rows.map((row) => (
        <article key={row.id} className="gc-audit-event">
          <span className="gc-event-dot" aria-hidden="true" />
          <div>
            <div className="gc-row">
              <strong>
                {row.actor || "Responsable sin nombre registrado"}
              </strong>
              <time dateTime={row.at}>{dateTimeName(row.at)}</time>
            </div>
            <p>
              {row.document || "Configuración general"} · {row.action}
              {row.period ? " · " + periodName(row.period) : ""}
            </p>
            <p className="gc-muted">{row.reason || "Cambio registrado"}</p>
            {Boolean(row.before || row.after) && (
              <details>
                <summary>Ver valores anteriores y nuevos</summary>
                <div className="gc-audit-values">
                  <div>
                    <b>Antes</b>
                    <AuditValue value={row.before} />
                  </div>
                  <div>
                    <b>Después</b>
                    <AuditValue value={row.after} />
                  </div>
                </div>
              </details>
            )}
          </div>
        </article>
      ))}
    </div>
  ) : (
    <Empty>No hay modificaciones en este contexto.</Empty>
  );
}
function AuditValue({ value }: { value: unknown }) {
  const labels: Record<string, string> = {
    name: "Nombre",
    description: "Descripción",
    category: "Categoría",
    level: "Nivel",
    frequency: "Frecuencia",
    conditions: "Condiciones",
    required: "Obligatoriedad",
    period_start: "Período inicial",
    period_end: "Período final",
    due_day: "Día límite",
    due_month_offset: "Meses hasta vencimiento",
    reason: "Motivo",
    scope: "Ámbito",
    state: "Estado",
    status: "Estado",
    notes: "Observaciones",
    observation: "Observación",
    alert_days: "Anticipación de alertas (días)",
    repeated_periods: "Períodos de reiteración",
    porteria_start_period: "Inicio de Portería",
    created_by: "Responsable",
    created_at: "Fecha",
    worker_name: "Trabajador observado",
    worker_rut: "RUT observado",
    movement_date: "Fecha de acceso",
    period: "Período",
  };
  if (value == null) return <p className="gc-muted">Sin valor registrado</p>;
  if (Array.isArray(value))
    return value.length ? (
      <div>
        {value.map((item, index) => (
          <AuditValue key={index} value={item} />
        ))}
      </div>
    ) : (
      <p className="gc-muted">Sin reglas anteriores</p>
    );
  if (typeof value !== "object")
    return (
      <p>
        {typeof value === "boolean" ? (value ? "Sí" : "No") : String(value)}
      </p>
    );
  const entries = Object.entries(value).filter(([key]) => labels[key]);
  return entries.length ? (
    <dl>
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{labels[key]}</dt>
          <dd>
            {item == null
              ? "Sin definir"
              : typeof item === "boolean"
                ? item
                  ? "Sí"
                  : "No"
                : typeof item === "object"
                  ? "Configuración registrada"
                  : states[String(item)] ||
                    frequencies[String(item)] ||
                    sources[String(item)] ||
                    ({
                      worker: "Trabajador",
                      contractor: "Contratista",
                      contractor_workers: "Contratista y trabajadores",
                      site_period: "Contratista, obra y período",
                    }[String(item)] ??
                      String(item))}
          </dd>
        </div>
      ))}
    </dl>
  ) : (
    <p className="gc-muted">Cambio registrado en el historial</p>
  );
}

export default function GeneralConfiguration({
  user,
  version,
  onBack,
  onOpenSettings,
  logout,
}: {
  user: Profile;
  version: string | null;
  onBack: () => void;
  onOpenSettings: () => void;
  logout: () => void;
}) {
  const [locationKey, setLocationKey] = useState(
    () => window.location.pathname + window.location.search,
  );
  useEffect(() => {
    const update = () =>
      setLocationKey(window.location.pathname + window.location.search);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  const query = useMemo(
    () => new URLSearchParams(locationKey.split("?")[1] || ""),
    [locationKey],
  );
  const pathname = locationKey.split("?")[0];
  const route = pathname.slice(ROOT.length).replace(/^\//, "");
  const associationId = route.startsWith("contratistas/")
    ? decodeURIComponent(route.split("/")[1])
    : "";
  const section = associationId ? "contratistas" : route;
  const tab = query.get("tab") || "resumen";
  const selectedPeriods = (query.get("periods") || nowMonth())
    .split(",")
    .filter(Boolean);
  const periodKey = selectedPeriods.join(",");
  const site = query.get("site_id") || "",
    category = query.get("category") || "",
    search = query.get("q") || "",
    state = query.get("state") || "";
  const [bootstrap, setBootstrap] = useState<ConfigurationBootstrap | null>(
      null,
    ),
    [data, setData] = useState<ConfigurationSummary | ContractorDetail | null>(
      null,
    );
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [revision, setRevision] = useState(0),
    [refreshTick, setRefreshTick] = useState(0),
    [page, setPage] = useState(0),
    [alertPage, setAlertPage] = useState(0),
    [usersSignal, setUsersSignal] = useState(0);
  const [mode, setMode] = useState(
      selectedPeriods.length > 1 ? "manual" : "single",
    ),
    [month, setMonth] = useState(selectedPeriods[0]),
    [endMonth, setEndMonth] = useState(selectedPeriods.at(-1) || nowMonth()),
    [year, setYear] = useState(Number(nowMonth().slice(0, 4))),
    [quarter, setQuarter] = useState(1),
    [manualMonths, setManualMonths] = useState<string[]>(selectedPeriods);
  const [audit, setAudit] = useState<{ rows: AuditRow[]; total: number }>({
      rows: [],
      total: 0,
    }),
    [auditPage, setAuditPage] = useState(0);
  const [auditActors, setAuditActors] = useState<
    { id: string; name: string }[]
  >([]);
  const [review, setReview] = useState<Obligation | null>(null),
    [reviewState, setReviewState] = useState<ReviewState>("approved"),
    [reviewNotes, setReviewNotes] = useState("");
  const [ruleScope, setRuleScope] = useState<RuleInput["scope"]>(
      associationId ? "association" : "general",
    ),
    [ruleDocument, setRuleDocument] = useState(""),
    [ruleCategory, setRuleCategory] = useState("CT"),
    [ruleSite, setRuleSite] = useState(site),
    [ruleAssociations, setRuleAssociations] = useState<string[]>(
      associationId ? [associationId] : [],
    ),
    [ruleRequired, setRuleRequired] = useState("true"),
    [ruleFrequency, setRuleFrequency] = useState("monthly"),
    [ruleStart, setRuleStart] = useState(nowMonth()),
    [ruleEnd, setRuleEnd] = useState(""),
    [ruleDay, setRuleDay] = useState(""),
    [ruleOffset, setRuleOffset] = useState(0),
    [ruleReason, setRuleReason] = useState(""),
    [retroactive, setRetroactive] = useState(false),
    [preview, setPreview] = useState<{
      result: RulePreview;
      body: RuleInput;
    } | null>(null);
  const [alertDays, setAlertDays] = useState(7),
    [repeatPeriods, setRepeatPeriods] = useState(3),
    [alertReason, setAlertReason] = useState("");
  const [porteriaStart, setPorteriaStart] = useState(nowMonth()),
    [porteriaReason, setPorteriaReason] = useState(""),
    [porteriaRetroactive, setPorteriaRetroactive] = useState(false),
    [porteriaPreview, setPorteriaPreview] = useState<{
      result: RulePreview;
      body: { period_start: string; reason: string; retroactive: boolean };
    } | null>(null);
  const detail = associationId && data && "contractor" in data ? data : null;
  const requestQuery = useMemo(() => {
    const params = new URLSearchParams({ periods: periodKey });
    if (site) params.set("site_id", site);
    if (category) params.set("category", category);
    if (search) params.set("q", search);
    if (state) params.set("state", state);
    return params.toString();
  }, [periodKey, site, category, search, state]);
  function navigate(path: string, next = query, replace = false) {
    const url =
      ROOT +
      (path ? "/" + path : "") +
      (next.size ? "?" + next.toString() : "");
    window.history[replace ? "replaceState" : "pushState"](
      { ...window.history.state, galantSection: "configuration" },
      "",
      url,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
    setPage(0);
    setReview(null);
  }
  function filter(key: string, value: string) {
    const next = new URLSearchParams(query);
    if (value) next.set(key, value);
    else next.delete(key);
    navigate(route, next, true);
  }
  function reload() {
    setRevision((value) => value + 1);
    window.dispatchEvent(new Event("galant-changed"));
  }
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    void cfg
      .bootstrap()
      .then((value) => {
        if (active) {
          setBootstrap(value);
          setAlertDays(value.settings.alert_days);
          setRepeatPeriods(value.settings.repeated_periods);
          setPorteriaStart(value.settings.porteria_start_period);
        }
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    return () => {
      active = false;
    };
  }, [revision]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void (
      associationId
        ? cfg.contractor(associationId, requestQuery)
        : cfg.summary(requestQuery)
    )
      .then((value) => {
        if (active) setData(value);
      })
      .catch((err) => {
        if (active) {
          setData(null);
          setError(errorText(err));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [associationId, requestQuery, revision, refreshTick]);
  useEffect(() => {
    const update = () => {
      if (!document.hidden) setRefreshTick((value) => value + 1);
    };
    const timer = window.setInterval(update, 15000);
    window.addEventListener("focus", update);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", update);
    };
  }, []);
  useEffect(() => {
    setManualMonths(periodKey.split(","));
  }, [periodKey]);
  useEffect(() => {
    if (associationId) {
      setRuleScope("association");
      setRuleAssociations([associationId]);
    }
    setPreview(null);
    setReview(null);
  }, [associationId]);
  useEffect(() => {
    if (section !== "auditoria" && tab !== "auditoria") return;
    let active = true;
    const params = new URLSearchParams({
      limit: "25",
      offset: String(auditPage * 25),
    });
    if (associationId) params.set("association_id", associationId);
    if (site) params.set("site_id", site);
    if (selectedPeriods.length === 1) params.set("period", selectedPeriods[0]);
    const actor = query.get("user_id");
    if (actor) params.set("user_id", actor);
    void net<Account[]>("/users")
      .then((rows) => {
        if (active)
          setAuditActors(
            rows.map((row) => ({
              id: row.id,
              name:
                row.name && !row.name.includes("@")
                  ? row.name
                  : "Responsable sin nombre registrado",
            })),
          );
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    void cfg
      .audit(params.toString())
      .then((value) => {
        if (active) setAudit(value);
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    return () => {
      active = false;
    };
  }, [
    section,
    tab,
    associationId,
    site,
    periodKey,
    query,
    auditPage,
    revision,
    refreshTick,
  ]);
  useEffect(() => { setAlertPage(0); }, [requestQuery, associationId]);
  function consultPeriods() {
    let values = [month];
    if (mode === "manual") values = manualMonths;
    if (mode === "range") values = monthsBetween(month, endMonth);
    if (mode === "quarter" || mode === "semester") {
      const count = mode === "quarter" ? 3 : 6,
        start = (quarter - 1) * count + 1;
      values = monthsBetween(
        year + "-" + String(start).padStart(2, "0"),
        year + "-" + String(start + count - 1).padStart(2, "0"),
      );
    }
    if (mode === "year") values = monthsBetween(year + "-01", year + "-12");
    if (mode === "all") values = bootstrap?.periods || [];
    values = [...new Set(values)].filter(Boolean).sort();
    if (!values.length || values.length > 60) {
      setError(
        "Selecciona entre 1 y 60 meses. Para registros más extensos consulta por rangos.",
      );
      return;
    }
    filter("periods", values.join(","));
  }
  function ruleBody(): RuleInput {
    return {
      document_type_id: ruleDocument,
      scope: ruleScope,
      category: ruleScope === "category" ? ruleCategory : undefined,
      site_id: ruleScope === "site" ? ruleSite : undefined,
      association_ids: ["association", "exception"].includes(ruleScope)
        ? ruleAssociations
        : [],
      required: ruleRequired === "inherit" ? null : ruleRequired === "true",
      frequency: ruleFrequency,
      period_start: ruleStart,
      period_end: ruleEnd || null,
      due_day: ruleDay ? Number(ruleDay) : null,
      due_month_offset: ruleOffset,
      reason: ruleReason,
      retroactive,
    };
  }
  const heading = associationId
    ? detail?.contractor.name || "Ficha del contratista"
    : section
      ? sections.find(([key]) => key === section)?.[1] ||
        "Configuración General"
      : "Configuración General";
  const ruleForm = (
    <section className="gc-card gc-rule-editor" aria-labelledby="gc-rule-title">
      <div className="gc-section-heading">
        <div>
          <span className="gc-eyebrow">REGLAS CON VIGENCIA</span>
          <h2 id="gc-rule-title">Configurar exigencia</h2>
        </div>
        <Settings2 aria-hidden="true" />
      </div>
      <p className="gc-muted">
        General → categoría → obra → contratista → excepción. Cada cambio
        conserva su período de aplicación y responsable.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const body = ruleBody();
            const result = await cfg.preview(body);
            setPreview({ result, body });
          });
        }}
        onChange={() => setPreview(null)}
      >
        <div className="gc-form-grid">
          <label>
            Documento de la regla
            <select
              disabled={busy}
              required
              aria-label="Documento de la regla"
              value={ruleDocument}
              onChange={(event) => setRuleDocument(event.target.value)}
            >
              <option value="">Selecciona un documento</option>
              {bootstrap?.catalog.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Ámbito de aplicación
            <select
              disabled={busy}
              aria-label="Ámbito de aplicación"
              value={ruleScope}
              onChange={(event) =>
                setRuleScope(event.target.value as RuleInput["scope"])
              }
            >
              <option value="general">Todos los contratistas</option>
              <option value="category">Plantilla por categoría</option>
              <option value="site">Todos los contratistas de una obra</option>
              <option value="association">Contratistas seleccionados</option>
              <option value="exception">Excepción temporal autorizada</option>
            </select>
          </label>
          {ruleScope === "category" && (
            <label>
              Categoría de la regla
              <select
                disabled={busy}
                aria-label="Categoría de la regla"
                value={ruleCategory}
                onChange={(event) => setRuleCategory(event.target.value)}
              >
                <option value="CT">CT · Fijo</option>
                <option value="CE">CE · Esporádico</option>
                <option value="CI">CI · Independiente</option>
              </select>
            </label>
          )}
          {ruleScope === "site" && (
            <label>
              Obra de la regla
              <select
                disabled={busy}
                required
                aria-label="Obra de la regla"
                value={ruleSite}
                onChange={(event) => setRuleSite(event.target.value)}
              >
                <option value="">Selecciona una obra</option>
                {bootstrap?.sites.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {["association", "exception"].includes(ruleScope) && (
            <label className="gc-field-wide">
              Contratistas de la regla
              <select
                disabled={busy}
                required
                multiple
                size={Math.min(5, bootstrap?.contractors.length || 2)}
                aria-label="Contratistas de la regla"
                value={ruleAssociations}
                onChange={(event) =>
                  setRuleAssociations(
                    Array.from(
                      event.target.selectedOptions,
                      (option) => option.value,
                    ),
                  )
                }
              >
                {bootstrap?.contractors.map((item) => (
                  <option key={item.association_id} value={item.association_id}>
                    {item.name} · {item.site} · {item.category}
                  </option>
                ))}
              </select>
              <small>
                Selecciona uno o varios contratistas. En computador puedes usar
                Ctrl o ⌘.
              </small>
            </label>
          )}
          <label>
            Obligatoriedad
            <select
              disabled={busy}
              aria-label="Obligatoriedad"
              value={ruleRequired}
              onChange={(event) => setRuleRequired(event.target.value)}
            >
              <option value="true">Obligatorio</option>
              <option value="false">No obligatorio / exento</option>
              <option value="inherit">Restaurar configuración heredada</option>
            </select>
          </label>
          <label>
            Frecuencia de la regla
            <select
              disabled={busy}
              aria-label="Frecuencia de la regla"
              value={ruleFrequency}
              onChange={(event) => setRuleFrequency(event.target.value)}
            >
              {Object.entries(frequencies).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Desde el período
            <input
              disabled={busy}
              required
              type="month"
              min="2000-01"
              max="2099-12"
              value={ruleStart}
              onChange={(event) => setRuleStart(event.target.value)}
            />
          </label>
          <label>
            Hasta el período
            <input
              disabled={busy}
              type="month"
              min={ruleStart}
              max="2099-12"
              aria-label="Hasta el período"
              value={ruleEnd}
              onChange={(event) => setRuleEnd(event.target.value)}
            />
            <small>Vacío: continúa sin fecha de término.</small>
          </label>
          <label>
            Día límite
            <input
              disabled={busy}
              type="number"
              min={1}
              max={31}
              value={ruleDay}
              onChange={(event) => setRuleDay(event.target.value)}
              placeholder="Sin fecha definida"
            />
          </label>
          <label>
            Mes del vencimiento
            <select
              disabled={busy}
              aria-label="Mes del vencimiento"
              value={ruleOffset}
              onChange={(event) => setRuleOffset(Number(event.target.value))}
            >
              <option value={0}>Mismo mes</option>
              <option value={1}>Mes siguiente</option>
            </select>
          </label>
          <label className="gc-field-wide">
            Motivo del cambio
            <textarea
              disabled={busy}
              required
              minLength={3}
              maxLength={2000}
              rows={3}
              value={ruleReason}
              onChange={(event) => setRuleReason(event.target.value)}
              placeholder="Describe el alcance y la razón de esta modificación"
            />
          </label>
          <label className="gc-check gc-field-wide">
            <input
              disabled={busy}
              type="checkbox"
              checked={retroactive}
              onChange={(event) => setRetroactive(event.target.checked)}
            />
            Solicito una corrección retroactiva y revisaré su impacto antes de
            confirmar.
          </label>
        </div>
        <p className="gc-callout">
          Informe de Portería es obligatorio para CT, CE y CI. Su exención
          requiere una excepción autorizada con motivo.
        </p>
        <button className="gc-primary" disabled={busy || !bootstrap}>
          Ver impacto
        </button>
      </form>
      {preview && (
        <div
          className="gc-preview"
          role="region"
          aria-label="Vista previa del cambio"
        >
          <h3>Vista previa del cambio</h3>
          <p>
            <strong>{preview.result.affected}</strong> contratistas afectados.
            {preview.result.historical &&
              " Incluye períodos históricos: revisa cuidadosamente los cambios."}
          </p>
          {preview.result.periods_previewed?.length ? (
            <p>
              Vista previa: {preview.result.periods_previewed[0]} a{" "}
              {preview.result.periods_previewed.at(-1)}.
              {preview.result.continues_after_preview &&
                " La regla continuará aplicándose después del rango mostrado hasta su fecha de término, o indefinidamente si no tiene término."}
            </p>
          ) : null}
          {preview.result.conflicts.length > 0 && (
            <>
              <h4>Reglas anteriores con vigencia coincidente</h4>
              <p>
                La nueva revisión tendrá prioridad desde el período indicado.
                Las reglas anteriores se conservan en el historial.
              </p>
              <ul>
                {preview.result.conflicts.map((item, index) => (
                  <li key={index}>
                    {typeof item === "string"
                      ? item
                      : (sources[item.scope] || item.scope) +
                        " · " +
                        item.period_start +
                        " a " +
                        (item.period_end || "sin término") +
                        " · " +
                        (item.required == null
                          ? "heredada"
                          : item.required
                            ? "obligatoria"
                            : "no obligatoria") +
                        (item.reason ? " · " + item.reason : "")}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="gc-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Contratista</th>
                  <th>Obra</th>
                  <th>Período</th>
                  <th>Antes</th>
                  <th>Después</th>
                </tr>
              </thead>
              <tbody>
                {preview.result.changes.slice(0, 30).map((item, index) => (
                  <tr key={index}>
                    <td>{item.name}</td>
                    <td>{item.site}</td>
                    <td>{item.period}</td>
                    <td>
                      {item.from_required == null
                        ? "Heredado"
                        : item.from_required
                          ? "Obligatorio"
                          : "No obligatorio"}
                    </td>
                    <td>
                      {item.to_required == null
                        ? "Heredado"
                        : item.to_required
                          ? "Obligatorio"
                          : "No obligatorio"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.result.changes.length > 30 && (
            <p>
              Se muestran los primeros 30 cambios de{" "}
              {preview.result.changes.length}.
            </p>
          )}
          <button
            className="gc-primary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await cfg.apply(preview.body, preview.result.preview_token);
                setPreview(null);
                setNotice(
                  "Configuración guardada. Se conservaron las reglas e historial anteriores.",
                );
                reload();
              })
            }
          >
            Confirmar y guardar
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setPreview(null)}
          >
            Cancelar
          </button>
        </div>
      )}
    </section>
  );
  function openReview(row: Obligation) {
    setReview(row);
    setReviewState(
      (Object.keys(states).includes(row.state) &&
      [
        "approved",
        "submitted",
        "missing",
        "incomplete",
        "rejected",
        "overdue",
        "not_applicable",
        "exempt",
        "no_movements",
      ].includes(row.state)
        ? row.state
        : "submitted") as ReviewState,
    );
    setReviewNotes(row.notes || "");
  }
  const obligations = data?.obligations || [];
  const documentTable = (
    <section className="gc-card">
      <div className="gc-section-heading">
        <div>
          <h2>Documentación y revisión manual</h2>
          <p className="gc-muted">
            Registra el resultado comprobado de la revisión. Los archivos
            históricos conservan su asociación.
          </p>
        </div>
      </div>
      {obligations.length ? (
        <>
          <div className="gc-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Documento / período</th>
                  <th>Estado</th>
                  <th>Regla y vencimiento</th>
                  <th>Última revisión</th>
                  <th>Acción</th>
                </tr>
              </thead>
              <tbody>
                {obligations.slice(page * 25, page * 25 + 25).map((row) => (
                  <tr
                    key={[
                      row.association_id,
                      row.period,
                      row.document_type_id,
                      row.subject,
                    ].join(":")}
                  >
                    <td>
                      <strong>{row.document}</strong>
                      {row.worker && <small>{row.worker}</small>}
                      <small>
                        {periodName(row.period)}
                        {!associationId ? " · " + row.contractor : ""}
                      </small>
                      {row.document_id && (
                        <a
                          href={api.pdf(row.document_id)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Ver original <ArrowUpRight size={12} />
                        </a>
                      )}
                    </td>
                    <td>
                      <Status value={row.state} />
                      {row.notes && <small>{row.notes}</small>}
                    </td>
                    <td>
                      {sources[row.rule_source] || row.rule_source}
                      <small>
                        {row.due_date
                          ? "Límite: " + dateName(row.due_date)
                          : "Sin fecha límite configurada"}
                      </small>
                    </td>
                    <td>
                      {row.reviewed_by || "Sin revisión registrada"}
                      <small>
                        {row.reviewed_at ? dateName(row.reviewed_at) : ""}
                      </small>
                    </td>
                    <td>
                      <button
                        type="button"
                        disabled={busy}
                        aria-label={
                          "Revisar " + row.document + " " + row.period
                        }
                        onClick={() => openReview(row)}
                      >
                        Revisar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} total={obligations.length} onPage={setPage} />
        </>
      ) : (
        <Empty>
          No hay obligaciones en los períodos y filtros seleccionados.
        </Empty>
      )}
      {review && (
        <form
          className="gc-review-form"
          aria-label="Formulario de revisión manual"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await cfg.review({
                association_id: review.association_id,
                period: review.period,
                document_type_id: review.document_type_id,
                state: reviewState,
                notes: reviewNotes,
                subject: review.subject || "contractor",
              });
              setReview(null);
              setNotice(
                "Revisión guardada y compartida con los administradores de la organización.",
              );
              reload();
            });
          }}
        >
          <h3>
            {review.document} · {periodName(review.period)}
          </h3>
          {review.worker && <p>{review.worker}</p>}
          <div className="gc-form-grid">
            <label>
              Estado de revisión
              <select
                disabled={busy}
                aria-label="Estado de revisión"
                value={reviewState}
                onChange={(event) =>
                  setReviewState(event.target.value as ReviewState)
                }
              >
                {(
                  [
                    "approved",
                    "submitted",
                    "missing",
                    "incomplete",
                    "rejected",
                    "overdue",
                    "not_applicable",
                    "exempt",
                    "no_movements",
                  ] as ReviewState[]
                ).map((value) => (
                  <option key={value} value={value}>
                    {states[value]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Observaciones de revisión
              <textarea
                disabled={busy}
                rows={3}
                required={[
                  "incomplete",
                  "rejected",
                  "overdue",
                  "not_applicable",
                  "exempt",
                  "no_movements",
                ].includes(reviewState)}
                minLength={3}
                maxLength={2000}
                value={reviewNotes}
                onChange={(event) => setReviewNotes(event.target.value)}
              />
            </label>
          </div>
          <p className="gc-muted">
            Las excepciones y la ausencia de movimientos requieren un motivo
            verificable. Ningún estado se deduce por la ausencia de un archivo.
          </p>
          <button className="gc-primary" disabled={busy}>
            Guardar revisión
          </button>
          <button type="button" onClick={() => setReview(null)}>
            Cancelar revisión
          </button>
        </form>
      )}
    </section>
  );
  const alertList = (
    <section className="gc-card">
      <div className="gc-section-heading">
        <h2>Alertas documentales</h2>
        <span className="gc-count">{data?.alerts.length || 0}</span>
      </div>
      {data?.alerts.length ? (
        <div className="gc-alert-list">
          {data.alerts.slice(alertPage * 25, (alertPage + 1) * 25).map((alert) => (
            <article key={alert.key} className="gc-alert">
              <span aria-hidden="true">!</span>
              <div>
                <strong>{alert.reason}</strong>
                <p>
                  {alert.contractor} · {alert.site} · {periodName(alert.period)}
                </p>
                <small>
                  {alert.document} · {alert.action}
                </small>
              </div>
              <button
                type="button"
                aria-label={"Revisar alerta de " + alert.contractor}
                onClick={() => {
                  const next = new URLSearchParams(query);
                  next.set("tab", "documentos");
                  next.set("periods", alert.period.replace(/\s+/g, ""));
                  next.delete("state");
                  next.delete("q");
                  navigate("contratistas/" + alert.association_id, next);
                }}
              >
                Revisar <ChevronRight size={14} />
              </button>
            </article>
          ))}
        </div>
      ) : (
        <Empty>No se detectaron alertas con la información disponible.</Empty>
      )}
      <Pagination page={alertPage} total={data?.alerts.length || 0} onPage={setAlertPage} />
    </section>
  );
  return (
    <div className="gc-root" data-testid="configuration-center">
      <header className="gc-topbar">
        <button
          type="button"
          className="gc-back"
          onClick={() => (associationId ? navigate("contratistas") : onBack())}
        >
          <ArrowLeft size={17} /> ← Volver
        </button>
        <a
          className="gc-brand"
          href={ROOT}
          onClick={(event) => {
            event.preventDefault();
            navigate("");
          }}
        >
          <span>G</span>
          <div>
            <b>GALANT POST</b>
            <small>Centro de configuración</small>
          </div>
        </a>
        <div className="gc-top-actions">
          <span className="gc-admin-label">
            <ShieldCheck size={15} /> Administrador · v{version}
          </span>
          <NetworkAccountMenu
            user={user}
            logout={logout}
            openSettings={onOpenSettings}
            openUsersSignal={usersSignal}
          />
        </div>
      </header>
      <div className="gc-layout">
        <aside className="gc-sidebar">
          <p>ADMINISTRACIÓN CENTRAL</p>
          <nav aria-label="Configuración General">
            {sections.map(([key, label, Icon]) => (
              <a
                key={key}
                href={ROOT + (key ? "/" + key : "")}
                aria-current={section === key ? "page" : undefined}
                className={section === key ? "active" : ""}
                onClick={(event) => {
                  event.preventDefault();
                  const next = new URLSearchParams(query);
                  next.delete("tab");
                  navigate(key, next);
                }}
              >
                <Icon size={18} />
                <span>{label}</span>
              </a>
            ))}
          </nav>
          <div className="gc-sidebar-note">
            <ShieldCheck size={20} />
            <strong>Configuración compartida</strong>
            <p>Los cambios se guardan con su vigencia, motivo y responsable.</p>
          </div>
        </aside>
        <main className="gc-content">
          <div className="gc-page-heading">
            <div>
              <span className="gc-eyebrow">
                {associationId
                  ? "FICHA INTEGRAL DEL CONTRATISTA"
                  : "CONTROL DOCUMENTAL · ADMINISTRADOR"}
              </span>
              <h1>{heading}</h1>
              <p>
                {detail
                  ? [
                      detail.contractor.rut || "RUT sin registrar",
                      detail.contractor.site,
                      detail.contractor.category,
                      detail.contractor.status === "active"
                        ? "Activo"
                        : "Inactivo",
                    ].join(" · ")
                  : "Administra exigencias, consulta períodos y conserva el historial de cada obra."}
              </p>
            </div>
            <button
              type="button"
              disabled={loading || busy}
              onClick={() => setRefreshTick((value) => value + 1)}
            >
              <RefreshCcw size={16} /> Actualizar
            </button>
          </div>
          <section
            className="gc-period-selector"
            aria-label="Consulta de varios períodos"
          >
            <div className="gc-period-title">
              <CalendarRange size={20} />
              <div>
                <strong>Consulta multiperíodo</strong>
                <small>Independiente del mes operativo de GALANT</small>
              </div>
            </div>
            <div className="gc-period-fields">
              <label>
                Selección de períodos
                <select
                  disabled={busy}
                  aria-label="Selección de períodos"
                  value={mode}
                  onChange={(event) => {
                    setMode(event.target.value);
                    setQuarter(1);
                  }}
                >
                  <option value="single">Un mes</option>
                  <option value="manual">Varios meses</option>
                  <option value="range">Rango de meses</option>
                  <option value="quarter">Trimestre</option>
                  <option value="semester">Semestre</option>
                  <option value="year">Año completo</option>
                  <option value="all">Todos los períodos disponibles</option>
                </select>
              </label>
              {["single", "manual", "range"].includes(mode) && (
                <label>
                  {mode === "manual"
                    ? "Agregar mes"
                    : mode === "range"
                      ? "Desde"
                      : "Mes de consulta"}
                  <input
                    disabled={busy}
                    type="month"
                    min="2000-01"
                    max="2099-12"
                    aria-label={
                      mode === "manual"
                        ? "Agregar mes"
                        : mode === "range"
                          ? "Desde"
                          : "Mes de consulta"
                    }
                    value={month}
                    onChange={(event) => setMonth(event.target.value)}
                  />
                </label>
              )}
              {mode === "range" && (
                <label>
                  Hasta
                  <input
                    disabled={busy}
                    type="month"
                    min={month}
                    max="2099-12"
                    value={endMonth}
                    onChange={(event) => setEndMonth(event.target.value)}
                  />
                </label>
              )}
              {["quarter", "semester", "year"].includes(mode) && (
                <label>
                  Año de consulta
                  <input
                    disabled={busy}
                    type="number"
                    min={2000}
                    max={2099}
                    value={year}
                    onChange={(event) => setYear(Number(event.target.value))}
                  />
                </label>
              )}
              {["quarter", "semester"].includes(mode) && (
                <label>
                  {mode === "quarter" ? "Trimestre" : "Semestre"}
                  <select
                    disabled={busy}
                    aria-label={mode === "quarter" ? "Trimestre" : "Semestre"}
                    value={quarter}
                    onChange={(event) => setQuarter(Number(event.target.value))}
                  >
                    {Array.from(
                      { length: mode === "quarter" ? 4 : 2 },
                      (_, index) => (
                        <option key={index} value={index + 1}>
                          {index + 1}°{" "}
                          {mode === "quarter" ? "trimestre" : "semestre"}
                        </option>
                      ),
                    )}
                  </select>
                </label>
              )}
              {mode === "manual" && (
                <button
                  type="button"
                  onClick={() =>
                    month &&
                    setManualMonths((values) =>
                      [...new Set([...values, month])].sort(),
                    )
                  }
                >
                  Agregar período
                </button>
              )}
              <button
                type="button"
                className="gc-primary"
                onClick={consultPeriods}
              >
                Consultar períodos
              </button>
            </div>
            {mode === "manual" && (
              <div className="gc-period-chips">
                {manualMonths.map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-label={"Quitar " + value}
                    onClick={() =>
                      setManualMonths((values) =>
                        values.filter((item) => item !== value),
                      )
                    }
                  >
                    {value} ×
                  </button>
                ))}
              </div>
            )}
            <p className="gc-muted gc-period-applied">
              Consulta actual:{" "}
              {selectedPeriods.length <= 3
                ? selectedPeriods.map(periodName).join(" · ")
                : selectedPeriods.length +
                  " meses, desde " +
                  selectedPeriods[0] +
                  " hasta " +
                  selectedPeriods.at(-1)}
            </p>
          </section>
          {!associationId && (
            <div className="gc-filters">
              <label>
                Obra de consulta
                <select
                  disabled={busy}
                  aria-label="Obra de consulta"
                  value={site}
                  onChange={(event) => filter("site_id", event.target.value)}
                >
                  <option value="">Todas las obras</option>
                  {bootstrap?.sites.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Categoría de consulta
                <select
                  disabled={busy}
                  aria-label="Categoría de consulta"
                  value={category}
                  onChange={(event) => filter("category", event.target.value)}
                >
                  <option value="">Todas las categorías</option>
                  <option value="CT">CT · Fijo</option>
                  <option value="CE">CE · Esporádico</option>
                  <option value="CI">CI · Independiente</option>
                </select>
              </label>
              <label>
                Buscar contratista
                <input
                  disabled={busy}
                  type="search"
                  value={search}
                  onChange={(event) => filter("q", event.target.value)}
                  placeholder="Nombre o RUT"
                />
              </label>
              <label>
                Estado documental
                <select
                  disabled={busy}
                  aria-label="Estado documental"
                  value={state}
                  onChange={(event) => filter("state", event.target.value)}
                >
                  <option value="">Todos los estados</option>
                  {Object.entries(states)
                    .filter(([key]) =>
                      [
                        "approved",
                        "submitted",
                        "missing",
                        "incomplete",
                        "rejected",
                        "overdue",
                        "no_movements",
                      ].includes(key),
                    )
                    .map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                </select>
              </label>
            </div>
          )}
          {error && (
            <div className="gc-error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="gc-success" role="status">
              <CheckCircle2 size={17} />
              {notice}
            </div>
          )}
          {loading && (
            <p className="gc-loading" role="status">
              Consultando información compartida…
            </p>
          )}
          {associationId && (
            <nav className="gc-tabs" aria-label="Ficha del contratista">
              {[
                ["resumen", "Resumen"],
                ["documentos", "Documentación"],
                ["trabajadores", "Trabajadores"],
                ["configuracion", "Configuración"],
                ["historial", "Historial"],
                ["auditoria", "Auditoría"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  aria-current={tab === value ? "page" : undefined}
                  className={tab === value ? "active" : ""}
                  onClick={() => {
                    const next = new URLSearchParams(query);
                    next.set("tab", value);
                    navigate(route, next);
                  }}
                >
                  {label}
                </button>
              ))}
            </nav>
          )}
          {data &&
            ((!section && !associationId) ||
              (associationId && tab === "resumen")) && (
              <>
                <Metrics counts={data.summary} />
                <div className="gc-quick-info">
                  <span>
                    <b>{data.summary.active || 0}</b> contratistas activos
                  </span>
                  <span>
                    <b>{data.summary.inactive || 0}</b> inactivos
                  </span>
                  {["CT", "CE", "CI"].map((value) => (
                    <span key={value}>
                      <b>{data.summary.categories?.[value] || 0}</b> {value}
                    </span>
                  ))}
                  <span>
                    <b>{data.summary.porteria_pending || 0}</b> Informes de
                    Portería pendientes
                  </span>
                </div>
                <section className="gc-card">
                  <div className="gc-section-heading">
                    <h2>Evolución del cumplimiento</h2>
                    <span className="gc-muted">
                      Aprobados / obligaciones exigibles
                    </span>
                  </div>
                  <PeriodTable rows={data.by_period} />
                </section>
                {!associationId && (
                  <section className="gc-card">
                    <h2>Cumplimiento por obra</h2>
                    <div className="gc-site-grid">
                      {data.by_site.map((item) => (
                        <button
                          key={item.site_id}
                          type="button"
                          onClick={() => {
                            filter("site_id", item.site_id);
                          }}
                        >
                          <Building2 size={18} />
                          <strong>{item.site}</strong>
                          <b>{percent(item.compliance)}</b>
                          <small>
                            {item.approved} de {item.required} aprobados
                          </small>
                        </button>
                      ))}
                    </div>
                  </section>
                )}
                {alertList}
              </>
            )}
          {section === "contratistas" && !associationId && (
            <section className="gc-card">
              <div className="gc-section-heading">
                <h2>Configuración de contratistas</h2>
                <span className="gc-count">
                  {data?.contractors.length || 0}
                </span>
              </div>
              <p className="gc-muted">
                Selecciona una ficha para revisar su situación, trabajadores y
                exigencias individuales.
              </p>
              {data?.contractors.length ? (
                <>
                  <div className="gc-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Contratista</th>
                          <th>Obra</th>
                          <th>Categoría</th>
                          <th>Cumplimiento</th>
                          <th>Estado</th>
                          <th>Ficha</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.contractors
                          .slice(page * 25, page * 25 + 25)
                          .map((item) => (
                            <tr key={item.association_id}>
                              <td>
                                <strong>{item.name}</strong>
                                <small>{item.rut || "RUT sin registrar"}</small>
                              </td>
                              <td>{item.site}</td>
                              <td>
                                <span className="gc-count">
                                  {item.category}
                                </span>
                              </td>
                              <td>
                                <strong>{percent(item.compliance)}</strong>
                                <small>
                                  {item.approved} / {item.required} aprobados
                                </small>
                              </td>
                              <td>
                                {item.status === "active"
                                  ? "Activo"
                                  : "Inactivo"}
                              </td>
                              <td>
                                <button
                                  type="button"
                                  aria-label={"Abrir ficha de " + item.name}
                                  onClick={() => {
                                    const next = new URLSearchParams(query);
                                    next.delete("state");
                                    next.delete("q");
                                    navigate(
                                      "contratistas/" + item.association_id,
                                      next,
                                    );
                                  }}
                                >
                                  Abrir ficha <ChevronRight size={14} />
                                </button>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination
                    page={page}
                    total={data.contractors.length}
                    onPage={setPage}
                  />
                </>
              ) : (
                <Empty>
                  No hay contratistas que coincidan con los filtros.
                </Empty>
              )}
            </section>
          )}
          {section === "documentos" && (
            <>
              <section className="gc-card">
                <h2>Catálogo general de documentos</h2>
                <p className="gc-muted">
                  La obligatoriedad se determina por las reglas vigentes; el
                  catálogo identifica el documento.
                </p>
                <div className="gc-document-grid">
                  {bootstrap?.catalog.map((item) => (
                    <article
                      key={item.id}
                      className={item.code === "porteria" ? "gc-porteria" : ""}
                    >
                      <FileCheck2 size={20} />
                      <h3>{item.name}</h3>
                      <p>{item.description || item.category}</p>
                      <small>
                        {frequencies[item.frequency] || item.frequency} ·{" "}
                        {item.level === "worker"
                          ? "Por trabajador"
                          : "Por contratista"}
                      </small>
                      {item.code === "porteria" && (
                        <b>Obligatorio CT · CE · CI</b>
                      )}
                    </article>
                  ))}
                </div>
              </section>
              <section className="gc-card">
                <h2>Agregar tipo documental</h2>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    const form = event.currentTarget,
                      values = new FormData(form);
                    void run(async () => {
                      await cfg.catalog({
                        name: String(values.get("name")),
                        description: String(values.get("description")),
                        category: String(values.get("category")),
                        level: String(values.get("level")),
                        frequency: String(values.get("frequency")),
                        conditions: String(values.get("conditions")),
                      });
                      form.reset();
                      setNotice(
                        "Documento incorporado al catálogo. Configura una regla para exigirlo.",
                      );
                      reload();
                    });
                  }}
                >
                  <div className="gc-form-grid">
                    <label>
                      Nombre del documento
                      <input
                        disabled={busy}
                        name="name"
                        required
                        minLength={2}
                        maxLength={180}
                      />
                    </label>
                    <label>
                      Categoría documental
                      <input
                        disabled={busy}
                        name="category"
                        required
                        defaultValue="Personalizado"
                        maxLength={100}
                      />
                    </label>
                    <label>
                      Nivel documental
                      <select
                        disabled={busy}
                        name="level"
                        aria-label="Nivel documental"
                      >
                        <option value="contractor">
                          Contratista / obra / período
                        </option>
                        <option value="worker">Trabajador / período</option>
                      </select>
                    </label>
                    <label>
                      Frecuencia documental
                      <select
                        disabled={busy}
                        name="frequency"
                        aria-label="Frecuencia documental"
                      >
                        {Object.entries(frequencies).map(([value, label]) => (
                          <option key={value} value={value}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Descripción
                      <input
                        disabled={busy}
                        name="description"
                        maxLength={1000}
                      />
                    </label>
                    <label>
                      Condiciones especiales
                      <input
                        disabled={busy}
                        name="conditions"
                        maxLength={1000}
                      />
                    </label>
                  </div>
                  <button className="gc-primary" disabled={busy}>
                    Agregar documento
                  </button>
                </form>
              </section>
              {ruleForm}
            </>
          )}
          {(section === "periodos" ||
            (associationId && tab === "configuracion")) && (
            <>
              {section === "periodos" && (
                <section className="gc-card gc-porteria-start">
                  <h2>Período inicial del Informe de Portería</h2>
                  <p className="gc-muted">
                    Se exige mensualmente a CT, CE y CI en todas las obras.
                    Cambia su fecha inicial con una vista previa; el historial
                    anterior permanece salvo corrección retroactiva explícita.
                  </p>
                  <form
                    onChange={() => setPorteriaPreview(null)}
                    onSubmit={(event) => {
                      event.preventDefault();
                      void run(async () => {
                        const body = {
                          period_start: porteriaStart,
                          reason: porteriaReason,
                          retroactive: porteriaRetroactive,
                        };
                        const result = await cfg.porteriaPreview(body);
                        setPorteriaPreview({ result, body });
                      });
                    }}
                  >
                    <div className="gc-form-grid">
                      <label>
                        Inicio general de Portería
                        <input
                          disabled={busy}
                          type="month"
                          required
                          min="2000-01"
                          max="2099-12"
                          value={porteriaStart}
                          onChange={(event) =>
                            setPorteriaStart(event.target.value)
                          }
                        />
                      </label>
                      <label>
                        Motivo del inicio de Portería
                        <input
                          disabled={busy}
                          required
                          minLength={3}
                          maxLength={2000}
                          value={porteriaReason}
                          onChange={(event) =>
                            setPorteriaReason(event.target.value)
                          }
                        />
                      </label>
                      <label className="gc-check gc-field-wide">
                        <input
                          disabled={busy}
                          type="checkbox"
                          checked={porteriaRetroactive}
                          onChange={(event) =>
                            setPorteriaRetroactive(event.target.checked)
                          }
                        />
                        Autorizo revisar una corrección retroactiva del inicio
                        de Portería.
                      </label>
                    </div>
                    <button disabled={busy} type="submit">
                      Ver impacto del inicio de Portería
                    </button>
                  </form>
                  {porteriaPreview && (
                    <div className="gc-preview">
                      <h3>Impacto del inicio de Portería</h3>
                      <p>
                        {porteriaPreview.result.affected} contratistas
                        afectados.
                        {porteriaPreview.result.historical
                          ? " Incluye una corrección histórica explícita."
                          : " Los períodos históricos anteriores se conservan."}
                      </p>
                      {porteriaPreview.result.periods_previewed?.length ? (
                        <p>
                          Se muestran los períodos{" "}
                          {porteriaPreview.result.periods_previewed[0]} a{" "}
                          {porteriaPreview.result.periods_previewed.at(-1)}.
                          {porteriaPreview.result.continues_after_preview &&
                            " La obligación continúa después de esta vista previa."}
                        </p>
                      ) : null}
                      <div className="gc-table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Contratista</th>
                              <th>Obra</th>
                              <th>Período</th>
                              <th>Antes</th>
                              <th>Después</th>
                            </tr>
                          </thead>
                          <tbody>
                            {porteriaPreview.result.changes
                              .slice(0, 30)
                              .map((item, index) => (
                                <tr key={index}>
                                  <td>{item.name}</td>
                                  <td>{item.site}</td>
                                  <td>{item.period}</td>
                                  <td>
                                    {item.from_required
                                      ? "Obligatorio"
                                      : "No exigible"}
                                  </td>
                                  <td>
                                    {item.to_required
                                      ? "Obligatorio"
                                      : "No exigible"}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                      {porteriaPreview.result.changes.length > 30 && (
                        <p>
                          Se muestran los primeros 30 de{" "}
                          {porteriaPreview.result.changes.length} cambios.
                        </p>
                      )}
                      <button
                        disabled={busy}
                        className="gc-primary"
                        onClick={() =>
                          void run(async () => {
                            await cfg.porteriaApply(
                              porteriaPreview.body,
                              porteriaPreview.result.preview_token,
                            );
                            setPorteriaPreview(null);
                            setNotice(
                              "Inicio de Portería guardado con trazabilidad.",
                            );
                            reload();
                          })
                        }
                      >
                        Confirmar inicio de Portería
                      </button>
                    </div>
                  )}
                </section>
              )}
              {ruleForm}
              {detail?.rules.length ? (
                <section className="gc-card">
                  <h2>Reglas registradas del contratista</h2>
                  <div className="gc-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Documento</th>
                          <th>Origen</th>
                          <th>Vigencia</th>
                          <th>Obligación</th>
                          <th>Motivo</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.rules.map((rule) => (
                          <tr key={rule.id}>
                            <td>
                              {rule.document ||
                                bootstrap?.catalog.find(
                                  (item) => item.id === rule.document_type_id,
                                )?.name ||
                                "Documento"}
                            </td>
                            <td>{sources[rule.scope] || rule.scope}</td>
                            <td>
                              {rule.period_start} →{" "}
                              {rule.period_end || "Sin término"}
                            </td>
                            <td>
                              {rule.required == null
                                ? "Heredada"
                                : rule.required
                                  ? "Obligatoria"
                                  : "No obligatoria"}
                            </td>
                            <td>{rule.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}
              {section === "periodos" && data && (
                <section className="gc-card">
                  <h2>Resultado por período</h2>
                  <PeriodTable rows={data.by_period} />
                </section>
              )}
            </>
          )}
          {section === "obras" && (
            <>
              <section className="gc-card">
                <h2>Reglas específicas por obra</h2>
                <p className="gc-muted">
                  Las nuevas obras heredan las reglas generales, incluido el
                  Informe de Portería para CT, CE y CI.
                </p>
                <div className="gc-site-grid">
                  {bootstrap?.sites.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setRuleScope("site");
                        setRuleSite(item.id);
                        setPreview(null);
                        document
                          .getElementById("gc-rule-title")
                          ?.scrollIntoView({ behavior: "smooth" });
                      }}
                    >
                      <Building2 size={20} />
                      <strong>{item.name}</strong>
                      <span>
                        Configurar esta obra <ChevronRight size={14} />
                      </span>
                    </button>
                  ))}
                </div>
              </section>
              {ruleForm}
            </>
          )}
          {section === "alertas" && (
            <>
              <section className="gc-card">
                <h2>Configurar alertas visuales</h2>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void run(async () => {
                      await cfg.alerts({
                        alert_days: alertDays,
                        repeated_periods: repeatPeriods,
                        reason: alertReason,
                      });
                      setNotice("Umbrales de alertas guardados.");
                      reload();
                    });
                  }}
                >
                  <div className="gc-form-grid">
                    <label>
                      Días de anticipación al vencimiento
                      <input
                        disabled={busy}
                        type="number"
                        min={0}
                        max={365}
                        value={alertDays}
                        onChange={(event) =>
                          setAlertDays(Number(event.target.value))
                        }
                      />
                    </label>
                    <label>
                      Períodos para detectar reiteración
                      <input
                        disabled={busy}
                        type="number"
                        min={2}
                        max={60}
                        value={repeatPeriods}
                        onChange={(event) =>
                          setRepeatPeriods(Number(event.target.value))
                        }
                      />
                    </label>
                    <label className="gc-field-wide">
                      Motivo de configuración de alertas
                      <input
                        disabled={busy}
                        required
                        minLength={3}
                        maxLength={2000}
                        value={alertReason}
                        onChange={(event) => setAlertReason(event.target.value)}
                      />
                    </label>
                  </div>
                  <button className="gc-primary" disabled={busy}>
                    Guardar alertas
                  </button>
                </form>
              </section>
              {alertList}
            </>
          )}
          {section === "usuarios" && (
            <section className="gc-card gc-users-card">
              <ShieldCheck size={38} />
              <h2>Usuarios y permisos</h2>
              <p>
                Administra las cuentas, roles y obras asignadas con la gestión
                de usuarios de GALANT.
              </p>
              <p className="gc-muted">
                Configuración General es exclusiva de administradores. Las
                administrativas y residentes conservan sus pantallas habituales.
              </p>
              <button
                type="button"
                className="gc-primary"
                onClick={() => setUsersSignal((value) => value + 1)}
              >
                Abrir gestión de usuarios <ArrowUpRight size={16} />
              </button>
            </section>
          )}
          {(section === "auditoria" ||
            (associationId && tab === "auditoria")) && (
            <section className="gc-card">
              <h2>Auditoría y responsables</h2>
              <p className="gc-muted">
                Historial de cambios del contexto seleccionado. Los eventos
                conservan los valores anteriores y nuevos.
              </p>
              <label className="gc-audit-actor">
                Responsable del cambio
                <select
                  disabled={busy}
                  aria-label="Responsable del cambio"
                  value={query.get("user_id") || ""}
                  onChange={(event) => {
                    setAuditPage(0);
                    filter("user_id", event.target.value);
                  }}
                >
                  <option value="">Todos los responsables</option>
                  {auditActors.map((actor) => (
                    <option key={actor.id} value={actor.id}>
                      {actor.name}
                    </option>
                  ))}
                </select>
              </label>
              <AuditTable rows={audit.rows} />
              <Pagination
                page={auditPage}
                total={audit.total}
                onPage={setAuditPage}
              />
            </section>
          )}
          {associationId && tab === "documentos" && (
            <>
              {documentTable}
              <section className="gc-card">
                <h2>Contrastar movimientos de portería</h2>
                <p className="gc-muted">
                  Registra accesos observados para contrastarlos con
                  trabajadores, contratos y firmas de asistencia. Las
                  diferencias requieren revisión.
                </p>
                <form
                  onSubmit={(event: FormEvent<HTMLFormElement>) => {
                    event.preventDefault();
                    const form = event.currentTarget,
                      values = new FormData(form),
                      movementDate = String(values.get("date"));
                    void run(async () => {
                      await cfg.gate({
                        association_id: associationId,
                        period: movementDate.slice(0, 7),
                        worker_name: String(values.get("name")),
                        worker_rut: String(values.get("rut")) || null,
                        movement_date: movementDate,
                        notes: String(values.get("notes")),
                      });
                      form.reset();
                      setNotice(
                        "Movimiento registrado. Las coincidencias y diferencias se actualizaron.",
                      );
                      reload();
                    });
                  }}
                >
                  <div className="gc-form-grid">
                    <label>
                      Nombre del trabajador observado
                      <input
                        disabled={busy}
                        name="name"
                        required
                        minLength={2}
                        maxLength={180}
                      />
                    </label>
                    <label>
                      RUT del trabajador observado
                      <input
                        disabled={busy}
                        name="rut"
                        maxLength={20}
                        placeholder="Opcional si no está disponible"
                      />
                    </label>
                    <label>
                      Fecha del acceso observado
                      <input disabled={busy} name="date" type="date" required />
                    </label>
                    <label>
                      Respaldo u observación del acceso
                      <input
                        disabled={busy}
                        name="notes"
                        required
                        minLength={3}
                        maxLength={2000}
                        placeholder="Referencia de la revisión realizada"
                      />
                    </label>
                  </div>
                  <button className="gc-primary" disabled={busy}>
                    Registrar movimiento de portería
                  </button>
                </form>
                {detail?.gate_movements?.length ? (
                  <div className="gc-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Trabajador observado</th>
                          <th>Fecha</th>
                          <th>Respaldo registrado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.gate_movements.map((item) => (
                          <tr key={item.id}>
                            <td>
                              {item.worker_name}
                              <small>
                                {item.worker_rut || "RUT sin informar"}
                              </small>
                            </td>
                            <td>{dateName(item.movement_date)}</td>
                            <td>{item.notes}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </section>
              {alertList}
            </>
          )}
          {detail && tab === "trabajadores" && (
            <section className="gc-card">
              <h2>Trabajadores asociados y contratos</h2>
              {detail.workers.length ? (
                <div className="gc-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Trabajador</th>
                        <th>Estado</th>
                        <th>Contratos registrados</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.workers.map((worker) => (
                        <tr key={worker.id}>
                          <td>
                            <strong>{worker.name}</strong>
                            <small>{worker.rut || "RUT sin registrar"}</small>
                          </td>
                          <td>{worker.active ? "Activo" : "Inactivo"}</td>
                          <td>
                            {worker.contracts.length
                              ? worker.contracts.map((contract) => (
                                  <p key={contract.id}>
                                    {dateName(contract.start_date)} →{" "}
                                    {contract.end_date
                                      ? dateName(contract.end_date)
                                      : "Sin término definido"}
                                    <small>{contract.status}</small>
                                  </p>
                                ))
                              : "Sin contrato registrado"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty>
                  No hay trabajadores asociados a este contratista y obra.
                </Empty>
              )}
            </section>
          )}
          {detail && tab === "historial" && (
            <section className="gc-card">
              <h2>Historial documental</h2>
              <p className="gc-muted">
                Resultados reproducidos con las reglas vigentes de cada mes.
              </p>
              <PeriodTable rows={detail.by_period} />
            </section>
          )}
          {!sections.some(([key]) => key === section) && !associationId && (
            <Empty>
              La sección solicitada no existe. Utiliza el menú de Configuración
              General.
            </Empty>
          )}
        </main>
      </div>
    </div>
  );
}
function Pagination({
  page,
  total,
  onPage,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
}) {
  return total > 25 ? (
    <div className="gc-pagination">
      <span>
        {page * 25 + 1}–{Math.min(total, (page + 1) * 25)} de {total}
      </span>
      <button
        type="button"
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
      >
        Anterior
      </button>
      <button
        type="button"
        disabled={(page + 1) * 25 >= total}
        onClick={() => onPage(page + 1)}
      >
        Siguiente
      </button>
    </div>
  ) : null;
}
