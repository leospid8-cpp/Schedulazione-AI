import streamlit as st
import google.generativeai as genai
import json
import time
from backend import DatabaseManager, LineaManager, OrdineManager

# imposta pagina
st.set_page_config(page_title="MES Dashboard 6.0", page_icon="📊", layout="wide")

# collegamento ai
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    model = genai.GenerativeModel('models/gemini-2.0-flash')
except:
    st.error("Occhio! Mancano le chiavi API nei secrets.")
    st.stop() # Blocco tutto se non ho le chiavi

# avvio db
if "db" not in st.session_state:
    st.session_state.db = DatabaseManager()
    st.session_state.linea_mgr = LineaManager(st.session_state.db)
    st.session_state.ordine_mgr = OrdineManager(st.session_state.db)

# esecuzione comandi ai
def esegui_azioni_ai(json_input):
    log = []
    try:
        # legge comandi JSON per ai
        dati = json.loads(json_input)
        if isinstance(dati, dict): dati = [dati] # Se è uno solo lo metto in lista
        
        for azione in dati:
            cmd = azione.get("comando")
            # se ai assegna linea
            if cmd == "assegna_linea":
                lid = azione.get("linea_id")
                cod = azione.get("codice_ordine")
                st.session_state.linea_mgr.assegna_commessa(lid, cod)
                log.append(f"✅ Linea {lid} -> Assegnata a {cod}")
            # se ferma una linea 
            elif cmd == "ferma_linea":
                lid = azione.get("linea_id")
                motivo = azione.get("motivo")
                st.session_state.linea_mgr.set_stato(lid, "Ferma", motivo)
                log.append(f"⛔ Linea {lid} STOP ({motivo})")
        
        return "\n".join(log) if log else "Nessuna azione."
    except Exception as e: return f"Errore nel comando AI: {e}"

#dashboard 
st.title("📊 Controllo Produzione Giornaliera")

# totali
tot_prodotti = st.session_state.linea_mgr.get_totale_produzione()
tot_target = st.session_state.ordine_mgr.get_totale_target()
ordini_raw = st.session_state.ordine_mgr.get_ordini()

# dizzionario magico
progress_dict = st.session_state.linea_mgr.get_produzione_per_ordine()

# disegno metriche principali
col1, col2, col3 = st.columns(3)
col1.metric("📦 Pezzi Fatti Oggi", tot_prodotti)
col2.metric("🎯 Obiettivo Totale", tot_target)
delta = tot_prodotti - tot_target
col3.metric("📉 Pezzi Mancanti", delta, delta_color="normal")

# barra avanzamento
if tot_target > 0:
    prog_generale = min(tot_prodotti / tot_target, 1.0)
    st.progress(prog_generale, text=f"Avanzamento Turno: {int(prog_generale*100)}%")
else:
    st.info("Nessun ordine. Usa la barra a sinistra per crearne uno.")

st.divider()

# barra laterale
with st.sidebar:
    st.header("🎛️ Operatore")
    
    # reset database
    with st.expander("🛠️ Reset Turno"):
        if st.button("⚠️ NUOVO TURNO (Cancella Tutto)"):
            st.session_state.ordine_mgr.reset_giornata()
            st.warning("Turno resettato.")
            st.rerun() # Ricarico la pagina

    # modulo per creare nuovi ordini
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
    st.header("🏭 Stato Linee")
    
    # Prendo lo stato delle 5 linee
    linee = st.session_state.linea_mgr.get_status()
    for l in linee:
        # Scelgo il pallino verde o rosso
        color = "🟢" if l['stato']=='Attiva' else "🔴"
        titolo = f"{color} {l['nome']}"
        
        with st.expander(titolo):
            st.caption(f"Vincoli: {l['vincoli']}")
            
            # avanzamento visualizzazione
            if l['target_assegnato']:
                ord_code = l['target_assegnato']
                
                # cerco quanto dobbiamo fare in totale per questo ordine
                target_ord = next((o['quantita'] for o in ordini_raw if o['codice'] == ord_code), 0)
                
                # cerco quanto abbiamo fatto IN TOTALE su tutte le linee per questo ordine
                fatti_totali = progress_dict.get(ord_code, 0)
                
                st.info(f"🔨 Lavora su: **{ord_code}**")
                
                # mostro il progresso condiviso
                perc = int((fatti_totali / target_ord * 100)) if target_ord > 0 else 0
                st.write(f"Avanzamento Ordine: **{fatti_totali}** / {target_ord} ({perc}%)")
                st.progress(min(perc/100, 1.0))
            else:
                st.warning("💤 In attesa")

            # contatori specifici
            c1, c2 = st.columns(2)
            c1.metric("Buoni (Qui)", l['pezzi_fatti'])
            c2.metric("Scarti (Qui)", l['pezzi_scarti'])
            
            # pulsanti per produzione
            if st.button(f"+10 OK L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], buoni=10); st.rerun()
            if st.button(f"+1 KO L{l['id']}"):
                st.session_state.linea_mgr.update_counts(l['id'], scarti=1); st.rerun()
            
            # start/stop
            if l['stato'] == 'Attiva':
                if st.button(f"STOP L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Ferma", "Manuale"); st.rerun()
            else:
                if st.button(f"START L{l['id']}"):
                    st.session_state.linea_mgr.set_stato(l['id'], "Attiva", ""); st.rerun()

# chat bot KPI
col_chat, col_kpi = st.columns([2, 1])

# chat bot
with col_chat:
    st.subheader("🤖 AI Factory Manager")
    
    # dati par ai
    context_lines = "\n".join([f"- L{l['id']} ({l['nome']}): Stato {l['stato']} | Fa: {l['target_assegnato']} | Prod: {l['pezzi_fatti']}" for l in linee])
    context_orders = st.session_state.ordine_mgr.get_ordini_text()
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Ciao! Gestisco la schedulazione. Chiedimi di assegnare gli ordini."}]

    # stampo la chat
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    # casella di testo
    prompt = st.chat_input("Es: 'Schedula gli ordini sulle linee migliori'")

    if prompt:
        st.chat_message("user").write(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # prompt per ai
        full_prompt = f"""
        Sei il Responsabile Produzione.
        
        DATI LIVE:
        {context_lines}
        
        ORDINI ATTIVI:
        {context_orders}
        
        VINCOLI:
        L1: Porsche/Mercedes | L2,L3: Ferrari/Audi | L4,L5: Jolly.
        
        DOMANDA UTENTE: {prompt}
        
        ISTRUZIONI:
        1. Se chiedono INFO: Rispondi a parole.
        2. Se chiedono AZIONI (schedula, sposta): Genera JSON.
           Formato JSON: [{{"comando": "assegna_linea", "linea_id": 1, "codice_ordine": "..."}}]
        """
        
        with st.chat_message("assistant"):
            with st.spinner("Analisi..."):
                try:
                    response = model.generate_content(full_prompt)
                    answ = response.text.strip()
                    
                    # controllo codice JSON nella risposta
                    json_found = None
                    if "```json" in answ:
                        s = answ.find("```json")+7; e = answ.find("```", s)
                        json_found = answ[s:e].strip()
                    elif answ.startswith("[") and answ.endswith("]"):
                        json_found = answ
                    
                    if json_found:
                        report = esegui_azioni_ai(json_found)
                        st.success(report)
                        st.session_state.messages.append({"role": "assistant", "content": report})
                        time.sleep(2); st.rerun()
                    else:
                        st.write(answ)
                        st.session_state.messages.append({"role": "assistant", "content": answ})
                        
                except Exception as e:
                    st.error(f"Errore: {e}")

# KPI
with col_kpi:
    st.info("📋 **Stato Avanzamento Ordini**")
    if ordini_raw:
        for o in ordini_raw:
            codice = o['codice']
            target = o['quantita']
            # totale
            fatti = progress_dict.get(codice, 0)
            
            # calcolo percentuale
            perc = int((fatti / target) * 100) if target > 0 else 0
            
            st.write(f"**{codice}**: {o['modello']}")
            st.caption(f"{fatti} su {target} pz ({perc}%)")
            st.progress(min(perc/100, 1.0))
            st.write("---")
    else:
        st.caption("Nessun ordine attivo.")
