"""HTTP routes."""

from fastapi import FastAPI

from .models import Reading, StockItem

app = FastAPI()
ROUTE_PREFIX = "/v1"


@app.get("/items/{sku}")
async def get_item(sku: str) -> StockItem:
    """Look up one item by SKU."""
    return StockItem(sku)


# Accepts a reading pushed by a sensor gateway.
@app.post("/readings")
async def post_reading(reading: Reading) -> dict:
    return {"alarm": reading.is_alarm()}
