import streamlit as st
import google.generativeai as genai
import json
import time
from datetime import date, timedelta

import pandas as pd
import altair as alt
import streamlit.components.v1 as components

from backend import DatabaseManager, LineaManager, OrdineManager

try:
    from backend import SchedulerManager
except ImportError:
    SchedulerManager = None


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

if "scheduler_mgr" not in st.session_state:
    if SchedulerManager is None:
        st.session_state.scheduler_mgr = None
        st.session_state.scheduler_init_error = (
            "Backend deploy non allineato: classe SchedulerManager non trovata."
        )
    else:
        try:
            st.session_state.scheduler_mgr = SchedulerManager(st.session_state.db)
            st.session_state.scheduler_init_error = ""
        except Exception as e:
            st.session_state.scheduler_mgr = None
            st.session_state.scheduler_init_error = str(e)

if "page" not in st.session_state:
    st.session_state.page = "home"  # home | linea
if "selected_linea_id" not in st.session_state:
    st.session_state.selected_linea_id = 1
if "app_section" not in st.session_state:
    st.session_state.app_section = "home"  # home | scada | graphs | planner | linea_detail


#
# funzioni utili
#
def goto_home():
    st.session_state.page = "home"
    st.session_state.app_section = "home"
    st.rerun()


def goto_linea(linea_id: int):
    st.session_state.page = "linea"
    st.session_state.selected_linea_id = int(linea_id)
    st.session_state.app_section = "linea_detail"
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


def parse_date_range_input(value):
    """
    Normalizza l'output di st.date_input in una coppia (start_day, end_day).
    """
    if isinstance(value, (tuple, list)):
        if len(value) >= 2:
            return value[0], value[1]
        if len(value) == 1:
            return value[0], value[0]
    return value, value


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


def grafico_schedulazione_tasks(df_tasks: pd.DataFrame, all_lines: list[str] | None = None):
    if df_tasks.empty:
        return None

    chart_df = df_tasks.copy()
    chart_df["line_id"] = chart_df["line_id"].astype(str)
    chart_df["code"] = chart_df["code"].astype(str)

    if all_lines:
        y_domain = sorted({str(x) for x in all_lines})
    else:
        y_domain = sorted(chart_df["line_id"].unique())

    unique_lines = max(1, len(y_domain))
    height = max(220, unique_lines * 26)

    return (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("start_min:Q", title="Timeline (minuti)"),
            x2="end_min:Q",
            y=alt.Y("line_id:N", title="Linea", sort=y_domain, scale=alt.Scale(domain=y_domain)),
            color=alt.Color("code:N", title="Codice"),
            tooltip=[
                alt.Tooltip("order_id:N", title="Ordine"),
                alt.Tooltip("code:N", title="Codice"),
                alt.Tooltip("line_id:N", title="Linea"),
                alt.Tooltip("qty:Q", title="Qta"),
                alt.Tooltip("setup_min:Q", title="Setup min"),
                alt.Tooltip("start_min:Q", title="Start min"),
                alt.Tooltip("end_min:Q", title="End min"),
                alt.Tooltip("tardy_min:Q", title="Ritardo min"),
            ],
        )
        .properties(height=height)
        .interactive()
    )


def apply_enterprise_theme():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

:root {
  --bg-1: #eef3f9;
  --bg-2: #e9f1ec;
  --panel: #ffffff;
  --ink: #0f1b2d;
  --muted: #4a5a70;
  --accent: #0b6bcb;
  --accent-2: #118a6f;
  --danger: #bf3b3b;
  --stroke: #cfd8e3;
  --soft: #f4f7fb;
}

html, body, [class*="css"] {
  font-family: "IBM Plex Sans", sans-serif;
}

.stApp {
  background: linear-gradient(145deg, var(--bg-1), var(--bg-2));
  color: var(--ink) !important;
}

.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {
  color: var(--ink) !important;
}

.stApp p, .stApp li, .stApp label, .stApp span, .stApp small, .stApp div {
  color: inherit;
}

.stApp a {
  color: var(--accent) !important;
}

.card-kpi {
  background: var(--panel);
  border: 1px solid var(--stroke);
  border-radius: 14px;
  padding: 14px 16px;
}

.section-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--ink);
}

.section-sub {
  color: var(--muted);
  font-size: 0.9rem;
}

div[data-testid="stMetric"] {
  background: var(--panel);
  border: 1px solid var(--stroke);
  border-radius: 14px;
  padding: 8px 10px;
}

div[data-testid="stMetricLabel"] p {
  color: var(--muted) !important;
  font-weight: 600 !important;
}

div[data-testid="stMetricValue"] {
  color: var(--ink) !important;
}

div[data-testid="stMarkdownContainer"] p,
div[data-testid="stMarkdownContainer"] li,
div[data-testid="stMarkdownContainer"] span {
  color: var(--ink) !important;
}

div[data-testid="stChatMessage"] {
  background: rgba(255,255,255,0.78);
  border: 1px solid var(--stroke);
  border-radius: 12px;
}

div[data-testid="stChatMessageContent"] * {
  color: var(--ink) !important;
}

div[data-testid="stChatInput"] textarea,
div[data-testid="stChatInput"] input {
  color: var(--ink) !important;
  background: var(--panel) !important;
}

div[data-testid="stChatInput"] textarea::placeholder,
div[data-testid="stChatInput"] input::placeholder {
  color: var(--muted) !important;
  opacity: 1 !important;
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--stroke);
  border-radius: 12px;
  overflow: hidden;
}

div[data-testid="stDataFrame"] * {
  color: var(--ink) !important;
}

div[data-testid="stProgressBar"] > div > div {
  background-color: var(--accent) !important;
}

.st-key-bottom_dock {
  position: fixed;
  left: 50vw !important;
  right: auto !important;
  transform: translateX(-50%) !important;
  bottom: 8px;
  z-index: 9999;
  width: min(368px, calc(100vw - 24px));
  background: rgba(11, 20, 38, 0.92);
  border: 1px solid #1f3354;
  border-radius: 16px;
  padding: 6px 8px;
  box-shadow: 0 12px 28px rgba(8, 16, 32, 0.35);
  backdrop-filter: blur(10px);
}

.st-key-bottom_dock > div {
  padding: 0 !important;
}

.st-key-bottom_dock div[data-testid="stHorizontalBlock"] {
  display: flex !important;
  flex-wrap: nowrap !important;
  width: 100% !important;
  justify-content: center !important;
  align-items: center !important;
  gap: 6px !important;
}

.st-key-bottom_dock div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
  flex: 1 1 0 !important;
  min-width: 0 !important;
  max-width: none !important;
}

.st-key-bottom_dock div[data-testid="stColumn"] {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100% !important;
}

.st-key-bottom_dock div[data-testid="stColumn"] div[data-testid="stButton"] {
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  width: 100% !important;
  margin: 0 !important;
}

.st-key-bottom_dock [class*="st-key-dock_btn_"] button {
  width: 48px !important;
  height: 48px !important;
  border-radius: 11px !important;
  border: 1px solid #2b4a78 !important;
  background: #122647 !important;
  color: #e8f2ff !important;
  padding: 0 !important;
  display: flex !important;
  justify-content: center !important;
  align-items: center !important;
  font-size: 1rem !important;
  line-height: 1 !important;
  font-weight: 700 !important;
  box-shadow: none !important;
  transition: all 0.2s ease;
}

.st-key-bottom_dock [class*="st-key-dock_btn_"] button span[data-testid="stIconMaterial"] {
  display: inline-flex !important;
  width: 1.18em !important;
  justify-content: center !important;
  align-items: center !important;
  text-align: center !important;
  font-size: 1.52rem !important;
  line-height: 1 !important;
}

.st-key-bottom_dock [class*="st-key-dock_btn_"] button:hover {
  border-color: #6ea2e4 !important;
  background: #19335d !important;
  transform: translateY(-1px);
}

.st-key-bottom_dock [class*="st-key-dock_btn_"] button:focus,
.st-key-bottom_dock [class*="st-key-dock_btn_"] button:focus-visible {
  outline: 2px solid #8dc4ff !important;
  outline-offset: 2px !important;
}

.block-container {
  padding-bottom: 90px !important;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_bottom_nav():
    with st.container(key="bottom_dock"):
        c1, c2, c3, c4 = st.columns(4, gap="small")
        with c1:
            if st.button("", key="dock_btn_home", icon=":material/home:", help="Home"):
                st.session_state.app_section = "home"
                st.rerun()
        with c2:
            if st.button("", key="dock_btn_scada", icon=":material/precision_manufacturing:", help="SCADA"):
                st.session_state.app_section = "scada"
                st.rerun()
        with c3:
            if st.button("", key="dock_btn_graphs", icon=":material/query_stats:", help="Grafici"):
                st.session_state.app_section = "graphs"
                st.rerun()
        with c4:
            if st.button("", key="dock_btn_planner", icon=":material/calendar_month:", help="Planner"):
                st.session_state.app_section = "planner"
                st.rerun()


def render_home_chat_panel():
    global model, _ai_key_index

    st.markdown('<div class="section-title">AI Factory Manager</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Chat operativa per informazioni e comandi linea.</div>', unsafe_allow_html=True)

    if model is None:
        st.info("AI non disponibile: configura GOOGLE_API_KEY in secrets.")
        return

    linee = st.session_state.linea_mgr.get_status()
    context_lines = "\n".join(
        [
            f"- L{l['id']} ({l['nome']}): Stato {l['stato']} | Ordine: {l['target_assegnato']} | Prod: {l['pezzi_fatti']}"
            for l in linee
        ]
    )
    context_orders = st.session_state.ordine_mgr.get_ordini_text()

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Ciao. Posso aiutarti con schedulazione e stato linee."}
        ]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    prompt = st.chat_input("Scrivi un comando o una domanda...", key="enterprise_chat_input")
    if not prompt:
        return

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
                st.session_state.messages.append({"role": "assistant", "content": report})
            else:
                st.session_state.messages.append({"role": "assistant", "content": answ})
        except Exception as e:
            st.session_state.messages.append({"role": "assistant", "content": f"Errore AI: {e}"})
    st.rerun()


def render_enterprise_home():
    st.title("MES Enterprise Control Room")
    st.caption("Panoramica turno, chat operativa e ordini in lavorazione.")

    tot_prodotti = st.session_state.linea_mgr.get_totale_produzione()
    tot_target = st.session_state.ordine_mgr.get_totale_target()
    ordini_raw = st.session_state.ordine_mgr.get_ordini()
    progress_dict = st.session_state.linea_mgr.get_produzione_per_ordine()
    mancanti = max(tot_target - tot_prodotti, 0)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="card-kpi">', unsafe_allow_html=True)
        st.metric("Pezzi fatti oggi", tot_prodotti)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card-kpi">', unsafe_allow_html=True)
        st.metric("Obiettivo totale", tot_target)
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="card-kpi">', unsafe_allow_html=True)
        st.metric("Pezzi mancanti", mancanti)
        st.markdown("</div>", unsafe_allow_html=True)

    if tot_target > 0:
        p = min(tot_prodotti / tot_target, 1.0)
        st.progress(p, text=f"Avanzamento turno: {int(p*100)}%")

    left, right = st.columns([2.1, 1.2])
    with left:
        render_home_chat_panel()
    with right:
        st.markdown('<div class="section-title">Ordini in lavorazione</div>', unsafe_allow_html=True)
        if not ordini_raw:
            st.caption("Nessun ordine attivo.")
        else:
            order_rows = []
            for o in ordini_raw:
                codice = o["codice"]
                target = int(o["quantita"])
                fatti = int(progress_dict.get(codice, 0))
                perc = int((fatti / target) * 100) if target > 0 else 0
                order_rows.append(
                    {
                        "Ordine": codice,
                        "Modello": o["modello"],
                        "Fatti": fatti,
                        "Target": target,
                        "Avanz. %": perc,
                    }
                )
            st.dataframe(pd.DataFrame(order_rows), use_container_width=True, hide_index=True)


def _latest_planned_code_by_line(mgr):
    out = {}
    if mgr is None:
        return out
    runs = mgr.get_recent_runs(limit=1)
    if not runs:
        return out
    tasks = mgr.get_tasks_for_run(int(runs[0]["run_id"]))
    for t in tasks:
        lid = str(t["line_id"])
        if lid not in out:
            out[lid] = t["code"]
    return out


def _line_aliases(linea_id: int):
    return {
        str(linea_id),
        f"L{linea_id}",
        f"L{linea_id:02d}",
        f"LM{linea_id}",
        f"LM{linea_id:02d}",
    }


def _sort_line_id_key(line_id: str):
    digits = "".join([c for c in str(line_id) if c.isdigit()])
    return (int(digits) if digits else 10**9, str(line_id))


def render_enterprise_scada():
    st.title("SCADA Live Overview")
    st.caption("Stato linee, contatori, codice in lavorazione e controlli rapidi.")

    mgr = st.session_state.get("scheduler_mgr")
    planned_by_line = _latest_planned_code_by_line(mgr)
    live_lines = st.session_state.linea_mgr.get_status()
    scheduler_lines = mgr.get_scheduler_lines() if mgr else []
    scheduler_ids = [str(x["line_id"]) for x in scheduler_lines] if scheduler_lines else []

    live_by_scheduler_id = {}
    for line in live_lines:
        for alias in _line_aliases(int(line["id"])):
            live_by_scheduler_id[alias] = line

    display_ids = sorted(set(scheduler_ids), key=_sort_line_id_key)
    if not display_ids:
        display_ids = [f"L{int(l['id'])}" for l in live_lines]

    top_c1, top_c2 = st.columns([1, 5])
    with top_c1:
        if st.button("Aggiorna", use_container_width=True, key="scada_refresh_btn"):
            st.rerun()
    with top_c2:
        st.caption(f"Linee visualizzate: {len(display_ids)}")

    cols = st.columns(3)
    for idx, line_id in enumerate(display_ids):
        live_line = live_by_scheduler_id.get(str(line_id))
        col = cols[idx % 3]
        with col:
            with st.container(border=True):
                if live_line:
                    stato = live_line["stato"]
                    status_color = "LIVE" if stato == "Attiva" else "STOP"
                    codice_live = live_line["target_assegnato"] if live_line["target_assegnato"] else "-"
                    st.markdown(f"**{line_id} - {live_line['nome']} ({status_color})**")
                    st.caption(f"Stato: {stato} | Vincoli: {live_line['vincoli']}")
                    st.write(f"Codice live: **{codice_live}**")
                    st.write(f"Codice pianificato: **{planned_by_line.get(line_id, '-')}**")
                    m1, m2 = st.columns(2)
                    m1.metric("Buoni", int(live_line["pezzi_fatti"]))
                    m2.metric("Scarti", int(live_line["pezzi_scarti"]))

                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("+10 OK", key=f"scada_ok_{live_line['id']}_{line_id}", use_container_width=True):
                            st.session_state.linea_mgr.update_counts(live_line["id"], buoni=10)
                            st.rerun()
                    with b2:
                        if st.button("+1 KO", key=f"scada_ko_{live_line['id']}_{line_id}", use_container_width=True):
                            st.session_state.linea_mgr.update_counts(live_line["id"], scarti=1)
                            st.rerun()

                    b3, b4 = st.columns(2)
                    with b3:
                        if stato == "Attiva":
                            if st.button("STOP", key=f"scada_stop_{live_line['id']}_{line_id}", use_container_width=True):
                                st.session_state.linea_mgr.set_stato(live_line["id"], "Ferma", "Manuale")
                                st.rerun()
                        else:
                            if st.button("START", key=f"scada_start_{live_line['id']}_{line_id}", use_container_width=True):
                                st.session_state.linea_mgr.set_stato(live_line["id"], "Attiva", "")
                                st.rerun()
                    with b4:
                        if st.button("Dettaglio", key=f"scada_det_{live_line['id']}_{line_id}", use_container_width=True):
                            goto_linea(live_line["id"])
                else:
                    st.markdown(f"**{line_id} - Solo schedulazione**")
                    st.caption("Linea presente in sched_lines ma non in telemetria live.")
                    st.write(f"Codice pianificato: **{planned_by_line.get(line_id, '-')}**")
                    m1, m2 = st.columns(2)
                    m1.metric("Stato", "n/d")
                    m2.metric("Produzione", "n/d")
                    st.caption("Per controlli live collega questa linea a linee_produttive.")


def render_enterprise_graphs():
    st.title("Analytics & Confronto Linee")
    st.caption("Seleziona una o più linee per confronto storico e performance.")

    lines = st.session_state.linea_mgr.get_status()
    line_map = {str(l["id"]): l["nome"] for l in lines}
    line_options = sorted(line_map.keys(), key=lambda x: int(x))
    default_sel = line_options[:2] if len(line_options) >= 2 else line_options

    selected = st.multiselect(
        "Linee da confrontare",
        options=line_options,
        default=default_sel,
        format_func=lambda lid: f"L{lid} - {line_map[lid]}",
        key="graphs_selected_lines",
    )
    if not selected:
        st.info("Seleziona almeno una linea.")
        return

    rng_col1, rng_col2 = st.columns([1.3, 2.7])
    with rng_col1:
        range_key = st.radio("Range", ["1g", "7g", "1m", "1a", "custom"], horizontal=True, key="graphs_range_key")
    with rng_col2:
        if range_key == "custom":
            raw_range = st.date_input(
                "Intervallo",
                value=(date.today() - timedelta(days=6), date.today()),
                key="graphs_custom_dates",
            )
            start_day, end_day = parse_date_range_input(raw_range)
        else:
            start_day, end_day = build_range(range_key)
            st.write(f"Intervallo: **{start_day} -> {end_day}**")

    frames = []
    summary = []
    for lid in selected:
        df = produzione_df(int(lid), start_day, end_day)
        df["linea"] = f"L{lid}"
        frames.append(df)
        summary.append(
            {
                "Linea": f"L{lid}",
                "Nome": line_map[lid],
                "OK": int(df["ok"].sum()),
                "KO": int(df["ko"].sum()),
                "Target": int(df["target_ok"].sum()),
                "Media OK/g": round(float(df["ok"].mean()), 2),
            }
        )

    all_df = pd.concat(frames, ignore_index=True)
    all_df["giorno"] = pd.to_datetime(all_df["giorno"])

    ok_chart = (
        alt.Chart(all_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("giorno:T", title="Giorno"),
            y=alt.Y("ok:Q", title="OK"),
            color=alt.Color("linea:N", title="Linea"),
            tooltip=["linea:N", "giorno:T", "ok:Q", "ko:Q", "target_ok:Q"],
        )
        .properties(height=300)
        .interactive()
    )
    st.altair_chart(ok_chart, use_container_width=True)

    bar_df = pd.DataFrame(summary)
    bar_chart = (
        alt.Chart(bar_df)
        .mark_bar()
        .encode(
            x=alt.X("Linea:N", title="Linea"),
            y=alt.Y("OK:Q", title="Totale OK"),
            color=alt.Color("Linea:N", legend=None),
            tooltip=["Linea:N", "Nome:N", "OK:Q", "KO:Q", "Target:Q"],
        )
        .properties(height=260)
    )
    st.altair_chart(bar_chart, use_container_width=True)
    st.dataframe(bar_df, use_container_width=True, hide_index=True)


def render_enterprise_planner():
    st.title("Planner Ordini & Gantt Schedulazione")
    st.caption("Vista ordini, piano linee e modifica manuale da operatore.")

    mgr = st.session_state.get("scheduler_mgr")
    if mgr is None:
        err = st.session_state.get("scheduler_init_error", "Scheduler non inizializzato.")
        st.error(f"Planner non disponibile: {err}")
        return

    c1, c2 = st.columns([1.2, 2.8])
    with c1:
        strategy = st.selectbox(
            "Strategia",
            ["due_date", "min_setup", "balanced", "both", "all"],
            key="planner_strategy",
        )
        if st.button("Genera nuovo piano", use_container_width=True, key="planner_run_btn"):
            try:
                res = mgr.run_scheduler(strategy=strategy)
                run_text = ", ".join([f"{r['strategy']}#{r['run_id']}" for r in res["saved_runs"]])
                st.success(f"Piani salvati: {run_text}")
                st.rerun()
            except Exception as e:
                st.error(f"Errore planner: {e}")
    with c2:
        stats = mgr.get_input_stats()
        st.write(
            f"Linee: **{stats['sched_lines']}** | Ordini: **{stats['sched_orders']}** | "
            f"Run: **{stats['sched_runs']}** | Task: **{stats['sched_tasks']}**"
        )

    orders = mgr.get_scheduler_orders(limit=500)
    if orders:
        st.markdown('<div class="section-title">Backlog ordini</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True)

    runs = mgr.get_recent_runs(limit=50)
    if not runs:
        st.info("Nessun run disponibile.")
        return

    run_by_id = {r["run_id"]: r for r in runs}
    run_ids = [r["run_id"] for r in runs]
    selected_run_id = st.selectbox(
        "Run piano",
        run_ids,
        format_func=lambda rid: f"Run {rid} | {run_by_id[rid]['strategy']} | {run_by_id[rid]['created_at']}",
        key="planner_selected_run",
    )

    row = run_by_id[selected_run_id]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Strategia", row["strategy"])
    m2.metric("Schedulati", row["scheduled_orders"])
    m3.metric("Ritardo tot min", f"{row['total_tardy_min']}")
    m4.metric("Setup tot min", f"{row['total_setup_min']}")

    tasks = mgr.get_tasks_for_run(int(selected_run_id))
    df_tasks = pd.DataFrame(tasks) if tasks else pd.DataFrame()
    if df_tasks.empty:
        st.warning("Il run selezionato non contiene task.")
        return

    sched_lines = mgr.get_scheduler_lines()
    line_domain = [x["line_id"] for x in sched_lines] if sched_lines else None

    st.altair_chart(grafico_schedulazione_tasks(df_tasks, all_lines=line_domain), use_container_width=True)

    edit_cols = ["order_id", "code", "line_id", "qty", "setup_min", "start_min", "end_min", "due_date"]
    df_edit = df_tasks[edit_cols].copy()
    line_options = line_domain if line_domain else sorted(df_edit["line_id"].astype(str).unique())

    edited = st.data_editor(
        df_edit,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "line_id": st.column_config.SelectboxColumn("line_id", options=line_options),
            "qty": st.column_config.NumberColumn("qty", min_value=0, step=1),
            "setup_min": st.column_config.NumberColumn("setup_min", min_value=0.0, step=0.1),
            "start_min": st.column_config.NumberColumn("start_min", min_value=0.0, step=0.1),
            "end_min": st.column_config.NumberColumn("end_min", min_value=0.0, step=0.1),
        },
        key="planner_editor",
    )

    if st.button("Salva come piano manuale", key="planner_save_manual_btn"):
        try:
            run_id = mgr.save_manual_run(edited.to_dict("records"))
            st.success(f"Piano manuale salvato con run_id={run_id}")
            st.rerun()
        except Exception as e:
            st.error(f"Errore salvataggio piano manuale: {e}")

    unscheduled = mgr.get_unscheduled_for_run(int(selected_run_id))
    with st.expander("Ordini non schedulati", expanded=False):
        if not unscheduled:
            st.caption("Nessun ordine non schedulato.")
        else:
            st.dataframe(pd.DataFrame(unscheduled), use_container_width=True, hide_index=True)


def render_scheduler_section():
    st.divider()
    st.subheader("📅 Schedulatore (solo DB)")

    mgr = st.session_state.get("scheduler_mgr")
    if mgr is None:
        err = st.session_state.get("scheduler_init_error", "Scheduler non inizializzato.")
        st.error(f"Scheduler non disponibile: {err}")
        return

    c2, c3 = st.columns([1.4, 1.8])

    with c2:
        strategy = st.selectbox(
            "Strategia",
            ["due_date", "min_setup", "balanced", "both", "all"],
            key="sched_strategy",
        )
        if st.button("Esegui schedulazione", use_container_width=True):
            try:
                res = mgr.run_scheduler(strategy=strategy)
                run_text = ", ".join([f"{r['strategy']}#{r['run_id']}" for r in res["saved_runs"]])
                st.success(f"Run salvati: {run_text}")
            except Exception as e:
                st.error(f"Errore esecuzione schedulatore: {e}")

    with c3:
        try:
            stats = mgr.get_input_stats()
            all_sched_lines = mgr.get_scheduler_lines()
            total_sched_lines = len(all_sched_lines) if all_sched_lines else 0
            st.caption("Stato tabelle sched_*")
            st.write(
                f"Linee sched: **{total_sched_lines}** | Ordini: **{stats['sched_orders']}** | "
                f"Cycle rows: **{stats['sched_cycle_times']}** | Runs: **{stats['sched_runs']}**"
            )
        except Exception as e:
            st.caption(f"Statistiche non disponibili: {e}")
            all_sched_lines = []

    runs = mgr.get_recent_runs(limit=30)
    if not runs:
        st.info("Nessun run schedulatore disponibile.")
        return

    def _run_label(r):
        created = str(r.get("created_at", ""))
        return f"Run {r['run_id']} | {r['strategy']} | {created}"

    run_ids = [r["run_id"] for r in runs]
    run_by_id = {r["run_id"]: r for r in runs}
    selected_run_id = st.selectbox(
        "Run salvati",
        run_ids,
        format_func=lambda rid: _run_label(run_by_id[rid]),
        key="sched_selected_run_id",
    )

    row = run_by_id[selected_run_id]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Strategia", row["strategy"])
    k2.metric("Ordini schedulati", row["scheduled_orders"])
    k3.metric("Totale ritardo (min)", f"{row['total_tardy_min']}")
    k4.metric("Totale setup (min)", f"{row['total_setup_min']}")

    tasks = mgr.get_tasks_for_run(selected_run_id)
    df_tasks = pd.DataFrame(tasks) if tasks else pd.DataFrame()
    if not df_tasks.empty:
        line_domain = [r["line_id"] for r in all_sched_lines] if all_sched_lines else None
        st.altair_chart(grafico_schedulazione_tasks(df_tasks, all_lines=line_domain), use_container_width=True)
        with st.expander("Dettaglio task", expanded=False):
            st.dataframe(df_tasks, use_container_width=True)
    else:
        st.caption("Nessun task per il run selezionato.")

    unscheduled = mgr.get_unscheduled_for_run(selected_run_id)
    df_uns = pd.DataFrame(unscheduled) if unscheduled else pd.DataFrame()
    with st.expander("Ordini non schedulati", expanded=False):
        if df_uns.empty:
            st.caption("Nessun ordine non schedulato.")
        else:
            st.dataframe(df_uns, use_container_width=True)


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
                            st.session_state.messages.append({"role": "assistant", "content": report})
                            if used_voice and tts_enabled:
                                speak_in_browser(report, rate=rate, pitch=pitch, volume=volume, voice_idx=voice_idx)
                        else:
                            st.session_state.messages.append({"role": "assistant", "content": answ})
                            if used_voice and tts_enabled:
                                speak_in_browser(answ, rate=rate, pitch=pitch, volume=volume, voice_idx=voice_idx)
                        time.sleep(0.2)
                        st.rerun()
                    except Exception as e:
                        st.session_state.messages.append({"role": "assistant", "content": f"Errore AI: {e}"})
                        st.rerun()

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


    render_scheduler_section()


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
            raw_range = st.date_input(
                "Seleziona intervallo",
                value=(date.today() - timedelta(days=6), date.today()),
            )
            start_day, end_day = parse_date_range_input(raw_range)
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
# app router (enterprise)
#
apply_enterprise_theme()

section = st.session_state.get("app_section", "home")
if section == "home":
    render_enterprise_home()
elif section == "scada":
    render_enterprise_scada()
elif section == "graphs":
    render_enterprise_graphs()
elif section == "planner":
    render_enterprise_planner()
elif section == "linea_detail":
    render_linea_detail(st.session_state.selected_linea_id)
else:
    st.session_state.app_section = "home"
    render_enterprise_home()

render_bottom_nav()




