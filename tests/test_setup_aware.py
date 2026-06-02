"""Test per la strategia setup_aware e la modalità auto.

Dataset sintetico: 2 linee, 4 ordini (2 coppie con lo stesso code).
Setup tra codici diversi = 60 min, stesso codice = 5 min → setup_aware
deve raggruppare i codici e ridurre il setup totale rispetto a due_date.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from team_pack.scheduler_algorithms import (
    schedulazione_due_date,
    schedulazione_setup_aware,
)
from team_pack.supabase_pipeline import run_requested_strategies


def _make_dataset():
    return {
        "calendar": {
            "shift_minutes": 480.0,
            "day_minutes": 1440.0,
            "shift_start_min": 0.0,
            "anchor_now": False,
            # anchor fissato per riproducibilità
            "anchor_work_abs": 0.0,
            "anchor_cal_abs": 0.0,
            "anchor_day_serial": 0.0,
        },
        "lines": [{"line_id": "L1"}, {"line_id": "L2"}],
        "orders": [
            {
                "order_id": "O1", "code": "A", "qty": 10,
                "due_serial": 46100, "due_date": "2026-03-01",
                "eligible_lines": ["L1", "L2"],
                "cycle_minutes_by_line": {"L1": 1.0, "L2": 1.0},
            },
            {
                "order_id": "O2", "code": "A", "qty": 10,
                "due_serial": 46101, "due_date": "2026-03-02",
                "eligible_lines": ["L1", "L2"],
                "cycle_minutes_by_line": {"L1": 1.0, "L2": 1.0},
            },
            {
                "order_id": "O3", "code": "B", "qty": 10,
                "due_serial": 46102, "due_date": "2026-03-03",
                "eligible_lines": ["L1", "L2"],
                "cycle_minutes_by_line": {"L1": 1.0, "L2": 1.0},
            },
            {
                "order_id": "O4", "code": "B", "qty": 10,
                "due_serial": 46103, "due_date": "2026-03-04",
                "eligible_lines": ["L1", "L2"],
                "cycle_minutes_by_line": {"L1": 1.0, "L2": 1.0},
            },
        ],
        "current_config": {},
        "setup_minutes": {
            "per_tool_minutes": 0,
            "from_current": {},
            "between_codes": {
                # stesso codice = 5 min, cambio codice = 60 min
                "A": {"A": 5.0, "B": 60.0},
                "B": {"A": 60.0, "B": 5.0},
            },
        },
    }


def _make_dataset_no_cycle():
    """Come il dataset base ma con un ordine senza cycle time su nessuna linea."""
    ds = _make_dataset()
    ds["orders"].append({
        "order_id": "O5", "code": "C", "qty": 5,
        "due_serial": 46104, "due_date": "2026-03-05",
        "eligible_lines": ["L1", "L2"],
        "cycle_minutes_by_line": {},
    })
    return ds


# --- Test 1: setup_aware ritorna strategy == "setup_aware" ---

def test_setup_aware_strategy_name():
    result = schedulazione_setup_aware(_make_dataset())
    assert result["strategy"] == "setup_aware"


# --- Test 2: ogni task ha end_min >= start_min ---

def test_task_end_ge_start():
    result = schedulazione_setup_aware(_make_dataset())
    for t in result["tasks"]:
        assert t["end_min"] >= t["start_min"], (
            f"Task {t['order_id']} su linea {t['line_id']}: end_min={t['end_min']} < start_min={t['start_min']}"
        )


# --- Test 3: nessun ordine schedulato due volte ---

def test_no_duplicate_orders():
    result = schedulazione_setup_aware(_make_dataset())
    scheduled_ids = [t["order_id"] for t in result["tasks"]]
    assert len(scheduled_ids) == len(set(scheduled_ids)), (
        f"Ordini duplicati: {scheduled_ids}"
    )


# --- Test 4: ordini senza cycle time finiscono in unscheduled ---

def test_no_cycle_goes_unscheduled():
    result = schedulazione_setup_aware(_make_dataset_no_cycle())
    unscheduled_ids = [u["order_id"] for u in result["unscheduled"]]
    scheduled_ids = [t["order_id"] for t in result["tasks"]]
    assert "O5" in unscheduled_ids, "O5 (no cycle time) deve essere in unscheduled"
    assert "O5" not in scheduled_ids, "O5 non deve essere in tasks"


# --- Test 5: i KPI contengono objective_score ---

def test_kpi_has_objective_score():
    result = schedulazione_setup_aware(_make_dataset())
    assert "objective_score" in result["kpi"], "objective_score mancante nei KPI"
    assert isinstance(result["kpi"]["objective_score"], float), (
        f"objective_score deve essere float, è {type(result['kpi']['objective_score'])}"
    )


# --- Test 6: auto ritorna strategy=="auto" e selected_strategy valido ---

def test_auto_strategy():
    results = run_requested_strategies(_make_dataset(), "auto")
    assert len(results) == 1, "auto deve restituire esattamente 1 risultato"
    r = results[0]
    assert r["strategy"] == "auto", f"strategy atteso 'auto', trovato '{r['strategy']}'"
    valid = {"due_date", "min_setup", "balanced", "setup_aware"}
    assert r.get("selected_strategy") in valid, (
        f"selected_strategy '{r.get('selected_strategy')}' non in {valid}"
    )


# --- Test 7: setup_aware riduce total_setup_min rispetto a due_date su dataset con codici ripetuti ---

def test_setup_aware_reduces_total_setup():
    ds = _make_dataset()
    sa = schedulazione_setup_aware(ds)
    dd = schedulazione_due_date(ds)
    assert sa["kpi"]["total_setup_min"] <= dd["kpi"]["total_setup_min"], (
        f"setup_aware total_setup_min ({sa['kpi']['total_setup_min']}) "
        f"> due_date ({dd['kpi']['total_setup_min']}): il raggruppamento non sta aiutando"
    )
