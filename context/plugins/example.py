"""Example plugin — a simple calculator and dice roller.

Drop this file in ``context/plugins/`` and it auto-registers via the ``@tool`` decorator.
"""

from micron.plugins import tool
import random


@tool(name="roll_dice", description="Roll N dice with M sides each")
def roll_dice(count: int = 1, sides: int = 6) -> str:
    """Roll *count* dice, each with *sides* faces. Returns results as text."""
    if count < 1 or count > 100:
        return "Error: count must be between 1 and 100"
    if sides < 2 or sides > 1000:
        return "Error: sides must be between 2 and 1000"
    results = [random.randint(1, sides) for _ in range(count)]
    total = sum(results)
    return f"Rolled {count}d{sides}: [{', '.join(str(r) for r in results)}] total={total}"


@tool(name="reverse_text", description="Reverse a string of text")
def reverse_text(text: str = "") -> str:
    """Reverse the input text."""
    if not text:
        return "Error: no text provided"
    return text[::-1]