# Consegna Persona 2 - Logica B (min_setup)

## Obiettivo
Ridurre i tempi morti dovuti ai cambi attrezzaggio, mantenendo un piano eseguibile.

## File da usare
- Input dati: `team_pack/data/scheduler_dataset.json`
- File da modificare: `team_pack/strategy_min_setup.py`
- File NON da toccare:
  - `team_pack/scheduler_engine.py`
  - `team_pack/strategy_due_date.py`
  - `app.py`
  - `backend.py`

## Cosa devi fare (minimo indispensabile)
1. Apri `team_pack/strategy_min_setup.py`.
2. Modifica solo i pesi:
   - `W_SETUP`
   - `W_START`
   - `W_TARDY`
3. Non cambiare il formato output.
4. Esegui:
   - `python -m team_pack.run_strategy --strategy min_setup`
5. Controlla che venga creato:
   - `team_pack/data/output_min_setup.json`

## Significato pesi
- `W_SETUP`: penalita per cambi attrezzaggio. Deve essere il peso principale.
- `W_START`: preferisce iniziare prima (meno idle).
- `W_TARDY`: penalita ritardo (deve restare presente ma inferiore a `W_SETUP`).

## Output atteso
Nel file `output_min_setup.json` devono esserci:
- `strategy`
- `kpi`
- `tasks`
- `unscheduled`

## Checklist finale
- [ ] Il comando gira senza errori.
- [ ] `kpi.scheduled_orders > 0`.
- [ ] `tasks` non e vuoto.
- [ ] Hai scritto una nota breve con i pesi scelti.
