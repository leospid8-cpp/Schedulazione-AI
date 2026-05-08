# Schedulazione-AI 

## Accesso rapido (Streamlit)
Apri l’app qui:  
https://schedulazione-ai-ukjrfht4yz4tmmwsvma3nc.streamlit.app/

Se l’app è spenta (sleep/idle), premi il pulsante **Turn this app on** e attendi il riavvio.
nel caso di errori aggiornare la pagina.

## Funzionamento (in breve)
Dashboard MES per monitorare più linee produttive.  
Mostra stato linee, contatori di produzione e storico.  
I dati arrivano da un database PostgreSQL/Supabase.

l’app può eseguire azioni controllate (assegna linea, ferma, avvia).  

## Come funziona 
- Interfaccia web: Streamlit  
- Backend: lettura/scrittura su DB (linee, eventi, obiettivi)  
- Opzionale: bridge seriale per collegare Arduino e incrementare i pezzi

## Avvio come app desktop

La dashboard può essere avviata come **applicazione desktop standalone** (finestra nativa, senza browser, senza Streamlit Cloud).

### Windows
Doppio click su `desktop.bat`.  
Al primo avvio crea il virtualenv e installa le dipendenze (qualche minuto); gli avvii successivi sono istantanei.

### macOS
```bash
chmod +x desktop.command
```
Poi doppio click su `desktop.command`.  
Al primo avvio crea il virtualenv e installa le dipendenze (qualche minuto); gli avvii successivi sono istantanei.

> **Nota:** la finestra ha titolo "Schedulazione-AI - MES Dashboard" e funziona completamente in locale, senza dipendenza da Streamlit Cloud.

## Note utili
- Se manca la configurazione del DB, l’app non parte.
- Se manca la chiave AI, l’app continua a funzionare ma senza AI.
