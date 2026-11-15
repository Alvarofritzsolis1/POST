import { useEffect, useState } from "react";
import { ArrowLeft, UserRound, Users, Building2, FileCheck2, SlidersHorizontal, Settings2, History, ChevronRight } from "lucide-react";
import CatalogEditor from "./CatalogEditor";
import { read, send, type OrgProfile, type Preferences } from "./platformApi";
import type { Site } from "./opsApi";
import Reconciliation from "./Reconciliation";
type Account = { id: string; email: string; role: string; enabled: boolean };
type SettingsView = "home" | "profile" | "users" | "sites" | "rules" | "historical";
export default function Settings({
  admin,
  sites,
  onPreferences,
  onOpenConfiguration,
  onOpenAutomation,
  onBack,
}: {
  admin: boolean;
  sites: Site[];
  onPreferences: (p: Preferences) => void;
  onOpenConfiguration?: (section?: string) => void;
  onOpenAutomation?: () => void;
  onBack: () => void;
}) {
  const [view, setView] = useState<SettingsView>("home");
  const [profile, setProfile] = useState<OrgProfile | null>(null),
    [users, setUsers] = useState<Account[]>([]),
    [rates, setRates] = useState<
      { effective_from: string; daily_clp: number }[]
    >([]),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [role, setRole] = useState("supervisor"),
    [oldPassword, setOldPassword] = useState(""),
    [newPassword, setNewPassword] = useState(""),
    [site, setSite] = useState(""),
    [rate, setRate] = useState(4950),
    [date, setDate] = useState(""),
    [catalogs, setCatalogs] = useState(""),
    [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [health, setHealth] = useState("");
  async function run(fn: () => Promise<void>) {
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await fn();
      setNotice("Cambios guardados.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    void Promise.all([
      read<OrgProfile>("/admin/profile"),
      read<object>("/admin/catalogs"),
      read<typeof rates>("/admin/rates"),
      read<{ status: string }>("/health"),
    ])
      .then(([p, c, r, h]) => {
        if (active) {
          setProfile(p);
          setCatalogs(JSON.stringify(c, null, 2));
          setRates(r);
          setHealth(h.status);
        }
      })
      .catch((e) => setError(String(e)));
    if (admin)
      void read<Account[]>("/admin/users")
        .then((u) => {
          if (active) setUsers(u);
        })
        .catch((e) => setError(String(e)));
    return () => {
      active = false;
    };
  }, [admin]);
  const prefs = profile?.preferences;
  function open(next: SettingsView) {
    setView(next);
    setError("");
    setNotice("");
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }
  const labels: Record<SettingsView, string> = {
    home: "Configuración", profile: "Mi cuenta", users: "Usuarios y permisos",
    sites: "Obras", rules: "Reglas operativas", historical: "Recuperación histórica",
  };
  return (
    <div className="settings-center" data-testid="settings-center">
      <header className="settings-heading">
        <button type="button" className="settings-back" onClick={() => view === "home" ? onBack() : open(view === "historical" ? "rules" : "home")}>
          <ArrowLeft size={18} /> {view === "home" ? "Volver" : "Configuración"}
        </button>
        <div>
          <p className="settings-breadcrumb">Inicio / Configuración{view === "home" ? "" : " / " + labels[view]}</p>
          <h1>{labels[view]}</h1>
          <p className="settings-description">{view === "home" ? "Todas las opciones administrativas en un solo lugar." : "Modifica solo lo necesario y conserva el resto de la información."}</p>
        </div>
      </header>
      {view === "home" && <div className="settings-category-grid" aria-label="Categorías de configuración">
        <button type="button" className="settings-category" onClick={() => open("profile")}>
          <span className="settings-category-icon"><UserRound size={22} /></span><strong>Mi cuenta</strong>
          <small>Perfil, preferencias y contraseña</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>
        {admin && <button type="button" className="settings-category" onClick={() => open("users")}>
          <span className="settings-category-icon"><Users size={22} /></span><strong>Usuarios y permisos</strong>
          <small>Cuentas y niveles de acceso</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
        {admin && <button type="button" className="settings-category" onClick={() => open("sites")}>
          <span className="settings-category-icon"><Building2 size={22} /></span><strong>Obras</strong>
          <small>Obras y datos generales</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
        {admin && <button type="button" className="settings-category" onClick={() => open("rules")}>
          <span className="settings-category-icon"><SlidersHorizontal size={22} /></span><strong>Reglas operativas</strong>
          <small>Retenciones, importaciones y alertas</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
        {admin && onOpenConfiguration && <button type="button" className="settings-category" onClick={() => onOpenConfiguration("documentos")}>
          <span className="settings-category-icon"><FileCheck2 size={22} /></span><strong>Exigencias documentales</strong>
          <small>Obras, contratistas, periodos y requisitos</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
        {admin && onOpenAutomation && <button type="button" className="settings-category" onClick={onOpenAutomation}>
          <span className="settings-category-icon"><Settings2 size={22} /></span><strong>Automatizaciones</strong>
          <small>Configuración de procesos de JAVIERA</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
        {admin && onOpenConfiguration && <button type="button" className="settings-category settings-category-advanced" onClick={() => onOpenConfiguration("auditoria")}>
          <span className="settings-category-icon"><History size={22} /></span><strong>Auditoría documental</strong>
          <small>Historial y trazabilidad de cambios</small><ChevronRight size={18} className="settings-category-arrow" />
        </button>}
      </div>}
      <div className="settings-detail">
      {view === "profile" && <section className="panel">
        <h2>Perfil y preferencias</h2>
        <p>
          {profile?.organization} · GALANT v{profile?.version} · Servicio:{" "}
          {health || "consultando"}
        </p>
        {prefs && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const next = await send<Preferences>(
                  "/admin/preferences",
                  prefs,
                  "PUT",
                );
                onPreferences(next);
              });
            }}
          >
            <label>
              Nombre
              <input
                value={prefs.name}
                onChange={(e) =>
                  setProfile({
                    ...profile!,
                    preferences: { ...prefs, name: e.target.value },
                  })
                }
              />
            </label>
            <label>
              Apariencia
              <select
                value={prefs.appearance}
                onChange={(e) =>
                  setProfile({
                    ...profile!,
                    preferences: {
                      ...prefs,
                      appearance: e.target.value as Preferences["appearance"],
                    },
                  })
                }
              >
                <option value="light">Clara</option>
                <option value="dark">Oscura</option>
              </select>
            </label>
            <label>
              Densidad
              <select
                value={prefs.density}
                onChange={(e) =>
                  setProfile({
                    ...profile!,
                    preferences: {
                      ...prefs,
                      density: e.target.value as Preferences["density"],
                    },
                  })
                }
              >
                <option value="comfortable">Cómoda</option>
                <option value="compact">Compacta</option>
              </select>
            </label>
            <label>
              Obra predeterminada
              <select
                value={prefs.default_site || ""}
                onChange={(e) =>
                  setProfile({
                    ...profile!,
                    preferences: {
                      ...prefs,
                      default_site: e.target.value || null,
                    },
                  })
                }
              >
                <option value="">Todas las obras</option>
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={prefs.notifications}
                onChange={(e) =>
                  setProfile({
                    ...profile!,
                    preferences: { ...prefs, notifications: e.target.checked },
                  })
                }
              />
              Avisos de actividad en pantalla
            </label>
            <p>Idioma: español · Fechas: dd/mm/aaaa</p>
            <button disabled={busy} className="primary">
              Guardar preferencias
            </button>
          </form>
        )}
        <h3>Cambio de contraseña</h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              await send("/admin/password", {
                current_password: oldPassword,
                new_password: newPassword,
              });
              setOldPassword("");
              setNewPassword("");
            });
          }}
        >
          <label>
            Contraseña actual
            <input
              type="password"
              required
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <label>
            Nueva contraseña
            <input
              type="password"
              required
              minLength={12}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <button disabled={busy}>Cambiar contraseña</button>
        </form>
      </section>}
      {admin && view === "users" && (
        <section className="panel">
          <h2>Administración de usuarios</h2>
          <p>
            Las cuentas nuevas compartirán la organización{" "}
            {profile?.organization}.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await send("/admin/users", { email, password, role });
                setUsers(await read<Account[]>("/admin/users"));
                setEmail("");
                setPassword("");
              });
            }}
          >
            <label>
              Correo
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Contraseña inicial
              <input
                type="password"
                minLength={12}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
            </label>
            <label>
              Rol
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="supervisor">Supervisor</option>
                <option value="reviewer">Revisor documental</option>
                <option value="administrative">Administrativa (asistencia)</option>
                <option value="analyst">Analista (legado)</option>
                <option value="viewer">Visualizador</option>
                <option value="admin">Administrador</option>
              </select>
            </label>
            <button disabled={busy} className="primary">
              Crear cuenta en esta organización
            </button>
          </form>
          <div className="settings-users-wrap">
            <table>
              <thead>
                <tr>
                  <th>Cuenta</th>
                  <th>Permisos</th>
                  <th>Acceso</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.email}</td>
                    <td>
                      <select
                        aria-label={"Rol " + u.email}
                        value={u.role}
                        disabled={busy}
                        onChange={(e) =>
                          void run(async () => {
                            await send(
                              "/admin/users/" + u.id,
                              { role: e.target.value, enabled: u.enabled },
                              "PATCH",
                            );
                            setUsers(await read<Account[]>("/admin/users"));
                          })
                        }
                      >
                        <option value="admin">Administrador</option>
                        <option value="supervisor">Supervisor</option>
                        <option value="reviewer">Revisor documental</option>
                        <option value="administrative">Administrativa (asistencia)</option>
                        <option value="analyst">Analista (legado)</option>
                        <option value="viewer">Visualizador</option>
                      </select>
                    </td>
                    <td>
                      <button
                        disabled={busy}
                        onClick={() =>
                          void run(async () => {
                            await send(
                              "/admin/users/" + u.id,
                              { role: u.role, enabled: !u.enabled },
                              "PATCH",
                            );
                            setUsers(await read<Account[]>("/admin/users"));
                          })
                        }
                      >
                        {u.enabled ? "Deshabilitar" : "Habilitar"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>Vincular una cuenta existente</summary>
            <p>
              Si su correo ya existe, el sistema bloquea una creación duplicada.
              El administrador del VPS debe ejecutar diagnose-user y revisar
              link-user con respaldo. No se fusionan organizaciones con
              información laboral.
            </p>
          </details>
        </section>
      )}
      {admin && view === "sites" && (
        <section className="panel">
          <h2>Obras de la organización</h2>
          <p>Obras registradas: {sites.length}</p>
          <ul className="settings-site-list">{sites.map((s) => <li key={s.id}><Building2 size={16} />{s.name}</li>)}</ul>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await send("/admin/sites", { name: site });
                setSite("");
                window.dispatchEvent(new Event("galant-changed"));
              });
            }}
          >
            <label>
              Nombre de obra
              <input
                required
                value={site}
                onChange={(e) => setSite(e.target.value)}
              />
            </label>
            <button disabled={busy}>Crear obra</button>
          </form>
        </section>
      )}
      {admin && view === "rules" && (<>
        <section className="panel">
          <h2>Retenciones y vigencias</h2>
          <h3>Valor diario con vigencia mensual</h3>
          <p>
            Valor registrado más reciente: ${(rates[0]?.daily_clp ?? 4950).toLocaleString("es-CL")} CLP.
            La retención es una estimación administrativa y cada vigencia conserva su historial.
          </p>
          <ul>
            {rates.map((r) => (
              <li key={r.effective_from}>
                {r.effective_from}: ${r.daily_clp.toLocaleString("es-CL")}
              </li>
            ))}
          </ul>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (rates.some((item) => item.effective_from === date + "-01")) {
                setError("Ya existe un valor para este mes. Se conservará el registro histórico.");
                return;
              }
              if (!window.confirm("¿Registrar una vigencia nueva de $" + rate.toLocaleString("es-CL") + " diarios desde " + date + "?")) return;
              void run(async () => {
                await send("/admin/rates", {
                  effective_from: date + "-01",
                  daily_clp: rate,
                });
                setRates(await read<typeof rates>("/admin/rates"));
              });
            }}
          >
            <label>
              Vigencia desde
              <input
                type="month"
                required
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            <label>
              Valor CLP
              <input
                type="number"
                required
                min={0}
                value={rate}
                onChange={(e) => setRate(Number(e.target.value))}
              />
            </label>
            <button disabled={busy}>Registrar vigencia</button>
          </form>
        </section>
        <section className="panel">
          <h2>Reglas de importación</h2>
          <p>
            Mapeo explícito de estados y códigos históricos; plazos de alertas,
            causales legales y tipos de contrato. COD no determina la frecuencia.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                setCatalogs(
                  JSON.stringify(
                    await send("/admin/catalogs", JSON.parse(catalogs), "PUT"),
                    null,
                    2,
                  ),
                );
              });
            }}
          >
            <CatalogEditor json={catalogs} onChange={setCatalogs} />
            <button disabled={busy} className="primary">Guardar reglas</button>
          </form>
        </section>
        <button type="button" className="settings-history" onClick={() => open("historical")}><History size={17} /> Recuperación de clasificaciones históricas <ChevronRight size={18} /></button>
      </>)}
      {admin && view === "historical" && <section className="panel"><h2>Recuperación de clasificaciones históricas</h2><Reconciliation /></section>}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {notice && <p role="status" className="settings-saved">{notice}</p>}
      </div>
    </div>
  );
}
