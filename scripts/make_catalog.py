#!/usr/bin/env python3
"""
Create catalog.json (read by the app) and release notes for a folder of packs.

    python3 scripts/make_catalog.py packs --notes notes.md [--failed DE,FR] [--carried PL]
"""
import argparse
import hashlib
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--notes", help="write release notes (Markdown) here")
    ap.add_argument("--failed", default="", help="comma-separated ids that failed to build")
    ap.add_argument("--carried", default="", help="comma-separated ids copied from the previous release")
    args = ap.parse_args()

    config = json.load(open(os.path.join(ROOT, "regions.json"), encoding="utf-8"))
    groups = {g["id"]: g["name"] for g in config["groups"]}
    order = {r["id"]: i for i, r in enumerate(config["regions"])}
    regions = {r["id"]: r for r in config["regions"]}

    packs = []
    for name in os.listdir(args.folder):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(args.folder, name)
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json"))
        pid = m.get("id", m["country"])
        region = regions.get(pid, {})
        packs.append({
            "id": pid,
            "country": m["country"],
            "name": region.get("name", m.get("name", pid)),
            "name_en": region.get("name_en", m.get("name_en", "")),
            "group": groups.get(region.get("group"), m.get("group", "")),
            "file": name,
            "size": os.path.getsize(path),
            "created": m["created"],
            "sha256": sha256(path),
            "roads": m.get("stats", {}).get("roads"),
            "maxspeed": m.get("stats", {}).get("maxspeed"),
        })
    packs.sort(key=lambda p: order.get(p["id"], 10_000))

    with open(os.path.join(args.folder, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"format": 1, "packs": packs}, f, ensure_ascii=False, indent=1)
    print(f"catalog.json: {len(packs)} packs, {sum(p['size'] for p in packs) / 1048576:.0f} MB")

    if args.notes:
        failed = [x for x in args.failed.split(",") if x]
        carried = [x for x in args.carried.split(",") if x]
        lines = [
            "Offline speed-limit packs for the SpeedNotify Android app.",
            "",
            "The app downloads them automatically: *Maps by country* → *Download*. "
            "To install manually, copy a `.zip` to the device and use *Import pack from file*.",
            "",
            "| Region | Country | Roads | With maxspeed | Size |",
            "|---|---|---:|---:|---:|",
        ]
        for p in packs:
            roads = f"{p['roads']:,}" if p.get("roads") else "—"
            ms = f"{p['maxspeed'] * 100 // p['roads']}%" if p.get("roads") and p.get("maxspeed") is not None else "—"
            mark = " (previous build)" if p["id"] in carried else ""
            lines.append(f"| {p['name_en'] or p['id']}{mark} | {p['country']} | {roads} | {ms} | "
                         f"{p['size'] / 1048576:.1f} MB |")
        if failed:
            lines += ["", f"⚠️ Failed to build this time: {', '.join(failed)}. "
                          "The previous version of these packs is kept where available."]
        lines += [
            "",
            "Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), "
            "available under the [Open Database License](https://opendatacommons.org/licenses/odbl/). "
            "Extracts by [Geofabrik](https://download.geofabrik.de/).",
        ]
        with open(args.notes, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
