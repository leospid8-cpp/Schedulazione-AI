import argparse

from team_pack.scheduler_engine import load_dataset, save_schedule
from team_pack.strategy_due_date import run as run_due_date
from team_pack.strategy_min_setup import run as run_min_setup
from team_pack.strategy_balanced import run as run_balanced


def main():
    parser = argparse.ArgumentParser(description="Run scheduling strategy.")
    parser.add_argument("--strategy", choices=["due_date", "min_setup", "balanced"], required=True)
    parser.add_argument("--input", default="team_pack/data/scheduler_dataset.json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    dataset = load_dataset(args.input)

    if args.strategy == "due_date":
        result = run_due_date(dataset)
        default_out = "team_pack/data/output_due_date.json"
    elif args.strategy == "min_setup":
        result = run_min_setup(dataset)
        default_out = "team_pack/data/output_min_setup.json"
    else:
        result = run_balanced(dataset)
        default_out = "team_pack/data/output_balanced.json"

    out_path = args.output or default_out
    save_schedule(result, out_path)
    print(f"Saved: {out_path}")
    print(f"KPI: {result['kpi']}")


if __name__ == "__main__":
    main()
