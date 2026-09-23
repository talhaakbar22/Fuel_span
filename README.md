# Fuel Route API (Django)

Django API that plans a USA driving route, picks cost-effective fuel stops from the
provided OPIS truck-stop price CSV, and returns route geometry + total fuel cost.

## Constraints encoded

| Constraint | Implementation |
|---|---|
| Start / finish in USA | Nominatim geocode with `countrycodes=us` |
| Max range 500 miles | Planner never exceeds ~480 mi between fills (20 mi safety) |
| 10 MPG | Gallons = miles / 10; tank ≈ 50 gal |
| Fuel prices from CSV | `data/fuel-prices.csv` loaded into SQLite |
| Minimize map API calls | 2× Nominatim + **1× OSRM** per request; stations are local |
| Fast responses | Stations pre-geocoded offline via `data/us_cities.csv` |

## CSV columns used

`OPIS Truckstop ID`, `Truckstop Name`, `Address`, `City`, `State`, `Rack ID`, `Retail Price`

The CSV has **no lat/lng**. At import time we map `City` + `State` to coordinates
using `data/us_cities.csv`. Non-US rows (e.g. Canadian provinces) are skipped.

## Setup

```bash
cd /Users/apple/Developer/fuelspan
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_fuel_stations --flush
python manage.py runserver
```

## UI

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) — enter start/finish, see the route on the map with fuel-stop markers, plus distance, drive time, and estimated fuel cost.

## API

```http
GET /api/route/?start=Chicago,%20IL&finish=Dallas,%20TX
```

or

```http
POST /api/route/
Content-Type: application/json

{"start": "Chicago, IL", "finish": "Dallas, TX"}
```

### Response (shape)

- `route.geometry` — GeoJSON `LineString` (plot on any map)
- `route.map_url` — OpenStreetMap directions link (no extra API call)
- `fuel_stops[]` — optimal on-route stops with price, gallons, cost
- `total_fuel_cost` — dollars spent on fuel for the trip (on-route purchases)

## Fuel algorithm (short)

1. One OSRM drive route → geometry + distance  
2. Select stations within ~10 miles of the route corridor  
3. Start full; while destination is beyond remaining range, among stations
   reachable before empty, pick the **cheapest** (farthest on price ties) and refill  
4. Sum gallons × price at each stop  

## External services

- **OSRM** (`router.project-osrm.org`) — routing  
- **Nominatim** — start/finish geocoding only  
