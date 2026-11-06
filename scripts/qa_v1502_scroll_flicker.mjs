import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const file = path => readFileSync(new URL(path, import.meta.url), "utf8");
const ops = file("../apps/frontend/src/Operations.tsx");
const app = file("../apps/frontend/src/App.tsx");
const main = file("../apps/frontend/src/main.tsx");
const index = file("../apps/frontend/index.html");
const pkg = JSON.parse(file("../apps/frontend/package.json"));
const lock = JSON.parse(file("../apps/frontend/package-lock.json"));
const version = file("../apps/backend/app/version.py");

test("la tabla de contratistas permanece montada durante un refresco", () => {
  assert.match(ops, /loading\s*&&\s*visibleContractors\.length\s*===\s*0\s*\?/);
  assert.doesNotMatch(ops, /\{loading\s*\?\s*<div className="ops-empty"/);
});

test("no vuelve a descargar al recuperar el foco y pausa el polling oculto", () => {
  assert.doesNotMatch(ops, /addEventListener\(['"]focus['"],\s*refresh\)/);
  assert.match(ops, /if\s*\(document\.hidden\)\s*return/);
  assert.match(ops, /setInterval\(refresh,\s*10000\)/);
});

test("la primera ruta respeta el historial y abre desde arriba", () => {
  assert.match(app, /\[section,\s*setSection\]\s*=\s*useState\(sectionFromLocation\)/);
  assert.match(app, /function sectionFromLocation\(\)/);
  assert.match(app, /nav\.some\(\(\[id\]\)\s*=>\s*id\s*===\s*saved\)/);
  assert.match(app, /next !== sectionRef\.current\) window\.scrollTo/);
  assert.match(app, /function go\(s: string\)[\s\S]*?window\.scrollTo\(\{top: 0, left: 0, behavior: "instant"\}\)/);
  assert.match(main, /window\.scrollTo\(\{top:0,left:0,behavior:"instant"\}\)/);
  assert.match(index, /history\.scrollRestoration = "manual"/);
  assert.match(app, /sessionStorage\.getItem\("galant-active-site"\)/);
  assert.match(app, /sessionStorage\.setItem\("galant-active-site"/);
});

test("la restauración del scroll sigue disponible dentro de la ficha", () => {
  assert.match(ops, /listScroll\.current=window\.scrollY/);
  assert.match(ops, /restoreListScroll\.current=true/);
  assert.match(ops, /window\.requestAnimationFrame\(\(\)=>window\.scrollTo\(\{top:listScroll\.current/);
});

test("la versión API y la instalación frontend corresponden al parche", () => {
  assert.match(pkg.version, /^(?:15\.0\.[0-9]+|16\.0\.[0-9]+)-rc1$/);
  assert.equal(lock.version, pkg.version);
  assert.equal(lock.packages[""].version, pkg.version);
  assert.ok(version.includes(`VERSION = "${pkg.version}"`));
});
