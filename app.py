import streamlit as st
import google.generativeai as genai
import json
import time
from backend import DatabaseManager, LineaManager, OrdineManager

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="MES AI Scheduler", page_icon="🏭", layout="wide")

try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.0-flash')
except:
    st.error("Chiavi API mancanti.")
    st.stop()

# --- INIZIALIZZAZIONE ---
if "db" not in st.session_state:
    db = DatabaseManager()
    st.session_state.linea_mgr = LineaManager(db)
    st.session_state.ordine_mgr = OrdineManager(db)

# ==========================================
# BARRA LATERALE: IL CUORE PRODUTTIVO
# ==========================================
with st.sidebar:
    st.header("🎛️ Pannello Operatore")
    
    # --- SEZIONE A: INPUT ORDINI ---
    with st.expander("📄 Crea Ordine Giornaliero", expanded=True):
        list_modelli = [
            "Diamantato Porsche", "Diamantato Ferrari", "Diamantato Audi", 
            "3-Mani Porsche", "3-Mani Ferrari", "3-Mani Audi", "3-Mani Mercedes"
        ]
        modello = st.selectbox("Modello", list_modelli)
        cod = st.text_input("Codice (es. ORD-01)")
        qta = st.number_input("Target Pz", 100, 5000, 500)
        tempo = st.time_input("Scadenza", value=None)
        
        if st.button("Inserisci Ordine"):
            deadline_str = str(tempo) if tempo else "Fine Turno"
            st.session_state.ordine_mgr.add_ordine(cod, modello, qta, deadline_str)
            st.success("Ordine Creato!")
            st.rerun()

    st.divider()
    st.header("🏭 Stato Linee (Live)")

    # --- SEZIONE B: MONITORAGGIO 5 LINEE ---
    # Recuperiamo i dati aggiornati
    linee = st.session_state.linea_mgr.get_status()
    
    for l in linee:
        # Colore pallino stato
        status_color = "🟢" if l['stato'] == 'Attiva' else "🔴"
        
        with st.expander(f"{status_color} {l['nome']}"):
            st.caption(f"Vincoli: {l['vincoli']}")
            
            # Controlli Produzione
            c1, c2 = st.columns(2)
            c1.metric("Buoni", l['pezzi_fatti'])
            c2.metric("Scarti", l['pezzi_scarti'])
            
            # Pulsanti rapidi produzione
            if st.button(f"+10 OK L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], buoni=10)
                st.rerun()
            if st.button(f"+1 Scarto L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], scarti=1)
                st.rerun()
            
            # Gestione Guasti
            st.write("---")
            if l['stato'] == 'Attiva':
                motivo = st.text_input(f"Motivo Stop L{l['id']}", placeholder="Es. Guasto robot")
                if st.button(f"⛔ FERMA L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Ferma", motivo)
                    st.rerun()
            else:
                st.error(f"FERMA: {l['motivo_fermo']}")
                if st.button(f"✅ RIPARTI L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Attiva", "")
                    st.rerun()

    st.divider()
    if st.button("⚠️ RESET TOTALE GIORNATA"):
        st.session_state.ordine_mgr.reset_giornata()
        st.warning("Database pulito. Ricarica la pagina.")

# ==========================================
# CHATBOT SCHEDULATORE (CENTRALE)
# ==========================================
st.title("🧠 AI Schedulatore Produzione")

# 1. Recupero Dati Completi per l'AI
dati_linee = []
for l in linee:
    dati_linee.append(f"- ID {l['id']} ({l['nome']}): Stato {l['stato']} | Prod: {l['pezzi_fatti']} | Scarti: {l['pezzi_scarti']} | Vincoli: {l['vincoli']}")
str_linee = "\n".join(dati_linee)

dati_ordini = st.session_state.ordine_mgr.get_ordini()

# 2. Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Ciao! Vedo i vincoli delle 5 linee e gli ordini. Chiedimi di ottimizzare la schedulazione."}]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Es: 'Abbiamo un problema sulla linea 2, come riorganizziamo gli ordini Ferrari?'")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # 3. Prompt Ingegneristico
    full_prompt = f"""
    Sei un Responsabile di Produzione (MES) esperto in schedulazione.
    
    OBIETTIVO:
    Organizzare la produzione dei cerchioni rispettando TASSATIVAMENTE i vincoli delle linee.
    
    DATI IMPIANTO (Real-time):
    {str_linee}
    
    ORDINI DA EVADERE (Target):
    {dati_ordini}
    
    VINCOLI RIGIDI DA RISPETTARE:
    - Linea 1: Fa SOLO Porsche e Mercedes.
    - Linea 2 e 3: Fanno SOLO Ferrari e Audi.
    - Linea 4 e 5: Sono JOLLY (possono fare tutto).
    
    DOMANDA UTENTE: {prompt}
    
    ISTRUZIONI:
    - Analizza gli ordini e assegnali alle linee corrette.
    - Se una linea è FERMA (es. Linea 2), devi spostare il suo carico sulle linee JOLLY (4 o 5).
    - Tieni conto degli scarti: se una linea ha molti scarti, suggerisci di rallentarla o controllarla.
    - Rispondi con un piano d'azione schematico e chiaro.
    """
    
    with st.chat_message("assistant"):
        with st.spinner("Calcolo ottimizazzione flussi..."):
            try:
                response = model.generate_content(full_prompt)
                st.write(response.text)
                st.session_state.messages.append({"role": "assistant", "content": response.text})
            except Exception as e:
                st.error(f"Errore AI: {e}")