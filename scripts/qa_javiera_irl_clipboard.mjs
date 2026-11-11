import test from "node:test";
import assert from "node:assert/strict";
import {parseIRLClipboard,serializeIRLClipboard} from "../apps/frontend/src/javiera-irl-clipboard.ts";

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


test("copia y vuelve a importar matrices sin perder nuevas líneas, tabs ni comillas",()=>{
  const rows=[
    ["Tarea extensa\nsegunda línea","Peligro con\ttabulación","Corte \"grave\"","Medida A\nMedida B"],
    ["Revisar herramientas","Golpes","Lesiones","Orden y aseo"],
  ];
  const payload=serializeIRLClipboard(rows);
  assert.match(payload,/"Tarea extensa\nsegunda línea"/);
  const again=parseIRLClipboard(payload);
  assert.equal(again.duplicates,0);
  assert.equal(again.sections.length,rows.length);
  for(let i=0;i<rows.length;i++){
    const row=again.sections[i];
    assert.equal(row,["Tarea: "+rows[i][0],"Peligro: "+rows[i][1],
      "Riesgo: "+rows[i][2],"Medidas: "+rows[i][3]].join("\n"));
  }
});
test("protege exportación a hojas de cálculo de expresiones de fórmula",()=>{
  const exported=serializeIRLClipboard([["=HYPERLINK(\"https://example.com\")","Corte",
    "Herida","Control"]],false);
  assert.match(exported,/^'=HYPERLINK/);
});
