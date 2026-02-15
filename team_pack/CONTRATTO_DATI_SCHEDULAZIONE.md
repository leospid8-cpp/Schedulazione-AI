# Contratto Dati per le 2 Logiche

## Input unico
File: `team_pack/data/scheduler_dataset.json`

## Campi input principali
- `lines`: elenco linee disponibili
  - `line_id` (es. `LM01`)
- `orders`: ordini da schedulare
  - `order_id` (es. `ORD_001`)
  - `code` (es. `CD333`)
  - `qty`
  - `due_serial`
  - `due_date`
  - `eligible_lines` (linee compatibili)
  - `cycle_minutes_by_line` (minuti/pezzo per linea)
- `current_config`:
  - codice attuale montato per linea
- `setup_minutes`:
  - `from_current[line][code]`
  - `between_codes[from_code][to_code]`

## Output obbligatorio (uguale per entrambe le logiche)
Il risultato deve contenere:
- `strategy`
- `kpi`
- `tasks`
- `unscheduled`

Ogni elemento di `tasks` contiene almeno:
- `task_id`
- `order_id`
- `code`
- `line_id`
- `qty`
- `setup_min`
- `start_min`
- `end_min`
- `tardy_min`

## Comandi standard
- Rigenera dataset da XLSX:
  - `python team_pack/build_scheduler_data.py`
- Esegui logica A:
  - `python -m team_pack.run_strategy --strategy due_date`
- Esegui logica B:
  - `python -m team_pack.run_strategy --strategy min_setup`
