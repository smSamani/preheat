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
    return next((r for r in res["records"] if r["envelope"] == env
                 and r["case"] == "nominal" and r["ceiling_c"] == ceiling), {})


def _num(value):
    return np.nan if value is None else value


def _avoided(rec):
    """'1.23 kWh (45.6%)', or just the kWh when the rule used no evening electricity."""
    text = f"{rec['avoided_kwh']:.2f} kWh"
    return text if rec.get("avoided_pct") is None else f"{text} ({rec['avoided_pct']:.1f}%)"


def flex_curve(res, path, diag=None):
    plt.rcParams.update({"font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), sharex=True)
    specs = [("avoided_pct", "Evening heat-pump electricity avoided\nvs one-hour rule (%)", (0, 105)),
             ("saving_eur", "Heating cost saved (€ per day)", (0, None))]
    for ax, (key, ylabel, ylim) in zip(axes, specs):
        for env in COL:
            nom = [_num(_pick(res, env, c).get(key)) for c in CEILINGS]
            bands = [b for b in res["bands"] if b["envelope"] == env]
            lo = [_num(b.get(key + "_min")) for b in bands]
            hi = [_num(b.get(key + "_max")) for b in bands]
            ax.fill_between(CEILINGS, lo, hi, color=COL[env], alpha=0.12, lw=0)
            ax.plot(CEILINGS, lo, ":", color=COL[env], lw=0.9)
            ax.plot(CEILINGS, hi, ":", color=COL[env], lw=0.9)
            ax.plot(CEILINGS, nom, "-o", color=COL[env], ms=4)
            ends = [_num(_pick(res, o, CEILINGS[-1]).get(key)) for o in COL]
            up = not np.isnan(nom[-1]) and nom[-1] >= np.nanmax(ends)
            ax.annotate(LAB[env], (CEILINGS[-1], nom[-1]), xytext=(-6, 9 if up else -13),
                        textcoords="offset points", color=COL[env], ha="right",
                        fontsize=9)
            if key == "saving_eur" and diag is not None:
                rows = {m["ceiling_c"]: m for m in diag["matched_foresight"]["rows"]
                        if m["envelope"] == env}
                matched = [_num(rows.get(c, {}).get("saving_vs_energy_lp_eur")) for c in CEILINGS]
                ax.plot(CEILINGS, matched, "--", color=COL[env], lw=1.1, alpha=0.8)
        if key == "saving_eur" and diag is not None:
            ax.plot([], [], "-", color="0.3", label="vs one-hour rule")
            ax.plot([], [], "--", color="0.3", label="vs same-foresight kWh-minimising LP")
            ax.legend(fontsize=8, loc="upper left", frameon=False)
        ax.axvline(REFERENCE_CEILING, color="grey", ls=(0, (2, 3)), lw=0.8)
        ax.text(REFERENCE_CEILING, 0.01, f" example in text ({REFERENCE_CEILING} °C)",
                transform=ax.get_xaxis_transform(), color="grey", fontsize=8,
                ha="left", va="bottom")
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
    if cur.get("status") == "ok" and ins.get("status") == "ok":
        line1 = (f"At {REFERENCE_CEILING} °C, vs the one-hour rule: current house avoids "
                 f"{_avoided(cur)} of evening use, saving "
                 f"€{cur['saving_eur']:.2f} of €{cur['baseline']['cost_eur']:.2f} a day; better "
                 f"insulated avoids {_avoided(ins)}, "
                 f"saving €{ins['saving_eur']:.2f} of €{ins['baseline']['cost_eur']:.2f}.")
    else:
        line1 = f"At {REFERENCE_CEILING} °C the nominal comparison did not solve for both houses."
    line2 = ("One synthetic winter day. Solid lines: nominal case vs the one-hour rule. Shading "
             "between dotted lines: range across 7 one-at-a-time what-if cases (not probabilities).")
    if diag is not None:
        line2 += ("\nDashed lines (right): saving vs a price-blind LP with the same whole-day "
                  "foresight that minimises daily kWh (nominal case).")
    if n_ok < 7:
        line2 += f" Some bands cover fewer than 7 cases (minimum {n_ok})."
    fig.text(0.5, -0.02, line1 + "\n" + line2, ha="center", va="top", fontsize=9)
    fig.savefig(path, **SAVE)
    plt.close(fig)


def example_day(res, path):
    ex = res["example_day"]
    if ex is None:
        print(f"example day not available (the reference case did not solve): {path} not written")
        return False
    plt.rcParams.update({"font.size": 10})
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 5.5), sharex=True)
    h = np.arange(25)
    floor = np.array(ex["floor_c"])
    ceil = ex["ceiling_c"]
    # Bounds are checked at the hourly points only, so join them like the temperature lines.
    a1.fill_between(h, floor, ceil, color="#2ca02c", alpha=0.12,
                    label="Allowed range (hourly bounds, joined)")
    a1.plot(h, ex["T_baseline_c"], "--", color="grey", label="One-hour rule (price-blind)")
    a1.plot(h, ex["T_optimised_c"], "-", color=COL["current"], label="Cost-minimising schedule")
    a1.plot([18, 19, 20, 21], [21] * 4, "k_", ms=10, label="Evening checkpoints")
    a1.set_ylabel("Indoor temperature (°C)")
    a1.legend(fontsize=8, loc="lower left", frameon=False)
    w = 0.4
    t = np.arange(24)
    a2.bar(t + 0.5 - w / 2, ex["p_baseline_kw"], w, color="grey",
           label="One-hour rule (price-blind)")
    a2.bar(t + 0.5 + w / 2, ex["p_optimised_kw"], w, color=COL["current"],
           label="Cost-minimising schedule")
    a2.legend(fontsize=8, loc="upper left", frameon=False)
    a2.set_ylabel("Heat-pump electrical power (kW)")
    a2.set_xlabel("Hour of day")
    a2.set_xticks(range(0, 25, 3))
    a2.set_xlim(0, 24)
    for ax in (a1, a2):
        ax.axvspan(17, 22, color="lightgrey", alpha=0.25, lw=0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    a1.text(19.5, a1.get_ylim()[1], f"Expensive hours (€{PRICE_EVENING:.2f}/kWh)",
            ha="center", va="bottom", fontsize=8)
    fig.suptitle(f"Example day: current house, maximum {ceil} °C (nominal case)")
    fig.savefig(path, **SAVE)
    plt.close(fig)
    return True
