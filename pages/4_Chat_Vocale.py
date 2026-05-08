"""
Chat vocale con l'AI per la dashboard MES.
Voce naturale tramite edge-tts (Microsoft Azure Neural Voices, gratuito).
Funziona in app desktop (pywebview) e web (browser).
"""

import asyncio

import edge_tts
import google.generativeai as genai
import streamlit as st
from streamlit_mic_recorder import speech_to_text

from backend import DatabaseManager, LineaManager, OrdineManager


VOCI_DISPONIBILI = {
    "Isabella (femminile, naturale)": "it-IT-IsabellaNeural",
    "Diego (maschile, naturale)": "it-IT-DiegoNeural",
    "Elsa (femminile, alternativa)": "it-IT-ElsaNeural",
    "Cataldo (maschile, espressivo)": "it-IT-CataldoNeural",
    "Giuseppe (maschile, alternativo)": "it-IT-GiuseppeNeural",
}

st.set_page_config(page_title="Chat Vocale", page_icon="🎤", layout="wide")

# Configurazione AI: stessa logica di app.py (GOOGLE_API_KEY / GOOGLE_API_KEY_2)
_ai_keys = []
for _k in ("GOOGLE_API_KEY", "GOOGLE_API_KEY_2"):
    try:
        _v = st.secrets.get(_k)
        if _v:
            _ai_keys.append(_v)
    except Exception:
        pass

_ai_model = None
if _ai_keys:
    try:
        genai.configure(api_key=_ai_keys[0])
        _ai_model = genai.GenerativeModel("models/gemini-flash-latest")
    except Exception:
        pass

# Backend managers: riutilizza quelli già in session_state (inizializzati da app.py)
# oppure li crea se l'utente apre direttamente questa pagina.
if "db" not in st.session_state:
    st.session_state.db = DatabaseManager()
if "linea_mgr" not in st.session_state:
    st.session_state.linea_mgr = LineaManager(st.session_state.db)
if "ordine_mgr" not in st.session_state:
    st.session_state.ordine_mgr = OrdineManager(st.session_state.db)


def get_contesto_sistema() -> str:
    """Raccoglie lo stato attuale delle linee e degli ordini per il contesto AI."""
    try:
        linee = st.session_state.linea_mgr.get_status()
        context_lines = "\n".join(
            f"- L{l['id']} ({l['nome']}): Stato {l['stato']} | "
            f"Ordine: {l['target_assegnato'] or '—'} | "
            f"Buoni: {l['pezzi_fatti']}, Scarti: {l['pezzi_scarti']}"
            for l in linee
        )
        context_orders = st.session_state.ordine_mgr.get_ordini_text()
        return f"LINEE PRODUTTIVE:\n{context_lines}\n\nORDINI ATTIVI:\n{context_orders}"
    except Exception as e:
        return f"(impossibile recuperare contesto: {e})"


def chiedi_ai(domanda: str, contesto: str) -> str:
    """Invia la domanda al modello Gemini con il contesto del sistema MES."""
    if _ai_model is None:
        return "AI non disponibile: configura GOOGLE_API_KEY in .streamlit/secrets.toml."

    prompt = (
        "Sei l'assistente di un sistema MES per linee produttive industriali. "
        "Rispondi in italiano, in modo conciso (massimo 2-3 frasi), "
        "con tono tecnico ma accessibile.\n\n"
        f"CONTESTO ATTUALE:\n{contesto}\n\n"
        f"DOMANDA: {domanda}\n\n"
        "RISPOSTA:"
    )
    try:
        response = _ai_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        msg = str(e).lower()
        if ("quota" in msg or "resource_exhausted" in msg or "429" in msg) and len(_ai_keys) > 1:
            try:
                genai.configure(api_key=_ai_keys[1])
                fallback = genai.GenerativeModel("models/gemini-flash-latest")
                response = fallback.generate_content(prompt)
                return response.text.strip()
            except Exception as e2:
                return f"Errore AI (quota esaurita su entrambe le chiavi): {e2}"
        return f"Errore AI: {e}"


async def _genera_audio_async(testo: str, voce: str) -> bytes:
    """Genera audio MP3 da testo usando edge-tts (Microsoft Azure Neural Voices)."""
    communicate = edge_tts.Communicate(testo, voce)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    return bytes(audio_data)


def genera_audio(testo: str, voce: str) -> bytes:
    """Wrapper sincrono per la generazione TTS."""
    try:
        return asyncio.run(_genera_audio_async(testo, voce))
    except RuntimeError:
        # Caso in cui un event loop asyncio sia già attivo (es. Streamlit Cloud)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_genera_audio_async(testo, voce))
        finally:
            loop.close()


# Inizializzazione session state per questa pagina
if "voice_chat_history" not in st.session_state:
    st.session_state.voice_chat_history = []
if "ultimo_audio" not in st.session_state:
    st.session_state.ultimo_audio = None


# --- UI ---
st.title("🎤 Chat vocale con l'AI")
st.caption("Voce neurale Microsoft Azure · Premi il microfono, parla in italiano, ricevi risposta vocale.")

if _ai_model is None:
    st.warning("AI non configurata. Aggiungi GOOGLE_API_KEY in .streamlit/secrets.toml per usare la chat.")

col1, col2 = st.columns([1, 3])

with col1:
    st.markdown("### Microfono")
    testo = speech_to_text(
        language="it-IT",
        start_prompt="🎤 Inizia",
        stop_prompt="⏹ Stop",
        just_once=True,
        use_container_width=True,
        key="STT_voice",
    )

    st.markdown("### Voce")
    voce_selezionata = st.selectbox(
        "Voce dell'assistente:",
        options=list(VOCI_DISPONIBILI.keys()),
        index=0,
    )
    voce_id = VOCI_DISPONIBILI[voce_selezionata]
    abilita_voce = st.checkbox("Risposta vocale", value=True)

    if st.button("🗑 Pulisci chat", use_container_width=True):
        st.session_state.voice_chat_history = []
        st.session_state.ultimo_audio = None
        st.rerun()

with col2:
    st.markdown("### Conversazione")

    if testo:
        st.session_state.voice_chat_history.append(("utente", testo))
        with st.spinner("L'AI sta pensando..."):
            contesto = get_contesto_sistema()
            risposta = chiedi_ai(testo, contesto)
        st.session_state.voice_chat_history.append(("ai", risposta))
        if abilita_voce:
            with st.spinner("Genero audio..."):
                try:
                    st.session_state.ultimo_audio = genera_audio(risposta, voce_id)
                except Exception as e:
                    st.warning(f"Errore generazione voce: {e}. Mostro solo testo.")
                    st.session_state.ultimo_audio = None

    if st.session_state.ultimo_audio:
        st.audio(st.session_state.ultimo_audio, format="audio/mp3", autoplay=True)

    chat_box = st.container(height=450)
    with chat_box:
        if not st.session_state.voice_chat_history:
            st.info("Nessun messaggio. Premi il microfono per iniziare.")
        for ruolo, msg in st.session_state.voice_chat_history:
            if ruolo == "utente":
                with st.chat_message("user", avatar="👤"):
                    st.write(msg)
            else:
                with st.chat_message("assistant", avatar="🤖"):
                    st.write(msg)

with st.expander("💡 Esempi di domande"):
    st.markdown("""
    - "Qual è lo stato della linea 1?"
    - "Quante linee sono attive in questo momento?"
    - "Qual è la linea che produce di più?"
    - "Riassumi la situazione attuale del turno"
    - "Ci sono ordini in ritardo?"
    """)
