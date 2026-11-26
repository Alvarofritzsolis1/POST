import { useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { matchesTrade, normalizeTrade, recruitmentPhotos, tradeFor } from "./networkRecruitmentCatalog";

/** Searchable editable combobox. Free-text trades remain possible. Native datalist
 * was intentionally removed: its OS popup cannot be styled or made consistent. */
export function NetworkSpecialtyPicker({
  value,
  onChange,
  suggestions,
  invalid = false,
}: {
  value: string;
  onChange: (value: string) => void;
  suggestions: string[];
  invalid?: boolean;
}) {
  const listId = useId();
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const normal = normalizeTrade;
  const options = useMemo(() => {
    const seen = new Set<string>();
    const selected = suggestions.some(term => normal(term) === normal(value));
    const needle = selected ? "" : normal(value);
    return [...suggestions]
      .filter((term) => {
        const key = normal(term);
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return matchesTrade(term, needle);
      })
      .sort((a, b) => {
        const aa = normal(a).startsWith(needle) ? 0 : 1;
        const bb = normal(b).startsWith(needle) ? 0 : 1;
        return aa - bb || a.localeCompare(b, "es-CL");
      });
  }, [suggestions, value]);
  function select(next: string) {
    onChange(next);
    setOpen(false);
    setActive(-1);
  }
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault(); setOpen(false); setActive(-1);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((current) => Math.min(current + 1, Math.max(0, options.length - 1)));
    } else if (event.key === "ArrowUp" && open) {
      event.preventDefault();
      setActive((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && open && active >= 0 && options[active]) {
      event.preventDefault(); select(options[active]);
    }
  }
  return (
    <div className={"nq-combo" + (invalid ? " nq-invalid" : "")}>
      <label htmlFor={inputId}>Oficio o especialidad <span className="nq-required">Obligatorio</span></label>
      <div className="nq-combo-control">
        <Search size={17} aria-hidden="true" />
        <input
          ref={inputRef}
          id={inputId}
          aria-label="Oficio o especialidad"
          value={value}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && active >= 0 ? listId + "-" + active : undefined}
          aria-invalid={invalid}
          autoComplete="off"
          minLength={2}
          maxLength={100}
          placeholder="Busca entre 26 especialidades o escribe otra"
          onFocus={() => { setOpen(true); setActive(-1); }}
          onBlur={() => { setOpen(false); setActive(-1); }}
          onKeyDown={keyDown}
          onChange={(event) => { onChange(event.target.value); setOpen(true); setActive(-1); }}
        />
        <button type="button" aria-label={open ? "Cerrar sugerencias" : "Mostrar sugerencias"}
          aria-expanded={open}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            if (open) { setOpen(false); setActive(-1); }
            else { inputRef.current?.focus(); setOpen(true); setActive(-1); }
          }}><ChevronDown size={16} aria-hidden="true" /></button>
      </div>
      {open && options.length > 0 && (
        <div className="nq-options nq-visual-options" id={listId} role="listbox" aria-label="Especialidades sugeridas">
          <div className="nq-option-count" role="presentation">{options.length} especialidades disponibles</div>
          {options.map((term, index) => {
            const item = tradeFor(term);
            const thumb = recruitmentPhotos(term)[0];
            return <div role="option" key={term} id={listId + "-" + index}
              ref={node => { if (index === active) node?.scrollIntoView({ block: "nearest" }); }}
              aria-selected={normal(term) === normal(value)}
              className={"nq-option nq-visual-option" + (index === active ? " active" : "")}
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => select(term)}>
              <span className="nq-trade-art" aria-hidden="true"><span>{item?.glyph ?? "＋"}</span>{thumb && <img src={thumb} loading="lazy" alt="" onError={event => { event.currentTarget.hidden = true; }}/>}</span>
              <span className="nq-trade-label"><strong>{term}</strong><small>{item?.group ?? "Personalizado"}</small></span>
              {normal(term) === normal(value) && <Check size={16} aria-hidden="true"/>}
            </div>;
          })}
        </div>
      )}
      {open && !options.length && value.trim().length > 1 && (
        <div className="nq-combo-hint">Puedes utilizar «{value.trim()}» como especialidad personalizada.</div>
      )}
    </div>
  );
}
