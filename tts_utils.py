"""
Utility per Text-to-Speech con edge-tts.
Voci neurali Microsoft Azure, gratuite, no API key.
"""
import asyncio

import edge_tts


VOCI_DISPONIBILI = {
    "Isabella (femminile, naturale)": "it-IT-IsabellaNeural",
    "Diego (maschile, naturale)": "it-IT-DiegoNeural",
    "Elsa (femminile, alternativa)": "it-IT-ElsaNeural",
    "Cataldo (maschile, espressivo)": "it-IT-CataldoNeural",
    "Giuseppe (maschile, alternativo)": "it-IT-GiuseppeNeural",
}


async def _genera_audio_async(testo: str, voce: str) -> bytes:
    communicate = edge_tts.Communicate(testo, voce)
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
    return bytes(audio_data)


def genera_audio(testo: str, voce: str = "it-IT-IsabellaNeural") -> bytes:
    """Genera audio MP3 da testo. Wrapper sincrono robusto per Streamlit."""
    try:
        return asyncio.run(_genera_audio_async(testo, voce))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_genera_audio_async(testo, voce))
        finally:
            loop.close()
