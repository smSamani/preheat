from preheat import sweep


def test_t10_deterministic():
    assert sweep.dumps(sweep.run()) == sweep.dumps(sweep.run())


def test_t11_shape():
    res = sweep.run()
    assert len(res["records"]) == 84 and len(res["bands"]) == 12
    for b in res["bands"]:
        assert b["n_cases_ok"] == 7
        nom = next(r for r in res["records"] if r["ceiling_c"] == b["ceiling_c"]
                   and r["envelope"] == b["envelope"] and r["case"] == "nominal")
        for key in ("avoided_pct", "saving_eur"):
            assert b[key + "_min"] - 1e-9 <= nom[key] <= b[key + "_max"] + 1e-9
