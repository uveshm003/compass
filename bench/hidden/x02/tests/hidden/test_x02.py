"""Hidden acceptance test for bench task x02: copied in after the run."""

import pytest

from inventory.models import StockItem


def test_restock_adds_to_the_quantity_on_hand():
    item = StockItem("sku-1")
    item.restock(5)
    item.restock(3)
    assert item.quantity == 8


def test_negative_amounts_still_raise():
    with pytest.raises(ValueError):
        StockItem("sku-1").restock(-1)
