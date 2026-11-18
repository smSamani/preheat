import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def found_section():
    m = re.search(r"## What I found\n(.*?)\n## ", README, re.S)
    return m.group(1)


def numbers(node, out):
    if isinstance(node, dict):
        for v in node.values():
            numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            numbers(v, out)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        out.add(f"{node:.1f}")
        out.add(f"{node:.2f}")
    return out


def test_t17_numbers_in_results():
    allowed = numbers(json.loads((ROOT / "results.json").read_text(encoding="utf-8")), set())
    sec = found_section().replace("All numbers come from `results.json`", "")
    for tok in re.findall(r"\d+(?:\.\d+)?", sec):
        assert tok in allowed, tok


def test_t18_no_annualising_and_paired_percentages():
    assert not re.search(r"annual|per year|a year|/yr|yearly", README, re.I)
    for line in found_section().splitlines():
        if "%" in line:
            assert "kWh" in line or "€" in line, line
