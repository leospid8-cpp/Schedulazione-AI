import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
from datetime import date, timedelta
from pathlib import Path


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


class SchedulerManager:
    """
    Gestione schedulatore avanzato:
    - crea/aggiorna schema sched_*
    - esegue strategie e salva run/tasks su DB
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        root = Path(__file__).resolve().parent
        self.schema_path = root / "team_pack" / "scheduler_schema.sql"
        self.ensure_schema()

    def _connect(self):
        return psycopg2.connect(self.db.db_url)

    def ensure_schema(self):
        from team_pack.supabase_pipeline import apply_schema, ensure_strategy_constraint

        with self._connect() as conn:
            with conn.cursor() as cur:
                apply_schema(cur, str(self.schema_path))
                ensure_strategy_constraint(cur)

    def _build_dataset_from_db(self):
        lines_raw = self.db.execute("SELECT line_id FROM public.sched_lines ORDER BY line_id")
        orders_raw = self.db.execute(
            """
            SELECT order_id, code, qty, due_date, due_serial
            FROM public.sched_orders
            ORDER BY order_id
            """
        )
        eligible_raw = self.db.execute("SELECT order_id, line_id FROM public.sched_eligible_lines")
        cycle_raw = self.db.execute("SELECT code, line_id, cycle_min_per_piece FROM public.sched_cycle_times")
        config_raw = self.db.execute("SELECT line_id, current_code, loaded_qty FROM public.sched_current_config")
        setup_from_raw = self.db.execute("SELECT line_id, to_code, setup_min FROM public.sched_setup_from_current")
        setup_between_raw = self.db.execute("SELECT from_code, to_code, setup_min FROM public.sched_setup_between_codes")

        lines = [{"line_id": r["line_id"]} for r in lines_raw]

        eligible_map = {}
        for r in eligible_raw:
            oid = r["order_id"]
            eligible_map.setdefault(oid, []).append(r["line_id"])

        cycle_by_code = {}
        for r in cycle_raw:
            code = r["code"]
            cycle_by_code.setdefault(code, {})[r["line_id"]] = float(r["cycle_min_per_piece"])

        orders = []
        for r in orders_raw:
            due_date = r.get("due_date")
            orders.append(
                {
                    "order_id": r["order_id"],
                    "code": r["code"],
                    "qty": int(r["qty"]),
                    "due_serial": int(r["due_serial"] or 0),
                    "due_date": due_date.isoformat() if due_date else None,
                    "eligible_lines": sorted(eligible_map.get(r["order_id"], [])),
                    "cycle_minutes_by_line": cycle_by_code.get(r["code"], {}),
                }
            )

        current_config = {}
        for r in config_raw:
            current_config[r["line_id"]] = {
                "current_code": r.get("current_code") or "",
                "loaded_qty": int(r.get("loaded_qty") or 0),
            }

        setup_from = {}
        for r in setup_from_raw:
            lid = r["line_id"]
            setup_from.setdefault(lid, {})[r["to_code"]] = float(r["setup_min"])

        setup_between = {}
        for r in setup_between_raw:
            frm = r["from_code"]
            setup_between.setdefault(frm, {})[r["to_code"]] = float(r["setup_min"])

        dataset = {
            "meta": {
                "source": "database",
                "generated_at": date.today().isoformat(),
            },
            "lines": lines,
            "orders": orders,
            "current_config": current_config,
            "setup_minutes": {
                "per_tool_minutes": 0,
                "from_current": setup_from,
                "between_codes": setup_between,
            },
        }
        return dataset

    def run_scheduler(self, strategy: str = "all"):
        from team_pack.supabase_pipeline import (
            persist_run,
            run_requested_strategies,
        )

        dataset = self._build_dataset_from_db()
        if not dataset["orders"] or not dataset["lines"]:
            raise RuntimeError("Dati schedulatore mancanti su DB. Carica prima le tabelle sched_*.")
        results = run_requested_strategies(dataset, strategy)

        saved_runs = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                for result in results:
                    run_id = persist_run(cur, result)
                    saved_runs.append(
                        {
                            "run_id": run_id,
                            "strategy": result.get("strategy"),
                            "kpi": result.get("kpi", {}),
                        }
                    )

        return {
            "source": "database",
            "saved_runs": saved_runs,
        }

    def get_input_stats(self):
        tables = [
            "sched_lines",
            "sched_orders",
            "sched_eligible_lines",
            "sched_cycle_times",
            "sched_runs",
            "sched_tasks",
            "sched_unscheduled",
        ]
        out = {}
        for table in tables:
            res = self.db.execute(f"SELECT COUNT(*) AS c FROM public.{table}")
            out[table] = int(res[0]["c"]) if res else 0
        return out

    def get_recent_runs(self, limit: int = 20):
        return self.db.execute(
            """
            SELECT
              run_id,
              strategy,
              created_at,
              total_orders,
              scheduled_orders,
              unscheduled_orders,
              total_tardy_min,
              total_setup_min,
              makespan_min,
              avg_completion_min
            FROM public.sched_runs
            ORDER BY run_id DESC
            LIMIT %s
            """,
            (limit,),
        )

    def get_scheduler_lines(self):
        return self.db.execute(
            """
            SELECT line_id
            FROM public.sched_lines
            ORDER BY line_id
            """
        )

    def get_tasks_for_run(self, run_id: int):
        return self.db.execute(
            """
            SELECT
              task_id,
              run_id,
              order_id,
              code,
              line_id,
              qty,
              setup_min,
              start_min,
              end_min,
              tardy_min,
              due_date
            FROM public.sched_tasks
            WHERE run_id = %s
            ORDER BY start_min, line_id, task_id
            """,
            (run_id,),
        )

    def get_unscheduled_for_run(self, run_id: int):
        return self.db.execute(
            """
            SELECT
              unscheduled_id,
              run_id,
              order_id,
              code,
              qty,
              reason
            FROM public.sched_unscheduled
            WHERE run_id = %s
            ORDER BY unscheduled_id
            """,
            (run_id,),
        )
