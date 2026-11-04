import { useEffect, useRef, type ReactNode } from "react";
import { X, Network } from "lucide-react";

export const errorText = (e: unknown) =>
  e instanceof Error ? e.message : String(e);
export const number = (n: number) =>
  n.toLocaleString("es-CL", { maximumFractionDigits: 3 });
export const dateText = (value: string) =>
  new Intl.DateTimeFormat("es-CL", {
    dateStyle: "medium",
    timeZone: "America/Santiago",
  }).format(new Date(value.length === 10 ? value + "T12:00:00-03:00" : value));
export const dateTime = (value: string) =>
  new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "America/Santiago",
  }).format(new Date(value));
export const todayISO = () =>
  new Intl.DateTimeFormat("sv-SE", {
    timeZone: "America/Santiago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const labels: Record<string, string> = {
  low: "Baja",
  normal: "Normal",
  high: "Alta",
  urgent: "Urgente",
  draft: "Borrador",
  published: "Publicado",
  cancelled: "Cancelado",
  none: "Sin adjudicaciones",
  full: "Totalmente adjudicado",
  partial: "Parcial",
  pending: "Pendiente",
  allocated: "Totalmente adjudicada",
  completed: "Finalizado",
  in_progress: "En ejecución",
  estimated: "Disponibilidad estimada",
  confirmed: "Disponibilidad confirmada",
  discarded: "Descartada",
  committed: "Capacidad comprometida",
  few_pending: "Pocas partidas pendientes",
  ending: "Próximo a finalizar",
  finished: "Finalizado",
  unconfirmed: "Por confirmar",
  total: "Capacidad total",
  interested: "Interés registrado",
  contacted: "Contacto iniciado",
  evaluating: "Evaluación de disponibilidad",
  proposed: "Propuesta pendiente de aprobación",
  approved: "Propuesta aprobada",
  documents_pending: "Habilitación documental pendiente",
  documents_complete: "Habilitación documental completada",
  rejected: "Rechazado",
  assigned: "Adjudicado",
  ready: "Habilitado para ejecución",
  revoked: "Revocado",
  resident: "Residente",
  admin: "Administrador",
  supervisor: "Supervisor",
  analyst: "Analista",
  viewer: "Visualizador",
  reviewer: "Revisor documental",
  administrative: "Administrativa",
};
export function Badge({ value }: { value: string }) {
  return (
    <span className={"nw-badge nw-" + value}>{labels[value] || value}</span>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="nw-empty">
      <Network size={32} />
      <h3>{title}</h3>
      <p>
        {children ||
          "Las publicaciones y coordinaciones de tu organización aparecerán aquí."}
      </p>
    </div>
  );
}
export function Drawer({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const previous = useRef<HTMLElement | null>(null);
  useEffect(() => {
    previous.current = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => {
      ref.current?.close();
      previous.current?.focus();
    };
  }, []);
  return (
    <dialog
      className="nw nw-drawer"
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (
          e.target === e.currentTarget &&
          e.clientX < e.currentTarget.getBoundingClientRect().left
        )
          onClose();
      }}
    >
      <div className="nw-drawer-heading">
        <div>
          <span className="nw-eyebrow">GALANT POST · RED DE OBRAS</span>
          <h2>{title}</h2>
        </div>
        <button
          type="button"
          className="nw-icon"
          aria-label="Cerrar panel"
          onClick={onClose}
        >
          <X />
        </button>
      </div>
      <div className="nw-drawer-body">{children}</div>
    </dialog>
  );
}
