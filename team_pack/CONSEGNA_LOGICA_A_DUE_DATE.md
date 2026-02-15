# Consegna Persona 1 - Logica A (due_date)

## Obiettivo
Schedulare gli ordini rispettando il piu possibile le scadenze.

## File da usare
- Input dati: `team_pack/data/scheduler_dataset.json`
- File da modificare: `team_pack/strategy_due_date.py`
- File NON da toccare:
  - `team_pack/scheduler_engine.py`
  - `team_pack/strategy_min_setup.py`
  - `app.py`
  - `backend.py`

## Cosa devi fare (minimo indispensabile)
1. Apri `team_pack/strategy_due_date.py`.
2. Modifica solo i pesi:
   - `W_TARDY`
   - `W_END`
   - `W_SETUP`
3. Non cambiare il formato output.
4. Esegui:
   - `python -m team_pack.run_strategy --strategy due_date`
5. Controlla che venga creato:
   - `team_pack/data/output_due_date.json`

## Significato pesi
- `W_TARDY`: penalita per ritardo. Deve essere il peso piu alto.
- `W_END`: preferisce completare prima.
- `W_SETUP`: penalizza cambi attrezzaggio.

## Output atteso
Nel file `output_due_date.json` devono esserci:
- `strategy`
- `kpi`
- `tasks`
- `unscheduled`

## Checklist finale
- [ ] Il comando gira senza errori.
- [ ] `kpi.scheduled_orders > 0`.
- [ ] `tasks` non e vuoto.
- [ ] Hai scritto una nota breve con i pesi scelti.
