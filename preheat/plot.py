"""Two figures, drawn only from the in-memory results (same data as results.json)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .fixture import CEILINGS, PRICE_EVENING, REFERENCE_CEILING

COL = {"current": "#D55E00", "insulated": "#0072B2"}
LAB = {"current": "Current house", "insulated": "Better insulated"}
SAVE = dict(dpi=150, bbox_inches="tight", metadata={"Software": None})


def _pick(res, env, ceiling):
    return next(r for r in res["records"] if r["envelope"] == env
                and r["case"] == "nominal" and r["ceiling_c"] == ceiling)


def flex_curve(res, path):
    plt.rcParams.update({"font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), sharex=True)
    specs = [("avoided_pct", "Evening heat-pump electricity avoided (%)", (0, 105)),
             ("saving_eur", "Heating cost saved (€ per day)", (0, None))]
    for ax, (key, ylabel, ylim) in zip(axes, specs):
        for env in COL:
            nom = [_pick(res, env, c)[key] for c in CEILINGS]
            bands = [b for b in res["bands"] if b["envelope"] == env]
            lo = [b[key + "_min"] for b in bands]
            hi = [b[key + "_max"] for b in bands]
            ax.fill_between(CEILINGS, lo, hi, color=COL[env], alpha=0.18, lw=0)
            ax.plot(CEILINGS, nom, "-o", color=COL[env], ms=4)
            up = nom[-1] >= max(_pick(res, o, CEILINGS[-1])[key] for o in COL)
            ax.annotate(LAB[env], (CEILINGS[-1], nom[-1]), xytext=(-6, 9 if up else -13),
                        textcoords="offset points", color=COL[env], ha="right",
                        fontsize=9)
        ax.axvline(REFERENCE_CEILING, color="grey", ls=":", lw=1)
        ax.set_xticks(CEILINGS)
        ax.set_xlim(21.4, 24.1)
        ax.set_ylim(*ylim)
        ax.set_xlabel("Maximum indoor temperature (°C)")
        ax.set_ylabel(ylabel)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.suptitle("How much evening heat-pump electricity could warming up earlier avoid?")
    ref = {e: _pick(res, e, REFERENCE_CEILING) for e in COL}
    n_ok = min(b["n_cases_ok"] for b in res["bands"])
    cur, ins = ref["current"], ref["insulated"]
    line1 = (f"At {REFERENCE_CEILING} °C: current house avoids {cur['avoided_kwh']:.2f} kWh "
             f"({cur['avoided_pct']:.1f}%) of evening use, saving €{cur['saving_eur']:.2f} of "
             f"€{cur['baseline']['cost_eur']:.2f} a day; better insulated avoids "
             f"{ins['avoided_kwh']:.2f} kWh ({ins['avoided_pct']:.1f}%), saving "
             f"€{ins['saving_eur']:.2f} of €{ins['baseline']['cost_eur']:.2f}.")
    line2 = ("One synthetic winter day. Lines: nominal case. Shading: range across 7 "
             "one-at-a-time what-if cases (not probabilities).")
    if n_ok < 7:
        line2 += f" Some bands cover fewer than 7 cases (minimum {n_ok})."
    fig.text(0.5, -0.02, line1 + "\n" + line2, ha="center", va="top", fontsize=9)
    fig.savefig(path, **SAVE)
    plt.close(fig)


def example_day(res, path):
    ex = res["example_day"]
    plt.rcParams.update({"font.size": 10})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.5), sharex=True)
    h = np.arange(25)
    floor = np.array(ex["floor_c"])
    ceil = ex["ceiling_c"]
    a1.fill_between(h, floor, ceil, step="post", color="#2ca02c", alpha=0.12,
                    label="Comfort band")
    a1.plot(h, ex["T_baseline_c"], "--", color="grey", label="Price-blind rule")
    a1.plot(h, ex["T_optimised_c"], "-", color=COL["current"], label="Cost-minimising schedule")
    a1.plot([18, 19, 20, 21], [21] * 4, "k_", ms=10, label="Evening checkpoints")
    a1.set_ylabel("Indoor temperature (°C)")
    a1.legend(fontsize=8, loc="lower left", frameon=False)
    w = 0.4
    t = np.arange(24)
    a2.bar(t + 0.5 - w / 2, ex["p_baseline_kw"], w, color="grey")
    a2.bar(t + 0.5 + w / 2, ex["p_optimised_kw"], w, color=COL["current"])
    a2.set_ylabel("Heat-pump electricity (kW)")
    a2.set_xlabel("Hour of day")
    a2.set_xticks(range(0, 25, 3))
    a2.set_xlim(0, 24)
    for ax in (a1, a2):
        ax.axvspan(17, 22, color="lightgrey", alpha=0.25, lw=0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    a1.text(19.5, a1.get_ylim()[1], f"Expensive hours (€{PRICE_EVENING:.2f}/kWh)",
            ha="center", va="bottom", fontsize=8)
    fig.savefig(path, **SAVE)
    plt.close(fig)
