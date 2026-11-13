/** Excel/Calc TSV clipboard, including quoted cells containing tabs or newlines. */
export function parseSheetClipboard(text:string):string[][] {
  const rows:string[][]=[]; let row:string[]=[],cell="",quoted=false;
  const value=text.replace(/\r\n?/g,"\n");
  for(let i=0;i<value.length;i++){
    const c=value[i];
    if(c==='"'&&(quoted||!cell)){
      if(quoted&&value[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;
    }else if(!quoted&&(c==='\t'||c==='\n')){
      row.push(cell);cell="";
      if(c==='\n'){rows.push(row);row=[];}
    }else cell+=c;
  }
  if(quoted)throw new Error("El texto copiado contiene comillas sin cerrar.");
  if(cell||row.length||!rows.length){row.push(cell);rows.push(row);}
  if(rows.reduce((n,r)=>n+r.length,0)>500)throw new Error("Pega hasta 500 celdas a la vez.");
  return rows;
}
