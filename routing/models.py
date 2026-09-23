from django.db import models


class FuelStation(models.Model):
    """Truck stop loaded from the OPIS fuel-prices CSV."""

    opis_id = models.PositiveIntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128, db_index=True)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=6)
    latitude = models.FloatField(null=True, blank=True, db_index=True)
    longitude = models.FloatField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["state", "city"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["opis_id", "name", "address", "city", "state"],
                name="unique_station_row",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) @ ${self.retail_price}"
