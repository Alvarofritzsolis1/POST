import type { CSSProperties } from "react";
import "./person-avatar.css";

/**
 * Avatar ilustrado local y determinista. No se infieren rasgos reales, sexo ni edad,
 * no se expone una foto inventada ni se solicita una imagen a servicios externos.
 */
const palettes = [
  { background: "#dff2ff", jacket: "#21659a", skin: "#eac2a3", hair: "#3c435c" },
  { background: "#f4e9ff", jacket: "#65539b", skin: "#bb8c71", hair: "#343b4f" },
  { background: "#dff5ed", jacket: "#277967", skin: "#d8a583", hair: "#55453b" },
  { background: "#e8efff", jacket: "#3659a0", skin: "#e7bb91", hair: "#483a39" },
  { background: "#fff0df", jacket: "#a86647", skin: "#aa735c", hair: "#373d42" },
  { background: "#f8e9eb", jacket: "#934d70", skin: "#d6a484", hair: "#55414f" },
] as const;

function avatarIndex(name: string) {
  // Hash estable por texto visible; sin derivar atributos demográficos.
  let value = 0;
  for (const char of (name.trim().toLocaleLowerCase("es-CL") || "?")) {
    value = (Math.imul(value, 31) + char.codePointAt(0)!) | 0;
  }
  return Math.abs(value) % palettes.length;
}

export type PersonAvatarProps = {
  name: string;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
  decorative?: boolean;
};

export default function PersonAvatar({
  name, size = "sm", className = "", decorative = true,
}: PersonAvatarProps) {
  const index = avatarIndex(name);
  const palette = palettes[index];
  const styles = {
    "--galant-avatar-bg": palette.background,
    "--galant-avatar-jacket": palette.jacket,
    "--galant-avatar-skin": palette.skin,
    "--galant-avatar-hair": palette.hair,
  } as CSSProperties;

  return <span
    className={`galant-person-avatar galant-person-avatar--${size} ${className}`.trim()}
    style={styles}
    aria-hidden={decorative ? "true" : undefined}
    role={decorative ? undefined : "img"}
    aria-label={decorative ? undefined : `Avatar ilustrado de ${name || "persona sin nombre"}`}
    title={decorative ? undefined : name}
  >
    <svg viewBox="0 0 64 64" fill="none" aria-hidden="true" focusable="false">
      <circle cx="32" cy="32" r="32" fill="var(--galant-avatar-bg)" />
      <path d="M9 63c1-12 10-18 23-18s22 6 23 18" fill="var(--galant-avatar-jacket)" />
      <path d="M25 45c2 7 12 7 14 0v-8H25v8Z" fill="var(--galant-avatar-skin)" />
      <path d="M20.6 25.2c0-9.1 5.2-14.8 11.4-14.8s11.4 5.7 11.4 14.8v8c0 8.4-5 14.3-11.4 14.3s-11.4-5.9-11.4-14.3v-8Z" fill="var(--galant-avatar-skin)" />
      <path d={index % 3 === 0
        ? "M20 30c-5-10-2-21 10-23 13-2 21 8 15 24-2-4-5-8-5-11-8 5-14 4-20 10Z"
        : index % 3 === 1
        ? "M19 31c-4-18 5-25 15-24 13 1 16 12 11 25l-4-10c-7-2-14-2-19 4l-3 5Z"
        : "M19 31c-3-15 5-24 15-24 11 0 17 10 11 25l-3-11c-6 2-12-1-19 4l-4 6Z"
      } fill="var(--galant-avatar-hair)" />
      <path d="M22 32c-3-4-5 0-4 3s3 5 5 3" fill="var(--galant-avatar-skin)" />
      <path d="M42 32c3-4 5 0 4 3s-3 5-5 3" fill="var(--galant-avatar-skin)" />
      <circle cx="27.5" cy="31.5" r="1.1" fill="#29384b" />
      <circle cx="36.5" cy="31.5" r="1.1" fill="#29384b" />
      <path d="M28.5 38.1c2.1 1.7 4.9 1.7 7 0" stroke="#875b58" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M24.8 27.6c1.6-.9 3-.9 4.2-.4m6 .0c1.4-.6 2.7-.5 4.2.4" stroke="var(--galant-avatar-hair)" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  </span>;
}
