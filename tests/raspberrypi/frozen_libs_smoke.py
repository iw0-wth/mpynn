# SPDX-License-Identifier: MIT
"""Board-side import/behavior test; no network requests or filesystem writes."""
import requests
import ntptime
import bisect
import functools
import itertools
import contextlib
from collections import defaultdict

assert callable(requests.get)
assert callable(ntptime.settime) # Not invoked: no automatic network/time changes.
items = [1, 3]
bisect.insort(items, 2)
assert items == [1, 2, 3]
assert functools.partial(pow, 2)(3) == 8
assert list(itertools.islice(itertools.count(10), 3)) == [10, 11, 12]
counts = defaultdict(int)
counts['key'] += 1
assert counts['key'] == 1

@contextlib.contextmanager
def example():
    yield 42

with example() as value:
    assert value == 42
print('MPYNN_FROZEN_LIBRARIES_PASS')
