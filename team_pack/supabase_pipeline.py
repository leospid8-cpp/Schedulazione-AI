import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import psycopg2
from psycopg2.extras import execute_batch

from team_pack.strategy_due_date import run as run_due_date
from team_pack.strategy_min_setup import run as run_min_setup
from team_pack.strategy_balanced import run as run_balanced


def load_dataset(path: str) -> Dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def apply_schema(cursor, schema_path: str):
    sql = Path(schema_path).read_text(encoding="utf-8")
    cursor.execute(sql)


def ensure_strategy_constraint(cursor):
    cursor.execute(
        """
        ALTER TABLE public.sched_runs
        DROP CONSTRAINT IF EXISTS sched_runs_strategy_check;
        """
    )
    cursor.execute(
        """
        ALTER TABLE public.sched_runs
        ADD CONSTRAINT sched_runs_strategy_check
        CHECK (strategy IN ('due_date', 'min_setup', 'balanced', 'manual'));
        """
    )


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _delete_by_text_keys(cursor, table: str, column: str, keys: Sequence[str]):
    if not keys:
        return
    cursor.execute(f"DELETE FROM public.{table} WHERE {column} = ANY(%s)", (list(keys),))


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
          SELECT 1
          FROM information_schema.tables
          WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table,),
    )
    return bool(cursor.fetchone()[0])


def _insert_lines(cursor, lines: List[Dict[str, Any]]):
    rows = [(str(l["line_id"]),) for l in lines if l.get("line_id")]
    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_lines(line_id)
        VALUES (%s)
        ON CONFLICT (line_id) DO NOTHING
        """,
        rows,
        page_size=500,
    )


def _insert_orders(cursor, orders: List[Dict[str, Any]]):
    rows = []
    for o in orders:
        order_id = str(o.get("order_id", ""))
        if not order_id:
            continue
        rows.append(
            (
                order_id,
                str(o.get("code", "")),
                _to_int(o.get("qty"), 0),
                o.get("due_date"),
                _to_int(o.get("due_serial"), 0),
            )
        )
    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_orders(order_id, code, qty, due_date, due_serial)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (order_id) DO UPDATE SET
          code = EXCLUDED.code,
          qty = EXCLUDED.qty,
          due_date = EXCLUDED.due_date,
          due_serial = EXCLUDED.due_serial
        """,
        rows,
        page_size=500,
    )


def _refresh_eligible_lines(cursor, orders: List[Dict[str, Any]]):
    order_ids = [str(o.get("order_id")) for o in orders if o.get("order_id")]
    _delete_by_text_keys(cursor, "sched_eligible_lines", "order_id", order_ids)

    rows = []
    for o in orders:
        order_id = str(o.get("order_id", ""))
        if not order_id:
            continue
        for line_id in o.get("eligible_lines", []):
            rows.append((order_id, str(line_id)))

    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_eligible_lines(order_id, line_id)
        VALUES (%s, %s)
        ON CONFLICT (order_id, line_id) DO NOTHING
        """,
        rows,
        page_size=1000,
    )


def _refresh_cycle_times(cursor, orders: List[Dict[str, Any]], cycle_table: str):
    codes = sorted({str(o.get("code", "")) for o in orders if o.get("code")})
    _delete_by_text_keys(cursor, cycle_table, "code", codes)

    rows = []
    for o in orders:
        code = str(o.get("code", ""))
        if not code:
            continue
        for line_id, cycle in o.get("cycle_minutes_by_line", {}).items():
            cycle_f = _to_float(cycle, 0.0)
            if cycle_f <= 0:
                continue
            rows.append((code, str(line_id), cycle_f))

    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.{cycle_table}(code, line_id, cycle_min_per_piece)
        VALUES (%s, %s, %s)
        ON CONFLICT (code, line_id) DO UPDATE SET
          cycle_min_per_piece = EXCLUDED.cycle_min_per_piece
        """.replace("{cycle_table}", cycle_table),
        rows,
        page_size=1000,
    )


def _refresh_current_config(cursor, current_config: Dict[str, Dict[str, Any]]):
    line_ids = [str(k) for k in current_config.keys()]
    _delete_by_text_keys(cursor, "sched_current_config", "line_id", line_ids)

    rows = []
    for line_id, cfg in current_config.items():
        rows.append((str(line_id), str(cfg.get("current_code", "")), _to_int(cfg.get("loaded_qty"), 0)))
    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_current_config(line_id, current_code, loaded_qty)
        VALUES (%s, %s, %s)
        ON CONFLICT (line_id) DO UPDATE SET
          current_code = EXCLUDED.current_code,
          loaded_qty = EXCLUDED.loaded_qty
        """,
        rows,
        page_size=500,
    )


def _refresh_setup_from_current(cursor, setup_from_current: Dict[str, Dict[str, Any]]):
    line_ids = [str(k) for k in setup_from_current.keys()]
    _delete_by_text_keys(cursor, "sched_setup_from_current", "line_id", line_ids)

    rows = []
    for line_id, inner in setup_from_current.items():
        for to_code, setup in inner.items():
            rows.append((str(line_id), str(to_code), _to_float(setup, 0.0)))
    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_setup_from_current(line_id, to_code, setup_min)
        VALUES (%s, %s, %s)
        ON CONFLICT (line_id, to_code) DO UPDATE SET
          setup_min = EXCLUDED.setup_min
        """,
        rows,
        page_size=1000,
    )


def _refresh_setup_between_codes(cursor, setup_between: Dict[str, Dict[str, Any]], codes: Sequence[str]):
    if codes:
        cursor.execute(
            """
            DELETE FROM public.sched_setup_between_codes
            WHERE from_code = ANY(%s) OR to_code = ANY(%s)
            """,
            (list(codes), list(codes)),
        )

    rows = []
    for from_code, inner in setup_between.items():
        for to_code, setup in inner.items():
            rows.append((str(from_code), str(to_code), _to_float(setup, 0.0)))

    if not rows:
        return
    execute_batch(
        cursor,
        """
        INSERT INTO public.sched_setup_between_codes(from_code, to_code, setup_min)
        VALUES (%s, %s, %s)
        ON CONFLICT (from_code, to_code) DO UPDATE SET
          setup_min = EXCLUDED.setup_min
        """,
        rows,
        page_size=1000,
    )


def import_scheduler_input(cursor, dataset: Dict[str, Any]):
    lines = dataset.get("lines", [])
    orders = dataset.get("orders", [])
    current_cfg = dataset.get("current_config", {})
    setup_minutes = dataset.get("setup_minutes", {})

    _insert_lines(cursor, lines)
    _insert_orders(cursor, orders)
    _refresh_eligible_lines(cursor, orders)
    cycle_table = "sched_cycle_times" if _table_exists(cursor, "sched_cycle_times") else "sched_cycle_lines"
    _refresh_cycle_times(cursor, orders, cycle_table)
    _refresh_current_config(cursor, current_cfg)
    _refresh_setup_from_current(cursor, setup_minutes.get("from_current", {}))
    order_codes = sorted({str(o.get("code", "")) for o in orders if o.get("code")})
    _refresh_setup_between_codes(cursor, setup_minutes.get("between_codes", {}), order_codes)


def persist_run(cursor, result: Dict[str, Any]) -> int:
    kpi = result.get("kpi", {})
    tasks = result.get("tasks", [])
    unscheduled = result.get("unscheduled", [])

    total_orders = _to_int(kpi.get("total_orders"), len(tasks) + len(unscheduled))
    scheduled_orders = _to_int(kpi.get("scheduled_orders"), len(tasks))
    unscheduled_orders = _to_int(kpi.get("unscheduled_orders"), len(unscheduled))

    cursor.execute(
        """
        INSERT INTO public.sched_runs(
          strategy,
          total_orders,
          scheduled_orders,
          unscheduled_orders,
          total_tardy_min,
          total_setup_min,
          makespan_min,
          avg_completion_min
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING run_id
        """,
        (
            str(result.get("strategy", "")),
            total_orders,
            scheduled_orders,
            unscheduled_orders,
            _to_float(kpi.get("total_tardy_min"), 0.0),
            _to_float(kpi.get("total_setup_min"), 0.0),
            _to_float(kpi.get("makespan_min"), 0.0),
            _to_float(kpi.get("avg_completion_min"), 0.0),
        ),
    )
    run_id = _to_int(cursor.fetchone()[0])

    task_rows = []
    for t in tasks:
        task_rows.append(
            (
                run_id,
                str(t.get("order_id", "")),
                str(t.get("code", "")),
                str(t.get("line_id", "")),
                _to_int(t.get("qty"), 0),
                _to_float(t.get("setup_min"), 0.0),
                _to_float(t.get("start_min"), 0.0),
                _to_float(t.get("end_min"), 0.0),
                _to_float(t.get("tardy_min"), 0.0),
                t.get("due_date"),
            )
        )

    if task_rows:
        execute_batch(
            cursor,
            """
            INSERT INTO public.sched_tasks(
              run_id, order_id, code, line_id, qty, setup_min, start_min, end_min, tardy_min, due_date
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            task_rows,
            page_size=1000,
        )

    unsched_rows = []
    for u in unscheduled:
        unsched_rows.append(
            (
                run_id,
                str(u.get("order_id", "")),
                str(u.get("code", "")),
                _to_int(u.get("qty"), 0),
                str(u.get("reason", "")),
            )
        )

    if unsched_rows:
        execute_batch(
            cursor,
            """
            INSERT INTO public.sched_unscheduled(run_id, order_id, code, qty, reason)
            VALUES (%s, %s, %s, %s, %s)
            """,
            unsched_rows,
            page_size=1000,
        )

    return run_id


def run_requested_strategies(dataset: Dict[str, Any], strategy: str) -> List[Dict[str, Any]]:
    if strategy == "due_date":
        return [run_due_date(dataset)]
    if strategy == "min_setup":
        return [run_min_setup(dataset)]
    if strategy == "balanced":
        return [run_balanced(dataset)]
    if strategy == "both":
        return [run_due_date(dataset), run_min_setup(dataset)]
    return [run_due_date(dataset), run_min_setup(dataset), run_balanced(dataset)]


def main():
    parser = argparse.ArgumentParser(
        description="Create schema, import scheduler input, run strategies, persist runs to Supabase."
    )
    parser.add_argument("--dataset", default="team_pack/data/scheduler_dataset.json")
    parser.add_argument("--schema", default="team_pack/scheduler_schema.sql")
    parser.add_argument("--db-url", default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--strategy", choices=["due_date", "min_setup", "balanced", "both", "all"], default="both")
    parser.add_argument("--skip-schema", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    results = run_requested_strategies(dataset, args.strategy)

    if args.dry_run:
        print("DRY RUN: no DB write.")
        for result in results:
            print(f"- {result['strategy']} KPI: {result['kpi']}")
        return

    if not args.db_url:
        raise RuntimeError("SUPABASE_URL non configurata. Passa --db-url o imposta variabile ambiente SUPABASE_URL.")

    conn = psycopg2.connect(args.db_url)
    try:
        with conn:
            with conn.cursor() as cursor:
                if not args.skip_schema:
                    apply_schema(cursor, args.schema)
                ensure_strategy_constraint(cursor)
                import_scheduler_input(cursor, dataset)
                run_ids = []
                for result in results:
                    run_ids.append((result["strategy"], persist_run(cursor, result)))
        print("Pipeline completata.")
        for strategy_name, run_id in run_ids:
            print(f"- strategy={strategy_name} run_id={run_id}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
