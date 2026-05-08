import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import time


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

    def execute(self, sql: str, params=(), strict: bool = False):
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
            if strict:
                raise RuntimeError(f"Errore DB: {e}") from e
            st.error(f"Errore DB: {e}")
            return [] if sql.strip().upper().startswith("SELECT") else False
        finally:
            if conn:
                conn.close()


class LineaManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._init_schema()
        self._use_sched = False
        self._last_source_check = 0.0
        self._sched_runtime_seeded = False
        self._sched_line_id_map = {}
        self._refresh_source_mode(force=True)

    def _table_exists(self, table_name: str) -> bool:
        res = self.db.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.tables
              WHERE table_schema='public' AND table_name=%s
            ) AS ok
            """,
            (table_name,),
        )
        return bool(res and res[0]["ok"])

    def _refresh_source_mode(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_source_check) < 20.0:
            return
        self._last_source_check = now

        has_sched_lines = self._table_exists("sched_lines")
        if not has_sched_lines:
            self._use_sched = False
            return

        cnt = self.db.execute("SELECT COUNT(*) AS c FROM public.sched_lines")
        sched_count = int(cnt[0]["c"]) if cnt else 0
        self._use_sched = sched_count > 0
        if self._use_sched and not self._sched_runtime_seeded:
            self._ensure_sched_runtime_rows()
            self._sched_runtime_seeded = True
        if self._use_sched and not self._sched_line_id_map:
            self._warm_sched_line_id_map(force=True)

    def _extract_line_number(self, line_id: str) -> int:
        m = re.findall(r"\d+", str(line_id or ""))
        if not m:
            return 0
        return int(m[-1])

    def _resolve_sched_line_id(self, linea_id: int) -> str | None:
        self._warm_sched_line_id_map()
        target = int(linea_id)
        return self._sched_line_id_map.get(target)

    def _warm_sched_line_id_map(self, force: bool = False):
        if self._sched_line_id_map and not force:
            return
        rows = self.db.execute("SELECT line_id FROM public.sched_lines ORDER BY line_id")
        mapped = {}
        for r in rows:
            lid = str(r["line_id"])
            n = self._extract_line_number(lid)
            if n > 0 and n not in mapped:
                mapped[n] = lid
        self._sched_line_id_map = mapped

    def _ensure_sched_runtime_rows(self):
        if not self._table_exists("sched_line_runtime"):
            return
        self.db.execute(
            """
            INSERT INTO public.sched_line_runtime(line_id, nome, vincoli)
            SELECT l.line_id, ('Linea ' || l.line_id), ''
            FROM public.sched_lines l
            ON CONFLICT (line_id) DO NOTHING
            """
        )

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

        # Nuovo schema runtime su sched_* (attivo quando sched_lines esiste e contiene righe)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS public.sched_line_runtime (
                line_id TEXT PRIMARY KEY REFERENCES public.sched_lines(line_id) ON DELETE CASCADE,
                nome TEXT,
                vincoli TEXT DEFAULT '',
                stato TEXT DEFAULT 'Attiva',
                motivo_fermo TEXT DEFAULT '',
                pezzi_fatti BIGINT DEFAULT 0,
                pezzi_scarti BIGINT DEFAULT 0,
                target_assegnato TEXT DEFAULT ''
            );
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS public.sched_production_events (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ NOT NULL DEFAULT now(),
                line_id TEXT NOT NULL REFERENCES public.sched_lines(line_id) ON DELETE CASCADE,
                order_id TEXT DEFAULT '',
                tipo TEXT NOT NULL CHECK (tipo IN ('OK','KO','START','STOP')),
                qta INTEGER NOT NULL DEFAULT 1
            );
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sched_prod_events_line_ts
            ON public.sched_production_events(line_id, ts);
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS public.sched_line_targets (
                giorno DATE NOT NULL,
                line_id TEXT NOT NULL REFERENCES public.sched_lines(line_id) ON DELETE CASCADE,
                target_ok INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (giorno, line_id)
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
        self._refresh_source_mode()
        if self._use_sched:
            rows = self.db.execute(
                """
                SELECT
                  l.line_id,
                  COALESCE(r.nome, '') AS nome,
                  COALESCE(r.vincoli, '') AS vincoli,
                  COALESCE(r.stato, 'Attiva') AS stato,
                  COALESCE(r.motivo_fermo, '') AS motivo_fermo,
                  COALESCE(r.pezzi_fatti, 0) AS pezzi_fatti,
                  COALESCE(r.pezzi_scarti, 0) AS pezzi_scarti,
                  COALESCE(r.target_assegnato, '') AS target_assegnato
                FROM public.sched_lines l
                LEFT JOIN public.sched_line_runtime r ON r.line_id = l.line_id
                ORDER BY l.line_id
                """
            )
            out = []
            for idx, r in enumerate(rows, start=1):
                line_id = str(r["line_id"])
                n = self._extract_line_number(line_id)
                out.append(
                    {
                        "id": n if n > 0 else idx,
                        "line_id": line_id,
                        "nome": r["nome"] if r["nome"] else f"Linea {line_id}",
                        "vincoli": r["vincoli"] or "",
                        "stato": r["stato"] or "Attiva",
                        "motivo_fermo": r["motivo_fermo"] or "",
                        "pezzi_fatti": int(r["pezzi_fatti"] or 0),
                        "pezzi_scarti": int(r["pezzi_scarti"] or 0),
                        "target_assegnato": r["target_assegnato"] or "",
                    }
                )
            return out
        return self.db.execute("SELECT * FROM linee_produttive ORDER BY id")

    def get_linea(self, linea_id: int):
        self._refresh_source_mode()
        if self._use_sched:
            target = int(linea_id)
            for row in self.get_status():
                if int(row["id"]) == target:
                    return row
            return None
        res = self.db.execute("SELECT * FROM linee_produttive WHERE id=%s", (linea_id,))
        return res[0] if res else None

    #
    # SCRITTURE (con storico)
    #
    def _log_evento(self, linea_id: int, tipo: str, qta: int = 1):
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return
            self.db.execute(
                """
                INSERT INTO public.sched_production_events(line_id, order_id, tipo, qta)
                VALUES (
                    %s,
                    COALESCE((SELECT target_assegnato FROM public.sched_line_runtime WHERE line_id=%s), ''),
                    %s,
                    %s
                )
                """,
                (lid, lid, tipo, qta),
            )
            return
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
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return
            if buoni > 0:
                self.db.execute(
                    """
                    INSERT INTO public.sched_production_events(line_id, order_id, tipo, qta)
                    VALUES (
                        %s,
                        COALESCE((SELECT target_assegnato FROM public.sched_line_runtime WHERE line_id=%s), ''),
                        'OK',
                        %s
                    )
                    """,
                    (lid, lid, buoni),
                )
                self.db.execute(
                    """
                    UPDATE public.sched_line_runtime
                    SET pezzi_fatti = COALESCE(pezzi_fatti, 0) + %s
                    WHERE line_id = %s
                    """,
                    (buoni, lid),
                )
            if scarti > 0:
                self.db.execute(
                    """
                    INSERT INTO public.sched_production_events(line_id, order_id, tipo, qta)
                    VALUES (
                        %s,
                        COALESCE((SELECT target_assegnato FROM public.sched_line_runtime WHERE line_id=%s), ''),
                        'KO',
                        %s
                    )
                    """,
                    (lid, lid, scarti),
                )
                self.db.execute(
                    """
                    UPDATE public.sched_line_runtime
                    SET pezzi_scarti = COALESCE(pezzi_scarti, 0) + %s
                    WHERE line_id = %s
                    """,
                    (scarti, lid),
                )
            return
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
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return
            current = self.db.execute(
                "SELECT stato FROM public.sched_line_runtime WHERE line_id=%s",
                (lid,),
            )
            old = current[0]["stato"] if current else None
            self.db.execute(
                """
                UPDATE public.sched_line_runtime
                SET stato=%s, motivo_fermo=%s
                WHERE line_id=%s
                """,
                (stato, motivo, lid),
            )
            if old and old != stato:
                if stato == "Attiva":
                    self.db.execute(
                        "INSERT INTO public.sched_production_events(line_id, order_id, tipo, qta) VALUES (%s, '', 'START', 1)",
                        (lid,),
                    )
                elif stato == "Ferma":
                    self.db.execute(
                        "INSERT INTO public.sched_production_events(line_id, order_id, tipo, qta) VALUES (%s, '', 'STOP', 1)",
                        (lid,),
                    )
            return
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
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return
            self.db.execute(
                "UPDATE public.sched_line_runtime SET target_assegnato=%s WHERE line_id=%s",
                (codice_commessa, lid),
            )
            return
        self.db.execute(
            "UPDATE linee_produttive SET target_assegnato=%s WHERE id=%s",
            (codice_commessa, linea_id),
        )

    #
    # KPI (HOME)
    #
    def get_produzione_per_ordine(self):
        self._refresh_source_mode()
        if self._use_sched:
            sql = """
                SELECT target_assegnato, SUM(pezzi_fatti) as tot
                FROM public.sched_line_runtime
                WHERE target_assegnato != ''
                GROUP BY target_assegnato
            """
            res = self.db.execute(sql)
            return {r["target_assegnato"]: int(r["tot"] or 0) for r in res}
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
        self._refresh_source_mode()
        if self._use_sched:
            res = self.db.execute("SELECT SUM(pezzi_fatti) as tot FROM public.sched_line_runtime")
            return int(res[0]["tot"]) if res and res[0]["tot"] else 0
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
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return []
            sql = """
                SELECT
                  (ts AT TIME ZONE 'Europe/Rome')::date AS giorno,
                  SUM(CASE WHEN tipo='OK' THEN qta ELSE 0 END) AS ok,
                  SUM(CASE WHEN tipo='KO' THEN qta ELSE 0 END) AS ko
                FROM public.sched_production_events
                WHERE line_id = %s
                  AND (ts AT TIME ZONE 'Europe/Rome')::date BETWEEN %s AND %s
                GROUP BY 1
                ORDER BY 1
            """
            return self.db.execute(sql, (lid, start_day, end_day))
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
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return []
            sql = """
                SELECT giorno, target_ok
                FROM public.sched_line_targets
                WHERE line_id = %s AND giorno BETWEEN %s AND %s
                ORDER BY giorno
            """
            return self.db.execute(sql, (lid, start_day, end_day))
        sql = """
            SELECT giorno, target_ok
            FROM obiettivi_linea_giorno
            WHERE linea_id = %s AND giorno BETWEEN %s AND %s
            ORDER BY giorno;
        """
        return self.db.execute(sql, (linea_id, start_day, end_day))

    def get_eventi_nel_range(self, linea_id: int, start_day: date, end_day: date) -> list:
        """
        Ritorna gli eventi (OK, KO, START, STOP) per una linea nel range di date.
        """
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return []
            sql = """
                SELECT ts, tipo, order_id, qta
                FROM public.sched_production_events
                WHERE line_id = %s
                  AND (ts AT TIME ZONE 'Europe/Rome')::date BETWEEN %s AND %s
                ORDER BY ts
            """
            return self.db.execute(sql, (lid, start_day, end_day))
        sql = """
            SELECT ts, tipo, ordine_codice, qta
            FROM produzione_eventi
            WHERE linea_id = %s
              AND (ts AT TIME ZONE 'Europe/Rome')::date BETWEEN %s AND %s
            ORDER BY ts;
        """
        return self.db.execute(sql, (linea_id, start_day, end_day))

    def set_obiettivo_giornaliero_range(self, linea_id: int, start_day: date, end_day: date, target_ok: int):
        """
        Imposta lo stesso target_ok per ogni giorno nel range (UPSERT).
        """
        self._refresh_source_mode()
        if self._use_sched:
            lid = self._resolve_sched_line_id(linea_id)
            if not lid:
                return
            giorno = start_day
            while giorno <= end_day:
                self.db.execute(
                    """
                    INSERT INTO public.sched_line_targets(giorno, line_id, target_ok)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (giorno, line_id)
                    DO UPDATE SET target_ok = EXCLUDED.target_ok
                    """,
                    (giorno, lid, target_ok),
                )
                giorno += timedelta(days=1)
            return
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
        self._use_sched = False
        self._last_source_check = 0.0
        self.init_orders()
        self._refresh_source_mode(force=True)

    def _table_exists(self, table_name: str) -> bool:
        res = self.db.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.tables
              WHERE table_schema='public' AND table_name=%s
            ) AS ok
            """,
            (table_name,),
        )
        return bool(res and res[0]["ok"])

    def _refresh_source_mode(self, force: bool = False):
        now = time.monotonic()
        if not force and (now - self._last_source_check) < 20.0:
            return
        self._last_source_check = now
        self._use_sched = self._table_exists("sched_orders")

    def _parse_due_date(self, deadline) -> date:
        if isinstance(deadline, date):
            return deadline
        raw = str(deadline or "").strip()
        if not raw:
            return date.today()
        try:
            return date.fromisoformat(raw)
        except Exception:
            pass
        for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except Exception:
                pass
        if "T" in raw:
            try:
                return date.fromisoformat(raw.split("T", 1)[0])
            except Exception:
                pass
        return date.today()

    def init_orders(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ordini_produzione (
                codice TEXT PRIMARY KEY,
                modello TEXT,
                quantita INTEGER,
                deadline TEXT
            );
        """)

    def _scheduler_cycle_table(self) -> str:
        if self._table_exists("sched_cycle_times"):
            return "sched_cycle_times"
        return "sched_cycle_lines"

    def _ensure_sched_defaults_for_order(self, order_id: str, code: str):
        lines = self.db.execute(
            "SELECT line_id FROM public.sched_lines ORDER BY line_id",
            strict=True,
        )
        if not lines:
            return

        for r in lines:
            self.db.execute(
                """
                INSERT INTO public.sched_eligible_lines(order_id, line_id)
                VALUES (%s, %s)
                ON CONFLICT (order_id, line_id) DO NOTHING
                """,
                (order_id, str(r["line_id"])),
                strict=True,
            )

        cycle_table = self._scheduler_cycle_table()
        existing = self.db.execute(
            f"""
            SELECT line_id, cycle_min_per_piece
            FROM public.{cycle_table}
            WHERE code = %s
            """,
            (code,),
            strict=True,
        )
        cycle_by_line = {str(x["line_id"]): float(x["cycle_min_per_piece"]) for x in existing}

        if len(cycle_by_line) < len(lines):
            avg_rows = self.db.execute(
                f"""
                SELECT line_id, AVG(cycle_min_per_piece) AS avg_cycle
                FROM public.{cycle_table}
                GROUP BY line_id
                """,
                strict=True,
            )
            avg_by_line = {str(x["line_id"]): float(x["avg_cycle"]) for x in avg_rows if x.get("avg_cycle") is not None}

            for r in lines:
                line_id = str(r["line_id"])
                if line_id in cycle_by_line:
                    continue
                cycle_value = float(avg_by_line.get(line_id, 1.0))
                self.db.execute(
                    f"""
                    INSERT INTO public.{cycle_table}(code, line_id, cycle_min_per_piece)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (code, line_id) DO NOTHING
                    """,
                    (code, line_id, cycle_value),
                    strict=True,
                )

    def add_ordine(self, codice: str, modello: str, quantita: int, deadline: str):
        self._refresh_source_mode()
        qty = int(quantita)
        if qty <= 0:
            raise RuntimeError("Quantita ordine non valida: deve essere > 0.")

        if self._use_sched:
            due_date = self._parse_due_date(deadline)
            self.db.execute(
                """
                INSERT INTO public.sched_orders(order_id, code, qty, due_date, due_serial)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (order_id)
                DO UPDATE SET
                  code = EXCLUDED.code,
                  qty = EXCLUDED.qty,
                  due_date = EXCLUDED.due_date,
                  due_serial = EXCLUDED.due_serial
                """,
                (codice, modello, qty, due_date, int(due_date.toordinal())),
                strict=True,
            )
            # Garantisce che l'ordine appena creato sia immediatamente schedulabile.
            self._ensure_sched_defaults_for_order(str(codice), str(modello))
            return
        self.db.execute(
            """
            INSERT INTO ordini_produzione (codice, modello, quantita, deadline)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (codice) DO UPDATE SET
              modello = EXCLUDED.modello,
              quantita = EXCLUDED.quantita,
              deadline = EXCLUDED.deadline
            """,
            (codice, modello, qty, deadline),
            strict=True,
        )

    def get_ordini(self):
        self._refresh_source_mode()
        if self._use_sched:
            rows = self.db.execute(
                """
                SELECT order_id, code, qty, due_date, due_serial
                FROM public.sched_orders
                ORDER BY due_serial NULLS LAST, order_id
                """
            )
            out = []
            for r in rows:
                due = r.get("due_date")
                due_txt = due.isoformat() if due else ""
                out.append(
                    {
                        "codice": r["order_id"],
                        "modello": r.get("code") or "",
                        "quantita": int(r.get("qty") or 0),
                        "deadline": due_txt,
                        "order_id": r["order_id"],
                        "code": r.get("code") or "",
                        "qty": int(r.get("qty") or 0),
                        "due_date": due_txt,
                        "due_serial": int(r.get("due_serial") or 0),
                    }
                )
            return out
        return self.db.execute("SELECT * FROM ordini_produzione")

    def get_ordini_text(self):
        data = self.get_ordini()
        if not data:
            return "Nessun ordine attivo."
        return "\n".join([f"- {o['codice']}: {o['quantita']}x {o['modello']} (Deadline: {o['deadline']})" for o in data])

    def reset_giornata(self):
        self._refresh_source_mode()
        if self._use_sched:
            # In modalita sched_* resettiamo solo la telemetria live.
            # Gli ordini master rimangono nel DB di pianificazione.
            self.db.execute(
                """
                UPDATE public.sched_line_runtime
                SET pezzi_fatti=0,
                    pezzi_scarti=0,
                    stato='Attiva',
                    motivo_fermo='',
                    target_assegnato=''
                """
            )
            return
        self.db.execute("DELETE FROM ordini_produzione")
        self.db.execute("""
            UPDATE linee_produttive
            SET pezzi_fatti=0, pezzi_scarti=0, stato='Attiva', motivo_fermo='', target_assegnato=''
        """)

    def get_totale_target(self):
        self._refresh_source_mode()
        if self._use_sched:
            res = self.db.execute("SELECT SUM(qty) as tot FROM public.sched_orders")
            return int(res[0]["tot"]) if res and res[0]["tot"] else 0
        res = self.db.execute("SELECT SUM(quantita) as tot FROM ordini_produzione")
        return res[0]["tot"] if res and res[0]["tot"] else 0


class SchedulerManager:
    """
    Gestione schedulatore avanzato:
    - crea/aggiorna schema sched_*
    - esegue strategie e salva run/tasks su DB
    """
    _schema_bootstrapped = False

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        root = Path(__file__).resolve().parent
        self.schema_path = root / "team_pack" / "scheduler_schema.sql"
        if not SchedulerManager._schema_bootstrapped:
            self.ensure_schema()
            SchedulerManager._schema_bootstrapped = True

    def _connect(self):
        return psycopg2.connect(self.db.db_url)

    def _table_exists(self, table_name: str) -> bool:
        res = self.db.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = %s
            ) AS ok
            """,
            (table_name,),
        )
        return bool(res and res[0]["ok"])

    def _get_table_columns(self, table_name: str) -> set[str]:
        rows = self.db.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {r["column_name"] for r in rows} if rows else set()

    def _schema_ready(self) -> bool:
        required_tables = [
            "sched_lines",
            "sched_orders",
            "sched_eligible_lines",
            "sched_runs",
            "sched_tasks",
            "sched_shift_config",
        ]
        return all(self._table_exists(t) for t in required_tables)

    def ensure_schema(self, force: bool = False):
        from team_pack.supabase_pipeline import apply_schema, ensure_strategy_constraint

        if not force and self._schema_ready():
            with self._connect() as conn:
                with conn.cursor() as cur:
                    ensure_strategy_constraint(cur)
            return

        with self._connect() as conn:
            with conn.cursor() as cur:
                apply_schema(cur, str(self.schema_path))
                ensure_strategy_constraint(cur)

    def _build_dataset_from_db(self):
        lines_raw = self.db.execute("SELECT line_id FROM public.sched_lines ORDER BY line_id", strict=True)
        orders_raw = self.db.execute(
            """
            SELECT order_id, code, qty, due_date, due_serial
            FROM public.sched_orders
            ORDER BY order_id
            """,
            strict=True,
        )
        eligible_raw = self.db.execute("SELECT order_id, line_id FROM public.sched_eligible_lines", strict=True)
        cycle_table = "sched_cycle_times"
        if not self._table_exists(cycle_table) and self._table_exists("sched_cycle_lines"):
            cycle_table = "sched_cycle_lines"
        cycle_raw = self.db.execute(
            f"SELECT code, line_id, cycle_min_per_piece FROM public.{cycle_table}",
            strict=True,
        )
        config_raw = self.db.execute(
            "SELECT line_id, current_code, loaded_qty FROM public.sched_current_config",
            strict=True,
        )
        setup_from_raw = self.db.execute(
            "SELECT line_id, to_code, setup_min FROM public.sched_setup_from_current",
            strict=True,
        )
        setup_between_raw = self.db.execute(
            "SELECT from_code, to_code, setup_min FROM public.sched_setup_between_codes",
            strict=True,
        )
        calendar_cfg = self._get_calendar_config()

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
            "calendar": calendar_cfg,
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

    def _get_calendar_config(self):
        cfg = {
            "shift_minutes": 480.0,
            "day_minutes": 1440.0,
            "shift_start_min": 360.0,
            "anchor_now": True,
        }
        if not self._table_exists("sched_shift_config"):
            return cfg
        rows = self.db.execute(
            """
            SELECT shift_minutes, day_minutes, shift_start_min
            FROM public.sched_shift_config
            WHERE config_id = 1
            """
        )
        if rows:
            r = rows[0]
            try:
                cfg["shift_minutes"] = float(r.get("shift_minutes") or 480.0)
            except Exception:
                cfg["shift_minutes"] = 480.0
            try:
                cfg["day_minutes"] = float(r.get("day_minutes") or 1440.0)
            except Exception:
                cfg["day_minutes"] = 1440.0
            try:
                cfg["shift_start_min"] = float(r.get("shift_start_min") or 360.0)
            except Exception:
                cfg["shift_start_min"] = 360.0

        if cfg["shift_minutes"] <= 0:
            cfg["shift_minutes"] = 480.0
        if cfg["day_minutes"] < cfg["shift_minutes"]:
            cfg["day_minutes"] = max(cfg["shift_minutes"], 1440.0)
        if cfg["shift_start_min"] < 0 or cfg["shift_start_min"] >= cfg["day_minutes"]:
            cfg["shift_start_min"] = 360.0

        today_serial = date.today().toordinal() - date(1899, 12, 30).toordinal()
        now_dt = datetime.now()
        minute_of_day = now_dt.hour * 60.0 + now_dt.minute + (now_dt.second / 60.0)
        shift_start = float(cfg["shift_start_min"])
        shift_minutes = float(cfg["shift_minutes"])
        shift_end = shift_start + shift_minutes
        if minute_of_day <= shift_start:
            in_shift = 0.0
        elif minute_of_day >= shift_end:
            in_shift = shift_minutes
        else:
            in_shift = minute_of_day - shift_start
        cfg["anchor_day_serial"] = float(today_serial)
        cfg["anchor_work_abs"] = float(today_serial * shift_minutes + in_shift)
        cfg["anchor_cal_abs"] = float(today_serial * float(cfg["day_minutes"]) + shift_start + in_shift)
        return cfg

    def _calendar_to_work_min(self, calendar_min: float, cfg: dict) -> float:
        day_minutes = float(cfg["day_minutes"])
        shift_minutes = float(cfg["shift_minutes"])
        shift_start = float(cfg["shift_start_min"])
        cal = max(0.0, float(calendar_min))
        day_idx = int(cal // day_minutes)
        in_day = cal - (day_idx * day_minutes)
        if in_day <= shift_start:
            in_shift = 0.0
        elif in_day >= (shift_start + shift_minutes):
            in_shift = shift_minutes
        else:
            in_shift = in_day - shift_start
        return (day_idx * shift_minutes) + in_shift

    def _work_to_calendar_parts(self, work_min: float, cfg: dict):
        shift_minutes = float(cfg["shift_minutes"])
        day_minutes = float(cfg["day_minutes"])
        shift_start = float(cfg["shift_start_min"])
        w = max(0.0, float(work_min))
        day_idx = int(w // shift_minutes)
        in_shift = w - (day_idx * shift_minutes)
        cal = (day_idx * day_minutes) + shift_start + in_shift
        return {
            "calendar_min": cal,
            "day": day_idx + 1,
            "shift_min": in_shift,
        }

    def _parse_datetime_like(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        s = str(value).strip()
        if not s:
            return None
        s = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m %H:%M"):
            try:
                d = datetime.strptime(s, fmt)
                if fmt == "%d/%m %H:%M":
                    now = datetime.now()
                    d = d.replace(year=now.year)
                return d
            except Exception:
                continue
        return None

    def _datetime_to_calendar_min(self, dt_value: datetime, cfg: dict) -> float:
        base = date(1899, 12, 30).toordinal()
        d_ord = dt_value.date().toordinal() - base
        minute_of_day = dt_value.hour * 60.0 + dt_value.minute + (dt_value.second / 60.0)
        return (d_ord * float(cfg["day_minutes"])) + minute_of_day

    def _calendar_min_to_datetime(self, calendar_min: float, cfg: dict) -> datetime:
        day_minutes = float(cfg["day_minutes"])
        cal = max(0.0, float(calendar_min))
        day_idx = int(cal // day_minutes)
        min_day = cal - (day_idx * day_minutes)
        hh = int(min_day // 60) % 24
        mm = int(min_day % 60)
        base_date = date(1899, 12, 30) + timedelta(days=day_idx)
        return datetime.combine(base_date, datetime.min.time()).replace(hour=hh, minute=mm)

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
        cycle_table = "sched_cycle_times"
        if not self._table_exists(cycle_table) and self._table_exists("sched_cycle_lines"):
            cycle_table = "sched_cycle_lines"

        tables = {
            "sched_lines": "sched_lines",
            "sched_orders": "sched_orders",
            "sched_eligible_lines": "sched_eligible_lines",
            "sched_cycle_times": cycle_table,
            "sched_shift_config": "sched_shift_config",
            "sched_runs": "sched_runs",
            "sched_tasks": "sched_tasks",
            "sched_unscheduled": "sched_unscheduled",
        }
        out = {}
        for key, table in tables.items():
            if not self._table_exists(table):
                out[key] = 0
                continue
            res = self.db.execute(f"SELECT COUNT(*) AS c FROM public.{table}")
            out[key] = int(res[0]["c"]) if res else 0
        return out

    def get_recent_runs(self, limit: int = 20):
        cols = self._get_table_columns("sched_runs")
        tardy_col = "total_tardy_min" if "total_tardy_min" in cols else ("total_tardy" if "total_tardy" in cols else "0")
        setup_col = "total_setup_min" if "total_setup_min" in cols else ("total_setup" if "total_setup" in cols else "0")
        makespan_col = "makespan_min" if "makespan_min" in cols else ("makespan" if "makespan" in cols else "0")
        avg_col = "avg_completion_min" if "avg_completion_min" in cols else ("avg_completion" if "avg_completion" in cols else "0")

        if not self._table_exists("sched_runs"):
            return []

        sql = f"""
            SELECT
              run_id,
              strategy,
              created_at,
              total_orders,
              scheduled_orders,
              unscheduled_orders,
              {tardy_col} AS total_tardy_min,
              {setup_col} AS total_setup_min,
              {makespan_col} AS makespan_min,
              {avg_col} AS avg_completion_min
            FROM public.sched_runs
            ORDER BY run_id DESC
            LIMIT %s
            """
        return self.db.execute(sql, (limit,))

    def get_scheduler_orders(self, limit: int = 500):
        return self.db.execute(
            """
            SELECT
              o.order_id,
              o.code,
              o.qty,
              o.due_date,
              o.due_serial,
              COALESCE(
                (SELECT COUNT(*) FROM public.sched_eligible_lines e WHERE e.order_id = o.order_id),
                0
              ) AS eligible_lines_count
            FROM public.sched_orders o
            ORDER BY o.due_serial NULLS LAST, o.order_id
            LIMIT %s
            """,
            (limit,),
        )

    def save_manual_run(self, edited_tasks):
        """
        Salva un run manuale partendo dai task editati dall'operatore.
        edited_tasks: lista di dict con almeno
          order_id, code, line_id, qty, setup_min, start_min, end_min, due_date
        """
        if not edited_tasks:
            raise RuntimeError("Nessun task da salvare.")

        orders = self.db.execute("SELECT order_id, due_serial, due_date FROM public.sched_orders", strict=True)
        calendar_cfg = self._get_calendar_config()
        shift_minutes = float(calendar_cfg["shift_minutes"])
        anchor_work_abs = float(calendar_cfg.get("anchor_work_abs", 0.0))
        due_by_order = {}
        serials = []
        for o in orders:
            s = float(o["due_serial"]) if o.get("due_serial") is not None else 0.0
            due_by_order[o["order_id"]] = {"due_serial": s, "due_date": o.get("due_date")}
            if s > 0:
                serials.append(s)
        base_serial = min(serials) if serials else 0.0

        normalized = []
        invalid_rows = []
        for row in edited_tasks:
            order_id = str(row.get("order_id", "")).strip()
            code = str(row.get("code", "")).strip()
            line_id = str(row.get("line_id", "")).strip()
            if not order_id or not code or not line_id:
                continue
            qty = int(float(row.get("qty", 0)))
            setup_min = float(row.get("setup_min", 0))
            start_dt = self._parse_datetime_like(row.get("start_at"))
            end_dt = self._parse_datetime_like(row.get("end_at"))

            if start_dt is not None:
                start_min = float(self._datetime_to_calendar_min(start_dt, calendar_cfg))
            else:
                raw_start_min = row.get("start_min")
                if raw_start_min in (None, ""):
                    invalid_rows.append(order_id or "<unknown>")
                    continue
                start_min = float(raw_start_min)
            if end_dt is not None:
                end_min = float(self._datetime_to_calendar_min(end_dt, calendar_cfg))
            else:
                raw_end_min = row.get("end_min")
                if raw_end_min in (None, ""):
                    invalid_rows.append(order_id or "<unknown>")
                    continue
                end_min = float(raw_end_min)
            if end_min < start_min:
                end_min = start_min

            start_work_min = float(row.get("start_work_min", self._calendar_to_work_min(start_min, calendar_cfg)))
            end_work_min = float(row.get("end_work_min", self._calendar_to_work_min(end_min, calendar_cfg)))
            if end_work_min < start_work_min:
                end_work_min = start_work_min
                end_min = max(end_min, start_min)

            due_info = due_by_order.get(order_id, {"due_serial": 0.0, "due_date": None})
            due_serial = float(due_info.get("due_serial") or 0.0)
            if due_serial > 0 and base_serial > 0:
                due_work_min = anchor_work_abs + ((due_serial - base_serial + 1.0) * shift_minutes)
                tardy_min = max(0.0, end_work_min - due_work_min)
            else:
                due_work_min = None
                tardy_min = max(0.0, float(row.get("tardy_min", 0)))

            due_date = row.get("due_date") or due_info.get("due_date")
            start_parts = self._work_to_calendar_parts(start_work_min, calendar_cfg)
            end_parts = self._work_to_calendar_parts(end_work_min, calendar_cfg)

            start_at = (
                start_dt.isoformat(timespec="minutes")
                if start_dt
                else self._calendar_min_to_datetime(start_min, calendar_cfg).isoformat(timespec="minutes")
            )
            end_at = (
                end_dt.isoformat(timespec="minutes")
                if end_dt
                else self._calendar_min_to_datetime(end_min, calendar_cfg).isoformat(timespec="minutes")
            )
            due_at = None
            if due_work_min is not None:
                due_parts = self._work_to_calendar_parts(due_work_min, calendar_cfg)
                due_cal = float(due_parts["calendar_min"])
                due_at = self._calendar_min_to_datetime(due_cal, calendar_cfg).isoformat(timespec="minutes")

            normalized.append(
                {
                    "order_id": order_id,
                    "code": code,
                    "line_id": line_id,
                    "qty": max(qty, 0),
                    "setup_min": max(setup_min, 0.0),
                    "start_min": max(start_min, 0.0),
                    "end_min": max(end_min, 0.0),
                    "tardy_min": max(tardy_min, 0.0),
                    "due_date": due_date,
                    "start_work_min": max(start_work_min, 0.0),
                    "end_work_min": max(end_work_min, 0.0),
                    "due_work_min": due_work_min,
                    "start_day": int(start_parts["day"]),
                    "end_day": int(end_parts["day"]),
                    "start_shift_min": float(start_parts["shift_min"]),
                    "end_shift_min": float(end_parts["shift_min"]),
                    "start_at": start_at,
                    "end_at": end_at,
                    "due_at": due_at,
                }
            )

        if invalid_rows:
            bad = ", ".join(invalid_rows[:8])
            raise RuntimeError(
                "Task manuali non validi: start_at/end_at (o start_min/end_min) mancanti per: "
                f"{bad}"
            )

        if not normalized:
            raise RuntimeError("Task non validi dopo validazione.")

        total_tardy = sum(t["tardy_min"] for t in normalized)
        total_setup = sum(t["setup_min"] for t in normalized)
        makespan = max(t["end_min"] for t in normalized)
        avg_completion = sum(t["end_min"] for t in normalized) / len(normalized)

        run_cols = self._get_table_columns("sched_runs")
        tardy_col = "total_tardy_min" if "total_tardy_min" in run_cols else "total_tardy"
        setup_col = "total_setup_min" if "total_setup_min" in run_cols else "total_setup"
        makespan_col = "makespan_min" if "makespan_min" in run_cols else "makespan"
        avg_col = "avg_completion_min" if "avg_completion_min" in run_cols else "avg_completion"

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO public.sched_runs(
                      strategy,
                      total_orders,
                      scheduled_orders,
                      unscheduled_orders,
                      {tardy_col},
                      {setup_col},
                      {makespan_col},
                      {avg_col}
                      {", shift_minutes" if "shift_minutes" in run_cols else ""}
                      {", day_minutes" if "day_minutes" in run_cols else ""}
                      {", shift_start_min" if "shift_start_min" in run_cols else ""}
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s
                      {", %s" if "shift_minutes" in run_cols else ""}
                      {", %s" if "day_minutes" in run_cols else ""}
                      {", %s" if "shift_start_min" in run_cols else ""}
                    )
                    RETURNING run_id
                    """,
                    tuple(
                        [
                            "manual",
                            len(normalized),
                            len(normalized),
                            0,
                            total_tardy,
                            total_setup,
                            makespan,
                            avg_completion,
                        ]
                        + ([calendar_cfg["shift_minutes"]] if "shift_minutes" in run_cols else [])
                        + ([calendar_cfg["day_minutes"]] if "day_minutes" in run_cols else [])
                        + ([calendar_cfg["shift_start_min"]] if "shift_start_min" in run_cols else [])
                    ),
                )
                run_id = int(cur.fetchone()[0])

                task_cols = self._get_table_columns("sched_tasks")
                insert_cols = [
                    "run_id",
                    "order_id",
                    "code",
                    "line_id",
                    "qty",
                    "setup_min",
                    "start_min",
                    "end_min",
                    "tardy_min",
                    "due_date",
                ]
                for extra_col in [
                    "start_work_min",
                    "end_work_min",
                    "due_work_min",
                    "start_day",
                    "end_day",
                    "start_shift_min",
                    "end_shift_min",
                    "start_at",
                    "end_at",
                    "due_at",
                ]:
                    if extra_col in task_cols:
                        insert_cols.append(extra_col)

                for t in normalized:
                    row_map = {
                        "run_id": run_id,
                        "order_id": t["order_id"],
                        "code": t["code"],
                        "line_id": t["line_id"],
                        "qty": t["qty"],
                        "setup_min": t["setup_min"],
                        "start_min": t["start_min"],
                        "end_min": t["end_min"],
                        "tardy_min": t["tardy_min"],
                        "due_date": t["due_date"],
                        "start_work_min": t.get("start_work_min"),
                        "end_work_min": t.get("end_work_min"),
                        "due_work_min": t.get("due_work_min"),
                        "start_day": t.get("start_day"),
                        "end_day": t.get("end_day"),
                        "start_shift_min": t.get("start_shift_min"),
                        "end_shift_min": t.get("end_shift_min"),
                        "start_at": t.get("start_at"),
                        "end_at": t.get("end_at"),
                        "due_at": t.get("due_at"),
                    }
                    cur.execute(
                        f"""
                        INSERT INTO public.sched_tasks(
                          {", ".join(insert_cols)}
                        )
                        VALUES ({", ".join(["%s"] * len(insert_cols))})
                        """,
                        tuple(row_map[c] for c in insert_cols),
                    )

        return run_id

    def get_scheduler_lines(self):
        return self.db.execute(
            """
            SELECT line_id
            FROM public.sched_lines
            ORDER BY line_id
            """
        )

    def get_scheduler_calendar_config(self):
        return self._get_calendar_config()

    def get_tasks_for_run(self, run_id: int):
        return self.db.execute(
            """
            SELECT *
            FROM public.sched_tasks
            WHERE run_id = %s
            ORDER BY COALESCE(start_at, to_timestamp(start_min * 60.0)), line_id, task_id
            """,
            (run_id,),
        )

    def get_unscheduled_for_run(self, run_id: int):
        if not self._table_exists("sched_unscheduled"):
            return []
        cols = self._get_table_columns("sched_unscheduled")
        id_col = "unscheduled_id" if "unscheduled_id" in cols else "unscheduled"
        return self.db.execute(
            f"""
            SELECT
              {id_col} AS unscheduled_id,
              run_id,
              order_id,
              code,
              qty,
              reason
            FROM public.sched_unscheduled
            WHERE run_id = %s
            ORDER BY {id_col}
            """,
            (run_id,),
        )
