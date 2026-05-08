# CLAUDE.md — Schedulazione-AI

Questo file contiene contesto, convenzioni e roadmap del progetto. Viene letto automaticamente da Claude Code e dalla GitHub Action di Claude per generare codice coerente con l'architettura esistente.

---

## 1. Cos'è il progetto

**Schedulazione-AI** è una dashboard MES (Manufacturing Execution System) per il monitoraggio e la gestione di linee produttive multiple. È un progetto di tesi universitaria.

### Funzionalità attuali
- Monitoraggio in tempo reale di più linee produttive (multilinea)
- Stato delle linee, contatori di produzione, storico eventi
- Azioni controllate sulle linee (assegna, avvia, ferma)
- Integrazione hardware tramite Arduino via bridge seriale per il conteggio pezzi
- Integrazione AI opzionale (richiede chiave API)

---

## 2. Stack tecnologico

| Componente | Tecnologia |
|---|---|
| UI / Frontend | Streamlit (Python) |
| Backend | Python (`backend.py`, `app.py`, `bridge_multilinea.py`) |
| Database | PostgreSQL via Supabase |
| Hardware | Arduino, codice in `codiceArduino.ino` (C++) |
| AI | API LLM esterna (chiave opzionale) |
| Hosting attuale | Streamlit Community Cloud |
| Dev environment | Devcontainer configurato (`.devcontainer/`) |

### File chiave
- `app.py` — entry point Streamlit
- `backend.py` — logica di accesso al DB e regole di business
- `bridge_multilinea.py` — gestione di più linee in parallelo
- `codiceArduino.ino` — firmware del microcontrollore per il conteggio pezzi
- `supabase_migration_mes61.sql` — schema del database
- `requirements.txt` — dipendenze Python

---

## 3. Come eseguire in locale

```bash
# 1. Crea virtualenv (consigliato)
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# 2. Installa dipendenze
pip install -r requirements.txt

# 3. Configura le credenziali (vedi sezione 4)

# 4. Avvia
streamlit run app.py

# Per accedere dalla LAN dello stabilimento:
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

---

## 4. Sicurezza e credenziali — REGOLE FERREE

**Il repository è pubblico.** Mai committare credenziali, in nessuna forma.

- Le credenziali Supabase, la chiave AI e qualsiasi token vanno in `.streamlit/secrets.toml`
- `.streamlit/secrets.toml` deve essere nel `.gitignore`
- Per accesso in produzione/locale usare variabili d'ambiente: `SUPABASE_URL`, `SUPABASE_KEY`, `AI_API_KEY`
- Mai stampare credenziali nei log o nei messaggi di errore esposti all'UI
- Se una credenziale entra per sbaglio in un commit: ruotarla immediatamente, anche se il commit viene rimosso

Esempio `secrets.toml` (NON committare):
```toml
[supabase]
url = "https://xxxxx.supabase.co"
key = "eyJhbGc..."

[ai]
api_key = "sk-..."
```

---

## 5. Convenzioni di codice

### Python
- Stile: PEP 8, indentazione 4 spazi
- Type hints sempre sulle funzioni pubbliche di `backend.py`
- Docstring in italiano sulle funzioni che implementano logica di business
- Niente codice di test o stampe di debug nel main branch
- Gestione errori: niente `except: pass` silenziosi; loggare e propagare

### Streamlit
- Cache con `@st.cache_data` per query DB read-only frequenti (stato linee, KPI)
- Cache con `@st.cache_resource` per oggetti pesanti (connessioni, client AI)
- Stato condiviso tramite `st.session_state`, non variabili globali

### Database
- Modifiche allo schema sempre tramite migrazioni SQL versionate (file numerati)
- Mai `SELECT *` in produzione, sempre colonne esplicite
- Indici su colonne usate in filtri frequenti (linea_id, timestamp)

### Arduino
- Commenti in italiano per coerenza con il resto del progetto
- Nessun delay bloccante > 100ms nel loop principale

---

## 6. Convenzioni Git

- Branch principale: `main`
- Feature branch: `feature/nome-breve`, fix: `fix/nome-breve`
- Commit message in italiano, formato: `tipo: descrizione breve`
  - Tipi: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`
  - Esempio: `feat: aggiungi export PDF report giornaliero`
- Pull request: descrizione con cosa cambia, perché, come testarlo

---

## 7. Roadmap

Le funzionalità sono organizzate in fasi. Quando lavori a una feature, leggi la issue corrispondente per i requisiti specifici.

### Fase 1 — Stabilizzazione e KPI (priorità alta)
- [ ] **OEE e KPI avanzati**: calcolo Disponibilità, Performance, Qualità e OEE complessivo per linea, con visualizzazione storica
- [ ] **Reportistica automatica**: export PDF e Excel del report giornaliero/settimanale per linea (libreria suggerita: `reportlab` per PDF, `openpyxl` per Excel)

### Fase 2 — Multi-utente
- [ ] **Autenticazione e ruoli**: login con Supabase Auth, ruoli `admin`, `operatore`, `visualizzatore`. Gli operatori possono solo registrare eventi sulla propria linea; gli admin possono modificare configurazioni

### Fase 3 — Intelligenza
- [ ] **Scheduling AI delle commesse**: dato un set di commesse con priorità, scadenze e tempi macchina, l'AI propone una pianificazione ottimale per le linee disponibili
- [ ] **Chat vocale con l'AI**: input vocale (Web Speech API in browser) per interrogare lo stato delle linee o richiedere una schedulazione, output vocale per la risposta

### Fase 4 — Distribuzione
- [ ] **App desktop standalone**: pacchettizzazione con Electron o Tauri, installer per Windows/macOS, modalità offline-first con sync verso Supabase

---

## 8. Come Claude Code deve lavorare su questo progetto

Quando viene aperta una issue e si chiede a Claude di implementarla:

1. **Leggere prima questo file** e i file menzionati nella sezione 2
2. **Non rompere ciò che esiste**: prima di modificare un file, verificare gli altri punti del codice che lo usano
3. **Seguire lo stack esistente**: non introdurre framework alternativi senza motivazione (es. niente Flask se il progetto è in Streamlit)
4. **Migrazioni DB**: per modifiche allo schema, creare un nuovo file `supabase_migration_NN.sql` con NN progressivo, mai modificare le migrazioni precedenti
5. **Test rapidi**: per nuove funzioni di backend aggiungere almeno un test in `tests/` se la cartella esiste, altrimenti documentare nel PR come è stato verificato
6. **Mai committare**: file `.streamlit/secrets.toml`, `.env`, chiavi API, dump DB con dati reali
7. **PR singole e mirate**: una PR = una issue. Niente PR mostre con 10 cose insieme
8. **Lingua**: codice in inglese (variabili, funzioni), commenti e UI in italiano

---

## 9. Comandi utili

```bash
# Esegui in locale
streamlit run app.py

# Esegui in LAN
streamlit run app.py --server.address 0.0.0.0

# Aggiorna dipendenze e verifica
pip install -r requirements.txt
pip check

# Test (se presenti)
pytest

# Lint
flake8 . --max-line-length=100
```
docs: aggiunge CLAUDE.md
