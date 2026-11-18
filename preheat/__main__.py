import argparse
import os
import sys

from . import sweep
from .fixture import REFERENCE_CEILING


def table(res):
    rows = {r["envelope"]: r for r in res["records"]
            if r["ceiling_c"] == REFERENCE_CEILING and r["case"] == "nominal"}
    print(f"Maximum indoor temperature {REFERENCE_CEILING} °C, nominal synthetic day")
    print(f"{'house':<10} {'evening kWh (base → opt)':<26} {'avoided':<18} "
          f"{'day cost (base → opt)':<24} saved")
    for env, r in rows.items():
        if r["status"] != "ok":
            print(f"{env:<10} {r['status']}: {r['reason']}")
            continue
        b, o = r["baseline"], r["optimised"]
        print(f"{env:<10} {b['evening_kwh']:.2f} → {o['evening_kwh']:.2f}".ljust(37)
              + f"{r['avoided_kwh']:.2f} kWh ({r['avoided_pct']:.1f}%)".ljust(19)
              + f"€{b['cost_eur']:.2f} → €{o['cost_eur']:.2f}".ljust(24)
              + f"€{r['saving_eur']:.2f}/day")


def run_sweep():
    from . import plot
    res = sweep.run()
    os.makedirs("figures", exist_ok=True)
    sweep.write(res, "results.json")
    plot.flex_curve(res, "figures/flex_curve.png")
    plot.example_day(res, "figures/example_day.png")
    table(res)
    bad = [r for r in res["records"] if r["status"] != "ok"]
    for r in bad:
        print("NOT OK:", r)
    print(f"{len(res['records']) - len(bad)}/{len(res['records'])} pairs ok")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="preheat")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("ask", help="language layer: one sentence -> one confirmed setting")
    a.add_argument("--offline", action="store_true", help="replay the recorded trace")
    a.add_argument("--trace", default=None)
    a.add_argument("--record", default=None, help="write a trace from a live session")
    a.add_argument("--eval", default=None, help="one-off live check on a phrasings file")
    args = ap.parse_args(argv)
    if args.cmd == "ask":
        from . import ask
        return ask.cli(args)
    return run_sweep()


if __name__ == "__main__":
    sys.exit(main())
