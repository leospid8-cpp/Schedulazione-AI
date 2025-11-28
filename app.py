import streamlit as st
import google.generativeai as genai
import json
import time
from backend import DatabaseManager, LineaManager, OrdineManager

# --- SETUP ---
st.set_page_config(page_title="MES Dashboard 5.0", page_icon="📊", layout="wide")

try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.0-flash')
except:
    st.error("Chiavi API mancanti.")
    st.stop()

if "db" not in st.session_state:
    st.session_state.db = DatabaseManager()
    st.session_state.linea_mgr = LineaManager(st.session_state.db)
    st.session_state.ordine_mgr = OrdineManager(st.session_state.db)

# --- ESECUTORE AZIONI ---
def esegui_azioni_ai(json_input):
    log = []
    try:
        dati = json.loads(json_input)
        if isinstance(dati, dict): dati = [dati] # Normalizza a lista
        
        for azione in dati:
            cmd = azione.get("comando")
            if cmd == "assegna_linea":
                lid = azione.get("linea_id")
                cod = azione.get("codice_ordine")
                st.session_state.linea_mgr.assegna_commessa(lid, cod)
                log.append(f"✅ Linea {lid} -> {cod}")
            elif cmd == "ferma_linea":
                lid = azione.get("linea_id")
                motivo = azione.get("motivo")
                st.session_state.linea_mgr.set_stato(lid, "Ferma", motivo)
                log.append(f"⛔ Linea {lid} STOP ({motivo})")
        
        return "\n".join(log) if log else "Nessuna azione."
    except Exception as e: return f"Errore: {e}"

# ==========================================
# DASHBOARD SUPERIORE (KPI GLOBALI)
# ==========================================
st.title("📊 Controllo Produzione Giornaliera")

# 1. Calcolo Dati Globali
tot_prodotti = st.session_state.linea_mgr.get_totale_produzione()
tot_target = st.session_state.ordine_mgr.get_totale_target()
ordini_raw = st.session_state.ordine_mgr.get_ordini()

# 2. Visualizzazione Grafica
col1, col2, col3 = st.columns(3)
col1.metric("📦 Pezzi Prodotti (Oggi)", tot_prodotti)
col2.metric("🎯 Target Totale", tot_target)
delta = tot_prodotti - tot_target
col3.metric("📉 Delta", delta, delta_color="normal")

# Barra di Progresso
if tot_target > 0:
    progress = min(tot_prodotti / tot_target, 1.0)
    st.progress(progress, text=f"Avanzamento Turno: {int(progress*100)}%")
else:
    st.info("Nessun ordine attivo. Crea ordini dalla barra laterale.")

st.divider()

# ==========================================
# BARRA LATERALE (CONTROLLI)
# ==========================================
with st.sidebar:
    st.header("🎛️ Operatore")
    
    with st.expander("🛠️ Reset"):
        if st.button("⚠️ NUOVO TURNO (Reset)"):
            st.session_state.ordine_mgr.reset_giornata()
            st.warning("Turno resettato.")
            st.rerun()

    with st.expander("📄 Nuovo Ordine", expanded=True):
        modelli = ["Porsche", "Ferrari", "Audi", "Mercedes"]
        mod = st.selectbox("Modello", modelli)
        cod = st.text_input("Codice", "ORD-01")
        qta = st.number_input("Qta", 100, 5000, 500)
        dead = st.time_input("Scadenza")
        if st.button("Inserisci"):
            st.session_state.ordine_mgr.add_ordine(cod, mod, qta, str(dead))
            st.rerun()

    st.divider()
    st.header("🏭 Dettaglio Linee")
    
    linee = st.session_state.linea_mgr.get_status()
    for l in linee:
        color = "🟢" if l['stato']=='Attiva' else "🔴"
        # Titolo Expander con Target specifico della linea
        titolo = f"{color} {l['nome']}"
        
        with st.expander(titolo):
            st.caption(f"Vincoli: {l['vincoli']}")
            
            # Mostra cosa sta facendo QUESTA linea vs il Totale
            if l['target_assegnato']:
                # Cerchiamo quanto è il target di quell'ordine
                target_ord = next((o['quantita'] for o in ordini_raw if o['codice'] == l['target_assegnato']), "N/A")
                st.info(f"🔨 Lavora su: **{l['target_assegnato']}**\n\n(Fatti {l['pezzi_fatti']} su {target_ord} tot ordine)")
            else:
                st.warning("💤 In attesa")

            c1, c2 = st.columns(2)
            c1.metric("Buoni", l['pezzi_fatti'])
            c2.metric("Scarti", l['pezzi_scarti'])
            
            if st.button(f"+10 OK L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], buoni=10); st.rerun()
            if st.button(f"+1 KO L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], scarti=1); st.rerun()
            
            if l['stato'] == 'Attiva':
                if st.button(f"STOP L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Ferma", "Manuale"); st.rerun()
            else:
                if st.button(f"START L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Attiva", ""); st.rerun()

# ==========================================
# CHATBOT INTELLIGENTE
# ==========================================
col_chat, col_kpi = st.columns([2, 1])

with col_chat:
    st.subheader("🤖 AI Factory Manager")
    
    # Prepariamo il contesto testuale
    context_lines = "\n".join([f"- L{l['id']} ({l['nome']}): Stato {l['stato']} | Fa: {l['target_assegnato']} | Prod: {l['pezzi_fatti']}" for l in linee])
    context_orders = st.session_state.ordine_mgr.get_ordini_text()
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Ciao! Sono pronto. Chiedimi informazioni sugli ordini o dimmi di schedulare la produzione."}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    prompt = st.chat_input("Es: 'Quali ordini abbiamo?' oppure 'Schedula la Ferrari'")

    if prompt:
        st.chat_message("user").write(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        full_prompt = f"""
        Sei il Responsabile Produzione.
        
        DATI LIVE:
        {context_lines}
        
        ORDINI ATTIVI:
        {context_orders}
        
        VINCOLI:
        L1: Porsche/Mercedes | L2,L3: Ferrari/Audi | L4,L5: Jolly.
        
        DOMANDA UTENTE: {prompt}
        
        ISTRUZIONI IMPORTANTI (Modalità Doppia):
        1. MODALITÀ INFORMATIVA: Se l'utente chiede "Quali ordini ci sono?", "Come vanno le linee?", "Specifiche ordini", RISPONDI SOLO A PAROLE. Spiega la situazione chiaramente. NON generare JSON.
        
        2. MODALITÀ AZIONE: Se l'utente chiede "Schedula", "Assegna", "Sposta", "Ferma", ALLORA genera una lista JSON per eseguire i comandi.
           Formato JSON: [{{"comando": "assegna_linea", "linea_id": 1, "codice_ordine": "..."}}]
        
        Sii intelligente: capisci se l'utente vuole sapere (parla) o fare (agisci).
        """
        
        with st.chat_message("assistant"):
            with st.spinner("Analisi..."):
                try:
                    response = model.generate_content(full_prompt)
                    answ = response.text.strip()
                    
                    # Logica di riconoscimento JSON
                    json_found = None
                    if "```json" in answ:
                        s = answ.find("```json")+7; e = answ.find("```", s)
                        json_found = answ[s:e].strip()
                    elif answ.startswith("[") and answ.endswith("]"):
                        json_found = answ
                    
                    if json_found:
                        # È un'azione!
                        report = esegui_azione_ai(json_found)
                        st.success(report)
                        st.session_state.messages.append({"role": "assistant", "content": report})
                        time.sleep(2); st.rerun()
                    else:
                        # È una risposta informativa
                        st.write(answ)
                        st.session_state.messages.append({"role": "assistant", "content": answ})
                        
                except Exception as e:
                    st.error(f"Errore: {e}")

# KPI Rapidi a destra della chat (Opzionale)
with col_kpi:
    st.info("📋 **Ordini Attivi**")
    if ordini_raw:
        for o in ordini_raw:
            st.write(f"**{o['codice']}**: {o['modello']}")
            st.progress(0, text=f"Target: {o['quantita']}")
    else:
        st.caption("Nessun ordine")
