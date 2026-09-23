"""Geocoding and OSRM routing — keep external HTTP calls to a minimum."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import requests
from django.conf import settings

from .geo import decode_polyline, route_cumulative_miles

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float
    display_name: str = ""


@dataclass(frozen=True)
class RouteResult:
    distance_miles: float
    duration_seconds: float
    coordinates: list[tuple[float, float]]  # (lat, lon)
    cumulative_miles: list[float]
    geometry_geojson: dict[str, Any]
    map_url: str


class GeocodingError(Exception):
    pass


class RoutingError(Exception):
    pass


def _nominatim_headers() -> dict[str, str]:
    return {
        "User-Agent": getattr(
            settings,
            "NOMINATIM_USER_AGENT",
            "fuel-route-api/1.0 (django assessment)",
        )
    }


@lru_cache(maxsize=256)
def geocode_location(query: str) -> LatLng:
    """
    Resolve a free-text USA place to coordinates via Nominatim (OpenStreetMap).

    Cached in-process so repeated identical start/finish strings do not
    burn extra external calls.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    try:
        response = requests.get(
            url, params=params, headers=_nominatim_headers(), timeout=20
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding failed for '{query}': {exc}") from exc

    if not data:
        raise GeocodingError(f"No USA location found for '{query}'")

    hit = data[0]
    return LatLng(
        lat=float(hit["lat"]),
        lng=float(hit["lon"]),
        display_name=hit.get("display_name", query),
    )


def fetch_route(start: LatLng, finish: LatLng) -> RouteResult:
    """
    Single OSRM driving route request (ideal: one map/routing API call).

    Uses the public OSRM demo server — free, no API key.
    """
    base = getattr(
        settings,
        "OSRM_BASE_URL",
        "https://router.project-osrm.org",
    ).rstrip("/")
    coords = f"{start.lng},{start.lat};{finish.lng},{finish.lat}"
    url = f"{base}/route/v1/driving/{coords}"
    params = {
        "overview": "full",
        "geometries": "polyline",
        "steps": "false",
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RoutingError(f"OSRM routing failed: {exc}") from exc

    if payload.get("code") != "Ok" or not payload.get("routes"):
        raise RoutingError(f"OSRM returned no route: {payload.get('code')}")

    route = payload["routes"][0]
    coordinates = decode_polyline(route["geometry"])
    cumulative = route_cumulative_miles(coordinates)
    # Prefer OSRM's road distance when available (meters → miles).
    distance_miles = float(route["distance"]) / 1609.344
    duration_seconds = float(route["duration"])

    geojson = {
        "type": "LineString",
        "coordinates": [[lon, lat] for lat, lon in coordinates],
    }
    # Shareable map link — no extra API call.
    mid = coordinates[len(coordinates) // 2]
    map_url = (
        "https://www.openstreetmap.org/directions?"
        f"engine=fossgis_osrm_car&route={start.lat}%2C{start.lng}"
        f"%3B{finish.lat}%2C{finish.lng}"
        f"#map=6/{mid[0]:.4f}/{mid[1]:.4f}"
    )

    return RouteResult(
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        coordinates=coordinates,
        cumulative_miles=cumulative,
        geometry_geojson=geojson,
        map_url=map_url,
    )


def static_map_hint(coordinates: list[tuple[float, float]]) -> str:
    """Lightweight OSM browse URL centered on the route midpoint."""
    if not coordinates:
        return "https://www.openstreetmap.org"
    mid = coordinates[len(coordinates) // 2]
    return f"https://www.openstreetmap.org/#map=6/{mid[0]:.4f}/{mid[1]:.4f}"
