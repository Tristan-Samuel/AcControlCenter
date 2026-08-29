"""Store temperatures in Celsius; display Fahrenheit in the UI."""

from __future__ import annotations


def celsius_to_fahrenheit(celsius: float | None) -> float | None:
    if celsius is None:
        return None
    return (celsius * 9 / 5) + 32


def fahrenheit_to_celsius(fahrenheit: float | None) -> float | None:
    if fahrenheit is None:
        return None
    return (fahrenheit - 32) * 5 / 9


def format_temp_f(temp_celsius: float | None, include_unit: bool = True) -> str:
    if temp_celsius is None:
        return "N/A"
    temp = celsius_to_fahrenheit(temp_celsius)
    suffix = "°F" if include_unit else ""
    return f"{temp:.1f}{suffix}"
