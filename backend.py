import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
from datetime import date, timedelta


class DatabaseManager:
    """
    Wrapper minimale per Supabase/PostgreSQL.
    - Se la query è SELECT -> ritorna lista di dict.
    - Altrimenti -> commit e ritorna True/False.
    """
    def __init__(self):
        try:
            self.db_url = st.secrets["SUPABASE_URL"]
        except Exception:
            st.error("Manca SUPABASE_URL nei secrets di Streamlit.")
            st.stop()

    def execute(self, sql: str, params=()):
        conn = None
        try:
            conn = psycopg2.connect(self.db_url)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, params)

            if sql.strip().upper().startswith("SELECT"):
                return cur.fetchall()

            conn.commit()
            return True
        except Exception as e:
            st.error(f"Errore DB: {e}")
            return [] if sql.strip().upper().startswith("SELECT") else False
        finally:
            if conn:
                conn.close()


class LineaManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._init_schema()

    #
    # SCHEMA / SETUP
    #
    def _init_schema(self):
        # Tabella linee
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS linee_produttive (
                id INTEGER PRIMARY KEY,
                nome TEXT,
                vincoli TEXT,
                stato TEXT DEFAULT 'Attiva',
                motivo_fermo TEXT DEFAULT '',
                pezzi_fatti INTEGER DEFAULT 0,
                pezzi_scarti INTEGER DEFAULT 0,
                target_assegnato TEXT DEFAULT ''
            );
        """)

        # Tabella eventi (storico)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS produzione_eventi (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                linea_id INTEGER NOT NULL REFERENCES linee_produttive(id) ON DELETE CASCADE,
                ordine_codice TEXT DEFAULT '',
                tipo TEXT NOT NULL CHECK (tipo IN ('OK','KO','START','STOP')),
                qta INTEGER NOT NULL DEFAULT 1
            );
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_prod_eventi_linea_ts
            ON produzione_eventi(linea_id, ts);
        """)

        # Tabella obiettivi giornalieri
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS obiettivi_linea_giorno (
                giorno DATE NOT NULL,
                linea_id INTEGER NOT NULL REFERENCES linee_produttive(id) ON DELETE CASCADE,
                target_ok INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (giorno, linea_id)
            );
        """)

        # Popola linee se vuota
        if not self.db.execute("SELECT 1 FROM linee_produttive LIMIT 1"):
            lines_setup = [
                (1, "Linea 1 (Porsche/Merc)", "SOLO Porsche, Mercedes"),
                (2, "Linea 2 (Ferrari/Audi)", "SOLO Ferrari, Audi"),
                (3, "Linea 3 (Ferrari/Audi)", "SOLO Ferrari, Audi"),
                (4, "Linea 4 (Jolly)", "TUTTI"),
                (5, "Linea 5 (Jolly)", "TUTTI"),
            ]
            for lid, nome, vincoli in lines_setup:
                self.db.execute(
                    "INSERT INTO linee_produttive (id, nome, vincoli) VALUES (%s, %s, %s)",
                    (lid, nome, vincoli),
                )

    #
    # LETTURA STATO
    #
    def get_status(self):
        return self.db.execute("SELECT * FROM linee_produttive ORDER BY id")

    def get_linea(self, linea_id: int):
        res = self.db.execute("SELECT * FROM linee_produttive WHERE id=%s", (linea_id,))
        return res[0] if res else None

    #
    # SCRITTURE (con storico)
    #
    def _log_evento(self, linea_id: int, tipo: str, qta: int = 1):
        # Lega l'evento all'ordine attuale (se presente)
        self.db.execute("""
            INSERT INTO produzione_eventi(linea_id, ordine_codice, tipo, qta)
            VALUES (
                %s,
                COALESCE((SELECT target_assegnato FROM linee_produttive WHERE id=%s), ''),
                %s,
                %s
            );
        """, (linea_id, linea_id, tipo, qta))

    def update_counts(self, linea_id: int, buoni: int = 0, scarti: int = 0):
        """
        Usata dai bottoni Streamlit (+10 OK, +1 KO).
        Aggiorna:
        - contatori live (linee_produttive)
        - storico (produzione_eventi)
        """
        if buoni > 0:
            self.db.execute("""
                WITH ins AS (
                  INSERT INTO produzione_eventi(linea_id, ordine_codice, tipo, qta)
                  VALUES (
                    %s,
                    COALESCE((SELECT target_assegnato FROM linee_produttive WHERE id=%s), ''),
                    'OK',
                    %s
                  )
                )
                UPDATE linee_produttive
                SET pezzi_fatti = pezzi_fatti + %s
                WHERE id = %s;
            """, (linea_id, linea_id, buoni, buoni, linea_id))

        if scarti > 0:
            self.db.execute("""
                WITH ins AS (
                  INSERT INTO produzione_eventi(linea_id, ordine_codice, tipo, qta)
                  VALUES (
                    %s,
                    COALESCE((SELECT target_assegnato FROM linee_produttive WHERE id=%s), ''),
                    'KO',
                    %s
                  )
                )
                UPDATE linee_produttive
                SET pezzi_scarti = pezzi_scarti + %s
                WHERE id = %s;
            """, (linea_id, linea_id, scarti, scarti, linea_id))

    def set_stato(self, linea_id: int, stato: str, motivo: str = ""):
        """
        Start/Stop con log eventi.
        """
        current = self.get_linea(linea_id)
        old = current["stato"] if current else None

        self.db.execute(
            "UPDATE linee_produttive SET stato=%s, motivo_fermo=%s WHERE id=%s",
            (stato, motivo, linea_id),
        )

        # Log solo se cambia davvero
        if old and old != stato:
            if stato == "Attiva":
                self._log_evento(linea_id, "START", 1)
            elif stato == "Ferma":
                self._log_evento(linea_id, "STOP", 1)

    def assegna_commessa(self, linea_id: int, codice_commessa: str):
        self.db.execute(
            "UPDATE linee_produttive SET target_assegnato=%s WHERE id=%s",
            (codice_commessa, linea_id),
        )

    #
    # KPI (HOME)
    #
    def get_produzione_per_ordine(self):
        # Manteniamo la tua logica attuale (somma per ordine sulle linee)
        # perché il progetto usa ancora i contatori "live".
        sql = """
            SELECT target_assegnato, SUM(pezzi_fatti) as tot
            FROM linee_produttive
            WHERE target_assegnato != ''
            GROUP BY target_assegnato
        """
        res = self.db.execute(sql)
        return {r["target_assegnato"]: r["tot"] for r in res}

    def get_totale_produzione(self):
        res = self.db.execute("SELECT SUM(pezzi_fatti) as tot FROM linee_produttive")
        return res[0]["tot"] if res and res[0]["tot"] else 0

    #
    # STORICO PRODUZIONE PER LINEA
    #
    def get_produzione_giornaliera(self, linea_id: int, start_day: date, end_day: date):
        """
        Ritorna lista di dict:
        {giorno, ok, ko}
        Raggruppata per giorno (Europe/Rome).
        """
        sql = """
            SELECT
              (ts AT TIME ZONE 'Europe/Rome')::date AS giorno,
              SUM(CASE WHEN tipo='OK' THEN qta ELSE 0 END) AS ok,
              SUM(CASE WHEN tipo='KO' THEN qta ELSE 0 END) AS ko
            FROM produzione_eventi
            WHERE linea_id = %s
              AND (ts AT TIME ZONE 'Europe/Rome')::date BETWEEN %s AND %s
            GROUP BY 1
            ORDER BY 1;
        """
        return self.db.execute(sql, (linea_id, start_day, end_day))

    def get_obiettivi_giornalieri(self, linea_id: int, start_day: date, end_day: date):
        sql = """
            SELECT giorno, target_ok
            FROM obiettivi_linea_giorno
            WHERE linea_id = %s AND giorno BETWEEN %s AND %s
            ORDER BY giorno;
        """
        return self.db.execute(sql, (linea_id, start_day, end_day))

    def set_obiettivo_giornaliero_range(self, linea_id: int, start_day: date, end_day: date, target_ok: int):
        """
        Imposta lo stesso target_ok per ogni giorno nel range (UPSERT).
        """
        giorno = start_day
        while giorno <= end_day:
            self.db.execute("""
                INSERT INTO obiettivi_linea_giorno(giorno, linea_id, target_ok)
                VALUES (%s, %s, %s)
                ON CONFLICT (giorno, linea_id)
                DO UPDATE SET target_ok = EXCLUDED.target_ok;
            """, (giorno, linea_id, target_ok))
            giorno += timedelta(days=1)


class OrdineManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.init_orders()

    def init_orders(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ordini_produzione (
                codice TEXT PRIMARY KEY,
                modello TEXT,
                quantita INTEGER,
                deadline TEXT
            );
        """)

    def add_ordine(self, codice: str, modello: str, quantita: int, deadline: str):
        self.db.execute(
            "INSERT INTO ordini_produzione (codice, modello, quantita, deadline) VALUES (%s, %s, %s, %s)",
            (codice, modello, quantita, deadline),
        )

    def get_ordini(self):
        return self.db.execute("SELECT * FROM ordini_produzione")

    def get_ordini_text(self):
        data = self.get_ordini()
        if not data:
            return "Nessun ordine attivo."
        return "\n".join([f"- {o['codice']}: {o['quantita']}x {o['modello']} (Deadline: {o['deadline']})" for o in data])

    def reset_giornata(self):
        self.db.execute("DELETE FROM ordini_produzione")
        self.db.execute("""
            UPDATE linee_produttive
            SET pezzi_fatti=0, pezzi_scarti=0, stato='Attiva', motivo_fermo='', target_assegnato=''
        """)

    def get_totale_target(self):
        res = self.db.execute("SELECT SUM(quantita) as tot FROM ordini_produzione")
        return res[0]["tot"] if res and res[0]["tot"] else 0
