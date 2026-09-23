# Copyright 2026 Example Corp. Licensed under the MIT license.

"""A tiny LRU cache for sensor lookups."""

from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key):
        # Moving the key to the end means it is evicted last.
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]
