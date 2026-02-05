import streamlit as st
import google.generativeai as genai
import json
import time
from datetime import date, timedelta

import pandas as pd
import altair as alt
import streamlit.components.v1 as components

from backend import DatabaseManager, LineaManager, OrdineManager


#
# configurazione
#
st.set_page_config(page_title="MES Dashboard 6.1", page_icon="📊", layout="wide")


#
# collegamento ai
#
def get_ai_keys():
    keys = []
    try:
        key1 = st.secrets.get("GOOGLE_API_KEY")
        if key1:
            keys.append(key1)
    except Exception:
        pass
    try:
        key2 = st.secrets.get("GOOGLE_API_KEY_2")
        if key2:
            keys.append(key2)
    except Exception:
        pass
    return keys


def make_model(api_key: str):
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("models/gemini-flash-latest")


def is_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return ("quota" in msg) or ("resource_exhausted" in msg) or ("429" in msg)


try:
    _ai_keys = get_ai_keys()
    model = make_model(_ai_keys[0]) if _ai_keys else None
    _ai_key_index = 0
except Exception:
    # L'app deve funzionare anche senza AI: mostro errore ma non blocco il MES.
    model = None
    _ai_keys = []
    _ai_key_index = 0
    st.sidebar.warning("AI non configurata (manca GOOGLE_API_KEY). La dashboard MES funziona lo stesso.")


#
# inizializzo db
#
if "db" not in st.session_state:
    st.session_state.db = DatabaseManager()
    st.session_state.linea_mgr = LineaManager(st.session_state.db)
    st.session_state.ordine_mgr = OrdineManager(st.session_state.db)

if "page" not in st.session_state:
    st.session_state.page = "home"  # home | linea
if "selected_linea_id" not in st.session_state:
    st.session_state.selected_linea_id = 1


#
# funzioni utili
#
def goto_home():
    st.session_state.page = "home"
    st.rerun()


def goto_linea(linea_id: int):
    st.session_state.page = "linea"
    st.session_state.selected_linea_id = int(linea_id)
    st.rerun()


def esegui_azioni_ai(json_input: str) -> str:
    """
    Applica SOLO azioni whitelisted (sicuro).
    """
    log = []
    try:
        dati = json.loads(json_input)
        if isinstance(dati, dict):
            dati = [dati]

        for azione in dati:
            cmd = azione.get("comando")

            if cmd == "assegna_linea":
                lid = int(azione.get("linea_id"))
                cod = str(azione.get("codice_ordine"))
                st.session_state.linea_mgr.assegna_commessa(lid, cod)
                log.append(f"✅ Linea {lid} -> Assegnata a {cod}")

            elif cmd == "ferma_linea":
                lid = int(azione.get("linea_id"))
                motivo = str(azione.get("motivo", "Manuale"))
                st.session_state.linea_mgr.set_stato(lid, "Ferma", motivo)
                log.append(f"⛔ Linea {lid} STOP ({motivo})")

            elif cmd == "avvia_linea":
                lid = int(azione.get("linea_id"))
                st.session_state.linea_mgr.set_stato(lid, "Attiva", "")
                log.append(f"▶️ Linea {lid} START")

        return "\n".join(log) if log else "Nessuna azione."
    except Exception as e:
        return f"Errore nel comando AI: {e}"


def voice_component():
    html = """
    <div style="font-family: sans-serif; padding: 6px;">
      <button id="startBtn">Start</button>
      <button id="stopBtn" disabled>Stop</button>
      <span id="status" style="margin-left:8px; color:#666;">Ready</span>
      <select id="voiceSelect" style="margin-left:8px;"></select>
      <div id="result" style="margin-top:8px; font-weight:600;"></div>
      <script>
        const statusEl = document.getElementById('status');
        const resultEl = document.getElementById('result');
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        const voiceSelect = document.getElementById('voiceSelect');

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
          statusEl.textContent = 'SpeechRecognition not supported in this browser.';
        } else {
          const rec = new SpeechRecognition();
          rec.lang = 'it-IT';
          rec.interimResults = false;
          rec.maxAlternatives = 1;

          startBtn.onclick = () => {
            rec.start();
            statusEl.textContent = 'Listening...';
            startBtn.disabled = true;
            stopBtn.disabled = false;
          };

          stopBtn.onclick = () => {
            rec.stop();
            statusEl.textContent = 'Stopped.';
            startBtn.disabled = false;
            stopBtn.disabled = true;
          };

          function sendValue(val) {
            if (window.Streamlit && window.Streamlit.setComponentValue) {
              window.Streamlit.setComponentValue(val);
            }
            window.parent.postMessage(
              { isStreamlitMessage: true, type: "streamlit:setComponentValue", value: val },
              "*"
            );
          }

          rec.onresult = (e) => {
            const text = e.results[0][0].transcript;
            resultEl.textContent = 'Text: ' + text;
            statusEl.textContent = 'Done.';
            sendValue({ text: text, voice: voiceSelect.value });
          };

          rec.onerror = (e) => {
            statusEl.textContent = 'Error: ' + e.error;
            startBtn.disabled = false;
            stopBtn.disabled = true;
          };

          rec.onend = () => {
            startBtn.disabled = false;
            stopBtn.disabled = true;
          };
        }

        function listVoices() {
          const voices = window.speechSynthesis.getVoices();
          voiceSelect.innerHTML = '';
          voices.forEach((v, idx) => {
            const opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = `${v.name} (${v.lang})`;
            voiceSelect.appendChild(opt);
          });
          if (voices.length > 0) {
            sendValue({ voice: voiceSelect.value, text: '' });
          }
        }

        if (window.speechSynthesis) {
          listVoices();
          window.speechSynthesis.onvoiceschanged = listVoices;
        }

        voiceSelect.onchange = () => {
          sendValue({ voice: voiceSelect.value, text: '' });
        };
      </script>
    </div>
    """
    return components.html(html, height=120)


def enhance_tts_text(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    t = t.replace("...", ". ")
    t = t.replace(";", ". ")
    t = t.replace("!", "! ")
    t = t.replace("?", "? ")
    t = t.replace(".", ". ")
    t = t.replace(",", ", ")
    t = " ".join(t.split())
    return t


def speak_in_browser(text: str, rate: float = 1.0, pitch: float = 1.0, volume: float = 1.0, voice_idx: int | None = None):
    if not text:
        return
    safe_text = enhance_tts_text(text)
    html = f"""
    <script>
      const msg = new SpeechSynthesisUtterance({json.dumps(safe_text)});
      msg.lang = 'it-IT';
      msg.rate = {rate};
      msg.pitch = {pitch};
      msg.volume = {volume};
      const voices = window.speechSynthesis.getVoices();
      const idx = {voice_idx if voice_idx is not None else 'null'};
      if (voices && voices.length && idx !== null && voices[idx]) {{
        msg.voice = voices[idx];
      }}
      window.speechSynthesis.speak(msg);
    </script>
    """
    components.html(html, height=0)


def build_range(range_key: str):
    """
    Ritorna (start_day, end_day) come date.
    """
    today = date.today()

    if range_key == "1g":
        return today, today
    if range_key == "7g":
        return today - timedelta(days=6), today
    if range_key == "1m":
        return today - timedelta(days=29), today
    if range_key == "1a":
        return today - timedelta(days=364), today

    # fallback
    return today - timedelta(days=6), today


def produzione_df(linea_id: int, start_day: date, end_day: date) -> pd.DataFrame:
    """
    Ritorna dataframe completo (tutti i giorni nel range, anche se 0):
    giorno, ok, ko, target_ok
    """
    prod = st.session_state.linea_mgr.get_produzione_giornaliera(linea_id, start_day, end_day)
    tgt = st.session_state.linea_mgr.get_obiettivi_giornalieri(linea_id, start_day, end_day)

    df_prod = pd.DataFrame(prod) if prod else pd.DataFrame(columns=["giorno", "ok", "ko"])
    df_tgt = pd.DataFrame(tgt) if tgt else pd.DataFrame(columns=["giorno", "target_ok"])

    # Normalizza date
    if not df_prod.empty:
        df_prod["giorno"] = pd.to_datetime(df_prod["giorno"]).dt.date
    if not df_tgt.empty:
        df_tgt["giorno"] = pd.to_datetime(df_tgt["giorno"]).dt.date

    # Costruisci tutti i giorni nel range
    all_days = pd.date_range(start=start_day, end=end_day, freq="D").date
    df_all = pd.DataFrame({"giorno": all_days})

    df = df_all.merge(df_prod, on="giorno", how="left").merge(df_tgt, on="giorno", how="left")
    df["ok"] = df["ok"].fillna(0).astype(int)
    df["ko"] = df["ko"].fillna(0).astype(int)
    df["target_ok"] = df["target_ok"].fillna(0).astype(int)

    return df


def grafico_produzione(df: pd.DataFrame):
    """
    Bar OK/KO + Line target.
    """
    df_chart = df.copy()
    df_chart["giorno"] = pd.to_datetime(df_chart["giorno"])

    # formato lungo per bar OK/KO
    df_long = df_chart.melt(
        id_vars=["giorno", "target_ok"],
        value_vars=["ok", "ko"],
        var_name="tipo",
        value_name="qta",
    )

    bars = (
        alt.Chart(df_long)
        .mark_bar()
        .encode(
            x=alt.X("giorno:T", title="Giorno"),
            y=alt.Y("qta:Q", title="Pezzi"),
            color=alt.Color("tipo:N", title="Tipo"),
            tooltip=[
                alt.Tooltip("giorno:T", title="Giorno"),
                alt.Tooltip("tipo:N", title="Tipo"),
                alt.Tooltip("qta:Q", title="Pezzi"),
            ],
        )
    )

    line = (
        alt.Chart(df_chart)
        .mark_line()
        .encode(
            x=alt.X("giorno:T"),
            y=alt.Y("target_ok:Q", title=""),
            tooltip=[
                alt.Tooltip("giorno:T", title="Giorno"),
                alt.Tooltip("target_ok:Q", title="Obiettivo"),
            ],
        )
    )

    return (bars + line).properties(height=340).interactive()


#
# pagine
#
def render_home():
    global model, _ai_key_index
    st.title("📊 Controllo Produzione Giornaliera")

    # totali
    tot_prodotti = st.session_state.linea_mgr.get_totale_produzione()
    tot_target = st.session_state.ordine_mgr.get_totale_target()
    ordini_raw = st.session_state.ordine_mgr.get_ordini()

    progress_dict = st.session_state.linea_mgr.get_produzione_per_ordine()

    # metriche
    col1, col2, col3 = st.columns(3)
    col1.metric("📦 Pezzi Fatti Oggi", tot_prodotti)
    col2.metric("🎯 Obiettivo Totale", tot_target)
    mancanti = max(tot_target - tot_prodotti, 0)
    col3.metric("📉 Pezzi Mancanti", mancanti)

    # avanzamento
    if tot_target > 0:
        prog_generale = min(tot_prodotti / tot_target, 1.0)
        st.progress(prog_generale, text=f"Avanzamento Turno: {int(prog_generale*100)}%")
    else:
        st.info("Nessun ordine. Usa la barra a sinistra per crearne uno.")

    st.divider()

    # Sidebar
    with st.sidebar:
        st.header("🎛️ Operatore")

        # reset
        with st.expander("🛠️ Reset Turno"):
            if st.button("⚠️ NUOVO TURNO (Cancella Ordini + Reset Contatori)"):
                st.session_state.ordine_mgr.reset_giornata()
                st.warning("Turno resettato.")
                st.rerun()

        # creazione ordini
        with st.expander("📄 Nuovo Ordine", expanded=True):
            modelli = ["Porsche", "Ferrari", "Audi", "Mercedes"]
            mod = st.selectbox("Modello", modelli)
            cod = st.text_input("Codice", "ORD-01")
            qta = st.number_input("Qta", 1, 5000, 500)
            dead = st.time_input("Scadenza")
            if st.button("Inserisci"):
                st.session_state.ordine_mgr.add_ordine(cod, mod, qta, str(dead))
                st.rerun()

        st.divider()
        st.header("🏭 Linee produttive")

        linee = st.session_state.linea_mgr.get_status()
        st.caption("Clicca su una linea per aprire la pagina dedicata.")
        for l in linee:
            color = "🟢" if l["stato"] == "Attiva" else "🔴"
            if st.button(f"{color} {l['nome']}", key=f"nav_{l['id']}"):
                goto_linea(l["id"])

        st.divider()
        st.subheader("⚡ Controlli rapidi")

        for l in linee:
            color = "🟢" if l["stato"] == "Attiva" else "🔴"
            titolo = f"{color} {l['nome']}"

            with st.expander(titolo):
                st.caption(f"Vincoli: {l['vincoli']}")

                # avanzamento ordine
                if l["target_assegnato"]:
                    ord_code = l["target_assegnato"]
                    target_ord = next((o["quantita"] for o in ordini_raw if o["codice"] == ord_code), 0)
                    fatti_totali = progress_dict.get(ord_code, 0)

                    st.info(f"🔨 Lavora su: **{ord_code}**")
                    perc = int((fatti_totali / target_ord * 100)) if target_ord > 0 else 0
                    st.write(f"Avanzamento Ordine: **{fatti_totali}** / {target_ord} ({perc}%)")
                    st.progress(min(perc / 100, 1.0))
                else:
                    st.warning("💤 In attesa")

                # contatori linea
                c1, c2 = st.columns(2)
                c1.metric("Buoni (Qui)", l["pezzi_fatti"])
                c2.metric("Scarti (Qui)", l["pezzi_scarti"])

                # pulsanti produzione manuale
                if st.button(f"+10 OK L{l['id']}", key=f"ok_{l['id']}"):
                    st.session_state.linea_mgr.update_counts(l["id"], buoni=10)
                    st.rerun()

                if st.button(f"+1 KO L{l['id']}", key=f"ko_{l['id']}"):
                    st.session_state.linea_mgr.update_counts(l["id"], scarti=1)
                    st.rerun()

                # start/stop
                if l["stato"] == "Attiva":
                    if st.button(f"STOP L{l['id']}", key=f"stop_{l['id']}"):
                        st.session_state.linea_mgr.set_stato(l["id"], "Ferma", "Manuale")
                        st.rerun()
                else:
                    if st.button(f"START L{l['id']}", key=f"start_{l['id']}"):
                        st.session_state.linea_mgr.set_stato(l["id"], "Attiva", "")
                        st.rerun()

    # Main: chat + KPI
    col_chat, col_kpi = st.columns([2, 1])

    # CHAT
    with col_chat:
        st.subheader("🤖 AI Factory Manager")

        if model is None:
            st.info("AI non disponibile: configura GOOGLE_API_KEY in secrets per usare il chatbot.")
        else:
            linee = st.session_state.linea_mgr.get_status()
            context_lines = "\n".join(
                [f"- L{l['id']} ({l['nome']}): Stato {l['stato']} | Ordine: {l['target_assegnato']} | Prod: {l['pezzi_fatti']}"
                 for l in linee]
            )
            context_orders = st.session_state.ordine_mgr.get_ordini_text()

            if "messages" not in st.session_state:
                st.session_state.messages = [{"role": "assistant", "content": "Ciao! Gestisco la schedulazione. Chiedimi di assegnare gli ordini."}]

            for i, msg in enumerate(st.session_state.messages):
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
                    if msg["role"] == "assistant":
                        if st.button("\U0001F3A7", key=f"tts_btn_{i}"):
                            rate = st.session_state.get("voice_rate", 1.0)
                            pitch = st.session_state.get("voice_pitch", 1.0)
                            volume = st.session_state.get("voice_volume", 1.0)
                            voice_idx = st.session_state.get("voice_idx")
                            speak_in_browser(msg["content"], rate=rate, pitch=pitch, volume=volume, voice_idx=voice_idx)
            used_voice = False
            voice_text = ""
            tts_enabled = False
            with st.expander("Voce (beta)", expanded=False):
                tts_enabled = st.checkbox("Leggi risposta ad alta voce", value=True, key="voice_tts")
                rate = st.slider("Velocita voce", min_value=0.7, max_value=1.3, value=1.0, step=0.05, key="voice_rate")
                pitch = st.slider("Tono voce", min_value=0.8, max_value=1.2, value=1.0, step=0.05, key="voice_pitch")
                volume = st.slider("Volume voce", min_value=0.5, max_value=1.0, value=1.0, step=0.05, key="voice_volume")
                voice_payload = voice_component()
                voice_text = ""
                voice_idx = None
                if isinstance(voice_payload, dict):
                    if "voice" in voice_payload:
                        try:
                            voice_idx = int(voice_payload["voice"])
                        except Exception:
                            voice_idx = None
                    if "text" in voice_payload and isinstance(voice_payload["text"], str):
                        voice_text = voice_payload["text"]
                elif isinstance(voice_payload, str):
                    voice_text = voice_payload
                if voice_idx is not None:
                    st.session_state.voice_idx = voice_idx
                elif "voice_idx" in st.session_state:
                    pass
                if voice_text:
                    used_voice = True

            prompt = st.chat_input("Es: 'Schedula gli ordini sulle linee migliori'")
            if not prompt and used_voice:
                prompt = voice_text

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

ISTRUZIONI:
1) Se chiedono INFO: rispondi a parole.
2) Se chiedono AZIONI (schedula, sposta, ferma, avvia): genera SOLO JSON.
   Formato JSON: [{{"comando":"assegna_linea","linea_id":1,"codice_ordine":"ORD-01"}}]
   Altri comandi ammessi: "ferma_linea" (linea_id, motivo), "avvia_linea" (linea_id).
                """

                with st.chat_message("assistant"):
                    with st.spinner("Analisi..."):
                        try:
                            try:
                                response = model.generate_content(full_prompt)
                            except Exception as e:
                                if is_quota_error(e) and _ai_key_index + 1 < len(_ai_keys):
                                    _ai_key_index += 1
                                    model = make_model(_ai_keys[_ai_key_index])
                                    response = model.generate_content(full_prompt)
                                else:
                                    raise
                            answ = response.text.strip()

                            json_found = None
                            if "```json" in answ:
                                s = answ.find("```json") + 7
                                e = answ.find("```", s)
                                json_found = answ[s:e].strip()
                            elif answ.startswith("[") and answ.endswith("]"):
                                json_found = answ

                            if json_found:
                                report = esegui_azioni_ai(json_found)
                                st.success(report)
                                st.session_state.messages.append({"role": "assistant", "content": report})
                                if used_voice and tts_enabled:
                                    speak_in_browser(report, rate=rate, pitch=pitch, volume=volume, voice_idx=voice_idx)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.write(answ)
                                st.session_state.messages.append({"role": "assistant", "content": answ})
                                if used_voice and tts_enabled:
                                    speak_in_browser(answ, rate=rate, pitch=pitch, volume=volume, voice_idx=voice_idx)
                        except Exception as e:
                            st.error(f"Errore AI: {e}")

    # KPI ORDINI
    with col_kpi:
        st.info("📋 **Stato Avanzamento Ordini**")
        if ordini_raw:
            for o in ordini_raw:
                codice = o["codice"]
                target = o["quantita"]
                fatti = progress_dict.get(codice, 0)
                perc = int((fatti / target) * 100) if target > 0 else 0

                st.write(f"**{codice}**: {o['modello']}")
                st.caption(f"{fatti} su {target} pz ({perc}%)")
                st.progress(min(perc / 100, 1.0))
                st.write("---")
        else:
            st.caption("Nessun ordine attivo.")


def render_linea_detail(linea_id: int):
    linea = st.session_state.linea_mgr.get_linea(linea_id)
    if not linea:
        st.error("Linea non trovata.")
        if st.button("⬅️ Torna alla Home"):
            goto_home()
        return

    # Header + back
    top_left, top_right = st.columns([1, 3])
    with top_left:
        if st.button("⬅️ Home"):
            goto_home()
    with top_right:
        st.title(f"📈 Dettaglio {linea['nome']}")

    st.caption(f"Vincoli: {linea['vincoli']}")

    # stato + ordine assegnato
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stato", linea["stato"])
    c2.metric("Ordine assegnato", linea["target_assegnato"] if linea["target_assegnato"] else "—")
    c3.metric("Buoni (contatore live)", linea["pezzi_fatti"])
    c4.metric("Scarti (contatore live)", linea["pezzi_scarti"])

    st.divider()

    # Range selector
    col_r1, col_r2 = st.columns([2, 3])
    with col_r1:
        range_key = st.radio("Range tempo", ["1g", "7g", "1m", "1a", "custom"], horizontal=True)
    with col_r2:
        if range_key == "custom":
            d1, d2 = st.date_input("Seleziona intervallo", value=(date.today() - timedelta(days=6), date.today()))
            start_day, end_day = d1, d2
        else:
            start_day, end_day = build_range(range_key)
            st.write(f"Intervallo: **{start_day} → {end_day}**")

    df = produzione_df(linea_id, start_day, end_day)

    # KPI su range
    total_ok = int(df["ok"].sum())
    total_ko = int(df["ko"].sum())
    total_target = int(df["target_ok"].sum())
    days = max(1, len(df))
    avg_ok = total_ok / days

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("OK nel range", total_ok)
    k2.metric("KO nel range", total_ko)
    k3.metric("Media OK/giorno", f"{avg_ok:.1f}")
    if total_target > 0:
        k4.metric("Target nel range", total_target, delta=f"{total_ok - total_target}")
    else:
        k4.metric("Target nel range", "—")

    st.subheader("Produzione vs Obiettivo")
    st.altair_chart(grafico_produzione(df), use_container_width=True)

    st.divider()

    # Imposta obiettivo
    st.subheader("🎯 Imposta obiettivo giornaliero (opzionale)")
    st.caption("Serve per il confronto nel grafico. Se non lo imposti, l'obiettivo resta 0.")
    col_t1, col_t2 = st.columns([1, 2])
    with col_t1:
        target_day = st.number_input("Target OK al giorno", min_value=0, max_value=200000, value=0, step=10)
    with col_t2:
        if st.button("Applica target al range selezionato"):
            st.session_state.linea_mgr.set_obiettivo_giornaliero_range(linea_id, start_day, end_day, int(target_day))
            st.success("Obiettivo salvato.")
            st.rerun()

    st.divider()

    # Tabella dettaglio
    st.subheader("📅 Dettaglio giornaliero")
    st.dataframe(df, use_container_width=True)


#
# cambio pagina
#
if st.session_state.page == "home":
    render_home()
else:
    render_linea_detail(st.session_state.selected_linea_id)




