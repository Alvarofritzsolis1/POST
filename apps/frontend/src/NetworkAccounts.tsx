import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Bell,
  Check,
  ChevronDown,
  Copy,
  LogOut,
  Network,
  Plus,
  Settings,
  UserCircle,
  Users,
} from "lucide-react";
import { request, type Profile } from "./api";
import {
  change,
  net,
  type Account,
  type Catalog,
  type Notices,
} from "./networkApi";
import { Badge, dateTime, Drawer, errorText, labels } from "./NetworkUI";
import "./network.css";

type AccessLink = {
  activation_path: string;
  expires_at: string;
  email_delivered: boolean;
};
export function NetworkAccountMenu({
  user,
  logout,
  openNetwork,
  openSettings,
  openUsersSignal,
}: {
  user: Profile;
  logout: () => void;
  openNetwork?: () => void;
  openSettings?: () => void;
  openUsersSignal?: number;
}) {
  const [profile, setProfile] = useState<Account | null>(null),
    [menu, setMenu] = useState(false),
    [bell, setBell] = useState(false);
  const [panel, setPanel] = useState(""),
    [catalog, setCatalog] = useState<Catalog | null>(null),
    [accounts, setAccounts] = useState<Account[]>([]);
  const [notices, setNotices] = useState<Notices>({
    rows: [],
    unread: 0,
    total: 0,
  });
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [target, setTarget] = useState<Account | null>(null);
  const [link, setLink] = useState<AccessLink | null>(null),
    [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const load = useCallback(async () => {
    try {
      const [p, n] = await Promise.all([
        net<Account>("/profile"),
        net<Notices>("/notifications"),
      ]);
      setProfile(p);
      setNotices(n);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 7000);
    const update = () => void load();
    window.addEventListener("galant-network-changed", update);
    return () => {
      clearInterval(timer);
      window.removeEventListener("galant-network-changed", update);
    };
  }, [load]);
  useEffect(() => {
    const close = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) {
        setMenu(false);
        setBell(false);
      }
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu(false);
        setBell(false);
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  async function open(kind: string, account?: Account) {
    setMenu(false);
    setBell(false);
    setPanel(kind);
    setError("");
    setNotice("");
    setLink(null);
    setTarget(account || null);
    try {
      if (kind !== "profile") {
        setCatalog(await net<Catalog>("/catalog"));
        if (kind === "users") setAccounts(await net<Account[]>("/users"));
      }
    } catch (err) {
      setError(errorText(err));
    }
  }
  useEffect(() => {
    if (openUsersSignal && user.role === "admin") void open("users");
  }, [openUsersSignal, user.role]);
  async function reset(account: Account) {
    setError("");
    setBusy(true);
    try {
      setLink(
        await change<AccessLink>("/users/" + account.id + "/access-link"),
      );
      setNotice("Enlace para " + account.email);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  async function saveProfile(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      setProfile(
        await change<Account>(
          "/profile",
          {
            name: d.get("name"),
            title: d.get("title"),
            notifications: d.get("notifications") === "on",
          },
          "PUT",
        ),
      );
      setNotice("Perfil guardado.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  const fullLink = link ? window.location.origin + link.activation_path : "";
  return (
    <div className="nw nw-account-tools" ref={ref}>
      <div className="nw-notification-anchor">
        <button
          className="nw-icon nw-bell"
          aria-label={"Notificaciones: " + notices.unread + " sin leer"}
          aria-expanded={bell}
          onClick={() => {
            setBell(!bell);
            setMenu(false);
          }}
        >
          <Bell size={19} />
          {notices.unread > 0 && (
            <span>{notices.unread > 99 ? "99+" : notices.unread}</span>
          )}
        </button>
        {bell && (
          <div className="nw-popover nw-notices">
            <div className="nw-row">
              <h3>Notificaciones</h3>
              <button
                className="nw-icon"
                title="Marcar todas como leídas"
                aria-label="Marcar todas como leídas"
                onClick={() =>
                  void change("/notifications/all/read")
                    .then(load)
                    .catch((err) => setError(errorText(err)))
                }
              >
                <Check size={17} />
              </button>
            </div>
            {!notices.rows.length && (
              <p className="nw-muted">No hay notificaciones nuevas.</p>
            )}
            {notices.rows.map((n) => (
              <button
                key={n.id}
                className={"nw-notice " + (!n.read ? "unread" : "")}
                onClick={() => {
                  setBell(false);
                  window.location.hash =
                    "red/" + n.resource_type + "/" + n.resource_id;
                  openNetwork?.();
                  void change("/notifications/" + n.id + "/read")
                    .then(load)
                    .catch((err) => setError(errorText(err)));
                }}
              >
                <b>{n.title}</b>
                <small>{dateTime(n.created_at)}</small>
              </button>
            ))}
          </div>
        )}
      </div>
      <button
        className="nw-profile-trigger"
        aria-label="Menú de usuario"
        aria-expanded={menu}
        onClick={() => {
          setMenu(!menu);
          setBell(false);
        }}
      >
        <span className="nw-avatar">
          {(profile?.name || user.email)
            .split(/\s+/)
            .slice(0, 2)
            .map((s) => s[0])
            .join("")
            .toUpperCase()}
        </span>
        <span>
          <b>{profile?.name || user.email}</b>
          <small>{labels[user.role] || user.role}</small>
        </span>
        <ChevronDown size={14} />
      </button>
      {menu && (
        <div className="nw-popover nw-user-popover">
          <p>{user.email}</p>
          <button onClick={() => void open("profile")}>
            <UserCircle size={17} />
            Mi perfil
          </button>
          {user.role === "admin" && (
            <>
              <button onClick={() => void open("create")}>
                <Plus size={17} />
                Crear cuenta
              </button>
              <button onClick={() => void open("users")}>
                <Users size={17} />
                Administrar usuarios
              </button>
              <button
                onClick={() => {
                  setMenu(false);
                  openSettings?.();
                }}
              >
                <Settings size={17} />
                Configuración general
              </button>
            </>
          )}
          <button onClick={logout}>
            <LogOut size={17} />
            Cerrar sesión
          </button>
        </div>
      )}
      {error && !panel && (
        <div className="nw-account-error" role="alert">
          {error}
          <button
            className="nw-btn"
            onClick={() => {
              setError("");
              void load();
            }}
          >
            Reintentar
          </button>
        </div>
      )}
      {panel && (
        <Drawer
          title={
            panel === "profile"
              ? "Mi perfil"
              : panel === "users"
                ? "Administrar usuarios"
                : target
                  ? "Editar cuenta"
                  : "Crear cuenta"
          }
          onClose={() => setPanel("")}
        >
          {error && (
            <p role="alert" className="nw-error">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="nw-success">
              {notice}
            </p>
          )}
          {link && (
            <div className="nw-callout">
              <b>
                {link.email_delivered
                  ? "Enlace enviado por correo"
                  : "Comparte este enlace con la persona invitada"}
              </b>
              <p>Es de un solo uso. Vence el {dateTime(link.expires_at)}.</p>
              <input
                aria-label="Enlace de acceso"
                value={fullLink}
                readOnly
                onFocus={(e) => e.target.select()}
              />
              <button
                className="nw-btn"
                onClick={() =>
                  void navigator.clipboard
                    .writeText(fullLink)
                    .then(() => setNotice("Enlace copiado."))
                    .catch(() => setNotice("Selecciona el enlace y cópialo."))
                }
              >
                <Copy size={15} />
                Copiar enlace
              </button>
            </div>
          )}
          {panel === "profile" && profile && (
            <form className="nw-form" onSubmit={(e) => void saveProfile(e)}>
              <label>
                Nombre completo
                <input
                  name="name"
                  defaultValue={profile.name}
                  required
                  minLength={2}
                  maxLength={180}
                />
              </label>
              <label>
                Cargo
                <input
                  name="title"
                  defaultValue={profile.title}
                  maxLength={180}
                />
              </label>
              <p>
                {profile.email} · <Badge value={profile.role} />
              </p>
              <label className="nw-check">
                <input
                  name="notifications"
                  type="checkbox"
                  defaultChecked={profile.notifications}
                />
                Recibir notificaciones internas
              </label>
              <button className="nw-btn nw-primary" disabled={busy}>
                {busy ? "Guardando…" : "Guardar perfil"}
              </button>
              <a href="#recuperar-clave" onClick={() => setPanel("")}>
                Recuperar o cambiar mi contraseña
              </a>
            </form>
          )}
          {panel === "users" && (
            <>
              <button
                className="nw-btn nw-primary"
                onClick={() => void open("create")}
              >
                <Plus size={16} />
                Crear cuenta
              </button>
              {accounts.map((a) => (
                <div className="nw-user-card" key={a.id}>
                  <div>
                    <b>{a.name}</b>
                    <p>{a.email}</p>
                    <Badge value={a.role} />{" "}
                    <span className="nw-muted">
                      {a.enabled ? "Activa" : "Suspendida"}
                    </span>
                  </div>
                  <div className="nw-row">
                    <button
                      className="nw-btn"
                      onClick={() => void open("create", a)}
                    >
                      Editar cuenta
                    </button>
                    <button
                      className="nw-btn"
                      disabled={busy || !a.enabled}
                      onClick={() => void reset(a)}
                    >
                      Enlace de acceso
                    </button>
                  </div>
                </div>
              ))}
            </>
          )}
          {panel === "create" && catalog && (
            <AccountForm
              key={target?.id || "new"}
              catalog={catalog}
              target={target || undefined}
              onSave={async (body) => {
                setError("");
                setBusy(true);
                try {
                  if (target) {
                    await change("/users/" + target.id, body, "PATCH");
                    setNotice(
                      "Cuenta actualizada. Los cambios de permisos revocan sus sesiones.",
                    );
                  } else {
                    const result = await change<AccessLink & { user: Account }>(
                      "/users",
                      body,
                    );
                    setLink(result);
                    setNotice("Cuenta creada para " + result.user.email);
                  }
                  await load();
                } catch (err) {
                  setError(errorText(err));
                } finally {
                  setBusy(false);
                }
              }}
              busy={busy}
            />
          )}
        </Drawer>
      )}
    </div>
  );
}

function AccountForm({
  catalog,
  target,
  onSave,
  busy,
}: {
  catalog: Catalog;
  target?: Account;
  onSave: (body: unknown) => Promise<void>;
  busy: boolean;
}) {
  const [role, setRole] = useState(target?.role || "resident"),
    [sites, setSites] = useState(target?.site_ids || []);
  return (
    <form
      className="nw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const d = new FormData(e.currentTarget);
        void onSave({
          name: d.get("name"),
          title: d.get("title"),
          role,
          site_ids: ["admin","doc_reviewer"].includes(role) ? [] : sites,
          enabled: d.get("enabled") === "on",
          can_award: d.get("can_award") === "on",
          ...(!target ? { email: d.get("email") } : {}),
        });
      }}
    >
      <fieldset disabled={busy}>
        <legend>Datos personales</legend>
        <label>
          Nombre completo
          <input
            name="name"
            defaultValue={target?.name}
            required
            minLength={2}
            maxLength={180}
          />
        </label>
        <label>
          Correo electrónico
          <input
            name="email"
            type="email"
            defaultValue={target?.email}
            required
            readOnly={!!target}
            maxLength={255}
          />
        </label>
        <label>
          Cargo (opcional)
          <input name="title" defaultValue={target?.title} maxLength={180} />
        </label>
        <label className="nw-check">
          <input
            type="checkbox"
            name="enabled"
            defaultChecked={target?.enabled ?? true}
          />
          Cuenta activa
        </label>
        <div className="nw-role-options">
          {["admin", "doc_reviewer", "administrative", "resident"].map((r) => (
            <button
              type="button"
              className={"nw-role-card " + (role === r ? "selected" : "")}
              aria-pressed={role === r}
              key={r}
              onClick={() => setRole(r)}
            >
              {r === "resident" ? <Network /> : r === "administrative" ? <Users /> : r === "doc_reviewer" ? <Check /> : <Settings />}
              <b>{labels[r]}</b>
              <small>
                {r === "resident" ? "Solo Red de Obras"
                  : r === "administrative" ? "Asistencia semanal y contratos de trabajo"
                  : r === "doc_reviewer" ? "Solo revisión de plantillas autorizadas, sin acceso a trabajadores ni contratistas"
                  : "Acceso completo de Administrador"}
              </small>
            </button>
          ))}
        </div>
        {target && !["admin", "administrative", "resident", "doc_reviewer"].includes(target.role) && (
          <p className="nw-callout">
            Esta cuenta tiene un perfil antiguo. Selecciona uno de los perfiles vigentes
            para habilitar nuevamente su acceso.
          </p>
        )}
        {["resident","administrative"].includes(role) ? (
          <>
            <b>Obras asignadas</b>
            {catalog.sites.map((s) => (
              <label className="nw-check" key={s.id}>
                <input
                  type="checkbox"
                  checked={sites.includes(s.id)}
                  onChange={(e) =>
                    setSites((old) =>
                      e.target.checked
                        ? [...old, s.id]
                        : old.filter((id) => id !== s.id),
                    )
                  }
                />
                {s.name}
              </label>
            ))}
            {!sites.length && (
              <p className="nw-muted">Selecciona al menos una obra.</p>
            )}
            {role === "resident" && <label className="nw-check">
              <input type="checkbox" name="can_award"
                defaultChecked={target?.can_award ?? false} />
              Autorización específica para confirmar adjudicaciones en sus obras
            </label>}
          </>
        ) : (
          <p className="nw-callout">
            {role === "doc_reviewer" ? "El revisor documental solo puede revisar y aprobar las plantillas que le deleguen, sin acceder a datos operativos." : "El administrador puede gestionar cuentas y confirmar adjudicaciones."}
          </p>
        )}
        <button
          className="nw-btn nw-primary"
          disabled={busy || (["resident","administrative"].includes(role) && !sites.length)}
        >
          {busy
            ? "Guardando…"
            : target
              ? "Guardar cuenta"
              : "Crear cuenta e invitación"}
        </button>
      </fieldset>
    </form>
  );
}

export function NetworkPasswordScreen({
  hash,
  done,
}: {
  hash: string;
  done: () => void;
}) {
  const token = hash.startsWith("#establecer-clave=")
    ? hash.slice("#establecer-clave=".length)
    : "";
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      if (token) {
        if (d.get("password") !== d.get("confirm"))
          throw new Error("Las contraseñas no coinciden");
        await request("/auth/network-password", {
          method: "POST",
          body: JSON.stringify({ token, password: d.get("password") }),
        });
        setNotice("Contraseña establecida. Ya puedes iniciar sesión.");
      } else {
        const result = await request<{ message: string }>(
          "/auth/forgot-password",
          { method: "POST", body: JSON.stringify({ email: d.get("email") }) },
        );
        setNotice(result.message);
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="nw nw-auth">
      <section>
        <Network size={36} />
        <span className="nw-eyebrow">GALANT POST</span>
        <h1>{token ? "Establece tu contraseña" : "Recupera tu acceso"}</h1>
        <form className="nw-form" onSubmit={(e) => void submit(e)}>
          {token ? (
            <>
              <label>
                Nueva contraseña (mínimo 12 caracteres)
                <input
                  type="password"
                  name="password"
                  minLength={12}
                  maxLength={256}
                  required
                  autoComplete="new-password"
                />
              </label>
              <label>
                Confirma la contraseña
                <input
                  type="password"
                  name="confirm"
                  minLength={12}
                  required
                  autoComplete="new-password"
                />
              </label>
            </>
          ) : (
            <label>
              Correo electrónico
              <input type="email" name="email" required autoComplete="email" />
            </label>
          )}
          {error && (
            <p className="nw-error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="nw-success" role="status">
              {notice}
            </p>
          )}
          <button
            className="nw-btn nw-primary"
            disabled={busy || (!!token && !!notice)}
          >
            {busy
              ? "Procesando…"
              : token
                ? "Establecer contraseña"
                : "Solicitar enlace"}
          </button>
        </form>
        <button className="nw-btn" onClick={done}>
          Volver a GALANT
        </button>
      </section>
    </main>
  );
}
