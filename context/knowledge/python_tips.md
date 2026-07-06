# 10 Essential Python Tips & Tricks

Source: Compiled from "Programming in Python: 10 Essential Tricks Every Developer Should Know in 2025" by Dovydas

---

## 1. Master Comprehensions and Generator Expressions

```python
# List comprehension (eager, in memory)
squares = [x * x for x in range(10) if x % 2 == 0]

# Dict comprehension
name_by_id = {u["id"]: u["name"] for u in users}

# Set comprehension (auto de-duplicate)
unique_domains = {email.split("@")[1] for email in emails}

# Generator expression (lazy, memory-friendly)
gen = (x * x for x in range(10_000_000))

# Nested comprehension
pairs = [(a, b) for a in A for b in B if a < b]

# Generator with sum/any
total = sum(x for x in numbers if x > 0)
```

## 2. Use Unpacking and the Walrus Operator

```python
# Swap without temp
a, b = b, a

# Extended iterable unpacking
first, *middle, last = [10, 20, 30, 40]  # first=10, middle=[20,30], last=40

# Merge dictionaries
merged = {**defaults, **overrides}

# Walrus operator — assign and use in one expression
while (line := input(">> ").strip()):
    print(line.upper())

# Walrus in comprehensions
pairs = [(s, n) for s in strings if (n := len(s)) > 3]
```

## 3. Level Up String Formatting with f-Strings

```python
# Debug mode (prints variable name and value)
total = 1234.567
print(f"{total=}")  # total=1234.567

# Number formatting
print(f"${price:,.2f}")  # $1,234.57

# Date formatting
from datetime import datetime
print(f"Report generated at {now:%Y-%m-%d %H:%M}")

# Repr for logs
print(f"{data!r}")

# Text alignment
print(f"[{user:^10}]")  # centered, width 10
```

## 4. Dataclasses + Typing

```python
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)
class Order:
    items: list[Product] = field(default_factory=list)
    tax_rate: float = 0.07

    def total(self) -> float:
        subtotal = sum(p.price for p in self.items)
        return round(subtotal * (1 + self.tax_rate), 2)

# Validation in __post_init__
@dataclass
class User:
    email: str
    def __post_init__(self):
        if "@" not in self.email:
            raise ValueError("Invalid email")
```

## 5. Structural Pattern Matching (match/case)

```python
# Simple value matching
match status_code:
    case 200: handle_ok()
    case 404: handle_not_found()
    case _:   handle_other()

# Deconstruct mappings
match event:
    case {"type": "user", "action": "create", "name": name}:
        create_user(name)
    case {"type": "user", "action": "delete", "id": user_id}:
        delete_user(user_id)
    case _: log_unhandled(event)

# Class patterns with dataclasses
match p:
    case Point(x=0, y=0): return "origin"
    case Point(x, y) if x > 0 and y > 0: return "Q1"
    case _: return "other"
```

## 6. The Batteries: itertools, collections, functools

```python
from collections import Counter, defaultdict

# Counter
words = "to be or not to be".split()
counts = Counter(words)  # {'to': 2, 'be': 2, 'or': 1, 'not': 1}

# defaultdict for auto-indexing
index = defaultdict(list)
for i, w in enumerate(words):
    index[w].append(i)

# deque with maxlen
from collections import deque
q = deque(maxlen=3)

# itertools: islice, pairwise, groupby, batched
from itertools import islice, pairwise, batched

first_ten = list(islice(range(1000), 10))
pairs = list(pairwise([1, 2, 4, 7]))  # [(1,2), (2,4), (4,7)]
batches = list(batched(range(10), 3))  # Python 3.12+

# functools: caching and partial
from functools import lru_cache, partial

@lru_cache(maxsize=256)
def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)

square = partial(power, exp=2)
```

## 7. Use pathlib for Files and Paths

```python
from pathlib import Path

base = Path.home() / "reports"
base.mkdir(parents=True, exist_ok=True)

report = base / "2025-01.txt"
report.write_text("Hello, world!\n", encoding="utf-8")
print(report.read_text(encoding="utf-8"))

# Glob files
for csv_path in base.glob("*.csv"):
    print(csv_path.name, csv_path.stat().st_size)

# Combine with json
import json
data = json.loads(data_path.read_text(encoding="utf-8"))
```

## 8. Context Managers for Resource Safety

```python
from contextlib import suppress, contextmanager, ExitStack

# Suppress specific exceptions
with suppress(FileNotFoundError):
    Path("maybe.txt").unlink()

# Manage multiple resources
with ExitStack() as stack:
    handles = [stack.enter_context(open(f, "w")) for f in files]

# Custom context manager
@contextmanager
def timed(label: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"{label} took {elapsed:.3f}s")
```

## 9. Debug Smarter with breakpoint() and Logging

```python
# Drop into debugger at any point
breakpoint()  # Opens pdb at this line

# Quick pdb commands: n (next), s (step), c (continue), p x (print), q (quit)

# Production logging (not print)
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("billing")
logger.info("Charge started for %s", customer_id)
logger.error("Charge failed", exc_info=True)

# Deprecation warnings
import warnings
warnings.warn("old_api is deprecated; use new_api", DeprecationWarning, stacklevel=2)
```

## 10. Concurrency: asyncio and Futures

```python
import asyncio

# Async I/O with timeouts (Python 3.11+)
async def main():
    try:
        async with asyncio.timeout(2):
            await fetch_slow()
    except TimeoutError:
        print("Timed out!")

# Offload blocking code
result = await asyncio.to_thread(do_blocking_work, arg1, arg2)

# CPU-bound work with processes
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor() as pool:
    results = list(pool.map(expensive_cpu_bound, numbers))
```

## Bonus Micro-Tricks

- Use `enumerate` and `zip` over index gymnastics: `for i, item in enumerate(items, start=1):`
- Use `any` and `all` for clean checks: `if any(err.severe for err in errors):`
- Default dict lookups: `value = mapping.get(key, default_value)`
- Measure with `timeit`: `timeit.timeit("sum(range(1000))", number=1000)`

---

Tags: python, tips, tricks, best-practices, 2025