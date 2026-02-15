import json
from copy import deepcopy
from pathlib import Path


def load_dataset(path="team_pack/data/scheduler_dataset.json"):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def save_schedule(result, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _line_state_from_dataset(dataset):
    states = {}
    current_cfg = dataset.get("current_config", {})
    for line in dataset.get("lines", []):
        line_id = line["line_id"]
        cfg = current_cfg.get(line_id, {})
        states[line_id] = {
            "next_free_min": 0.0,
            "last_code": cfg.get("current_code", ""),
            "scheduled_count": 0,
        }
    return states


def _setup_minutes(dataset, line_id, from_code, to_code):
    if from_code:
        return float(dataset["setup_minutes"]["between_codes"].get(from_code, {}).get(to_code, 60))
    return float(dataset["setup_minutes"]["from_current"].get(line_id, {}).get(to_code, 0))


def _compute_kpi(tasks, total_orders, unscheduled):
    total_setup = sum(t["setup_min"] for t in tasks)
    total_tardy = sum(t["tardy_min"] for t in tasks)
    makespan = max((t["end_min"] for t in tasks), default=0)
    return {
        "scheduled_orders": len(tasks),
        "unscheduled_orders": len(unscheduled),
        "total_orders": total_orders,
        "total_setup_min": round(total_setup, 2),
        "total_tardy_min": round(total_tardy, 2),
        "makespan_min": round(makespan, 2),
    }


def build_schedule(dataset, strategy_name, order_sort_key, line_score_fn):
    """
    Generic greedy scheduler.
    - order_sort_key(order): key for sorting orders
    - line_score_fn(candidate): lower score = better
    candidate fields:
      order, line_id, setup_min, run_min, start_min, end_min, tardy_min, state
    """
    data = deepcopy(dataset)
    orders = data.get("orders", [])
    line_states = _line_state_from_dataset(data)
    scheduled = []
    unscheduled = []

    sorted_orders = sorted(orders, key=order_sort_key)

    valid_due_serials = [float(o.get("due_serial", 0)) for o in orders if float(o.get("due_serial", 0)) > 0]
    base_due_serial = min(valid_due_serials) if valid_due_serials else 0.0

    for idx, order in enumerate(sorted_orders, start=1):
        code = order["code"]
        qty = float(order["qty"])
        due_serial = float(order.get("due_serial", 0))
        due_min = ((due_serial - base_due_serial + 1.0) * 1440.0) if due_serial > 0 else float("inf")
        best = None
        eligible = order.get("eligible_lines", [])
        cycles = order.get("cycle_minutes_by_line", {})

        for line_id in eligible:
            if line_id not in line_states:
                continue
            cycle_min = cycles.get(line_id)
            if cycle_min is None or cycle_min <= 0:
                continue

            st = line_states[line_id]
            setup_min = _setup_minutes(data, line_id, st["last_code"], code)
            run_min = cycle_min * qty
            start_min = float(st["next_free_min"]) + setup_min
            end_min = start_min + run_min
            tardy_min = max(0.0, end_min - due_min)

            candidate = {
                "order": order,
                "line_id": line_id,
                "setup_min": float(setup_min),
                "run_min": float(run_min),
                "start_min": float(start_min),
                "end_min": float(end_min),
                "tardy_min": float(tardy_min),
                "state": st,
            }
            score = line_score_fn(candidate)
            if best is None or score < best["score"]:
                best = {"score": score, "candidate": candidate}

        if best is None:
            unscheduled.append(
                {
                    "order_id": order["order_id"],
                    "code": code,
                    "qty": order["qty"],
                    "reason": "No eligible line/cycle time.",
                }
            )
            continue

        c = best["candidate"]
        state = line_states[c["line_id"]]
        state["next_free_min"] = c["end_min"]
        state["last_code"] = code
        state["scheduled_count"] += 1

        scheduled.append(
            {
                "task_id": f"T{idx:04d}",
                "order_id": order["order_id"],
                "code": code,
                "line_id": c["line_id"],
                "qty": order["qty"],
                "cycle_min_per_piece": cycles[c["line_id"]],
                "setup_min": round(c["setup_min"], 2),
                "start_min": round(c["start_min"], 2),
                "end_min": round(c["end_min"], 2),
                "due_serial": order.get("due_serial"),
                "due_date": order.get("due_date"),
                "tardy_min": round(c["tardy_min"], 2),
            }
        )

    result = {
        "strategy": strategy_name,
        "kpi": _compute_kpi(scheduled, len(orders), unscheduled),
        "tasks": scheduled,
        "unscheduled": unscheduled,
    }
    return result
