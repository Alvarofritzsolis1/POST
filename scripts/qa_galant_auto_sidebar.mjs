// Contratos estáticos del shell; la prueba funcional de hover está en QA Chromium.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
const path = (name) => fileURLToPath(new URL("../apps/frontend/src/" + name, import.meta.url));
const app = readFileSync(path("App.tsx"), "utf8");
const sidebar = readFileSync(path("GalantSidebar.tsx"), "utf8");
const css = readFileSync(path("galant-sidebar-auto.css"), "utf8");
const main = readFileSync(path("main.tsx"), "utf8");

test("El lateral inicia siempre compacto, incluso con preferencias antiguas", () => {
  assert.match(app, /\[sidebarCollapsed\]\s*=\s*useState\(true\)/);
  assert.match(app, /localStorage\.removeItem\("galant-sidebar-pinned"\)/);
  assert.doesNotMatch(app, /setSidebarCollapsed|localStorage\.setItem\("galant-sidebar-pinned"/);
});
test("Hover, foco, salida y Escape están disponibles para abrir/cerrar", () => {
  assert.match(sidebar, /onMouseEnter=\{onEnter\}/);
  assert.match(sidebar, /onMouseLeave=\{onLeave\}/);
  assert.match(sidebar, /onFocusCapture=\{onEnter\}/);
  assert.match(sidebar, /event\.key === "Escape"/);
  assert.match(sidebar, /id="galant-sidebar"/);
  assert.match(app, /aria-controls="galant-sidebar"/);
  assert.match(app, /sidebarHoverTimer\.current = setTimeout/);
});
test("El botón de automatización se muestra exclusivamente en JAVIERA", () => {
  assert.match(app, /user\.role === "admin" && section === "javiera" && <button type="button" className="v16-automation-entry"/);
  assert.doesNotMatch(app, /section !== "settings" && <button type="button" className="v16-automation-entry"/);
});
test("Rail de 66px, overlay sin desplazamiento y movimiento reducido", () => {
  assert.match(main, /import "\.\/galant-sidebar-auto\.css"/);
  assert.match(css, /width:\s*66px\s*!important/);
  assert.match(css, /margin-left:\s*66px\s*!important/);
  assert.match(css, /galant-sidebar-peek/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
});
