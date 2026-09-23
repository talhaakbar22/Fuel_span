from __future__ import annotations

import json

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from routing.services.fuel_planner import plan_fuel_stops, stations_near_route
from routing.services.geo import MAX_RANGE_MILES, MPG
from routing.services.routing import (
    GeocodingError,
    RoutingError,
    fetch_route,
    geocode_location,
)


def home(request):
    """Interactive map UI for planning a route and fuel stops."""
    return render(
        request,
        "routing/index.html",
        {
            "max_range_miles": int(MAX_RANGE_MILES),
            "mpg": int(MPG),
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        },
    )


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def route_fuel_plan(request):
    """
    Plan a USA driving route and cost-effective fuel stops.

    GET query params or JSON body:
      - start: free-text location (e.g. "Chicago, IL")
      - finish: free-text location (e.g. "Dallas, TX")
    """
    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode() or "{}")
        except json.JSONDecodeError:
            return _error("Invalid JSON body")
        start_q = (payload.get("start") or "").strip()
        finish_q = (payload.get("finish") or "").strip()
    else:
        start_q = (request.GET.get("start") or "").strip()
        finish_q = (request.GET.get("finish") or "").strip()

    if not start_q or not finish_q:
        return _error("Both 'start' and 'finish' are required (USA locations).")

    try:
        start = geocode_location(start_q)
        finish = geocode_location(finish_q)
        route = fetch_route(start, finish)
        candidates = stations_near_route(route.coordinates, route.cumulative_miles)
        plan = plan_fuel_stops(route.distance_miles, candidates)
    except GeocodingError as exc:
        return _error(str(exc), status=404)
    except RoutingError as exc:
        return _error(str(exc), status=502)
    except ValueError as exc:
        return _error(str(exc), status=422)

    stops_payload = [
        {
            "opis_id": stop.station.opis_id,
            "name": stop.station.name,
            "address": stop.station.address,
            "city": stop.station.city,
            "state": stop.station.state,
            "latitude": stop.station.latitude,
            "longitude": stop.station.longitude,
            "price_per_gallon": stop.price_per_gallon,
            "miles_along_route": stop.miles_along_route,
            "detour_miles": stop.detour_miles,
            "gallons": stop.gallons,
            "cost": stop.cost,
        }
        for stop in plan.stops
    ]

    return JsonResponse(
        {
            "start": {
                "query": start_q,
                "latitude": start.lat,
                "longitude": start.lng,
                "display_name": start.display_name,
            },
            "finish": {
                "query": finish_q,
                "latitude": finish.lat,
                "longitude": finish.lng,
                "display_name": finish.display_name,
            },
            "vehicle": {
                "max_range_miles": MAX_RANGE_MILES,
                "mpg": MPG,
                "assumed_start_tank_gallons": plan.assumed_start_tank_gallons,
            },
            "route": {
                "distance_miles": round(route.distance_miles, 2),
                "duration_seconds": round(route.duration_seconds, 1),
                "geometry": route.geometry_geojson,
                "map_url": route.map_url,
                "candidate_stations_along_route": len(candidates),
            },
            "fuel_stops": stops_payload,
            "total_gallons": plan.total_gallons,
            "total_fuel_cost": plan.total_fuel_cost,
            "external_api_calls": {
                "nominatim_geocode": 2,
                "osrm_route": 1,
                "note": "Fuel prices and station coordinates are served from the local DB.",
            },
        }
    )
