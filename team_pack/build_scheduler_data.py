import argparse
import json
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": MAIN_NS, "r": DOC_REL_NS}


def excel_serial_to_iso(value):
    try:
        serial = float(value)
    except Exception:
        return None
    base = datetime(1899, 12, 30)
    dt = base + timedelta(days=serial)
    return dt.date().isoformat()


def normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_number(value):
    text = normalize_text(value).replace(",", ".")
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def normalize_key(value):
    text = normalize_text(value).lower()
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    return " ".join(text.split())


def col_to_idx(col):
    idx = 0
    for ch in col:
        if "A" <= ch <= "Z":
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def idx_to_col(idx):
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def sorted_cols(cols):
    return sorted(cols, key=col_to_idx)


def read_shared_strings(zf):
    shared = []
    if "xl/sharedStrings.xml" not in zf.namelist():
        return shared
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    for si in root.findall("m:si", NS):
        parts = [t.text or "" for t in si.findall(".//m:t", NS)]
        shared.append("".join(parts))
    return shared


def workbook_sheets(zf):
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {}
    for rel in rels.findall(f"{{{REL_NS}}}Relationship"):
        rid_to_target[rel.attrib["Id"]] = rel.attrib["Target"]

    out = {}
    for sheet in wb.findall("m:sheets/m:sheet", NS):
        name = sheet.attrib.get("name")
        rid = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
        target = rid_to_target.get(rid, "")
        if not target.startswith("worksheets/"):
            target = "worksheets/" + target.split("/")[-1]
        out[name] = "xl/" + target
    return out


def find_sheet_path(sheets, *aliases):
    alias_keys = [normalize_key(a) for a in aliases]
    for name, path in sheets.items():
        nk = normalize_key(name)
        if nk in alias_keys:
            return name, path
    for name, path in sheets.items():
        nk = normalize_key(name)
        if any(a in nk for a in alias_keys):
            return name, path
    raise KeyError(f"Nessun foglio trovato per alias: {aliases}")


def cell_value(cell, shared_strings):
    t = cell.attrib.get("t")
    v = cell.find("m:v", NS)
    if v is not None and v.text is not None:
        if t == "s":
            try:
                return shared_strings[int(v.text)]
            except Exception:
                return v.text
        return v.text

    inline = cell.find("m:is", NS)
    if inline is not None:
        parts = [t.text or "" for t in inline.findall(".//m:t", NS)]
        return "".join(parts)
    return ""


def sheet_rows(zf, xml_path, shared_strings):
    root = ET.fromstring(zf.read(xml_path))
    rows = root.findall("m:sheetData/m:row", NS)
    parsed = []
    for row in rows:
        row_data = {}
        for cell in row.findall("m:c", NS):
            ref = cell.attrib.get("r", "")
            col = "".join(ch for ch in ref if ch.isalpha())
            row_data[col] = cell_value(cell, shared_strings)
        parsed.append({"row": int(row.attrib.get("r", "0")), "cells": row_data})
    return parsed


def parse_generic_specs(rows, id_col="A", only_ids=None):
    if not rows:
        return {}
    header = rows[0]["cells"]
    headers = {
        col: normalize_text(label)
        for col, label in header.items()
        if normalize_text(label)
    }
    cols = sorted_cols(headers.keys())
    out = {}
    only_set = set(only_ids or [])
    use_filter = bool(only_ids)

    for r in rows[1:]:
        entity_id = normalize_text(r["cells"].get(id_col))
        if not entity_id:
            continue
        if use_filter and entity_id not in only_set:
            continue
        specs = {}
        for col in cols:
            if col == id_col:
                continue
            key = headers[col]
            raw = r["cells"].get(col)
            num = normalize_number(raw)
            val = num if num is not None else normalize_text(raw)
            if val == "":
                continue
            specs[key] = val
        out[entity_id] = specs
    return out


def parse_setup_tools(rows_setup):
    """
    Estrae mappa "attrezzatura -> minuti cambio" dal foglio SETUP.
    Cerca la riga con i nomi attrezzature (es: occhioni, pinzette, ...),
    poi legge i primi valori numerici sulle stesse colonne.
    """
    if not rows_setup:
        return {}

    tool_row = None
    for r in rows_setup:
        vals = [normalize_text(v).lower() for v in r["cells"].values()]
        if "occhioni" in vals and "pinzette" in vals:
            tool_row = r
            break
    if tool_row is None:
        return {}

    tool_cols = {}
    for col, label in tool_row["cells"].items():
        name = normalize_text(label).lower()
        if name:
            tool_cols[col] = name

    minutes = {}
    for col, tool_name in tool_cols.items():
        value = None
        for r in rows_setup:
            if r["row"] <= tool_row["row"]:
                continue
            n = normalize_number(r["cells"].get(col))
            if n is not None and n > 0:
                value = float(n)
                break
        if value is not None:
            minutes[tool_name] = value
    return minutes


def parse_setup_cases(rows_setup, valid_lines):
    """
    Estrae casi riga-linea dal foglio SETUP (layout operativo).
    Campi usati:
    - B: line_id
    - C: codice attuale
    - E: codice target principale
    - F: qty target
    - K: codice target alternativo (se presente)
    """
    valid_line_set = set(valid_lines)
    out = []
    for r in rows_setup:
        line_id = normalize_text(r["cells"].get("B"))
        if not line_id or line_id not in valid_line_set:
            continue
        current_code = normalize_text(r["cells"].get("C"))
        target_code = normalize_text(r["cells"].get("E"))
        alt_target = normalize_text(r["cells"].get("K"))
        qty = normalize_number(r["cells"].get("F"))
        out.append(
            {
                "line_id": line_id,
                "current_code": current_code if current_code else None,
                "target_code": target_code if target_code else None,
                "target_qty": int(qty) if qty is not None else None,
                "alt_target_code": alt_target if alt_target else None,
                "row_index": r["row"],
            }
        )
    return out


def parse_min_pieces(rows_min_pz, line_ids, only_codes):
    """
    Foglio MIN|PZ LM:
    - col A: codice
    - colonne successive: min pezzi per linea in ordine LM01..LMxx
    """
    out = {}
    code_filter = set(only_codes)
    for r in rows_min_pz:
        code = normalize_text(r["cells"].get("A"))
        if not code or code not in code_filter:
            continue
        row_map = {}
        for i, line_id in enumerate(line_ids, start=2):
            col = idx_to_col(i)
            n = normalize_number(r["cells"].get(col))
            if n is None:
                continue
            row_map[line_id] = n
        out[code] = row_map
    return out


def build_dataset(xlsx_path):
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings = read_shared_strings(zf)
        sheets = workbook_sheets(zf)

        name_orders, path_orders = find_sheet_path(sheets, "ORDINI (sheet3)", "ordini")
        name_lines, path_lines = find_sheet_path(sheets, "linee")
        name_codes, path_codes = find_sheet_path(sheets, "codici")
        name_compat, path_compat = find_sheet_path(sheets, "compatibilità", "compatibilita")
        name_cycle, path_cycle = find_sheet_path(sheets, "tempi ciclo")
        name_att, path_att = find_sheet_path(sheets, "attrezzature")
        name_config, path_config = find_sheet_path(sheets, "CONFIG (sheet4)", "config")
        name_setup, path_setup = find_sheet_path(sheets, "setup")
        name_min_pz, path_min_pz = find_sheet_path(sheets, "MIN|PZ LM (sheet2)", "min|pz lm")

        rows_orders = sheet_rows(zf, path_orders, shared_strings)
        rows_lines = sheet_rows(zf, path_lines, shared_strings)
        rows_codes = sheet_rows(zf, path_codes, shared_strings)
        rows_compat = sheet_rows(zf, path_compat, shared_strings)
        rows_cycle = sheet_rows(zf, path_cycle, shared_strings)
        rows_att = sheet_rows(zf, path_att, shared_strings)
        rows_config = sheet_rows(zf, path_config, shared_strings)
        rows_setup = sheet_rows(zf, path_setup, shared_strings)
        rows_min_pz = sheet_rows(zf, path_min_pz, shared_strings)

    orders = []
    for r in rows_orders:
        code = normalize_text(r["cells"].get("A"))
        qty = normalize_number(r["cells"].get("B"))
        due_serial = normalize_number(r["cells"].get("C"))
        if not code:
            continue
        orders.append(
            {
                "order_id": f"ORD_{len(orders) + 1:03d}",
                "code": code,
                "qty": int(qty or 0),
                "due_serial": int(due_serial or 0),
                "due_date": excel_serial_to_iso(due_serial),
            }
        )

    ordered_codes = sorted({o["code"] for o in orders})

    lines = []
    for r in rows_lines[1:]:
        line_id = normalize_text(r["cells"].get("A"))
        if not line_id:
            continue
        lines.append(
            {
                "line_id": line_id,
                "h_canale": normalize_number(r["cells"].get("B")),
                "diametro_ruota": normalize_number(r["cells"].get("C")),
                "fresata_tassello": normalize_number(r["cells"].get("D")),
                "h_piano_bordo_post": normalize_number(r["cells"].get("E")),
                "fori_stile_y": normalize_number(r["cells"].get("F")),
                "foro_valvola_y": normalize_number(r["cells"].get("G")),
            }
        )

    line_ids = [l["line_id"] for l in lines]

    compat_header_row = next((r for r in rows_compat if normalize_text(r["cells"].get("A")) == "idCodice"), None)
    if compat_header_row is None:
        raise RuntimeError("Header idCodice non trovato nel foglio compatibilita.")

    compat_line_cols = {}
    for col, val in compat_header_row["cells"].items():
        vv = normalize_text(val)
        if vv.startswith("LM"):
            compat_line_cols[col] = vv

    compatibility = {}
    compatibility_flags = {}
    header_row_num = compat_header_row["row"]
    for r in rows_compat:
        if r["row"] <= header_row_num:
            continue
        code = normalize_text(r["cells"].get("A"))
        if not code or code not in ordered_codes:
            continue
        allowed = []
        flags = {}
        for col, line_id in compat_line_cols.items():
            flag = normalize_text(r["cells"].get(col)).upper()
            is_allowed = flag == "SI"
            flags[line_id] = is_allowed
            if is_allowed:
                allowed.append(line_id)
        compatibility[code] = sorted(allowed)
        compatibility_flags[code] = flags

    cycle_header = rows_cycle[0]["cells"]
    cycle_line_cols = {}
    for col, val in cycle_header.items():
        vv = normalize_text(val)
        if vv.startswith("LM"):
            cycle_line_cols[col] = vv

    cycle_minutes = {}
    for r in rows_cycle[1:]:
        code = normalize_text(r["cells"].get("A"))
        if not code or code not in ordered_codes:
            continue
        code_map = {}
        for col, line_id in cycle_line_cols.items():
            n = normalize_number(r["cells"].get(col))
            if n is not None and n > 0:
                code_map[line_id] = float(n)
        cycle_minutes[code] = code_map

    att_header = rows_att[0]["cells"] if rows_att else {}
    tool_cols = []
    for col, val in att_header.items():
        h = normalize_text(val)
        if h and h.upper() != "CODICE":
            tool_cols.append((col, h))

    tooling_by_code = {}
    for r in rows_att[1:]:
        code = normalize_text(r["cells"].get("A"))
        if not code:
            continue
        features = {}
        for col, name in tool_cols:
            raw = normalize_text(r["cells"].get(col))
            if raw:
                features[name] = raw
        tooling_by_code[code] = features

    current_config = {}
    for r in rows_config:
        line_id = normalize_text(r["cells"].get("A"))
        if not line_id:
            continue
        current_config[line_id] = {
            "current_code": normalize_text(r["cells"].get("B")),
            "loaded_qty": int(normalize_number(r["cells"].get("C")) or 0),
        }

    setup_tool_minutes = parse_setup_tools(rows_setup)
    setup_cases = parse_setup_cases(rows_setup, line_ids)
    if setup_tool_minutes:
        per_tool_minutes = sum(setup_tool_minutes.values()) / len(setup_tool_minutes)
    else:
        per_tool_minutes = 10.0

    def setup_minutes(from_code, to_code):
        if not from_code or not to_code or from_code == to_code:
            return 0.0
        from_f = tooling_by_code.get(from_code, {})
        to_f = tooling_by_code.get(to_code, {})
        if not from_f or not to_f:
            return round(6 * per_tool_minutes, 2)
        keys = sorted(set(from_f.keys()) | set(to_f.keys()))
        changes = 0
        for k in keys:
            if normalize_text(from_f.get(k)) != normalize_text(to_f.get(k)):
                changes += 1
        return round(changes * per_tool_minutes, 2)

    setup_from_current = {}
    for line_id in line_ids:
        current_code = current_config.get(line_id, {}).get("current_code", "")
        setup_from_current[line_id] = {}
        for code in ordered_codes:
            setup_from_current[line_id][code] = setup_minutes(current_code, code)

    setup_between_codes = {}
    for c_from in ordered_codes:
        setup_between_codes[c_from] = {}
        for c_to in ordered_codes:
            setup_between_codes[c_from][c_to] = setup_minutes(c_from, c_to)

    enriched_orders = []
    for o in orders:
        code = o["code"]
        eligible = compatibility.get(code, [])
        cycles = cycle_minutes.get(code, {})
        enriched_orders.append(
            {
                **o,
                "eligible_lines": [l for l in eligible if l in line_ids and l in cycles],
                "cycle_minutes_by_line": {k: v for k, v in cycles.items() if k in line_ids},
            }
        )

    line_specs = parse_generic_specs(rows_lines, id_col="A")
    code_specs = parse_generic_specs(rows_codes, id_col="A", only_ids=ordered_codes)
    min_pieces_by_code_line = parse_min_pieces(rows_min_pz, line_ids, ordered_codes)

    dataset = {
        "meta": {
            "source_file": str(xlsx_path),
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "notes": [
                "Dataset estratto da XLSX per schedulazione.",
                "Tempi setup stimati da differenze attrezzature.",
            ],
            "sheet_map": {
                "orders": name_orders,
                "lines": name_lines,
                "codes": name_codes,
                "compatibility": name_compat,
                "cycle_times": name_cycle,
                "tooling": name_att,
                "config": name_config,
                "setup": name_setup,
                "min_pieces": name_min_pz,
            },
        },
        "lines": lines,
        "orders": enriched_orders,
        "compatibility": compatibility,
        "compatibility_flags": compatibility_flags,
        "cycle_minutes": cycle_minutes,
        "current_config": current_config,
        "setup_minutes": {
            "per_tool_minutes": round(per_tool_minutes, 2),
            "from_current": setup_from_current,
            "between_codes": setup_between_codes,
        },
        "calendar": {
            "shift_minutes": 480,
            "day_minutes": 1440,
            "shift_start_min": 0,
            "anchor_now": True,
        },
        "excel_context": {
            "line_specs": line_specs,
            "code_specs": code_specs,
            "min_pieces_by_code_line": min_pieces_by_code_line,
            "setup_sheet": {
                "tool_change_minutes": setup_tool_minutes,
                "cases": setup_cases,
            },
        },
    }
    return dataset


def main():
    parser = argparse.ArgumentParser(description="Build scheduler dataset from XLSX.")
    parser.add_argument(
        "--xlsx",
        default=r"C:\Users\leo\Downloads\SUPPORTO PROGRAMMAZIONE MECCANICA_SENZA PASSWORD - Copia.XLSX",
        help="Path to source XLSX.",
    )
    parser.add_argument(
        "--out",
        default="team_pack/data/scheduler_dataset.json",
        help="Output JSON file.",
    )
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = build_dataset(xlsx_path)
    out_path.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    print(
        f"Wrote {out_path} with {len(dataset['orders'])} orders, "
        f"{len(dataset['lines'])} lines, "
        f"{len(dataset.get('excel_context', {}).get('code_specs', {}))} code specs."
    )


if __name__ == "__main__":
    main()
