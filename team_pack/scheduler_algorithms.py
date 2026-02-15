from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
from typing import Any, Dict, List, Optional, Tuple


EXCEL_BASE = date(1899, 12, 30)


@dataclass
class Order:
    order_id: str
    code: str
    qty: float
    due_min: float
    due_date: Optional[str]
    eligible_lines: List[str]
    cycle_minutes_by_line: Dict[str, float]
    due_sort_key: Tuple[float, int]


@dataclass
class Task:
    order_id: str
    code: str
    line_id: str
    qty: float
    setup_min: float
    start_min: float
    end_min: float
    tardy_min: float
    due_date: Optional[str]
    start_work_min: float
    end_work_min: float
    due_work_min: Optional[float]
    start_day: int
    end_day: int
    start_shift_min: float
    end_shift_min: float
    start_at: str
    end_at: str


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _excel_serial_from_iso(iso_date: Optional[str]) -> Optional[float]:
    if not iso_date:
        return None
    try:
        y, m, d = [int(x) for x in str(iso_date).split("-")]
        return float(date(y, m, d).toordinal() - EXCEL_BASE.toordinal())
    except Exception:
        return None


def _today_excel_serial(now_dt: Optional[datetime] = None) -> int:
    now_dt = now_dt or datetime.now()
    return int(now_dt.date().toordinal() - EXCEL_BASE.toordinal())


def _calendar_config(dataset: Dict[str, Any]) -> Dict[str, float]:
    raw = dataset.get("calendar", {}) if isinstance(dataset, dict) else {}
    shift_minutes = _safe_float(raw.get("shift_minutes"), 480.0)
    day_minutes = _safe_float(raw.get("day_minutes"), 1440.0)
    shift_start_min = _safe_float(raw.get("shift_start_min"), 0.0)
    anchor_now = bool(raw.get("anchor_now", True))

    if shift_minutes <= 0:
        shift_minutes = 480.0
    if day_minutes < shift_minutes:
        day_minutes = max(shift_minutes, 1440.0)
    if shift_start_min < 0 or shift_start_min >= day_minutes:
        shift_start_min = 0.0

    cfg = {
        "shift_minutes": shift_minutes,
        "day_minutes": day_minutes,
        "shift_start_min": shift_start_min,
        "anchor_now": anchor_now,
    }

    now_dt = datetime.now()
    today_serial = _today_excel_serial(now_dt)

    minute_of_day = (now_dt.hour * 60.0) + now_dt.minute + (now_dt.second / 60.0)
    shift_start = shift_start_min
    shift_end = shift_start + shift_minutes
    if minute_of_day <= shift_start:
        in_shift = 0.0
    elif minute_of_day >= shift_end:
        in_shift = shift_minutes
    else:
        in_shift = minute_of_day - shift_start

    anchor_work_abs = (today_serial * shift_minutes) + (in_shift if anchor_now else 0.0)
    anchor_cal_abs = (today_serial * day_minutes) + shift_start + (in_shift if anchor_now else 0.0)

    cfg["anchor_day_serial"] = float(today_serial)
    cfg["anchor_work_abs"] = float(anchor_work_abs)
    cfg["anchor_cal_abs"] = float(anchor_cal_abs)
    return cfg


def _work_abs_to_parts(work_abs: float, cfg: Dict[str, float]) -> Dict[str, Any]:
    shift_minutes = cfg["shift_minutes"]
    day_minutes = cfg["day_minutes"]
    shift_start = cfg["shift_start_min"]

    w = max(0.0, float(work_abs))
    day_serial = int(w // shift_minutes)
    in_shift = w - (day_serial * shift_minutes)
    cal_abs = (day_serial * day_minutes) + shift_start + in_shift

    dt = datetime.combine(EXCEL_BASE + timedelta(days=day_serial), datetime.min.time()) + timedelta(minutes=shift_start + in_shift)
    rel_day = int(day_serial - cfg["anchor_day_serial"] + 1)

    return {
        "day_serial": day_serial,
        "relative_day": rel_day,
        "shift_min": in_shift,
        "calendar_abs_min": cal_abs,
        "at": dt,
    }


def _compute_due_context(dataset: Dict[str, Any], cfg: Dict[str, float]) -> Dict[str, float]:
    shift_minutes = cfg["shift_minutes"]
    due_minutes: Dict[str, float] = {}
    for o in dataset.get("orders", []):
        serial = _safe_float(o.get("due_serial"), 0.0)
        if serial <= 0:
            serial = _excel_serial_from_iso(o.get("due_date")) or 0.0
        if serial > 0:
            due_minutes[o.get("order_id", "")] = serial * shift_minutes
        else:
            due_minutes[o.get("order_id", "")] = float("inf")
    return due_minutes


def _setup_time(dataset: Dict[str, Any], line_id: str, from_code: Optional[str], to_code: str) -> float:
    if not to_code:
        return 0.0
    if from_code:
        between = dataset.get("setup_minutes", {}).get("between_codes", {})
        return _safe_float(between.get(from_code, {}).get(to_code), 60.0)
    from_current = dataset.get("setup_minutes", {}).get("from_current", {})
    return _safe_float(from_current.get(line_id, {}).get(to_code), 0.0)


def _to_order_objects(dataset: Dict[str, Any], due_minutes: Dict[str, float]) -> List[Order]:
    out: List[Order] = []
    for idx, raw in enumerate(dataset.get("orders", [])):
        order_id = str(raw.get("order_id", f"ORD_{idx+1:03d}"))
        code = str(raw.get("code", ""))
        qty = _safe_float(raw.get("qty"), 0.0)
        due_serial = _safe_float(raw.get("due_serial"), 0.0)
        due_key = due_serial if due_serial > 0 else float("inf")
        out.append(
            Order(
                order_id=order_id,
                code=code,
                qty=qty,
                due_min=due_minutes.get(order_id, float("inf")),
                due_date=raw.get("due_date"),
                eligible_lines=list(raw.get("eligible_lines", [])),
                cycle_minutes_by_line={k: _safe_float(v, 0.0) for k, v in raw.get("cycle_minutes_by_line", {}).items()},
                due_sort_key=(due_key, idx),
            )
        )
    return out


def _kpi(tasks: List[Task], unscheduled: List[Dict[str, Any]], cfg: Dict[str, float]) -> Dict[str, float]:
    total_tardy = sum(t.tardy_min for t in tasks)
    total_setup = sum(t.setup_min for t in tasks)

    if tasks:
        makespan_cal = max(t.end_min for t in tasks) - cfg["anchor_cal_abs"]
        makespan_work = max(t.end_work_min for t in tasks) - cfg["anchor_work_abs"]
        avg_completion = (sum(t.end_min for t in tasks) / len(tasks)) - cfg["anchor_cal_abs"]
        avg_completion_work = (sum(t.end_work_min for t in tasks) / len(tasks)) - cfg["anchor_work_abs"]
    else:
        makespan_cal = 0.0
        makespan_work = 0.0
        avg_completion = 0.0
        avg_completion_work = 0.0

    total_orders = len(tasks) + len(unscheduled)
    return {
        "total_tardy_min": round(total_tardy, 2),
        "total_setup_min": round(total_setup, 2),
        "makespan_min": round(max(0.0, makespan_cal), 2),
        "makespan_work_min": round(max(0.0, makespan_work), 2),
        "avg_completion_min": round(max(0.0, avg_completion), 2),
        "avg_completion_work_min": round(max(0.0, avg_completion_work), 2),
        "total_orders": total_orders,
        "scheduled_orders": len(tasks),
        "unscheduled_orders": len(unscheduled),
    }


def _tasks_to_dict(tasks: List[Task]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, t in enumerate(tasks, start=1):
        due_work_min = None
        if t.due_work_min is not None and math.isfinite(t.due_work_min):
            due_work_min = round(t.due_work_min, 2)
        out.append(
            {
                "task_id": f"T{i:04d}",
                "order_id": t.order_id,
                "code": t.code,
                "line_id": t.line_id,
                "qty": int(t.qty) if float(t.qty).is_integer() else t.qty,
                "setup_min": round(t.setup_min, 2),
                "start_min": round(t.start_min, 2),
                "end_min": round(t.end_min, 2),
                "tardy_min": round(t.tardy_min, 2),
                "due_date": t.due_date,
                "start_work_min": round(t.start_work_min, 2),
                "end_work_min": round(t.end_work_min, 2),
                "due_work_min": due_work_min,
                "start_day": int(t.start_day),
                "end_day": int(t.end_day),
                "start_shift_min": round(t.start_shift_min, 2),
                "end_shift_min": round(t.end_shift_min, 2),
                "start_at": t.start_at,
                "end_at": t.end_at,
            }
        )
    return out


def _build_task(order: Order, line_id: str, setup: float, start_work_abs: float, end_work_abs: float, tardy: float, cfg: Dict[str, float]) -> Task:
    s = _work_abs_to_parts(start_work_abs, cfg)
    e = _work_abs_to_parts(end_work_abs, cfg)

    return Task(
        order_id=order.order_id,
        code=order.code,
        line_id=line_id,
        qty=order.qty,
        setup_min=setup,
        start_min=s["calendar_abs_min"],
        end_min=e["calendar_abs_min"],
        tardy_min=tardy,
        due_date=order.due_date,
        start_work_min=start_work_abs,
        end_work_min=end_work_abs,
        due_work_min=order.due_min if math.isfinite(order.due_min) else None,
        start_day=s["relative_day"],
        end_day=e["relative_day"],
        start_shift_min=s["shift_min"],
        end_shift_min=e["shift_min"],
        start_at=s["at"].isoformat(timespec="minutes"),
        end_at=e["at"].isoformat(timespec="minutes"),
    )


def schedulazione_due_date(dataset: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _calendar_config(dataset)
    due_minutes = _compute_due_context(dataset, cfg)
    orders = sorted(_to_order_objects(dataset, due_minutes), key=lambda o: o.due_sort_key)

    line_ids = [str(l.get("line_id")) for l in dataset.get("lines", []) if l.get("line_id")]
    timeline_work = {line_id: float(cfg["anchor_work_abs"]) for line_id in line_ids}
    last_code: Dict[str, Optional[str]] = {
        line_id: dataset.get("current_config", {}).get(line_id, {}).get("current_code")
        for line_id in line_ids
    }

    tasks: List[Task] = []
    unscheduled: List[Dict[str, Any]] = []

    for order in orders:
        best = None
        for line_id in sorted(order.eligible_lines):
            if line_id not in timeline_work:
                continue
            cycle = _safe_float(order.cycle_minutes_by_line.get(line_id), 0.0)
            if cycle <= 0:
                continue

            setup = _setup_time(dataset, line_id, last_code.get(line_id), order.code)
            start_work = timeline_work[line_id] + setup
            end_work = start_work + (order.qty * cycle)
            tardy = max(0.0, end_work - order.due_min)
            candidate = (tardy, end_work, setup, line_id)
            if best is None or candidate < best[0]:
                best = (candidate, line_id, setup, start_work, end_work, tardy)

        if best is None:
            unscheduled.append({
                "order_id": order.order_id,
                "code": order.code,
                "qty": int(order.qty) if float(order.qty).is_integer() else order.qty,
                "reason": "No eligible line/cycle time.",
            })
            continue

        _, line_id, setup, start_work, end_work, tardy = best
        timeline_work[line_id] = end_work
        last_code[line_id] = order.code
        tasks.append(_build_task(order, line_id, setup, start_work, end_work, tardy, cfg))

    return {
        "strategy": "due_date",
        "tasks": _tasks_to_dict(tasks),
        "unscheduled": unscheduled,
        "kpi": _kpi(tasks, unscheduled, cfg),
    }


class MinSetupScheduler:
    def __init__(self, dataset: Dict[str, Any]):
        self.dataset = dataset
        self.cfg = _calendar_config(dataset)
        due_minutes = _compute_due_context(dataset, self.cfg)
        self.orders = _to_order_objects(dataset, due_minutes)
        self.line_ids = [str(l.get("line_id")) for l in dataset.get("lines", []) if l.get("line_id")]
        self.timeline_work = {line_id: float(self.cfg["anchor_work_abs"]) for line_id in self.line_ids}
        self.last_code: Dict[str, Optional[str]] = {
            line_id: dataset.get("current_config", {}).get(line_id, {}).get("current_code")
            for line_id in self.line_ids
        }
        self.tasks: List[Task] = []
        self.unscheduled: List[Dict[str, Any]] = []

    def _processing_time(self, order: Order, line_id: str) -> Optional[float]:
        cycle = _safe_float(order.cycle_minutes_by_line.get(line_id), 0.0)
        if cycle <= 0:
            return None
        return order.qty * cycle

    def _assign_order(self, order: Order, line_id: str):
        start_base = self.timeline_work[line_id]
        setup = _setup_time(self.dataset, line_id, self.last_code.get(line_id), order.code)
        proc = self._processing_time(order, line_id)
        if proc is None:
            self.unscheduled.append({
                "order_id": order.order_id,
                "code": order.code,
                "qty": int(order.qty) if float(order.qty).is_integer() else order.qty,
                "reason": "No cycle time for selected line.",
            })
            return

        start_work = start_base + setup
        end_work = start_work + proc
        tardy = max(0.0, end_work - order.due_min)

        self.timeline_work[line_id] = end_work
        self.last_code[line_id] = order.code
        self.tasks.append(_build_task(order, line_id, setup, start_work, end_work, tardy, self.cfg))

    def run(self) -> Dict[str, Any]:
        remaining = list(self.orders)
        while remaining:
            best: Optional[Tuple[Tuple[float, float, float, str], Order, str]] = None
            non_schedulable: List[Order] = []

            for order in remaining:
                local_best = None
                for line_id in sorted(order.eligible_lines):
                    if line_id not in self.timeline_work:
                        continue
                    proc = self._processing_time(order, line_id)
                    if proc is None:
                        continue
                    setup = _setup_time(self.dataset, line_id, self.last_code.get(line_id), order.code)
                    start_work = self.timeline_work[line_id] + setup
                    score = (setup, start_work, order.due_min, line_id)
                    if local_best is None or score < local_best[0]:
                        local_best = (score, line_id)

                if local_best is None:
                    non_schedulable.append(order)
                    continue

                score, line_id = local_best
                if best is None or score < best[0]:
                    best = (score, order, line_id)

            for order in non_schedulable:
                self.unscheduled.append({
                    "order_id": order.order_id,
                    "code": order.code,
                    "qty": int(order.qty) if float(order.qty).is_integer() else order.qty,
                    "reason": "No eligible line/cycle time.",
                })
                remaining.remove(order)

            if best is None:
                break

            _, order, line_id = best
            self._assign_order(order, line_id)
            remaining.remove(order)

        return {
            "strategy": "min_setup",
            "tasks": _tasks_to_dict(self.tasks),
            "unscheduled": self.unscheduled,
            "kpi": _kpi(self.tasks, self.unscheduled, self.cfg),
        }


def schedulazione_min_setup(dataset: Dict[str, Any]) -> Dict[str, Any]:
    return MinSetupScheduler(dataset).run()


def schedulazione_balanced(dataset: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _calendar_config(dataset)
    due_minutes = _compute_due_context(dataset, cfg)
    orders = sorted(_to_order_objects(dataset, due_minutes), key=lambda o: o.due_sort_key)

    line_ids = [str(l.get("line_id")) for l in dataset.get("lines", []) if l.get("line_id")]
    timeline_work = {line_id: float(cfg["anchor_work_abs"]) for line_id in line_ids}
    last_code: Dict[str, Optional[str]] = {
        line_id: dataset.get("current_config", {}).get(line_id, {}).get("current_code")
        for line_id in line_ids
    }

    tasks: List[Task] = []
    unscheduled: List[Dict[str, Any]] = []

    for order in orders:
        best = None
        for line_id in sorted(order.eligible_lines):
            if line_id not in timeline_work:
                continue
            cycle = _safe_float(order.cycle_minutes_by_line.get(line_id), 0.0)
            if cycle <= 0:
                continue

            setup = _setup_time(dataset, line_id, last_code.get(line_id), order.code)
            start_work = timeline_work[line_id] + setup
            end_work = start_work + (order.qty * cycle)
            tardy = max(0.0, end_work - order.due_min)

            candidate = (
                1 if tardy > 0 else 0,
                tardy,
                setup,
                end_work,
                line_id,
            )
            if best is None or candidate < best[0]:
                best = (candidate, line_id, setup, start_work, end_work, tardy)

        if best is None:
            unscheduled.append({
                "order_id": order.order_id,
                "code": order.code,
                "qty": int(order.qty) if float(order.qty).is_integer() else order.qty,
                "reason": "No eligible line/cycle time.",
            })
            continue

        _, line_id, setup, start_work, end_work, tardy = best
        timeline_work[line_id] = end_work
        last_code[line_id] = order.code
        tasks.append(_build_task(order, line_id, setup, start_work, end_work, tardy, cfg))

    return {
        "strategy": "balanced",
        "tasks": _tasks_to_dict(tasks),
        "unscheduled": unscheduled,
        "kpi": _kpi(tasks, unscheduled, cfg),
    }
