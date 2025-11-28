import streamlit as st
import google.generativeai as genai
import json
import time
from backend import DatabaseManager, LineaManager, OrdineManager

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="MES AI Scheduler", page_icon="🏭", layout="wide")

try:
    # RECUPERA LA CHIAVE DAI SECRETS (Cloud)
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

# --- FUNZIONE AGENTE (ESECUTORE) ---
def esegui_azione_ai(azione_json):
    try:
        dati = json.loads(azione_json)
        comando = dati.get("comando")
        
        if comando == "assegna_linea":
            linea_id = dati.get("linea_id")
            codice = dati.get("codice_ordine")
            st.session_state.linea_mgr.assegna_commessa(linea_id, codice)
            return f"✅ SCHEDULAZIONE: Linea {linea_id} assegnata a {codice}."
            
        return "⚠️ Comando non riconosciuto."
    except Exception as e:
        return f"❌ Errore esecuzione: {e}"

# ==========================================
# BARRA LATERALE: CONTROLLO OPERATIVO
# ==========================================
with st.sidebar:
    st.header("🎛️ Pannello Operatore")
    
    # --- RESET GIORNATA ---
    with st.expander("🛠️ Manutenzione Dati"):
        if st.button("⚠️ RESETTA GIORNATA (Pulisci DB)"):
            st.session_state.ordine_mgr.reset_giornata()
            st.warning("Database resettato. Ricarica la pagina.")

    st.divider()

    # --- INPUT ORDINI ---
    with st.expander("📄 Crea Ordine", expanded=True):
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

    # --- MONITORAGGIO 5 LINEE ---
    linee = st.session_state.linea_mgr.get_status()
    
    for l in linee:
        status_color = "🟢" if l['stato'] == 'Attiva' else "🔴"
        
        with st.expander(f"{status_color} {l['nome']}"):
            st.caption(f"Vincoli: {l['vincoli']}")
            if l['target_assegnato']:
                st.info(f"Lavora su: **{l['target_assegnato']}**")
            
            # Controlli Produzione
            c1, c2 = st.columns(2)
            c1.metric("Buoni", l['pezzi_fatti'])
            c2.metric("Scarti", l['pezzi_scarti'])
            
            if st.button(f"+10 OK L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], buoni=10)
                st.rerun()
            if st.button(f"+1 Scarto L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], scarti=1)
                st.rerun()
            
            st.write("---")
            if l['stato'] == 'Attiva':
                motivo = st.text_input(f"Motivo Stop L{l['id']}", placeholder="Guasto...")
                if st.button(f"⛔ FERMA L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Ferma", motivo)
                    st.rerun()
            else:
                st.error(f"FERMA: {l['motivo_fermo']}")
                if st.button(f"✅ RIPARTI L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Attiva", "")
                    st.rerun()

# ==========================================
# CHATBOT SCHEDULATORE
# ==========================================
st.title("🧠 AI Schedulatore Produzione")

# 1. Recupero Dati per l'AI
dati_linee = []
for l in linee:
    dati_linee.append(f"- ID {l['id']} ({l['nome']}): Stato {l['stato']} | Prod: {l['pezzi_fatti']} | Scarti: {l['pezzi_scarti']} | Lavora su: {l['target_assegnato']} | Vincoli: {l['vincoli']}")
str_linee = "\n".join(dati_linee)

dati_ordini = st.session_state.ordine_mgr.get_ordini()

# 2. Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Ciao! Vedo i vincoli delle 5 linee e gli ordini. Chiedimi di ottimizzare la schedulazione."}]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

prompt = st.chat_input("Es: 'Come gestiamo l'ordine Ferrari se la linea 2 è ferma?'")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # 3. Prompt Schedulatore
    full_prompt = f"""
    Sei un Responsabile MES esperto in schedulazione.
    
    DATI IMPIANTO:
    {str_linee}
    
    ORDINI DA EVADERE:
    {dati_ordini}
    
    VINCOLI RIGIDI:
    - Linea 1: SOLO Porsche, Mercedes.
    - Linea 2 e 3: SOLO Ferrari, Audi.
    - Linea 4 e 5: JOLLY (Tutti).
    
    DOMANDA UTENTE: {prompt}
    
    ISTRUZIONI:
    - Se l'utente chiede un piano, proponi quali linee usare per quali ordini.
    - Se devi assegnare ufficialmente una linea, usa SOLO questo JSON:
      {{"comando": "assegna_linea", "linea_id": 1, "codice_ordine": "ORD-XX"}}
    """
    
    with st.chat_message("assistant"):
        with st.spinner("Calcolo ottimizzazione..."):
            try:
                response = model.generate_content(full_prompt)
                risposta = response.text.strip()
                
                # Parsing JSON (Fix robusto)
                json_exec = None
                if "```json" in risposta:
                    s = risposta.find("```json") + 7
                    e = risposta.find("```", s)
                    json_exec = risposta[s:e].strip()
                elif risposta.startswith("{") and risposta.endswith("}"):
                    json_exec = risposta
                
                if json_exec:
                    esito = esegui_azione_ai(json_exec)
                    st.success(esito)
                    st.session_state.messages.append({"role": "assistant", "content": esito})
                    time.sleep(2)
                    st.rerun()
                else:
                    st.write(risposta)
                    st.session_state.messages.append({"role": "assistant", "content": risposta})
                    
            except Exception as e:
                st.error(f"Errore AI: {e}")
