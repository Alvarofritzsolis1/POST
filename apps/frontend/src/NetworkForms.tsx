import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import {
  attach,
  change,
  net,
  type Award,
  type Capacity,
  type Catalog,
  type Coordination,
  type Item,
  type Page,
  type Requirement,
} from "./networkApi";
import {
  Badge,
  dateText,
  errorText,
  labels,
  number,
  todayISO,
} from "./NetworkUI";

type Part = {
  id?: string;
  name: string;
  description: string;
  quantity: number;
  unit: string;
  start_date: string;
  end_date: string;
  notes: string;
};
const blank = (date: string): Part => ({
  name: "",
  description: "",
  quantity: 1,
  unit: "un",
  start_date: date,
  end_date: date,
  notes: "",
});
const dataText = (d: FormData, key: string) => String(d.get(key) || "");
export function RequirementForm({
  catalog,
  current,
  done,
}: {
  catalog: Catalog;
  current?: Requirement;
  done: (message: string, req?: Requirement) => void;
}) {
  const initial = todayISO();
  const [parts, setParts] = useState<Part[]>(
    current?.items.map((i) => ({
      id: i.id,
      name: i.name,
      description: i.description,
      quantity: i.quantity,
      unit: i.unit,
      start_date: i.start_date,
      end_date: i.end_date,
      notes: i.notes,
    })) || [blank(initial)],
  );
  const [start, setStart] = useState(current?.start_date || initial),
    [end, setEnd] = useState(current?.end_date || initial);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const clientKey = useRef(crypto.randomUUID());
  const ownSites = catalog.sites.filter((s) => s.editable);
  const update = (i: number, field: keyof Part, value: string | number) =>
    setParts((p) =>
      p.map((v, index) => (index === i ? { ...v, [field]: value } : v)),
    );
  const reorder = (i: number, delta: number) =>
    setParts((old) => {
      const copy = [...old];
      [copy[i], copy[i + delta]] = [copy[i + delta], copy[i]];
      return copy;
    });
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const state =
      (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") ||
      "published";
    setBusy(true);
    setError("");
    try {
      const body = {
        site_id: dataText(data, "site_id"),
        specialty: dataText(data, "specialty"),
        title: dataText(data, "title"),
        description: dataText(data, "description"),
        priority: dataText(data, "priority"),
        workers: Number(data.get("workers")),
        start_date: start,
        end_date: end,
        deadline: dataText(data, "deadline"),
        items: parts,
        state,
        client_key: clientKey.current,
        ...(current
          ? { version: current.version, reason: dataText(data, "reason") }
          : {}),
      };
      const req = await change<Requirement>(
        "/requirements" + (current ? "/" + current.id : ""),
        body,
        current ? "PUT" : "POST",
      );
      const failed: string[] = [];
      for (const file of data.getAll("files"))
        if (file instanceof File && file.size) {
          try {
            await attach(file, "requirement_id", req.id);
          } catch (err) {
            failed.push(file.name + ": " + errorText(err));
          }
        }
      done(
        (state === "draft"
          ? "Borrador guardado."
          : state === "cancelled"
            ? "Requerimiento cancelado."
            : "Requerimiento publicado en la red.") +
          (failed.length
            ? " No se pudieron adjuntar: " + failed.join("; ")
            : ""),
        req,
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nw-form" onSubmit={(e) => void submit(e)}>
      <fieldset disabled={busy}>
        <legend>Información general</legend>
        <label>
          Obra
          <select
            name="site_id"
            defaultValue={current?.site_id || ownSites[0]?.id}
            required
          >
            {ownSites.map((s) => (
              <option value={s.id} key={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Especialidad
          <input
            name="specialty"
            list="network-specialties"
            defaultValue={current?.specialty}
            required
            minLength={2}
            maxLength={100}
            placeholder="Ej. Carpintería"
          />
        </label>
        <label>
          Título del requerimiento
          <input
            name="title"
            defaultValue={current?.title}
            required
            minLength={3}
            maxLength={180}
            placeholder="Ej. Carpinteros para terminaciones interiores"
          />
        </label>
        <label>
          Descripción
          <textarea
            name="description"
            defaultValue={current?.description}
            maxLength={10000}
            rows={3}
          />
        </label>
        <div className="nw-form-grid">
          <label>
            Prioridad
            <select
              name="priority"
              defaultValue={current?.priority || "normal"}
            >
              {["low", "normal", "high", "urgent"].map((v) => (
                <option value={v} key={v}>
                  {labels[v]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Trabajadores estimados
            <input
              name="workers"
              type="number"
              required
              min={1}
              max={10000}
              defaultValue={current?.workers || 1}
            />
          </label>
        </div>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Programación</legend>
        <div className="nw-form-grid">
          <label>
            Inicio necesario
            <input
              type="date"
              name="start_date"
              value={start}
              onChange={(e) => {
                const value = e.target.value;
                setStart(value);
                setParts((old) =>
                  old.map((p) =>
                    p.start_date === start ? { ...p, start_date: value } : p,
                  ),
                );
              }}
              required
            />
          </label>
          <label>
            Término estimado
            <input
              type="date"
              name="end_date"
              min={start}
              value={end}
              onChange={(e) => {
                const value = e.target.value;
                setEnd(value);
                setParts((old) =>
                  old.map((p) =>
                    p.end_date === end ? { ...p, end_date: value } : p,
                  ),
                );
              }}
              required
            />
          </label>
          <label>
            Fecha límite del contratista
            <input
              type="date"
              name="deadline"
              max={end}
              defaultValue={current?.deadline || initial}
              required
            />
          </label>
        </div>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Partidas requeridas · {parts.length}</legend>
        <p className="nw-muted">
          Agrega, ordena y describe todas las partidas necesarias.
        </p>
        {parts.map((p, i) => (
          <div className="nw-part-form" key={p.id || i}>
            <div className="nw-row">
              <b>Partida {i + 1}</b>
              <span className="nw-spacer" />
              <button
                type="button"
                className="nw-icon"
                aria-label={"Subir partida " + (i + 1)}
                disabled={i === 0}
                onClick={() => reorder(i, -1)}
              >
                <ArrowUp size={16} />
              </button>
              <button
                type="button"
                className="nw-icon"
                aria-label={"Bajar partida " + (i + 1)}
                disabled={i === parts.length - 1}
                onClick={() => reorder(i, 1)}
              >
                <ArrowDown size={16} />
              </button>
              <button
                type="button"
                className="nw-icon"
                aria-label={"Eliminar partida " + (i + 1)}
                disabled={parts.length === 1}
                onClick={() => setParts((old) => old.filter((_, j) => i !== j))}
              >
                <Trash2 size={16} />
              </button>
            </div>
            <label>
              Nombre de partida
              <input
                value={p.name}
                onChange={(e) => update(i, "name", e.target.value)}
                required
                minLength={2}
                maxLength={180}
              />
            </label>
            <div className="nw-form-grid">
              <label>
                Cantidad
                <input
                  type="number"
                  min={0.001}
                  step="0.001"
                  required
                  value={p.quantity}
                  onChange={(e) =>
                    update(i, "quantity", Number(e.target.value))
                  }
                />
              </label>
              <label>
                Unidad
                <input
                  list="network-units"
                  required
                  maxLength={24}
                  value={p.unit}
                  onChange={(e) => update(i, "unit", e.target.value)}
                />
              </label>
              <label>
                Inicio de partida
                <input
                  type="date"
                  min={start}
                  max={end}
                  required
                  value={p.start_date}
                  onChange={(e) => update(i, "start_date", e.target.value)}
                />
              </label>
              <label>
                Término de partida
                <input
                  type="date"
                  min={p.start_date}
                  max={end}
                  required
                  value={p.end_date}
                  onChange={(e) => update(i, "end_date", e.target.value)}
                />
              </label>
            </div>
            <label>
              Descripción y alcance
              <textarea
                value={p.description}
                onChange={(e) => update(i, "description", e.target.value)}
                maxLength={5000}
              />
            </label>
            <label>
              Observaciones
              <input
                value={p.notes}
                onChange={(e) => update(i, "notes", e.target.value)}
                maxLength={2000}
              />
            </label>
          </div>
        ))}
        <button
          type="button"
          className="nw-btn"
          onClick={() =>
            setParts((p) => [...p, { ...blank(start), end_date: end }])
          }
        >
          <Plus size={16} /> Agregar partida
        </button>
      </fieldset>
      <label>
        Planos, fotografías o especificaciones (PDF, JPG, PNG)
        <input
          name="files"
          type="file"
          accept=".pdf,.png,.jpg,.jpeg"
          multiple
        />
      </label>
      {current && (
        <label>
          Motivo del cambio
          <input
            name="reason"
            required={current.state !== "draft"}
            maxLength={2000}
          />
        </label>
      )}
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <div className="nw-form-actions">
        <button className="nw-btn" type="submit" value="draft" disabled={busy}>
          Guardar borrador
        </button>
        {current?.state === "published" && (
          <button
            className="nw-btn"
            type="submit"
            value="cancelled"
            disabled={busy}
          >
            Cancelar requerimiento
          </button>
        )}
        <button
          className="nw-btn nw-primary"
          type="submit"
          value="published"
          disabled={busy}
        >
          {busy ? "Guardando…" : "Publicar requerimiento"}
        </button>
      </div>
    </form>
  );
}

export function CapacityForm({
  catalog,
  current,
  done,
}: {
  catalog: Catalog;
  current?: Capacity;
  done: (message: string) => void;
}) {
  const ownSites = catalog.sites.filter((s) => s.editable);
  const [site, setSite] = useState(current?.site_id || ownSites[0]?.id || ""),
    [company, setCompany] = useState(current?.contractor_id || "");
  const [pending, setPending] = useState(current?.pending_items || []);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const clientKey = useRef(crypto.randomUUID());
  const companies = catalog.contractors.filter((c) =>
    c.site_ids.includes(site),
  );
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await change(
        "/capacities" + (current ? "/" + current.id : ""),
        {
          site_id: site,
          contractor_id: company,
          specialty: dataText(d, "specialty"),
          situation: dataText(d, "situation"),
          available_date: dataText(d, "available_date"),
          workers: Number(d.get("workers")),
          mode: dataText(d, "mode"),
          availability: dataText(d, "availability"),
          notes: dataText(d, "notes"),
          can_transfer: d.get("can_transfer") === "on",
          state: dataText(d, "state"),
          validity_days: Number(d.get("validity_days")),
          pending_items: pending,
          client_key: clientKey.current,
          ...(current ? { version: current.version } : {}),
        },
        current ? "PUT" : "POST",
      );
      done(
        "Capacidad guardada. Su publicación no asigna al contratista ni a sus trabajadores.",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nw-form" onSubmit={(e) => void submit(e)}>
      <fieldset disabled={busy}>
        <legend>Contratista y obra de origen</legend>
        <label>
          Obra
          <select
            value={site}
            disabled={!!current}
            onChange={(e) => {
              setSite(e.target.value);
              setCompany("");
            }}
            required
          >
            {ownSites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Contratista registrado
          <select
            required
            value={company}
            disabled={!!current}
            onChange={(e) => setCompany(e.target.value)}
          >
            <option value="">Seleccionar contratista</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <p className="nw-muted">
          RUT:{" "}
          {catalog.contractors.find((c) => c.id === company)?.rut ||
            "Sin registro"}
        </p>
        {!companies.length && (
          <p className="nw-callout">
            La administración debe registrar un contratista activo en esta obra.
          </p>
        )}
        <label>
          Especialidad
          <input
            name="specialty"
            list="network-specialties"
            required
            minLength={2}
            maxLength={100}
            defaultValue={current?.specialty}
          />
        </label>
        <label>
          Situación actual
          <select
            name="situation"
            defaultValue={current?.situation || "few_pending"}
          >
            {[
              "few_pending",
              "ending",
              "partial",
              "finished",
              "unconfirmed",
            ].map((v) => (
              <option value={v} key={v}>
                {labels[v]}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Posible disponibilidad</legend>
        <div className="nw-form-grid">
          <label>
            Fecha prevista
            <input
              type="date"
              name="available_date"
              required
              defaultValue={current?.available_date || todayISO()}
            />
          </label>
          <label>
            Trabajadores estimados
            <input
              type="number"
              name="workers"
              min={1}
              max={10000}
              required
              defaultValue={current?.workers || 1}
            />
          </label>
          <label>
            Tipo de capacidad
            <select name="mode" defaultValue={current?.mode || "total"}>
              <option value="total">Total</option>
              <option value="partial">Parcial</option>
            </select>
          </label>
          <label>
            Confirmación
            <select
              name="availability"
              defaultValue={current?.availability || "estimated"}
            >
              {[
                "estimated",
                "pending",
                "confirmed",
                "discarded",
                "committed",
              ].map((v) => (
                <option key={v} value={v}>
                  {labels[v]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Vigencia (días)
            <input
              type="number"
              name="validity_days"
              min={1}
              max={90}
              defaultValue={14}
              required
            />
          </label>
          <label>
            Publicación
            <select name="state" defaultValue={current?.state || "published"}>
              <option value="published">Compartida con la red</option>
              <option value="draft">Borrador de mi obra</option>
            </select>
          </label>
        </div>
        <label className="nw-check">
          <input
            name="can_transfer"
            type="checkbox"
            defaultChecked={current?.can_transfer ?? true}
          />
          Posibilidad de trabajar en otra obra, sujeta a confirmación
        </label>
        <label>
          Observaciones
          <textarea
            name="notes"
            maxLength={5000}
            defaultValue={current?.notes}
            rows={3}
          />
        </label>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Partidas pendientes</legend>
        {pending.map((p, i) => (
          <div className="nw-part-form" key={i}>
            <label>
              Nombre
              <input
                value={p.name}
                required
                minLength={2}
                maxLength={180}
                onChange={(e) =>
                  setPending((old) =>
                    old.map((v, j) =>
                      i === j ? { ...v, name: e.target.value } : v,
                    ),
                  )
                }
              />
            </label>
            <div className="nw-form-grid">
              <label>
                Cantidad
                <input
                  type="number"
                  min={0.001}
                  step="0.001"
                  required
                  value={p.quantity}
                  onChange={(e) =>
                    setPending((old) =>
                      old.map((v, j) =>
                        i === j
                          ? { ...v, quantity: Number(e.target.value) }
                          : v,
                      ),
                    )
                  }
                />
              </label>
              <label>
                Unidad
                <input
                  required
                  maxLength={24}
                  value={p.unit}
                  onChange={(e) =>
                    setPending((old) =>
                      old.map((v, j) =>
                        i === j ? { ...v, unit: e.target.value } : v,
                      ),
                    )
                  }
                />
              </label>
              <label>
                Término previsto
                <input
                  type="date"
                  required
                  value={p.end_date}
                  onChange={(e) =>
                    setPending((old) =>
                      old.map((v, j) =>
                        i === j ? { ...v, end_date: e.target.value } : v,
                      ),
                    )
                  }
                />
              </label>
            </div>
            <button
              className="nw-btn"
              type="button"
              onClick={() => setPending((old) => old.filter((_, j) => i !== j))}
            >
              Eliminar partida pendiente
            </button>
          </div>
        ))}
        <button
          type="button"
          className="nw-btn"
          onClick={() =>
            setPending((p) => [
              ...p,
              { name: "", quantity: 1, unit: "un", end_date: todayISO() },
            ])
          }
        >
          <Plus size={16} /> Agregar partida pendiente
        </button>
      </fieldset>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <button className="nw-btn nw-primary" disabled={busy || !company}>
        {busy ? "Guardando…" : "Guardar capacidad"}
      </button>
    </form>
  );
}

export function AwardForm({
  req,
  item,
  catalog,
  done,
}: {
  req: Requirement;
  item: Item;
  catalog: Catalog;
  done: (message: string) => void;
}) {
  const [company, setCompany] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [capacities, setCapacities] = useState<Capacity[]>([]),
    [capacityId, setCapacityId] = useState(""),
    [coordinationId, setCoordinationId] = useState("");
  const [coordinations, setCoordinations] = useState<Coordination[]>([]),
    [clearance, setClearance] = useState<{
      label: string;
      state: string;
    } | null>(null);
  const clientKey = useRef(crypto.randomUUID());
  useEffect(() => {
    let active = true;
    setClearance(null);
    setCapacities([]);
    setCapacityId("");
    setCoordinationId("");
    if (!company) return;
    void Promise.all([
      net<Page<Capacity>>(
        "/capacities?contractor_id=" + company + "&limit=100",
      ),
      net<{ label: string; state: string }>(
        "/contractors/" +
          company +
          "/clearance?site_id=" +
          req.site_id +
          "&period=" +
          item.start_date.slice(0, 7),
      ),
      net<Page<Coordination>>(
        "/coordinations?requirement_id=" + req.id + "&limit=100",
      ),
    ])
      .then(([caps, state, coords]) => {
        if (active) {
          setCapacities(
            caps.rows.filter(
              (c) => c.availability === "confirmed" && !c.expired,
            ),
          );
          setClearance(state);
          setCoordinations(
            coords.rows.filter((c) =>
              [
                "approved",
                "documents_pending",
                "documents_complete",
                "finished",
              ].includes(c.state),
            ),
          );
        }
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    return () => {
      active = false;
    };
  }, [company, req.id, req.site_id, item.start_date]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await change("/awards", {
        item_id: item.id,
        contractor_id: company,
        quantity: Number(d.get("quantity")),
        start_date: dataText(d, "start_date"),
        end_date: dataText(d, "end_date"),
        notes: dataText(d, "notes"),
        client_key: clientKey.current,
        capacity_id: capacityId || null,
        coordination_id: coordinationId || null,
        workers: capacityId ? Number(d.get("workers")) : 0,
        acknowledge_conflict: d.get("acknowledge_conflict") === "on",
        conflict_reason: dataText(d, "conflict_reason"),
      });
      done(
        "Partida adjudicada. El ingreso y la ejecución requieren habilitación en la obra de destino.",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nw-form" onSubmit={(e) => void submit(e)}>
      <div className="nw-callout">
        <b>{item.name}</b>
        <p>
          {req.site} · Saldo pendiente: {number(item.pending)} {item.unit}
        </p>
      </div>
      <label>
        Contratista
        <select
          required
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        >
          <option value="">Seleccionar contratista</option>
          {catalog.contractors.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <p>
        RUT:{" "}
        {catalog.contractors.find((c) => c.id === company)?.rut ||
          "Sin registro"}
      </p>
      {clearance && <p className="nw-callout">{clearance.label}</p>}
      <label>
        Capacidad confirmada vinculada (opcional)
        <select
          value={capacityId}
          onChange={(e) => {
            setCapacityId(e.target.value);
            setCoordinationId("");
          }}
        >
          <option value="">
            Adjudicación directa sin reserva de cuadrilla publicada
          </option>
          {capacities.map((c) => (
            <option value={c.id} key={c.id}>
              {c.site} · {c.workers} trabajadores · {dateText(c.available_date)}
            </option>
          ))}
        </select>
      </label>
      {capacityId && (
        <>
          <label>
            Coordinación aprobada (opcional)
            <select
              value={coordinationId}
              onChange={(e) => setCoordinationId(e.target.value)}
            >
              <option value="">Sin coordinación previa</option>
              {coordinations
                .filter((c) => c.capacity_id === capacityId)
                .map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.origin} → {c.site}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Trabajadores comprometidos
            <input
              name="workers"
              type="number"
              min={1}
              max={10000}
              defaultValue={Math.min(
                req.workers,
                capacities.find((c) => c.id === capacityId)?.workers || 1,
              )}
              required
            />
          </label>
          <label className="nw-check">
            <input name="acknowledge_conflict" type="checkbox" />
            Confirmar excepción si existe conflicto de fecha o capacidad
          </label>
          <label>
            Motivo de la excepción
            <input
              name="conflict_reason"
              maxLength={2000}
              placeholder="Solo cuando existan otras cuadrillas o fechas confirmadas"
            />
          </label>
        </>
      )}
      <label>
        Cantidad adjudicada ({item.unit})
        <input
          type="number"
          name="quantity"
          min={0.001}
          step="0.001"
          max={item.pending}
          defaultValue={item.pending}
          required
        />
      </label>
      <div className="nw-form-grid">
        <label>
          Inicio de ejecución
          <input
            name="start_date"
            type="date"
            defaultValue={item.start_date}
            min={item.start_date}
            max={item.end_date}
            required
          />
        </label>
        <label>
          Término de ejecución
          <input
            name="end_date"
            type="date"
            defaultValue={item.end_date}
            min={item.start_date}
            max={item.end_date}
            required
          />
        </label>
      </div>
      <label>
        Observaciones
        <textarea name="notes" maxLength={5000} />
      </label>
      <label className="nw-check">
        <input type="checkbox" required />
        Confirmo la adjudicación oficial de esta cantidad y contratista.
      </label>
      <p className="nw-muted">
        La adjudicación no habilita el ingreso a {req.site}. GALANT comprobará
        el control documental de esta obra.
      </p>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <button className="nw-btn nw-primary" disabled={busy}>
        {busy ? "Confirmando…" : "Confirmar adjudicación"}
      </button>
    </form>
  );
}

export function AwardProgressForm({
  award,
  done,
}: {
  award: Award;
  done: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const allowed: Record<string, string[]> = {
    assigned: ["ready", "revoked"],
    ready: ["assigned", "in_progress", "revoked"],
    in_progress: ["in_progress", "completed"],
  };
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await change(
        "/awards/" + award.id,
        {
          state: dataText(d, "state"),
          executed: Number(d.get("executed")),
          version: award.version,
          reason: dataText(d, "reason"),
        },
        "PATCH",
      );
      done("Seguimiento registrado en el historial.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="nw-form" onSubmit={(e) => void submit(e)}>
      <h3>{award.item_name}</h3>
      <p>
        Adjudicado a: <b>{award.contractor}</b>
      </p>
      <Badge value={award.state} />
      <p>
        {number(award.quantity)} {award.unit} · {dateText(award.start_date)}
      </p>
      <p className="nw-callout">{award.clearance?.label}</p>
      <label>
        Nuevo estado
        <select name="state">
          {(allowed[award.state] || []).map((v) => (
            <option value={v} key={v}>
              {labels[v]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Cantidad efectivamente ejecutada
        <input
          name="executed"
          type="number"
          min={award.executed}
          max={award.quantity}
          step="0.001"
          defaultValue={award.executed}
          required
        />
      </label>
      <label>
        Motivo y observaciones
        <textarea name="reason" minLength={3} maxLength={2000} required />
      </label>
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <button
        className="nw-btn nw-primary"
        disabled={busy || !allowed[award.state]?.length}
      >
        {busy ? "Guardando…" : "Guardar seguimiento"}
      </button>
    </form>
  );
}

export function AwardRevisionForm({
  award,
  item,
  done,
}: {
  award: Award;
  item: Item;
  done: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <form
      className="nw-form"
      onSubmit={(e) => {
        e.preventDefault();
        const d = new FormData(e.currentTarget);
        setBusy(true);
        setError("");
        void change("/awards/" + award.id + "/revise", {
          quantity: Number(d.get("quantity")),
          start_date: d.get("start_date"),
          end_date: d.get("end_date"),
          version: award.version,
          reason: d.get("reason"),
          acknowledge_conflict: d.get("acknowledge_conflict") === "on",
          conflict_reason: d.get("conflict_reason"),
        })
          .then(() =>
            done("Cantidad y programación actualizadas con historial."),
          )
          .catch((err) => setError(errorText(err)))
          .finally(() => setBusy(false));
      }}
    >
      <h3>{award.item_name}</h3>
      <p>
        ADJUDICADO A: <b>{award.contractor}</b>
      </p>
      <p className="nw-callout">
        Conserva al menos las {number(award.executed)} {award.unit} ejecutadas.
        El saldo que se libere podrá adjudicarse a otro contratista.
      </p>
      <label>
        Nueva cantidad adjudicada ({award.unit})
        <input
          name="quantity"
          type="number"
          min={Math.max(0.001, award.executed)}
          max={item.pending + award.quantity}
          step="0.001"
          defaultValue={award.quantity}
          required
        />
      </label>
      <div className="nw-form-grid">
        <label>
          Inicio
          <input
            name="start_date"
            type="date"
            defaultValue={award.start_date}
            min={item.start_date}
            max={item.end_date}
            required
          />
        </label>
        <label>
          Término
          <input
            name="end_date"
            type="date"
            defaultValue={award.end_date}
            min={item.start_date}
            max={item.end_date}
            required
          />
        </label>
      </div>
      <label>
        Motivo de modificación
        <textarea name="reason" minLength={5} maxLength={2000} required />
      </label>
      {award.capacity_id && (
        <>
          <label className="nw-check">
            <input name="acknowledge_conflict" type="checkbox" />
            Confirmar excepción de capacidad tras revisar otras cuadrillas
          </label>
          <label>
            Motivo de excepción
            <input name="conflict_reason" maxLength={2000} />
          </label>
        </>
      )}
      {error && (
        <p className="nw-error" role="alert">
          {error}
        </p>
      )}
      <button className="nw-btn nw-primary" disabled={busy}>
        {busy ? "Guardando…" : "Confirmar modificación"}
      </button>
    </form>
  );
}
