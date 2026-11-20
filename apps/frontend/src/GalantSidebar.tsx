import { Building2 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type SidebarEntry = readonly [id: string, label: string, icon: LucideIcon];
export type SidebarGroup = Readonly<{ title: string; ids: readonly string[] }>;

export function GalantSidebar({
  entries, groups, selected, collapsed, preview, touch,
  organization, version, revision, navigate, onEnter, onLeave,
}: {
  entries: readonly SidebarEntry[];
  groups: readonly SidebarGroup[];
  selected: string;
  collapsed: boolean;
  preview: boolean;
  touch: boolean;
  organization?: string | null;
  version?: string | null;
  revision?: string | null;
  navigate: (id: string) => void;
  onEnter: () => void;
  onLeave: () => void;
}) {
  return <aside id="galant-sidebar" className="sidebar" aria-label="Menú lateral de GALANT"
    onMouseEnter={onEnter} onMouseLeave={onLeave}
    onFocusCapture={onEnter}
    onBlurCapture={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onLeave();
    }}
    onKeyDown={(event) => {
      if (event.key === "Escape" && preview) {
        onLeave();
        document.querySelector<HTMLButtonElement>(".topbar .menu-toggle")?.focus();
      }
    }}>
    <div className="brand galant-brand">
      <span className="galant-brand-symbol" aria-hidden="true"><Building2 size={23} /></span>
      <div><b>GALANT<span className="galant-brand-post"> POST</span></b><small>Gestión de contratistas</small></div>
    </div>
    <p className="sidebar-label">ORGANIZACIÓN COMPARTIDA</p>
    <nav aria-label="Navegación principal">
      {groups.map(group => <div className="nav-group" role="group" aria-label={group.title} key={group.title}>
        <p className="nav-group-title">{group.title}</p>
        {group.ids.map(id => {
          const entry = entries.find(([key]) => key === id);
          if (!entry) return null;
          const [, label, Icon] = entry;
          return <button type="button" key={id} className={"nav-item " + (selected === id ? "active" : "")}
            aria-current={selected === id ? "page" : undefined} aria-label={label}
            title={collapsed && !preview && !touch ? label : undefined}
            onClick={() => navigate(id)}>
            <Icon size={18} aria-hidden="true" />
            <span className="v91-nav-label">{label}</span>
          </button>;
        })}
      </div>)}
    </nav>
    <div className="sidebar-bottom">
      <p>{organization}</p>
      <small>v{version} · {revision && revision !== "unbuilt" ? revision.slice(0, 8) + " · " : ""} Administrador</small>
    </div>
  </aside>;
}
