import argparse
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import execute_batch


ROME_TZ = ZoneInfo("Europe/Rome")


def table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1
          FROM information_schema.tables
          WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    return bool(cur.fetchone()[0])


def get_shift_config(cur):
    if not table_exists(cur, "sched_shift_config"):
        return 360.0, 480.0
    cur.execute(
        """
        SELECT shift_start_min, shift_minutes
        FROM public.sched_shift_config
        WHERE config_id = 1
        """
    )
    row = cur.fetchone()
    if not row:
        return 360.0, 480.0
    start_min = float(row[0] or 360.0)
    shift_min = float(row[1] or 480.0)
    if start_min < 0:
        start_min = 0.0
    if shift_min <= 0:
        shift_min = 480.0
    return start_min, shift_min


def random_ts_for_day(day_dt: datetime, shift_start_min: float, shift_minutes: float) -> datetime:
    minute_in_shift = random.randint(0, max(1, int(shift_minutes) - 1))
    return day_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        minutes=shift_start_min + minute_in_shift
    )


def ensure_sched_runtime(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.sched_line_runtime (
            line_id TEXT PRIMARY KEY REFERENCES public.sched_lines(line_id) ON DELETE CASCADE,
            nome TEXT,
            vincoli TEXT DEFAULT '',
            stato TEXT DEFAULT 'Attiva',
            motivo_fermo TEXT DEFAULT '',
            pezzi_fatti BIGINT DEFAULT 0,
            pezzi_scarti BIGINT DEFAULT 0,
            target_assegnato TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        INSERT INTO public.sched_line_runtime(line_id, nome, vincoli)
        SELECT l.line_id, ('Linea ' || l.line_id), ''
        FROM public.sched_lines l
        ON CONFLICT (line_id) DO NOTHING
        """
    )


def seed_sched_history(cur, days: int, events_per_day: int, reset_window: bool):
    cur.execute("SELECT line_id FROM public.sched_lines ORDER BY line_id")
    line_ids = [str(r[0]) for r in cur.fetchall()]
    if not line_ids:
        raise RuntimeError("Nessuna linea in sched_lines.")

    ensure_sched_runtime(cur)
    shift_start_min, shift_minutes = get_shift_config(cur)

    if reset_window:
        cur.execute(
            """
            DELETE FROM public.sched_production_events
            WHERE order_id = 'HIST_SEED'
              AND (ts AT TIME ZONE 'Europe/Rome')::date >= (CURRENT_DATE - (%s * INTERVAL '1 day'))
            """,
            (days,),
        )

    now_rome = datetime.now(ROME_TZ)
    rows = []
    for back in range(days - 1, -1, -1):
        day = (now_rome - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        for line_id in line_ids:
            start_ts = day + timedelta(minutes=shift_start_min)
            stop_ts = day + timedelta(minutes=shift_start_min + shift_minutes)
            rows.append((start_ts, line_id, "HIST_SEED", "START", 1))

            for _ in range(events_per_day):
                ts = random_ts_for_day(day, shift_start_min, shift_minutes)
                evt = "OK" if random.random() < 0.86 else "KO"
                qty = random.randint(1, 8) if evt == "OK" else random.randint(1, 2)
                rows.append((ts, line_id, "HIST_SEED", evt, qty))

            rows.append((stop_ts, line_id, "HIST_SEED", "STOP", 1))

    execute_batch(
        cur,
        """
        INSERT INTO public.sched_production_events(ts, line_id, order_id, tipo, qta)
        VALUES (%s, %s, %s, %s, %s)
        """,
        rows,
        page_size=2000,
    )

    cur.execute(
        """
        WITH agg AS (
          SELECT
            line_id,
            SUM(CASE WHEN tipo='OK' THEN qta ELSE 0 END) AS ok_sum,
            SUM(CASE WHEN tipo='KO' THEN qta ELSE 0 END) AS ko_sum
          FROM public.sched_production_events
          WHERE (ts AT TIME ZONE 'Europe/Rome')::date = CURRENT_DATE
          GROUP BY line_id
        )
        UPDATE public.sched_line_runtime r
        SET pezzi_fatti = COALESCE(a.ok_sum, 0),
            pezzi_scarti = COALESCE(a.ko_sum, 0),
            stato = 'Attiva',
            motivo_fermo = ''
        FROM agg a
        WHERE r.line_id = a.line_id
        """
    )

    return len(line_ids), len(rows)


def seed_legacy_history(cur, days: int, events_per_day: int, reset_window: bool):
    cur.execute("SELECT id FROM linee_produttive ORDER BY id")
    line_ids = [int(r[0]) for r in cur.fetchall()]
    if not line_ids:
        raise RuntimeError("Nessuna linea in linee_produttive.")

    if reset_window:
        cur.execute(
            """
            DELETE FROM produzione_eventi
            WHERE ordine_codice = 'HIST_SEED'
              AND (ts AT TIME ZONE 'Europe/Rome')::date >= (CURRENT_DATE - (%s * INTERVAL '1 day'))
            """,
            (days,),
        )

    now_rome = datetime.now(ROME_TZ)
    rows = []
    shift_start_min = 360.0
    shift_minutes = 480.0
    for back in range(days - 1, -1, -1):
        day = (now_rome - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        for line_id in line_ids:
            start_ts = day + timedelta(minutes=shift_start_min)
            stop_ts = day + timedelta(minutes=shift_start_min + shift_minutes)
            rows.append((start_ts, line_id, "HIST_SEED", "START", 1))

            for _ in range(events_per_day):
                ts = random_ts_for_day(day, shift_start_min, shift_minutes)
                evt = "OK" if random.random() < 0.86 else "KO"
                qty = random.randint(1, 8) if evt == "OK" else random.randint(1, 2)
                rows.append((ts, line_id, "HIST_SEED", evt, qty))

            rows.append((stop_ts, line_id, "HIST_SEED", "STOP", 1))

    execute_batch(
        cur,
        """
        INSERT INTO produzione_eventi(ts, linea_id, ordine_codice, tipo, qta)
        VALUES (%s, %s, %s, %s, %s)
        """,
        rows,
        page_size=2000,
    )

    cur.execute(
        """
        WITH agg AS (
          SELECT
            linea_id,
            SUM(CASE WHEN tipo='OK' THEN qta ELSE 0 END) AS ok_sum,
            SUM(CASE WHEN tipo='KO' THEN qta ELSE 0 END) AS ko_sum
          FROM produzione_eventi
          WHERE (ts AT TIME ZONE 'Europe/Rome')::date = CURRENT_DATE
          GROUP BY linea_id
        )
        UPDATE linee_produttive l
        SET pezzi_fatti = COALESCE(a.ok_sum, 0),
            pezzi_scarti = COALESCE(a.ko_sum, 0),
            stato = 'Attiva',
            motivo_fermo = ''
        FROM agg a
        WHERE l.id = a.linea_id
        """
    )

    return len(line_ids), len(rows)


def main():
    parser = argparse.ArgumentParser(description="Genera dati storici per ogni linea produttiva.")
    parser.add_argument("--db-url", default=os.getenv("SUPABASE_URL"), help="Connection string PostgreSQL/Supabase")
    parser.add_argument("--days", type=int, default=21, help="Numero giorni storici da generare")
    parser.add_argument("--events-per-day", type=int, default=28, help="Eventi produzione per linea/giorno")
    parser.add_argument(
        "--reset-window",
        action="store_true",
        help="Cancella prima i soli eventi seed (order_id/ordine_codice = HIST_SEED) nello stesso intervallo giorni",
    )
    args = parser.parse_args()

    if not args.db_url:
        raise RuntimeError("SUPABASE_URL mancante. Passa --db-url o imposta variabile ambiente SUPABASE_URL.")
    if args.days <= 0:
        raise RuntimeError("--days deve essere > 0")
    if args.events_per_day <= 0:
        raise RuntimeError("--events-per-day deve essere > 0")

    conn = psycopg2.connect(args.db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                if table_exists(cur, "sched_lines") and table_exists(cur, "sched_production_events"):
                    n_lines, n_rows = seed_sched_history(
                        cur,
                        days=args.days,
                        events_per_day=args.events_per_day,
                        reset_window=args.reset_window,
                    )
                    mode = "sched"
                elif table_exists(cur, "linee_produttive") and table_exists(cur, "produzione_eventi"):
                    n_lines, n_rows = seed_legacy_history(
                        cur,
                        days=args.days,
                        events_per_day=args.events_per_day,
                        reset_window=args.reset_window,
                    )
                    mode = "legacy"
                else:
                    raise RuntimeError("Schema MES non trovato (né sched_* né legacy).")
        print(f"Storico generato. mode={mode} linee={n_lines} righe_inserite={n_rows}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
