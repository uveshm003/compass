"""Inventory service: stock levels from warehouse sensors."""

from inventory.models import Reading, StockItem

__all__ = ["Reading", "StockItem"]
