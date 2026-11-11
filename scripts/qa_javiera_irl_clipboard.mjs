import test from "node:test";
import assert from "node:assert/strict";
import {parseIRLClipboard} from "../apps/frontend/src/javiera-irl-clipboard.ts";

test("pega cuatro columnas con cabecera Excel y mantiene la relación técnica",()=>{
  const tsv="Actividad\tPeligro\tConsecuencia\tMedida preventiva\n"+
    "Instalar tuberías\tHerramientas cortantes\tCortes\tRevisión previa de herramientas";
  const result=parseIRLClipboard(tsv);
  assert.equal(result.sections.length,1);
  assert.equal(result.duplicates,0);
  assert.match(result.sections[0],/^Tarea: Instalar tuberías\nPeligro: Herramientas cortantes\nRiesgo: Cortes\nMedidas: Revisión previa/);
});
test("agrupa solo duplicados exactos, no controla ni aprueba un riesgo distinto",()=>{
  const row="Instalar tuberías\tCorte\tHeridas\tGuantes apropiados";
  const result=parseIRLClipboard(row+"\n"+row+"\n"+
    "Instalar tuberías\tCorte\tHeridas\tRevisar equipos");
  assert.equal(result.sections.length,2);
  assert.equal(result.duplicates,1);
});
test("respeta saltos de línea y tabulaciones dentro de celdas entrecomilladas",()=>{
  const result=parseIRLClipboard('Actividad\tPeligro\tConsecuencia\tMedida preventiva\n'+
    '"Tarea\ncompleja"\t"Corte\tproyección"\tHerida\t"Control doble"');
  assert.equal(result.sections.length,1);
  assert.match(result.sections[0],/Tarea\ncompleja/);
  assert.match(result.sections[0],/Corte\tproyección/);
});
test("rechaza filas incompletas, columnas desplazadas y comillas sin cerrar",()=>{
  assert.throws(()=>parseIRLClipboard("Tarea\tPeligro\tRiesgo"),/cuatro columnas/);
  assert.throws(()=>parseIRLClipboard("Tarea\tPeligro\tRiesgo\t"),/cuatro celdas/);
  assert.throws(()=>parseIRLClipboard('"Tarea\tPeligro\tRiesgo\tMedidas'),/comillas sin cerrar/);
});
