"""Many traps, one picture: outbreak map and early warnings between neighbouring farms.

Pure functions (no database):
  - distance_km(): great-circle distance between two stations
  - early_warnings(): farms near an outbreak that are still below their threshold
  - heat_grid(): a smooth "pest pressure" surface between stations for the map,
                 by inverse-distance weighting (IDW) - nearer stations count more

"Pressure" = pests per day / that station's action threshold
             (1.0 = exactly at the action level).
"""
from __future__ import annotations

import math


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance on the Earth's surface."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pressure(station: dict) -> float:
    return station["pests_per_day"] / station["threshold"] if station["threshold"] else 0.0


def early_warnings(stations: list[dict], radius_km: float) -> dict[str, list[dict]]:
    """For each station still below its threshold, the outbreaks (stations at/above threshold)
    within radius_km, nearest first."""
    out: dict[str, list[dict]] = {s["id"]: [] for s in stations}
    for s in stations:
        if pressure(s) >= 1:
            continue  # already an outbreak itself: it has its own SPRAY/BIOCONTROL advice
        for o in stations:
            if o["id"] == s["id"] or pressure(o) < 1:
                continue
            km = distance_km(s["lat"], s["lon"], o["lat"], o["lon"])
            if km <= radius_km:
                out[s["id"]].append({"neighbour_id": o["id"], "neighbour": o["name"], "km": round(km, 1),
                                     "neighbour_pests_per_day": o["pests_per_day"],
                                     "neighbour_action": o.get("action")})
        out[s["id"]].sort(key=lambda w: w["km"])
    return out


def heat_grid(stations: list[dict], cols: int = 40, rows: int = 30, pad: float = 0.25,
              power: float = 2.0) -> dict:
    """IDW-interpolated pressure on a lat/lon grid around the stations."""
    if not stations:
        return {"cells": [], "bbox": None, "cols": cols, "rows": rows}
    lats = [s["lat"] for s in stations]
    lons = [s["lon"] for s in stations]
    dlat = max(max(lats) - min(lats), 0.01)
    dlon = max(max(lons) - min(lons), 0.01)
    bbox = {"south": min(lats) - pad * dlat, "north": max(lats) + pad * dlat,
            "west": min(lons) - pad * dlon, "east": max(lons) + pad * dlon}
    cells = []
    for r in range(rows):
        lat = bbox["north"] - (r + 0.5) * (bbox["north"] - bbox["south"]) / rows
        row = []
        for c in range(cols):
            lon = bbox["west"] + (c + 0.5) * (bbox["east"] - bbox["west"]) / cols
            num = den = 0.0
            exact = None
            for s in stations:
                d = distance_km(lat, lon, s["lat"], s["lon"])
                if d < 0.05:
                    exact = pressure(s)
                    break
                w = 1 / d ** power
                num += w * pressure(s)
                den += w
            row.append(round(exact if exact is not None else num / den, 3))
        cells.append(row)
    return {"cells": cells, "bbox": bbox, "cols": cols, "rows": rows}
