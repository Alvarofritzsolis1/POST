/** Pegado tabular seguro para el editor IRL: no interpreta fórmulas ni HTML. */
const LABELS=["Tarea","Peligro","Riesgo","Medidas"];

function splitTsv(source:string):string[][]{
  const rows:string[][]=[];
  let record:string[]=[];let cell="";let quoted=false;
  for(let i=0;i<source.length;i++){
    const ch=source[i];
    if(ch==='"'){
      if(quoted&&source[i+1]==='"'){cell+='"';i++;}
      else quoted=!quoted;
    }else if(ch==="\\t"&&!quoted){record.push(cell);cell="";}
    else if((ch==="\\r"||ch==="\\n")&&!quoted){
      record.push(cell);if(record.some(v=>v.trim()))rows.push(record);
      record=[];cell="";
      if(ch==="\\r"&&source[i+1]==="\\n")i++;
    }else{cell+=ch;}
  }
  if(quoted)throw new Error("El texto pegado contiene comillas sin cerrar.");
  record.push(cell);if(record.some(v=>v.trim()))rows.push(record);
  return rows;
}
const clean=(value:string)=>value.trim().normalize("NFKC").replace(/\\s+/g," ").toLowerCase();

export function parseIRLClipboard(source:string){
  if(source.length>250_000)throw new Error("El pegado supera 250.000 caracteres.");
  const rows=splitTsv(source);
  if(!rows.length)throw new Error("Copia cuatro columnas desde Excel e intenta nuevamente.");
  if(rows[0].length!==4)throw new Error("Se requieren cuatro columnas: actividad, peligro, consecuencia y medida.");
  const first=rows[0].map(clean);
  const hasHeader=/^(actividad|tarea|labor)$/.test(first[0])
    && /^(peligro|riesgos? detectados?)$/.test(first[1])
    && /^(riesgo|consecuencias?( potenciales?)?)$/.test(first[2])
    && /^(medidas?( preventivas?( obligatorias?)?)?)$/.test(first[3]);
  const body=hasHeader?rows.slice(1):rows;
  if(!body.length)throw new Error("El texto contiene encabezados, pero ninguna labor.");
  if(body.length>1500)throw new Error("El máximo es de 1.500 labores por cargo.");
  const invalid=body.findIndex(row=>row.length!==4||row.some(v=>!v.trim()));
  if(invalid!==-1)throw new Error("Fila "+(invalid+1+(hasHeader?1:0))+
    ": se requieren cuatro celdas completas, sin columnas desplazadas.");
  const seen=new Set<string>();let duplicates=0;
  const sections:string[]=[];
  for(const row of body){
    const key=row.map(clean).join("\\u001f");
    if(seen.has(key)){duplicates++;continue;}
    seen.add(key);
    sections.push(LABELS.map((name,i)=>name+": "+row[i].trim()).join("\\n"));
  }
  return {sections,duplicates,originalRows:body.length};
}
