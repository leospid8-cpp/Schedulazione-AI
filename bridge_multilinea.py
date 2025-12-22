import os
import serial
import time
import psycopg2
from psycopg2.extras import RealDictCursor

#
# configurazione
#
ARDUINO_PORT = "COM3"
BAUD_RATE = 9600

# Consiglio: usa variabile d'ambiente DB_URL per non hardcodare password.
# Esempio Windows (PowerShell):
#   $env:DB_URL="postgresql://...:PASSWORD@.../postgres"
DB_URL = os.getenv(
    "DB_URL",
    "postgresql://postgres.topizuytggdbpgpawgdw:LA_TUA_PASSWORD@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
)


def connect_db():
    try:
        return psycopg2.connect(DB_URL)
    except Exception as e:
        print(f"[DB] Connessione fallita: {e}")
        return None


def ensure_tables(conn):
    """
    Crea la tabella storico se non esiste.
    (Se la tua Streamlit app parte prima, questo è comunque ok.)
    """
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS produzione_eventi (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                linea_id INTEGER NOT NULL REFERENCES linee_produttive(id) ON DELETE CASCADE,
                ordine_codice TEXT DEFAULT '',
                tipo TEXT NOT NULL CHECK (tipo IN ('OK','KO','START','STOP')),
                qta INTEGER NOT NULL DEFAULT 1
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_prod_eventi_linea_ts
            ON produzione_eventi(linea_id, ts);
        """)
        conn.commit()
    except Exception as e:
        print(f"[DB] ensure_tables error: {e}")


def log_ok_piece(conn, linea_id: int):
    """
    Quando Arduino invia BTN:X:
    - inserisce evento OK nello storico
    - incrementa contatore live pezzi_fatti
    In un'unica operazione atomica.
    """
    cur = conn.cursor()
    cur.execute("""
        WITH ins AS (
          INSERT INTO produzione_eventi(linea_id, ordine_codice, tipo, qta)
          VALUES (
            %s,
            COALESCE((SELECT target_assegnato FROM linee_produttive WHERE id=%s), ''),
            'OK',
            1
          )
        )
        UPDATE linee_produttive
        SET pezzi_fatti = pezzi_fatti + 1
        WHERE id = %s;
    """, (linea_id, linea_id, linea_id))
    conn.commit()


def build_stato_stringa(conn) -> str:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, stato FROM linee_produttive ORDER BY id ASC")
    rows = cur.fetchall()

    stato_stringa = ""
    for r in rows:
        stato_stringa += "1" if r["stato"] == "Attiva" else "0"
    return stato_stringa


def main():
    print(f"[SERIAL] Cerco Arduino su {ARDUINO_PORT}...")
    try:
        ser = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        print("[SERIAL] Connesso ad Arduino.")
    except Exception as e:
        print(f"[SERIAL] Errore: non trovo Arduino ({e}).")
        return

    conn = connect_db()
    if conn is None:
        print("[DB] Non posso partire senza DB.")
        return

    ensure_tables(conn)

    # Loop
    while True:
        # 1) Leggo Arduino (eventi)
        if ser.in_waiting > 0:
            try:
                line = ser.readline().decode("utf-8", errors="ignore").strip()

                if line.startswith("BTN:"):
                    linea_id = int(line.split(":")[1])
                    print(f"[EVENT] BTN da linea {linea_id}")

                    if conn.closed:
                        conn = connect_db()
                        if conn is None:
                            time.sleep(1)
                            continue

                    log_ok_piece(conn, linea_id)
                    print(f"[DB] OK +1 registrato (linea {linea_id})")

            except Exception as e:
                print(f"[EVENT] Errore gestione seriale/DB: {e}")

        # 2) Polling stato linee -> Arduino (LED + relè)
        try:
            if conn.closed:
                conn = connect_db()
                if conn is None:
                    time.sleep(1)
                    continue

            stato_stringa = build_stato_stringa(conn)

            if len(stato_stringa) == 5:
                ser.write((stato_stringa + "\n").encode())

        except Exception:
            # in beta non spammiamo log: riprova al prossimo ciclo
            pass

        time.sleep(0.2)


if __name__ == "__main__":
    main()
