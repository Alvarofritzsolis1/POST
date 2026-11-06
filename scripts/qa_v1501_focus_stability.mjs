import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = source("../apps/frontend/src/App.tsx");
const admin = source("../apps/frontend/src/AdminAttendanceV93.tsx");
const attendance = source("../apps/frontend/src/AdministrativeControlV92.tsx");
const css = source("../apps/frontend/src/v15-premium.css");
const apiVersion = source("../apps/backend/app/version.py");
const packageJson = JSON.parse(source("../apps/frontend/package.json"));

test("no dispara solicitudes duplicadas al regresar a una pestaña", () => {
  for (const component of [app, admin, attendance]) {
    assert.doesNotMatch(component, /window\.addEventListener\(["']focus["'],\s*update\)/);
    assert.match(component, /document\.hidden/);
    assert.match(component, /setInterval\(update,\s*(?:10000|30000)\)/);
    assert.match(component, /window\.addEventListener\(["']galant-changed["'],\s*update\)/);
  }
});

test("solo sondea consolidado de todas las obras cuando corresponde", () => {
  assert.match(admin, /if \(siteId\) return;/);
  assert.match(admin, /}, \[siteId\]\);/);
});

test("el texto de actualización no cambia la altura de las tablas", () => {
  assert.match(attendance, /loading && !overview && <p role="status"/);
  assert.match(admin, /loading && !portfolio && <p className="av92-muted"/);
  assert.match(app, /className="v1501-refresh-status" role="status"/);
  assert.match(css, /\.platform \.v1501-refresh-status\s*\{\s*position:\s*fixed;/);
});

test("las barras de desplazamiento conservan su espacio", () => {
  assert.match(css, /html\s*\{\s*scrollbar-gutter:\s*stable;/);
  assert.match(css, /\.platform \.sidebar\s*\{[^}]*scrollbar-gutter:\s*stable;/s);
  assert.match(css, /overscroll-behavior-y:\s*contain;/);
});

test("las versiones frontend y API del parche coinciden", () => {
  assert.match(packageJson.version, /^(?:15\.0\.[1-9][0-9]*|16\.0\.[0-9]+)-rc1$/);
  assert.match(apiVersion, new RegExp(`VERSION = "${packageJson.version.replace(/\./g, "\\.")}"`));
});
