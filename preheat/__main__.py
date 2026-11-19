import sys

if sys.version_info < (3, 12):        # before any third-party import
    sys.exit("preheat needs Python 3.12 or newer.")

import argparse  # noqa: E402
import os  # noqa: E402

from . import sweep  # noqa: E402
from .fixture import REFERENCE_CEILING  # noqa: E402


def _pct(value):
    return "n/a" if value is None else f"{value:.1f}%"


def table(res, diag=None):
    rows = {r["envelope"]: r for r in res["records"]
            if r["ceiling_c"] == REFERENCE_CEILING and r["case"] == "nominal"}
    print(f"Maximum indoor temperature {REFERENCE_CEILING} °C, nominal synthetic day, "
          "cost-minimising LP vs the one-hour rule")
    print(f"{'house':<10} {'evening kWh (rule → LP)':<26} {'avoided':<18} "
          f"{'day cost (rule → LP)':<24} saved")
    for env, r in rows.items():
        if r["status"] != "ok":
            print(f"{env:<10} {r['status']}: {r['reason']}")
            continue
        b, o = r["baseline"], r["optimised"]
        print(f"{env:<10} {b['evening_kwh']:.2f} → {o['evening_kwh']:.2f}".ljust(37)
              + f"{r['avoided_kwh']:.2f} kWh ({_pct(r['avoided_pct'])})".ljust(19)
              + f"€{b['cost_eur']:.2f} → €{o['cost_eur']:.2f}".ljust(24)
              + f"€{r['saving_eur']:.2f}/day")
    if diag is None:
        return
    print("Matched-foresight check (price-blind LP minimising daily kWh, billed at the tariff):")
    for m in diag["matched_foresight"]["rows"]:
        if m["ceiling_c"] != REFERENCE_CEILING or "saving_vs_energy_lp_eur" not in m:
            continue
        print(f"{m['envelope']:<10} day cost €{m['energy_lp']['cost_eur']:.2f} → "
              f"€{m['cost_lp']['cost_eur']:.2f}: €{m['saving_vs_energy_lp_eur']:.2f}/day "
              "from responding to the tariff")


def run_sweep():
    from . import plot
    res = sweep.run()
    diag = sweep.diagnostics()
    os.makedirs("figures", exist_ok=True)
    sweep.write(res, "results.json")
    sweep.write(diag, "diagnostics.json")
    plot.flex_curve(res, "figures/flex_curve.png", diag)
    plot.example_day(res, "figures/example_day.png")
    table(res, diag)
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
    e = sub.add_parser("eval", help="score the language layer on authored conversations")
    e.add_argument("--mode", choices=("rules", "replay", "live"), required=True)
    e.add_argument("--split", choices=("dev", "heldout", "both"), default=None)
    e.add_argument("--out", default=None, help="report path (rules and replay only)")
    e.add_argument("--quiet", action="store_true", help="print only the gate result")
    w = sub.add_parser("web", help="serve the local simulator dashboard")
    w.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    if args.cmd == "web":
        from . import web
        return web.serve(args.port)
    if args.cmd == "eval":
        from . import evals
        return evals.cli(args)
    if args.cmd == "ask":
        from . import ask
        return ask.cli(args)
    return run_sweep()


if __name__ == "__main__":
    sys.exit(main())
