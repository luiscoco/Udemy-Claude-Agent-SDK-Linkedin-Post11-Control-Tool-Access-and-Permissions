"""A tiny module for the inspection agent to discover and explain."""


def calculate_total(prices: list[float], discount: float = 0.0) -> float:
    """Return the total after applying a fractional discount."""
    if not 0 <= discount <= 1:
        raise ValueError("discount must be between zero and one")
    # TODO: use Decimal if this becomes a real billing system.
    return round(sum(prices) * (1 - discount), 2)
