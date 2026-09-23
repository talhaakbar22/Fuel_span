"""Load OPIS fuel-price CSV and attach coordinates from the US cities dataset."""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from routing.models import FuelStation
from routing.services.geo import US_STATE_CODES


def _load_city_coordinates(path: Path) -> dict[tuple[str, str], tuple[float, float]]:
    """Map (city_lower, state_code) → (lat, lon). Prefer first occurrence."""
    coords: dict[tuple[str, str], tuple[float, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["CITY"].strip().lower(), row["STATE_CODE"].strip().upper())
            if key in coords:
                continue
            try:
                coords[key] = (float(row["LATITUDE"]), float(row["LONGITUDE"]))
            except (KeyError, TypeError, ValueError):
                continue
    return coords


class Command(BaseCommand):
    help = (
        "Import data/fuel-prices.csv into FuelStation and geocode via data/us_cities.csv"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fuel-csv",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "fuel-prices.csv"),
        )
        parser.add_argument(
            "--cities-csv",
            type=str,
            default=str(Path(settings.BASE_DIR) / "data" / "us_cities.csv"),
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing FuelStation rows before import",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        fuel_path = Path(options["fuel_csv"])
        cities_path = Path(options["cities_csv"])

        if not fuel_path.exists():
            raise CommandError(f"Fuel CSV not found: {fuel_path}")
        if not cities_path.exists():
            raise CommandError(f"Cities CSV not found: {cities_path}")

        if options["flush"]:
            deleted, _ = FuelStation.objects.all().delete()
            self.stdout.write(f"Deleted {deleted} existing station rows")

        city_coords = _load_city_coordinates(cities_path)
        self.stdout.write(f"Loaded {len(city_coords)} city coordinates")

        created = updated = skipped_non_us = skipped_bad = unmatched_geo = 0
        seen_keys: set[tuple] = set()

        with fuel_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            expected = {
                "OPIS Truckstop ID",
                "Truckstop Name",
                "Address",
                "City",
                "State",
                "Rack ID",
                "Retail Price",
            }
            if not reader.fieldnames or not expected.issubset(set(reader.fieldnames)):
                raise CommandError(
                    f"Unexpected CSV headers: {reader.fieldnames}. Expected {expected}"
                )

            batch: list[FuelStation] = []
            for row in reader:
                state = (row.get("State") or "").strip().upper()
                if state not in US_STATE_CODES:
                    skipped_non_us += 1
                    continue

                try:
                    opis_id = int(str(row["OPIS Truckstop ID"]).strip())
                    price = Decimal(str(row["Retail Price"]).strip())
                except (ValueError, InvalidOperation):
                    skipped_bad += 1
                    continue

                name = (row.get("Truckstop Name") or "").strip()
                address = (row.get("Address") or "").strip()
                city = (row.get("City") or "").strip()
                if not name or not city:
                    skipped_bad += 1
                    continue

                rack_raw = (row.get("Rack ID") or "").strip()
                try:
                    rack_id = int(rack_raw) if rack_raw else None
                except ValueError:
                    rack_id = None

                dedupe_key = (opis_id, name.lower(), address.lower(), city.lower(), state)
                if dedupe_key in seen_keys:
                    skipped_bad += 1
                    continue
                seen_keys.add(dedupe_key)

                lat = lon = None
                geo = city_coords.get((city.lower(), state))
                if geo:
                    lat, lon = geo
                else:
                    unmatched_geo += 1

                batch.append(
                    FuelStation(
                        opis_id=opis_id,
                        name=name[:255],
                        address=address[:255],
                        city=city[:128],
                        state=state,
                        rack_id=rack_id,
                        retail_price=price,
                        latitude=lat,
                        longitude=lon,
                    )
                )

                if len(batch) >= 500:
                    FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
                    created += len(batch)
                    batch.clear()

            if batch:
                FuelStation.objects.bulk_create(batch, ignore_conflicts=True)
                created += len(batch)

        total = FuelStation.objects.count()
        with_coords = FuelStation.objects.filter(latitude__isnull=False).count()
        self.stdout.write(self.style.SUCCESS(
            f"Import finished. rows_written≈{created}, db_total={total}, "
            f"with_coordinates={with_coords}, skipped_non_us={skipped_non_us}, "
            f"skipped_bad_or_dup={skipped_bad}, unmatched_city_geocode={unmatched_geo}"
        ))
