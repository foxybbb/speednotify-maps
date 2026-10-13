#!/usr/bin/env python3
"""
Build a SpeedNotify offline speed-limit pack from an OpenStreetMap extract.

    pip install osmium
    # optional but much faster for big countries:
    osmium tags-filter germany-latest.osm.pbf \
        w/highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link,secondary,secondary_link,tertiary,tertiary_link,unclassified,residential,living_street,road \
        n/place=city,town,village,hamlet,suburb -o filtered.osm.pbf
    python3 scripts/build_pack.py --id DE --country DE --name Германия \
        --pbf filtered.osm.pbf --poly germany.poly --out dist

Pack format (version 1), a zip archive:
  manifest.json            first entry; country, tile size, list of complete tiles, list of blocks
  blocks/<bx>_<by>.json    0.5°×0.5° blocks in Overpass JSON format;
                           way geometry is compact: "g": [lat, lon, lat, lon, ...]

Road classes and tags must match the app (map/OverpassClient.kt, map/Road.kt).
A tile is "complete" when it lies fully inside the extract boundary (.poly); border tiles
are marked incomplete so the app can top them up with roads of the neighbouring country.
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
import zipfile
from collections import OrderedDict

try:
    import osmium
except ImportError:
    sys.exit("pyosmium is required: pip install osmium")

TILE_DEG = 0.05          # = TileStore.TILE_DEG in the app
BLOCK_TILES = 10         # pack block = 10×10 tiles
MARGIN = 0.0005          # = MapRepository.saveResult in the app
PLACE_PAD = 0.06

HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "road",
}
WANTED_TAGS = (
    "highway", "maxspeed", "maxspeed:forward", "maxspeed:backward", "maxspeed:type",
    "source:maxspeed", "zone:maxspeed", "zone:traffic", "oneway", "junction",
)
PLACES = {"city", "town", "village", "hamlet", "suburb"}


# ---------------------------------------------------------------- boundary (.poly)

def read_poly(path):
    """Returns (outer, holes): lists of rings [(lon, lat), ...]."""
    outer, holes = [], []
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f]
    i = 1  # first line is the polygon name
    while i < len(lines):
        name = lines[i]
        i += 1
        if name == "END" or not name:
            continue
        ring = []
        while lines[i] != "END":
            lon, lat = map(float, lines[i].split()[:2])
            ring.append((lon, lat))
            i += 1
        i += 1
        (holes if name.startswith("!") else outer).append(ring)
    return outer, holes


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for k in range(len(ring)):
        xi, yi = ring[k]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = k
    return inside


def segment_hits_rect(x1, y1, x2, y2, rx0, ry0, rx1, ry1):
    """Liang–Barsky segment/rectangle intersection test."""
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - rx0), (dx, rx1 - x1), (-dy, y1 - ry0), (dy, ry1 - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def complete_tiles(outer, holes):
    """Tiles lying fully inside the extract boundary — they contain every road."""
    edges = []
    for ring in outer + holes:
        for k in range(len(ring)):
            (x1, y1), (x2, y2) = ring[k - 1], ring[k]
            edges.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2), x1, y1, x2, y2))

    def inside(x, y):
        return any(point_in_ring(x, y, r) for r in outer) and not any(point_in_ring(x, y, r) for r in holes)

    xs = [p[0] for r in outer for p in r]
    ys = [p[1] for r in outer for p in r]
    result = set()
    for tx in range(math.floor(min(xs) / TILE_DEG), math.floor(max(xs) / TILE_DEG) + 1):
        x0, x1 = tx * TILE_DEG, (tx + 1) * TILE_DEG
        col_edges = [e for e in edges if e[2] >= x0 and e[0] <= x1]
        for ty in range(math.floor(min(ys) / TILE_DEG), math.floor(max(ys) / TILE_DEG) + 1):
            y0, y1 = ty * TILE_DEG, (ty + 1) * TILE_DEG
            row_edges = [e for e in col_edges if e[3] >= y0 and e[1] <= y1]
            if any(segment_hits_rect(e[4], e[5], e[6], e[7], x0, y0, x1, y1) for e in row_edges):
                continue
            # No boundary edge crosses the tile, so one corner decides for the whole tile.
            if inside(x0, y0):
                result.add((tx, ty))
    return result


# ---------------------------------------------------------------- OSM

def blocks_of(minlat, minlon, maxlat, maxlon, pad):
    bd = TILE_DEG * BLOCK_TILES
    for bx in range(math.floor((minlon - pad) / bd), math.floor((maxlon + pad) / bd) + 1):
        for by in range(math.floor((minlat - pad) / bd), math.floor((maxlat + pad) / bd) + 1):
            yield bx, by


class BlockWriter:
    """Appends JSON elements to one temp file per block, keeping a bounded number of open files."""

    def __init__(self, folder, max_open=200):
        self.folder = folder
        self.max_open = max_open
        self.open_files = OrderedDict()
        self.blocks = set()

    def write(self, block, line):
        f = self.open_files.pop(block, None)
        if f is None:
            if len(self.open_files) >= self.max_open:
                _, old = self.open_files.popitem(last=False)
                old.close()
            f = open(self.path(block), "a", encoding="utf-8")
        self.open_files[block] = f
        if block in self.blocks:
            f.write(",")
        else:
            self.blocks.add(block)
        f.write(line)

    def path(self, block):
        return os.path.join(self.folder, f"{block[0]}_{block[1]}.part")

    def close(self):
        for f in self.open_files.values():
            f.close()
        self.open_files.clear()


class Collector(osmium.SimpleHandler):
    def __init__(self, writer):
        super().__init__()
        self.writer = writer
        self.places = []
        self.ways = 0
        self.with_maxspeed = 0

    def node(self, n):
        place = n.tags.get("place")
        if place in PLACES and n.location.valid():
            self.places.append((n.id, round(n.location.lat, 6), round(n.location.lon, 6), place))

    def way(self, w):
        if w.tags.get("highway") not in HIGHWAYS:
            return
        g = []
        for nd in w.nodes:
            loc = nd.location
            if loc.valid():
                g.append(round(loc.lat, 6))
                g.append(round(loc.lon, 6))
        if len(g) < 4:
            return
        tags = {k: w.tags.get(k) for k in WANTED_TAGS if k in w.tags}
        self.ways += 1
        if "maxspeed" in tags:
            self.with_maxspeed += 1
        line = json.dumps({"type": "way", "id": w.id, "tags": tags, "g": g}, separators=(",", ":"))
        lats, lons = g[0::2], g[1::2]
        for b in blocks_of(min(lats), min(lons), max(lats), max(lons), MARGIN):
            self.writer.write(b, line)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True, help="pack id, e.g. DE or RU-CFD")
    ap.add_argument("--country", required=True, help="ISO 3166-1 alpha-2 code used for default limits")
    ap.add_argument("--name", required=True, help="display name in the app")
    ap.add_argument("--name-en", default="", help="English name for release notes")
    ap.add_argument("--group", default="", help="group name shown in the app")
    ap.add_argument("--pbf", required=True)
    ap.add_argument("--poly", required=True)
    ap.add_argument("--file", help="output file name (default: <id>.zip)")
    ap.add_argument("--source-date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, args.file or f"{args.id}.zip")
    tmp = tempfile.mkdtemp(prefix="pack-")
    try:
        t = time.time()
        print(f"[1/3] Reading {args.pbf}")
        writer = BlockWriter(tmp)
        c = Collector(writer)
        c.apply_file(args.pbf, locations=True)
        writer.close()
        print(f"  roads: {c.ways}, with maxspeed: {c.with_maxspeed}, places: {len(c.places)}, {time.time() - t:.0f}s")

        print("[2/3] Boundary")
        outer, holes = read_poly(args.poly)
        complete = complete_tiles(outer, holes)
        print(f"  complete tiles: {len(complete)}")

        blocks = set(writer.blocks)
        for tx, ty in complete:
            blocks.add((tx // BLOCK_TILES, ty // BLOCK_TILES))
        place_blocks = {}
        for p in c.places:
            for b in blocks_of(p[1], p[2], p[1], p[2], PLACE_PAD):
                place_blocks.setdefault(b, []).append(p)

        print("[3/3] Writing pack")
        manifest = {
            "format": 1,
            "id": args.id,
            "country": args.country.upper(),
            "name": args.name,
            "name_en": args.name_en,
            "group": args.group,
            "created": int(time.time() * 1000),
            "tileDeg": TILE_DEG,
            "source": f"© OpenStreetMap contributors (ODbL), Geofabrik extract {args.source_date}",
            "stats": {"roads": c.ways, "maxspeed": c.with_maxspeed, "places": len(c.places)},
            "complete": [v for tx, ty in sorted(complete) for v in (tx, ty)],
            "blocks": [
                {"file": f"blocks/{bx}_{by}.json",
                 "x0": bx * BLOCK_TILES, "x1": bx * BLOCK_TILES + BLOCK_TILES - 1,
                 "y0": by * BLOCK_TILES, "y1": by * BLOCK_TILES + BLOCK_TILES - 1}
                for bx, by in sorted(blocks)
            ],
        }
        with zipfile.ZipFile(out + ".part", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
            for b in sorted(blocks):
                places = ",".join(
                    json.dumps({"type": "node", "id": p[0], "lat": p[1], "lon": p[2], "tags": {"place": p[3]}},
                               separators=(",", ":"))
                    for p in place_blocks.get(b, []))
                part = writer.path(b)
                ways = open(part, encoding="utf-8").read() if os.path.exists(part) else ""
                body = ",".join(x for x in (ways, places) if x)
                z.writestr(f"blocks/{b[0]}_{b[1]}.json", '{"elements":[' + body + "]}")
        os.replace(out + ".part", out)
        print(f"  {out}: {os.path.getsize(out) / 1048576:.1f} MB, {len(blocks)} blocks, {time.time() - t:.0f}s total")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
