#!/usr/bin/env python3
"""
Print the build matrix for GitHub Actions.

    python3 scripts/plan.py ""            # all regions
    python3 scripts/plan.py "EE,LV,LT"    # a subset (ids from regions.json)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

config = json.load(open(os.path.join(ROOT, "regions.json"), encoding="utf-8"))
groups = {g["id"]: g["name"] for g in config["groups"]}
wanted = {x.strip().upper() for x in (sys.argv[1] if len(sys.argv) > 1 else "").split(",") if x.strip()}
unknown = wanted - {r["id"] for r in config["regions"]}
if unknown:
    sys.exit(f"Unknown region ids: {', '.join(sorted(unknown))}")

matrix = [
    {**r, "group_name": groups[r["group"]]}
    for r in config["regions"]
    if not wanted or r["id"] in wanted
]
print(f"matrix={json.dumps(matrix, ensure_ascii=False)}")
print(f"ids={','.join(r['id'] for r in matrix)}")
print(f"Regions: {len(matrix)}", file=sys.stderr)
