"""
App desktop standalone per Schedulazione-AI.
Avvia Streamlit in background e apre la dashboard in una finestra desktop nativa
tramite pywebview. Doppio click su desktop.bat (Windows) o desktop.command (macOS)
per avviare.
"""

import subprocess
import threading
import time
import sys
import os
import socket
from contextlib import closing


def find_free_port(default=8501):
    """Trova una porta libera, parte dal default."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind(("127.0.0.1", default))
            return default
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def wait_for_streamlit(port, timeout=30):
    """Attende che Streamlit risponda sulla porta."""
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=1)
            return True
        except (urllib.error.URLError, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def start_streamlit(port):
    """Avvia Streamlit come processo separato, headless."""
    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--global.developmentMode", "false",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000  # CREATE_NO_WINDOW su Windows
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def main():
    try:
        import webview
    except ImportError:
        print("ERRORE: pywebview non installato. Esegui: pip install pywebview")
        sys.exit(1)

    port = find_free_port(8501)
    print(f"Avvio Streamlit sulla porta {port}...")
    streamlit_proc = start_streamlit(port)

    if not wait_for_streamlit(port):
        print("ERRORE: Streamlit non si e' avviato in tempo.")
        streamlit_proc.terminate()
        sys.exit(1)

    print("Streamlit pronto. Apro finestra desktop...")
    window = webview.create_window(
        "Schedulazione-AI - MES Dashboard",
        url=f"http://127.0.0.1:{port}",
        width=1280,
        height=800,
        resizable=True,
        confirm_close=True,
    )

    def on_closed():
        print("Chiusura app...")
        streamlit_proc.terminate()
        try:
            streamlit_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            streamlit_proc.kill()

    window.events.closed += on_closed
    webview.start()


if __name__ == "__main__":
    main()
