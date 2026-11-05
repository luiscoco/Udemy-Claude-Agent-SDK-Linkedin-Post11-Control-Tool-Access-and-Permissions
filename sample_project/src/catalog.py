"""A small catalog with a deliberate TODO for content searches."""

PRODUCTS = {"notebook": 5.0, "pen": 1.5, "folder": 3.0}


def find_price(product: str) -> float:
    # TODO: provide a clearer error for unknown products.
    return PRODUCTS[product]
