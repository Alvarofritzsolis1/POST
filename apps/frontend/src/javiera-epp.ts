/** Presentación de los ocho EPP con cantidades explícitas.
 * Los nombres/alias se obtienen del catálogo backend, fuente única de verdad.
 */
export type EppChoice={name:string;aliases:string[];max_quantity:number};
export type EppDraft={quantities:number[];invalid:string[]};

export const normalizeEpp=(value:string)=>value.trim().toLowerCase()
  .normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/\s+/g," ");

export function parseEppDraft(raw:string,choices:EppChoice[]):EppDraft{
  const quantities=choices.map(()=>0);
  const invalid:string[]=[];
  for(const part of raw.split(/[,;\n]/).map(s=>s.trim()).filter(Boolean)){
    const match=/^(?:(\d{1,2})\s*(?:[x×]\s*)?\s+|(\d{1,2})[x×]\s*)?(.+)$/i.exec(part);
    if(!match){invalid.push(part);continue;}
    const count=Number(match[1]||match[2]||1);
    const description=normalizeEpp(match[3]);
    const indexes=choices.flatMap((choice,index)=>
      [choice.name,...choice.aliases].some(a=>normalizeEpp(a)===description)?[index]:[]);
    if(indexes.length!==1||!Number.isInteger(count)||count<1||
       count>choices[indexes[0]]?.max_quantity||
       quantities[indexes[0]]+count>choices[indexes[0]].max_quantity){
      invalid.push(part);continue;
    }
    quantities[indexes[0]]+=count;
  }
  return {quantities,invalid};
}

export function serializeEppDraft(choices:EppChoice[],quantities:number[]):string{
  return choices.flatMap((choice,i)=>quantities[i]>0?
    [String(quantities[i])+" x "+choice.name]:[]).join("; ");
}
