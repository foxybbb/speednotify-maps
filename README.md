# SpeedNotify map packs

Offline speed-limit data for the **SpeedNotify** Android app (a floating speedometer with
iGO-style over-speed warnings for car head units).

Each pack contains the roads of one country or region, their `maxspeed` tags and the
settlements used to tell urban roads from rural ones. The data comes from OpenStreetMap.
Packs are rebuilt every month by GitHub Actions and published as
[releases](../../releases/latest).

## Using the packs

The app downloads packs by itself: **Maps by country → Download**. It reads the catalog from

```
https://github.com/foxybbb/speednotify-maps/releases/latest/download/catalog.json
```

so a new monthly release is picked up automatically, and the app offers an update when a newer
pack is available. A head unit without internet can import a pack from a USB stick:
copy the `.zip` from the release and use **Import pack from file**.

## Coverage

| Group | Regions |
|---|---|
| Baltics | Estonia (`EE`), Latvia (`LV`), Lithuania (`LT`) |
| Northern Europe | Denmark (`DK`), Finland (`FI`), Faroe Islands (`FO`), Iceland (`IS`), Norway (`NO`), Sweden (`SE`) |
| Western Europe | Belgium (`BE`), France (`FR`), United Kingdom (`GB`), Guernsey and Jersey (`GG`), Ireland (`IE`), Isle of Man (`IM`), Luxembourg (`LU`), Monaco (`MC`), Netherlands (`NL`) |
| Central Europe | Austria (`AT`), Switzerland (`CH`), Czechia (`CZ`), Germany (`DE`), Hungary (`HU`), Liechtenstein (`LI`), Poland (`PL`), Slovakia (`SK`), Slovenia (`SI`) |
| Southern Europe | Andorra (`AD`), Cyprus (`CY`), Spain (`ES`), Greece (`GR`), Italy (`IT`), Malta (`MT`), Portugal (`PT`), Azores (`PT-AZ`), Turkey (`TR`) |
| Balkans | Albania (`AL`), Bosnia and Herzegovina (`BA`), Bulgaria (`BG`), Croatia (`HR`), Montenegro (`ME`), North Macedonia (`MK`), Romania (`RO`), Serbia (`RS`), Kosovo (`XK`) |
| Eastern Europe | Belarus (`BY`), Georgia (`GE`), Moldova (`MD`), Ukraine (`UA`) |
| Russia (European part) | Russia: Central FD (`RU-CFD`), Russia: Northwestern FD (`RU-NWFD`), Russia: Southern FD (`RU-SFD`), Russia: Volga FD (`RU-VFD`), Russia: North Caucasian FD (`RU-NCFD`), Russia: Kaliningrad (`RU-KGD`) |

Russia is split into the federal districts of its European part. To add a region,
add a line to [`regions.json`](regions.json) with the matching
[Geofabrik](https://download.geofabrik.de/) path.

## How a release is built

[`.github/workflows/build-maps.yml`](.github/workflows/build-maps.yml) runs on the 3rd of every month
and can also be started by hand (*Actions → Build map packs → Run workflow*). You can pass a list of
region ids to rebuild only some of them.

1. **plan** reads `regions.json` and makes a build matrix.
2. **build**, one job per region:
   - downloads the Geofabrik extract and its boundary (`.poly`);
   - keeps only roads and places with `osmium tags-filter`;
   - runs [`scripts/build_pack.py`](scripts/build_pack.py).
3. **publish**:
   - collects the packs; for any region that was not rebuilt or failed, it keeps that region's
     pack from the previous release;
   - writes `catalog.json` and the release notes with [`scripts/make_catalog.py`](scripts/make_catalog.py);
   - publishes the release;
   - keeps the three newest releases and deletes older ones.

To build a pack locally:

```sh
pip install osmium
python3 scripts/build_pack.py --id EE --country EE --name Estonia \
    --pbf estonia-latest.osm.pbf --poly estonia.poly --out dist
```

## Pack format (version 1)

A zip archive:

- `manifest.json` comes first and holds:
  - `id`, `country` (ISO 3166-1, used for the country's default limits) and `name`;
  - `tileDeg` (0.05° tiles);
  - `complete`: a flat list of tile coordinates `[x, y, …]`. These tiles lie fully inside the
    extract boundary. Border tiles are left out, so the app can top them up with roads of the
    neighbouring country;
  - `blocks`: the list of block files.
- `blocks/<bx>_<by>.json` are 0.5°×0.5° blocks in Overpass JSON format. Way geometry is stored
  compactly as `"g": [lat, lon, lat, lon, …]`.

`catalog.json`:

```json
{"format": 1, "packs": [{"id": "EE", "country": "EE", "name": "Эстония", "name_en": "Estonia",
  "group": "Прибалтика", "group_id": "baltic", "file": "EE-estonia.zip", "size": 7605137,
  "created": 1760345000000, "sha256": "…"}]}
```

## License

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under
the [Open Database License (ODbL) 1.0](LICENSE). Extracts are provided by
[Geofabrik](https://download.geofabrik.de/). The scripts in this repository may be used under the same terms.
