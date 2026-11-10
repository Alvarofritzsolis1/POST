import {useEffect, useRef} from "react";
import {AlignCenter, AlignLeft, AlignRight, Bold, Heading2, Heading3, Italic, List, ListOrdered, Redo2, Table2, Undo2, Underline} from "lucide-react";

type Props={html:string;onChange:(value:string)=>void;resetKey:string};
const fields=[
  ["worker.name","Nombre del trabajador"],["worker.rut","RUT del trabajador"],
  ["employer.name","Empresa"],["employer.rut","RUT de la empresa"],
  ["site.name","Obra"],["role","Cargo"],["event.date","Fecha del documento"]
] as const;
const safeTags=new Set(["p","h2","h3","strong","b","em","i","u","ol","ul","li",
  "table","thead","tbody","tr","td","th","br","blockquote"]);
const blockTags=new Set(["p","h2","h3","ul","ol","table","blockquote"]);
const labels:Record<string,string>=Object.fromEntries(fields);
function esc(text:string){return text.replaceAll("&","&amp;").replaceAll("<","&lt;")
  .replaceAll(">","&gt;").replaceAll('"',"&quot;");}

function visualHtml(html:string):string{
  return html.replace(/\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g,(_all:string,key:string)=>{
    const title=labels[key]||key;
    return '<span class="jne-variable" data-token="'+esc(key)+'" contenteditable="false">'+esc(title)+'</span>';
  });
}

// The browser's editing DOM is not trusted. Persist ONLY the backend-allowed
// subset and turn visual chips back into the exact original template tokens.
function serialize(node:Node):string{
  if(node.nodeType===Node.TEXT_NODE)return esc(node.textContent||"");
  if(node.nodeType!==Node.ELEMENT_NODE)return "";
  const el=node as HTMLElement;
  const token=el.getAttribute("data-token");
  if(token && /^[a-zA-Z0-9_.]+$/.test(token) && el.classList.contains("jne-variable"))
    return "{{"+token+"}}";
  const tag=el.tagName.toLowerCase();
  let children=Array.from(el.childNodes).map(serialize).join("");
  if(tag==="div")return "<p>"+children+"</p>";
  if(tag==="font"||tag==="span")return children;
  if(!safeTags.has(tag))return children;
  if(tag==="br")return "<br/>";
  const alignment=el.getAttribute("align")||el.style.textAlign;
  const allowedAlign=["left","center","right"].includes(alignment);
  const attr=allowedAlign && ["p","h2","h3","th","td"].includes(tag)
    ? ' align="'+alignment+'"' : "";
  if(tag==="table"&& !children.includes("<tr>") && !children.includes("<tbody>"))return children;
  if(blockTags.has(tag)&&!children.trim())children=" ";
  return "<"+tag+attr+">"+children+"</"+tag+">";
}
function toHtml(root:HTMLElement):string {
  const parts=Array.from(root.childNodes).map(serialize).join("");
  // Bare characters from the editor belong in a paragraph.
  return parts.trim().startsWith("<")?parts:"<p>"+parts+"</p>";
}

export default function JavieraVisualCanvas({html,onChange,resetKey}:Props){
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(ref.current)ref.current.innerHTML=visualHtml(html||"<p></p>");
    // Reset only when switching documents/revisions, never on each keystroke.
  },[resetKey]);
  function emit(){if(ref.current)onChange(toHtml(ref.current));}
  function command(name:string,value?:string){
    ref.current?.focus();
    document.execCommand(name,false,value);
    emit();
  }
  function insertVariable(key:string){
    command("insertHTML",'<span class="jne-variable" data-token="'+esc(key)+
      '" contenteditable="false">'+esc(labels[key]||key)+'</span>&nbsp;');
  }
  function pasteText(event:React.ClipboardEvent<HTMLDivElement>){
    event.preventDefault();
    const plain=event.clipboardData.getData("text/plain").slice(0,18000);
    command("insertText",plain);
  }
  return <div className="jne-visual">
    <div role="toolbar" aria-label="Formato del documento" className="jne-visual-toolbar">
      <button type="button" title="Negrita" aria-label="Negrita" onMouseDown={e=>e.preventDefault()} onClick={()=>command("bold")}><Bold size={17}/></button>
      <button type="button" title="Cursiva" aria-label="Cursiva" onMouseDown={e=>e.preventDefault()} onClick={()=>command("italic")}><Italic size={17}/></button>
      <button type="button" title="Subrayado" aria-label="Subrayado" onMouseDown={e=>e.preventDefault()} onClick={()=>command("underline")}><Underline size={17}/></button>
      <button type="button" title="Título" aria-label="Título" onMouseDown={e=>e.preventDefault()} onClick={()=>command("formatBlock","h2")}><Heading2 size={17}/></button>
      <button type="button" title="Subtítulo" aria-label="Subtítulo" onMouseDown={e=>e.preventDefault()} onClick={()=>command("formatBlock","h3")}><Heading3 size={17}/></button>
      <button type="button" title="Lista" aria-label="Lista con viñetas" onMouseDown={e=>e.preventDefault()} onClick={()=>command("insertUnorderedList")}><List size={17}/></button>
      <button type="button" title="Lista numerada" aria-label="Lista numerada" onMouseDown={e=>e.preventDefault()} onClick={()=>command("insertOrderedList")}><ListOrdered size={17}/></button>
      <button type="button" title="Izquierda" aria-label="Alinear a la izquierda" onMouseDown={e=>e.preventDefault()} onClick={()=>command("justifyLeft")}><AlignLeft size={17}/></button>
      <button type="button" title="Centrar" aria-label="Centrar texto" onMouseDown={e=>e.preventDefault()} onClick={()=>command("justifyCenter")}><AlignCenter size={17}/></button>
      <button type="button" title="Derecha" aria-label="Alinear a la derecha" onMouseDown={e=>e.preventDefault()} onClick={()=>command("justifyRight")}><AlignRight size={17}/></button>
      <button type="button" title="Insertar tabla" aria-label="Insertar tabla" onMouseDown={e=>e.preventDefault()}
        onClick={()=>command("insertHTML","<table><tbody><tr><th>Concepto</th><th>Detalle</th></tr><tr><td>Escribir</td><td>Completar</td></tr></tbody></table><p> </p>")}><Table2 size={17}/></button>
      <button type="button" title="Deshacer" aria-label="Deshacer" onMouseDown={e=>e.preventDefault()} onClick={()=>command("undo")}><Undo2 size={17}/></button>
      <button type="button" title="Rehacer" aria-label="Rehacer" onMouseDown={e=>e.preventDefault()} onClick={()=>command("redo")}><Redo2 size={17}/></button>
      <select aria-label="Insertar dato automático" defaultValue=""
        onChange={e=>{if(e.target.value)insertVariable(e.target.value);e.currentTarget.value="";}}>
        <option value="">Insertar dato automático…</option>
        {fields.map(([key,label])=><option key={key} value={key}>{label}</option>)}
      </select>
      <button type="button" onMouseDown={e=>e.preventDefault()}
        onClick={()=>command("insertHTML","<p>☐ Marcar al revisar</p>")}>☐ Casilla</button>
    </div>
    <div className="jne-editable-paper" ref={ref} contentEditable suppressContentEditableWarning
      role="textbox" aria-label="Documento editable" aria-multiline="true" spellCheck
      onInput={emit} onPaste={pasteText} onBlur={emit}/>
    <p className="jne-help">Escribe sobre la hoja, selecciona texto para darle formato o inserta campos automáticos.
      Los campos marcados se completan con los datos del expediente al generar el PDF.</p>
  </div>;
}
