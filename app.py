import streamlit as st
import google.generativeai as genai
import json
import time
from backend import DatabaseManager, LineaManager, OrdineManager

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="MES AI Scheduler Pro", page_icon="🏭", layout="wide")

try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.0-flash')
except:
    st.error("Chiave Google mancante. Impostala nei Secrets.")
    st.stop()

# --- INIZIALIZZAZIONE DB ---
if "db" not in st.session_state:
    st.session_state.db = DatabaseManager()
    st.session_state.linea_mgr = LineaManager(st.session_state.db)
    st.session_state.ordine_mgr = OrdineManager(st.session_state.db)

# --- NUOVO ESECUTORE MULTI-AZIONE 🧠 ---
def esegui_azioni_ai(json_input):
    log_azioni = []
    try:
        # L'AI potrebbe restituire una lista [...] o un oggetto singolo {...}
        dati = json.loads(json_input)
        
        # Se è un singolo oggetto, lo trasformiamo in lista per gestirlo uguale
        if isinstance(dati, dict):
            dati = [dati]
            
        # Eseguiamo tutte le azioni in sequenza
        for azione in dati:
            comando = azione.get("comando")
            
            if comando == "assegna_linea":
                lid = azione.get("linea_id")
                cod = azione.get("codice_ordine")
                st.session_state.linea_mgr.assegna_commessa(lid, cod)
                log_azioni.append(f"✅ Linea {lid} -> Assegnata a {cod}")
                
            elif comando == "ferma_linea":
                lid = azione.get("linea_id")
                motivo = azione.get("motivo")
                st.session_state.linea_mgr.set_stato(lid, "Ferma", motivo)
                log_azioni.append(f"⛔ Linea {lid} FERMATA ({motivo})")

        if not log_azioni:
            return "⚠️ Nessuna azione eseguita."
            
        return "\n".join(log_azioni)

    except Exception as e:
        return f"❌ Errore critico nel parsing azioni: {e}"

# ==========================================
# BARRA LATERALE
# ==========================================
with st.sidebar:
    st.header("🎛️ Pannello Operatore")
    
    with st.expander("🛠️ Manutenzione"):
        if st.button("⚠️ RESETTA GIORNATA"):
            st.session_state.ordine_mgr.reset_giornata()
            st.warning("Reset completato.")

    st.divider()

    # --- INPUT ORDINI ---
    with st.expander("📄 Crea Ordine", expanded=True):
        list_modelli = [
            "Diamantato Porsche", "Diamantato Ferrari", "Diamantato Audi", 
            "3-Mani Porsche", "3-Mani Ferrari", "3-Mani Audi", "3-Mani Mercedes"
        ]
        modello = st.selectbox("Modello", list_modelli)
        cod = st.text_input("Codice (es. ORD-01)")
        qta = st.number_input("Quantità", 50, 5000, 250)
        tempo = st.time_input("Scadenza", value=None)
        
        if st.button("Inserisci Ordine"):
            deadline_str = str(tempo) if tempo else "Fine Turno"
            st.session_state.ordine_mgr.add_ordine(cod, modello, qta, deadline_str)
            st.success("Ordine Creato!")
            st.rerun()

    st.divider()
    st.header("🏭 Linee (Live)")

    # --- MONITORAGGIO ---
    linee = st.session_state.linea_mgr.get_status()
    
    for l in linee:
        icon = "🟢" if l['stato'] == 'Attiva' else "🔴"
        with st.expander(f"{icon} {l['nome']}"):
            st.caption(f"Vincoli: {l['vincoli']}")
            if l['target_assegnato']:
                st.info(f"Lavora su: **{l['target_assegnato']}**")
            else:
                st.warning("In attesa di ordini")
            
            c1, c2 = st.columns(2)
            c1.metric("Buoni", l['pezzi_fatti'])
            c2.metric("Scarti", l['pezzi_scarti'])
            
            if st.button(f"+10 OK L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], buoni=10); st.rerun()
            if st.button(f"+1 Scarto L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], scarti=1); st.rerun()

            if l['stato'] == 'Attiva':
                if st.button(f"⛔ STOP L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Ferma", "Manuale"); st.rerun()
            else:
                if st.button(f"✅ START L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Attiva", ""); st.rerun()

# ==========================================
# AI SCHEDULATORE (MULTITASKING)
# ==========================================
st.title("🧠 AI Schedulatore (Ottimizzazione Parallela)")

# Prepariamo i dati per il prompt
dati_linee = []
for l in linee:
    dati_linee.append(f"- ID {l['id']} ({l['nome']}): Stato {l['stato']} | Attualmente fa: {l['target_assegnato']} | Vincoli: {l['vincoli']}")
str_linee = "\n".join(dati_linee)

dati_ordini = st.session_state.ordine_mgr.get_ordini()

# Chat
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Ciao! Sono pronto a schedulare più linee contemporaneamente per ottimizzare i flussi."}]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Es: 'Schedula la produzione per finire prima le Ferrari'")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # --- PROMPT AVANZATO PER MULTI-AZIONE ---
    full_prompt = f"""
    Sei il Responsabile Schedulazione (MES AI).
    
    SITUAZIONE IMPIANTO:
    {str_linee}
    
    ORDINI IN CODA:
    {dati_ordini}
    
    REGOLE DI OTTIMIZZAZIONE (Logica di pensiero):
    1. Se un ordine è grande (es. > 200 pezzi), SUDDIVIDILO su tutte le linee compatibili disponibili per finire prima (Parallelismo).
    2. Dai priorità agli ordini con quantità maggiore o scadenza vicina.
    3. VINCOLI:
       - L1: Solo Porsche/Mercedes.
       - L2, L3: Solo Ferrari/Audi.
       - L4, L5: Jolly (Usale per aiutare chi è in ritardo).
    
    DOMANDA UTENTE: {prompt}
    
    OUTPUT RICHIESTO:
    Se devi agire, rispondi SOLAMENTE con una LISTA JSON di comandi.
    Esempio: Dividere Ferrari su L2 e L3:
    [
      {{"comando": "assegna_linea", "linea_id": 2, "codice_ordine": "ORD-FERRARI"}},
      {{"comando": "assegna_linea", "linea_id": 3, "codice_ordine": "ORD-FERRARI"}}
    ]
    
    Se non devi agire, spiega il piano a parole.
    """
    
    with st.chat_message("assistant"):
        with st.spinner("Calcolo allocazione risorse..."):
            try:
                response = model.generate_content(full_prompt)
                risposta = response.text.strip()
                
                # Parsing Intelligente (Cerca liste JSON o oggetti singoli)
                json_exec = None
                
                # Caso Markdown
                if "```json" in risposta:
                    s = risposta.find("```json") + 7
                    e = risposta.find("```", s)
                    json_exec = risposta[s:e].strip()
                # Caso Lista JSON [...]
                elif risposta.startswith("[") and risposta.endswith("]"):
                    json_exec = risposta
                # Caso Oggetto Singolo {...}
                elif risposta.startswith("{") and risposta.endswith("}"):
                    json_exec = risposta
                
                if json_exec:
                    # Esegue tutte le azioni in un colpo solo
                    esito = esegui_azioni_ai(json_exec)
                    st.success(esito) # Mostra report completo
                    st.session_state.messages.append({"role": "assistant", "content": esito})
                    time.sleep(2)
                    st.rerun()
                else:
                    st.write(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    
            except Exception as e:
                st.error(f"Errore AI: {e}")
