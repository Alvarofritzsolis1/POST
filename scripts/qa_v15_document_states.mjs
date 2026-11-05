import test from "node:test";
import assert from "node:assert/strict";
import {summarizeRequirements, requirementPending, statusTone, statusLabel} from "../apps/frontend/src/documentUX.ts";

function req(kind,state,applicable=true,required_count=1,approved_count=0){
  return {kind,state,applicable,required_count,approved_count,source:null,document_id:null,
    reviewed_by:null,reviewed_at:null,notes:"",request_date:null,due_date:null};
}

test("sin obligaciones evaluables no inventa cumplimiento de 100%",()=>{
  const s=summarizeRequirements([]);
  assert.equal(s.percent,null);
  assert.equal(s.required,0);
  assert.equal(s.pending.length,0);
});
test("exento, sin movimientos, no aplica e inactivo no son incumplimientos",()=>{
  const s=summarizeRequirements([
    req("porteria","exempt"),req("f30","no_movements"),
    req("f30_1","not_applicable"),req("liquidaciones","inactive"),
    req("asistencia","not_yet_required"),req("cotizaciones","not_required")
  ]);
  assert.equal(s.required,0);
  assert.equal(s.approved,0);
  assert.equal(s.percent,null);
  assert.equal(s.pending.length,0);
});
test("la suma es ponderada por trabajadores, no por filas",()=>{
  const s=summarizeRequirements([
    req("liquidaciones","incomplete",true,4,3),
    req("porteria","approved",true,1,1),
    req("f30_1","missing",true,1,0)
  ]);
  assert.equal(s.required,6);
  assert.equal(s.approved,4);
  assert.equal(s.percent,67);
  assert.equal(s.pending.length,2);
  assert.equal(s.urgent.length,2);
});
test("calendario faltante requiere configurar sin penalizar porcentaje",()=>{
  const s=summarizeRequirements([req("f30","approved",true,1,1),req("porteria","schedule_not_configured")]);
  assert.equal(s.percent,100);
  assert.equal(s.pending.length,1);
  assert.equal(s.pending[0].kind,"porteria");
});
test("exigibilidad indefinida requiere atención sin atribuir falta",()=>{
  const unknown=req("f30_1","needs_classification",null);
  assert.equal(requirementPending(unknown),true);
  const s=summarizeRequirements([unknown]);
  assert.equal(s.percent,null);
  assert.equal(s.pending.length,1);
});
test("datos defensivos: aprobado nunca supera lo exigible",()=>{
  const s=summarizeRequirements([req("liquidaciones","approved",true,2,9)]);
  assert.equal(s.approved,2);
  assert.equal(s.percent,100);
});
test("estados visibles conservan significado y no dependen solo del color",()=>{
  assert.equal(statusTone("missing"),"bad");
  assert.equal(statusTone("no_movements"),"muted");
  assert.equal(statusLabel("submitted"),"Entregado, pendiente de revisión");
  assert.equal(statusLabel("incomplete"),"Entregado incompleto");
});
