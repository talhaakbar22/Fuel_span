"""Cost-aware fuel-stop planner for a fixed driving route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from routing.models import FuelStation

from .geo import (
    MAX_RANGE_MILES,
    MPG,
    TANK_GALLONS,
    bounding_box_for_route,
    project_point_onto_route,
)


@dataclass
class RouteStation:
    station: FuelStation
    miles_along_route: float
    detour_miles: float


@dataclass
class FuelStopPlan:
    station: FuelStation
    miles_along_route: float
    detour_miles: float
    gallons: float
    cost: float
    price_per_gallon: float


@dataclass
class FuelPlanResult:
    stops: list[FuelStopPlan]
    total_fuel_cost: float
    total_gallons: float
    assumed_start_tank_gallons: float


DEFAULT_CORRIDOR_MILES = 10.0
RANGE_SAFETY_MILES = 20.0


def stations_near_route(
    coordinates: Sequence[tuple[float, float]],
    cumulative: Sequence[float],
    corridor_miles: float = DEFAULT_CORRIDOR_MILES,
) -> list[RouteStation]:
    """Load candidate stations in the route bbox, then filter by corridor distance."""
    min_lat, max_lat, min_lon, max_lon = bounding_box_for_route(coordinates)
    qs = FuelStation.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__gte=min_lat,
        latitude__lte=max_lat,
        longitude__gte=min_lon,
        longitude__lte=max_lon,
    )

    nearby: list[RouteStation] = []
    for station in qs.iterator(chunk_size=500):
        along, offset = project_point_onto_route(
            station.latitude,
            station.longitude,
            coordinates,
            cumulative,
        )
        if offset <= corridor_miles:
            nearby.append(
                RouteStation(
                    station=station,
                    miles_along_route=along,
                    detour_miles=offset,
                )
            )

    nearby.sort(key=lambda s: s.miles_along_route)
    return nearby


def plan_fuel_stops(
    route_distance_miles: float,
    candidates: Sequence[RouteStation],
    max_range_miles: float = MAX_RANGE_MILES,
    mpg: float = MPG,
) -> FuelPlanResult:
    """
    Greedy cost-effective refueling along the route.

    Assumptions:
    - Starts with a full tank (50 gal / 500 miles).
    - At each stop, refill the miles of fuel burned since the previous fill
      (top back up to full), and at the final stop also buy fuel for the
      remaining miles to the destination.
    - When a refill is required, choose the cheapest reachable station in
      the current range window (farthest wins ties).
    """
    usable_range = max_range_miles - RANGE_SAFETY_MILES

    if route_distance_miles <= usable_range:
        return FuelPlanResult(
            stops=[],
            total_fuel_cost=0.0,
            total_gallons=0.0,
            assumed_start_tank_gallons=TANK_GALLONS,
        )

    ahead = [
        c
        for c in candidates
        if 0.5 < c.miles_along_route < route_distance_miles - 0.5
    ]
    position = 0.0
    fuel_miles = usable_range
    stops: list[FuelStopPlan] = []
    total_cost = 0.0
    total_gallons = 0.0

    while position + fuel_miles < route_distance_miles:
        reach = position + fuel_miles
        window = [c for c in ahead if position < c.miles_along_route <= reach]
        if not window:
            raise ValueError(
                f"No fuel stations reachable between mile {position:.1f} "
                f"and {reach:.1f}."
            )

        chosen = min(
            window,
            key=lambda c: (float(c.station.retail_price), -c.miles_along_route),
        )

        miles_driven = chosen.miles_along_route - position
        gallons_bought = miles_driven / mpg
        price = float(chosen.station.retail_price)
        cost = gallons_bought * price

        stops.append(
            FuelStopPlan(
                station=chosen.station,
                miles_along_route=round(chosen.miles_along_route, 2),
                detour_miles=round(chosen.detour_miles, 2),
                gallons=round(gallons_bought, 3),
                cost=round(cost, 2),
                price_per_gallon=round(price, 6),
            )
        )
        total_cost += cost
        total_gallons += gallons_bought
        position = chosen.miles_along_route
        fuel_miles = usable_range
        ahead = [c for c in ahead if c.miles_along_route > position]

    if stops:
        remaining_miles = route_distance_miles - stops[-1].miles_along_route
        extra_gallons = remaining_miles / mpg
        extra_cost = extra_gallons * stops[-1].price_per_gallon
        stops[-1].gallons = round(stops[-1].gallons + extra_gallons, 3)
        stops[-1].cost = round(stops[-1].cost + extra_cost, 2)
        total_gallons += extra_gallons
        total_cost += extra_cost

    return FuelPlanResult(
        stops=stops,
        total_fuel_cost=round(total_cost, 2),
        total_gallons=round(total_gallons, 3),
        assumed_start_tank_gallons=TANK_GALLONS,
    )
