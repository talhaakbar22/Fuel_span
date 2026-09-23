"""Shared helpers for routing and fuel optimization."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_MILES = 3958.7613
MAX_RANGE_MILES = 500.0
MPG = 10.0
TANK_GALLONS = MAX_RANGE_MILES / MPG  # 50 gallons

# Contiguous US + AK/HI/DC — assignment is USA-only.
US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
        "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
        "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
        "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
        "WI", "WY", "DC",
    }
)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def decode_polyline(polyline: str, precision: int = 5) -> list[tuple[float, float]]:
    """Decode Google-encoded polyline into (lat, lon) pairs."""
    coordinates: list[tuple[float, float]] = []
    index = lat = lon = 0
    factor = 10**precision

    while index < len(polyline):
        result = shift = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else (result >> 1)
        lat += dlat

        result = shift = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if result & 1 else (result >> 1)
        lon += dlon
        coordinates.append((lat / factor, lon / factor))

    return coordinates


def route_cumulative_miles(
    coordinates: Sequence[tuple[float, float]],
) -> list[float]:
    """Cumulative road distance along consecutive coordinates."""
    miles = [0.0]
    total = 0.0
    for i in range(1, len(coordinates)):
        total += haversine_miles(
            coordinates[i - 1][0],
            coordinates[i - 1][1],
            coordinates[i][0],
            coordinates[i][1],
        )
        miles.append(total)
    return miles


def project_point_onto_route(
    lat: float,
    lon: float,
    coordinates: Sequence[tuple[float, float]],
    cumulative: Sequence[float],
) -> tuple[float, float]:
    """
    Approximate distance-along-route and perpendicular offset for a point.

    Returns (miles_along_route, distance_to_route_miles).
    """
    best_offset = float("inf")
    best_along = 0.0

    for i in range(len(coordinates) - 1):
        lat1, lon1 = coordinates[i]
        lat2, lon2 = coordinates[i + 1]
        seg_len = cumulative[i + 1] - cumulative[i]
        if seg_len <= 0:
            continue

        # Project in a local equirectangular plane (good enough for short segments).
        x = (lon - lon1) * math.cos(math.radians((lat + lat1) / 2))
        y = lat - lat1
        dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
        dy = lat2 - lat1
        denom = dx * dx + dy * dy
        t = 0.0 if denom == 0 else max(0.0, min(1.0, (x * dx + y * dy) / denom))
        proj_lat = lat1 + t * (lat2 - lat1)
        proj_lon = lon1 + t * (lon2 - lon1)
        offset = haversine_miles(lat, lon, proj_lat, proj_lon)
        if offset < best_offset:
            best_offset = offset
            best_along = cumulative[i] + t * seg_len

    return best_along, best_offset


def bounding_box_for_route(
    coordinates: Iterable[tuple[float, float]],
    padding_degrees: float = 0.75,
) -> tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lon, max_lon) with padding."""
    lats = [c[0] for c in coordinates]
    lons = [c[1] for c in coordinates]
    return (
        min(lats) - padding_degrees,
        max(lats) + padding_degrees,
        min(lons) - padding_degrees,
        max(lons) + padding_degrees,
    )
