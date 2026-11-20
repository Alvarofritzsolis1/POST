import type { SVGProps } from "react";

/** Marca vectorial de GALANT: estructura de obra y nodos conectados. */
export default function GalantMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 48 48" width="44" height="44" fill="none"
      role="img" aria-label="GALANT" {...props}>
      <defs>
        <linearGradient id="galantMarkFill" x1="3" y1="2" x2="45" y2="46" gradientUnits="userSpaceOnUse">
          <stop stopColor="#286FE8" />
          <stop offset="1" stopColor="#087E7B" />
        </linearGradient>
      </defs>
      <rect x="1.5" y="1.5" width="45" height="45" rx="13" fill="url(#galantMarkFill)" />
      <path d="M12 34V23L19 18V34M19 34V14L27 10V34M27 34V22L36 16V34"
        stroke="white" strokeOpacity=".95" strokeWidth="2.6" strokeLinecap="round"
        strokeLinejoin="round" />
      <path d="M10.5 35.5h27" stroke="#D7F6F2" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="36" cy="16" r="3" fill="#84F5D2" stroke="white" strokeWidth="1.4" />
    </svg>
  );
}
