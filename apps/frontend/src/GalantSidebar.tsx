import { Building2, Pin, PinOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type SidebarEntry = readonly [id: string, label: string, icon: LucideIcon];
export type SidebarGroup = Readonly<{ title: string; ids: readonly string[] }>;

export function GalantSidebar({
  entries, groups, selected, collapsed, preview, touch,
  organization, version, revision, navigate, togglePin, onEnter, onLeave,
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
  togglePin: () => void;
  onEnter: () => void;
  onLeave: () => void;
}) {
  return <aside className="sidebar" aria-label="Menú lateral de GALANT"
    onMouseEnter={onEnter} onMouseLeave={onLeave}
    onFocusCapture={onEnter}
    onBlurCapture={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onLeave();
    }}>
    <div className="brand galant-brand">
      <span className="galant-brand-symbol" aria-hidden="true"><Building2 size={23} /></span>
      <div><b>GALANT<span className="galant-brand-post"> POST</span></b><small>Gestión de contratistas</small></div>
      <button type="button" className="galant-sidebar-pin"
        title={collapsed ? "Fijar menú abierto" : "Usar menú automático"}
        aria-label={collapsed ? "Fijar menú abierto" : "Activar contracción automática"}
        aria-pressed={!collapsed} onClick={togglePin}>
        {collapsed ? <Pin size={16} aria-hidden="true" /> : <PinOff size={16} aria-hidden="true" />}
      </button>
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
