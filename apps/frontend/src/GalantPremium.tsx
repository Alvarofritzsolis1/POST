import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, Building2, CircleCheck, ShieldAlert } from "lucide-react";

export type MetricTone = "neutral" | "success" | "warning" | "danger" | "info";

export function DashboardMetricCard({label, value, icon: Icon, tone = "neutral", onClick}: {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone?: MetricTone;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`v15-dashboard-kpi galant-metric galant-tone-${tone}`} onClick={onClick}>
      <span className="galant-metric-head"><span className="galant-metric-icon"><Icon size={19} aria-hidden="true" /></span><ArrowUpRight size={16} className="galant-metric-arrow" aria-hidden="true" /></span>
      <span className="galant-metric-label">{label}</span>
      <strong>{value}</strong>
      <small>Ver detalle <span aria-hidden="true">→</span></small>
    </button>
  );
}

export function PageSkeleton({title="Preparando módulo"}: {title?: string}) {
  return <section className="galant-skeleton-page" aria-label={title} role="status">
    <span className="galant-visually-hidden">{title}</span>
    <div className="galant-skeleton galant-skeleton-heading" aria-hidden="true" />
    <div className="galant-skeleton-grid" aria-hidden="true">
      {[0, 1, 2, 3, 4].map(i => <div className="galant-skeleton-tile" key={i}><span className="galant-skeleton galant-skeleton-icon"/><span className="galant-skeleton galant-skeleton-line"/><span className="galant-skeleton galant-skeleton-number"/></div>)}
    </div>
    <div className="galant-skeleton galant-skeleton-panel" aria-hidden="true" />
  </section>;
}

export function StartupSplash() {
  return <div className="galant-startup" role="status" aria-label="Iniciando GALANT">
    <div className="galant-startup-panel">
      <span className="galant-startup-logo"><Building2 size={30} aria-hidden="true"/></span>
      <strong>GALANT</strong>
      <span>Preparando el espacio de trabajo</span>
      <div className="galant-startup-track" aria-hidden="true"><i /></div>
    </div>
  </div>;
}

export function DashboardStatus({children, tone}: {children: ReactNode; tone: MetricTone}) {
  const Icon = tone === "success" ? CircleCheck : tone === "danger" || tone === "warning" ? ShieldAlert : Building2;
  return <span className={`galant-dashboard-status galant-tone-${tone}`} role="status"><Icon size={15} aria-hidden="true" />{children}</span>;
}

/** Decoración secundaria; nunca se usa como dato o representación de una obra real. */
export function ArchitecturalBanner() {
  return <aside className="galant-architecture-banner" aria-label="GALANT: gestión inteligente de obras">
    <img
      src="https://images.unsplash.com/photo-1707499482789-9450160aaf83?auto=format&fit=crop&w=1320&q=72"
      loading="lazy" decoding="async" width="1320" height="440"
      alt="Fachada de una vivienda moderna con jardín" />
    <div className="galant-architecture-copy">
      <span className="galant-architecture-mark"><Building2 size={22} aria-hidden="true" /></span>
      <span className="galant-architecture-wordmark">GALANT</span>
      <strong>Gestión inteligente de obras.</strong>
    </div>
    <a className="galant-architecture-credit" href="https://unsplash.com/photos/LJhgmYcAVqU" target="_blank" rel="noreferrer">Fotografía: Unsplash</a>
  </aside>;
}
