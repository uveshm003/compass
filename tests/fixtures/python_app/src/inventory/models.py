"""Domain models for stock tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

DEFAULT_THRESHOLD = 10
_CACHE_SIZE = 256
registry = {}


class Unit(Enum):
    """Measurement unit reported by a sensor."""

    PPM = "ppm"
    PERCENT_LEL = "%LEL"


@dataclass
class Reading:
    """A single sensor reading. Values are raw, not calibrated."""

    sensor_id: str
    value: float
    unit: Unit = Unit.PPM

    def is_alarm(self, threshold: float = DEFAULT_THRESHOLD) -> bool:
        """True when the reading crosses the alarm threshold."""
        return self.value >= threshold

    @property
    def label(self) -> str:
        return f"{self.sensor_id}:{self.value}{self.unit.value}"


# Stock for one SKU, aggregated across warehouses.
@dataclass
class StockItem:
    sku: str
    quantity: int = 0
    locations: list[str] = field(default_factory=list)

    def restock(self, amount: int) -> None:
        """Add ``amount`` units.

        Raises ValueError for negative amounts.
        """
        if amount < 0:
            raise ValueError("amount must be positive")
        self.quantity += amount

    def _audit(self) -> dict:
        def fmt(value):  # local helper, kept out of the map
            return str(value)

        return {"sku": fmt(self.sku)}

    class History:
        """Change log kept per item."""

        def append(self, entry: str) -> None:
            pass


def merge_items(
    a: StockItem,
    b: StockItem,
) -> StockItem:
    """Combine two items with the same SKU."""
    return StockItem(a.sku, a.quantity + b.quantity, a.locations + b.locations)
