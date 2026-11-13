import test from 'node:test';
import assert from 'node:assert/strict';
import {parseSheetClipboard} from '../apps/frontend/src/javiera-sheet-paste.ts';
test('Excel quoted TSV preserves multiline text, quotes, blanks and formula-looking text',()=>{
 assert.deepEqual(parseSheetClipboard('Empresa\tRUT\r\n"texto\ncon salto"\t"dijo ""hola"""\r\n'),[['Empresa','RUT'],['texto\ncon salto','dijo "hola"']]);
 assert.deepEqual(parseSheetClipboard('=SUM(A1:A2)\t\n'),[['=SUM(A1:A2)','']]);
 assert.deepEqual(parseSheetClipboard('00123\t-5'),[['00123','-5']]);
});
test('oversized or unclosed clipboard is rejected before any edit',()=>{
 assert.throws(()=>parseSheetClipboard(Array(501).fill('x').join('\t')),/500/);
 assert.throws(()=>parseSheetClipboard('"unclosed'),/comillas/);
});

const {stableFingerprint,dossierFields}=await import('../apps/frontend/src/javiera-dossier-state.ts');
test('a recovered dossier compares equally despite database key order and absent optional fields',()=>{
 const saved={extra:{worker_city:'Talca',afp:'QA'},contract:{hours:42,start:'2026-11-01'},role:'PINTOR'};
 const loaded=dossierFields(saved);
 const reordered={...loaded,contract:{...loaded.contract,start:'2026-11-01',hours:'42'},extra:{afp:'QA',worker_city:'Talca'}};
 assert.equal(stableFingerprint(loaded),stableFingerprint(reordered));
 assert.equal(loaded.contract.end,'');assert.equal(loaded.event.date,'');
 assert.notEqual(stableFingerprint({data:loaded,parentId:'a'}),stableFingerprint({data:loaded,parentId:'b'}));
});
