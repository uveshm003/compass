from inventory.models import Reading, StockItem


def test_alarm():
    assert Reading("s1", 50.0).is_alarm()


def test_restock():
    item = StockItem("A1")
    item.restock(5)
    assert item.quantity == 5
