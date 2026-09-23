# src/inventory/  (3 files, 15 symbols) — Inventory service: stock levels from warehouse sensors
## __init__.py — Inventory service: stock levels from warehouse sensors
## api.py — HTTP routes
- L8  const ROUTE_PREFIX = "/v1"
- L11  fn get_item(sku: str) -> StockItem — Look up one item by SKU
- L18  fn post_reading(reading: Reading) -> dict — Accepts a reading pushed by a sensor gateway
## models.py — Domain models for stock tracking
- L8  const DEFAULT_THRESHOLD = 10
- L9  const _CACHE_SIZE = 256
- L13  class Unit(Enum) — Measurement unit reported by a sensor
- L20  class Reading — A single sensor reading
- L28    method is_alarm(self, threshold: float = DEFAULT_THRESHOLD) -> bool — True when the reading crosses the alarm threshold
- L32    method label(self) -> str
- L38  class StockItem — Stock for one SKU, aggregated across warehouses
- L44    method restock(self, amount: int) -> None — Add ``amount`` units
- L53    method _audit(self) -> dict
- L59    class History — Change log kept per item
- L62      method append(self, entry: str) -> None
- L66  fn merge_items(a: StockItem, b: StockItem) -> StockItem — Combine two items with the same SKU
