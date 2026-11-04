import { useEffect, useState } from "react";
import { read, send, type OrgProfile, type Preferences } from "./platformApi";
import type { Site } from "./opsApi";
import Reconciliation from "./Reconciliation";
type Account = { id: string; email: string; role: string; enabled: boolean };
export default function Settings({
  admin,
  sites,
  onPreferences,
}: {
  admin: boolean;
  sites: Site[];
  onPreferences: (p: Preferences) => void;
}) {
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
  return (
    <div className="settings-grid">
      <section className="panel">
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
      </section>
      {admin && (
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
          <div className="table-wrap">
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
      {admin && (
        <section className="panel">
          <h2>Obras, catálogos y retenciones</h2>
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
          <h3>Valor diario con vigencia mensual</h3>
          <p>
            Valor inicial: $4.950 CLP. La retención es una estimación
            administrativa.
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
              void run(async () => {
                await send("/admin/rates", {
                  effective_from: date,
                  daily_clp: rate,
                });
                setRates(await read<typeof rates>("/admin/rates"));
              });
            }}
          >
            <label>
              Vigencia desde
              <input
                type="date"
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
          <h3>Reglas de importación</h3>
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
            <textarea
              rows={12}
              aria-label="Catálogos de importación"
              value={catalogs}
              onChange={(e) => setCatalogs(e.target.value)}
            />
            <button disabled={busy}>Guardar catálogos</button>
          </form>
        </section>
      )}
      {admin && <Reconciliation />}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </div>
  );
}
