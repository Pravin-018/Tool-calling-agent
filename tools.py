"""Offline tools for reading and working with the shop's stock CSV."""

import csv
import math
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


DATA_FILE = Path(__file__).resolve().parent / "data" / "stock.csv"
MAX_RESULT_LENGTH = 1200


def _short(text: str) -> str:
    """Keep tool responses concise so large CSVs do not flood the model context."""
    if len(text) <= MAX_RESULT_LENGTH:
        return text
    return text[: MAX_RESULT_LENGTH - 20].rstrip() + "\n[Output shortened.]"


def _read_stock() -> tuple[list[dict[str, str]], str | None]:
    """Load CSV rows and return a polite error instead of raising file/format errors."""
    try:
        with DATA_FILE.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            required_columns = {
                "product_id",
                "product_name",
                "category",
                "quantity",
                "reorder_level",
                "supplier",
                "daily_sales",
            }
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                return [], "The stock file is missing one or more required columns."
            rows = list(reader)
            if any(None in row for row in rows):
                return [], "The stock file contains a row with an invalid number of columns."
            return rows, None
    except FileNotFoundError:
        return [], "The stock file could not be found. Please check data/stock.csv."
    except (OSError, UnicodeError, csv.Error):
        return [], "The stock file could not be read. Please check that it is a valid CSV."


def _field(row: dict[str, str], name: str) -> str:
    """Return one trimmed CSV value without treating it as executable instructions."""
    return (row.get(name) or "").strip()


def _number(row: dict[str, str], field: str) -> float | None:
    try:
        value = float(_field(row, field))
        if not math.isfinite(value) or value < 0:
            return None
        return value
    except (TypeError, ValueError):
        return None


def _format_quantity(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


@tool
def lookup_stock(query: str) -> str:
    """Look up products by name or category when the owner asks for their stock details."""
    search_text = query.strip().casefold() if isinstance(query, str) else ""
    if not search_text:
        return "Please provide a product name or category to search for."

    rows, error = _read_stock()
    if error:
        return error

    matches = [
        row
        for row in rows
        if search_text in _field(row, "product_name").casefold()
        or search_text in _field(row, "category").casefold()
    ]
    if not matches:
        return f"No matching product was found for '{_short(search_text)}'."

    results = []
    for row in matches[:15]:
        results.append(
            "- "
            f"{_short(_field(row, 'product_name'))}: quantity {_short(_field(row, 'quantity'))}, "
            f"reorder level {_short(_field(row, 'reorder_level'))}, "
            f"supplier {_short(_field(row, 'supplier'))}, "
            f"daily sales {_short(_field(row, 'daily_sales'))}."
        )
    if len(matches) > 15:
        results.append(f"Showing 15 of {len(matches)} matches.")
    return _short("\n".join(results))


@tool
def calculate_stock_status(product_name: str = "all") -> str:
    """Calculate reorder status and estimated days remaining for one product or all products."""
    search_text = product_name.strip().casefold() if isinstance(product_name, str) else ""
    if not search_text:
        return "Provide a product name, or use 'all' to check every product."

    rows, error = _read_stock()
    if error:
        return error

    if search_text == "all":
        matches = rows
    else:
        matches = [
            row for row in rows if search_text in _field(row, "product_name").casefold()
        ]
    if not matches:
        return f"No matching product was found for '{_short(search_text)}'."

    results = []
    for row in matches:
        name = _short(_field(row, "product_name"))
        quantity = _number(row, "quantity")
        reorder_level = _number(row, "reorder_level")
        daily_sales = _number(row, "daily_sales")

        if quantity is None or reorder_level is None:
            results.append(f"- {name}: stock status unavailable (invalid quantity or reorder level).")
            continue

        status = "LOW" if quantity < reorder_level else "OK"
        if daily_sales is None:
            days = "days n/a (invalid daily sales)"
        elif daily_sales == 0:
            days = "days n/a (zero daily sales)"
        else:
            days = f"{quantity / daily_sales:.1f} days"
        results.append(
            f"- {name}: {_format_quantity(quantity)} on hand, "
            f"level {_format_quantity(reorder_level)}, {status}, {days}."
        )

    if search_text == "all":
        low_stock_count = sum(
            1
            for row in matches
            if _number(row, "quantity") is not None
            and _number(row, "reorder_level") is not None
            and _number(row, "quantity") < _number(row, "reorder_level")
        )
        results.insert(0, f"{low_stock_count} product(s) are below their reorder level.")
    return _short("\n".join(results))


@tool
def draft_reorder_note(product_name: str, suggested_quantity: int | None = None) -> str:
    """Draft a reorder note for the owner to review without sending or placing an order."""
    search_text = product_name.strip().casefold() if isinstance(product_name, str) else ""
    if not search_text:
        return "Please provide the product name for the reorder draft."
    if suggested_quantity is not None and (
        isinstance(suggested_quantity, bool)
        or not isinstance(suggested_quantity, int)
        or suggested_quantity <= 0
    ):
        return "The suggested reorder quantity must be a positive whole number."

    rows, error = _read_stock()
    if error:
        return error

    matches = [
        row for row in rows if search_text in _field(row, "product_name").casefold()
    ]
    if not matches:
        return f"No matching product was found for '{_short(search_text)}'."
    if len(matches) > 1:
        names = ", ".join(_short(_field(row, "product_name")) for row in matches[:5])
        return f"More than one product matched. Please specify one: {names}."

    row: dict[str, Any] = matches[0]
    current_quantity = _number(row, "quantity")
    reorder_level = _number(row, "reorder_level")
    if current_quantity is None or reorder_level is None:
        return "A reorder draft cannot be prepared because the stock quantity data is invalid."

    if suggested_quantity is None:
        # Use twice the reorder level as a simple target, less the current stock.
        suggested_quantity = max(1, int(reorder_level * 2 - current_quantity))

    return _short(
        "Reorder draft for owner review (not sent):\n"
        f"Product: {_short(_field(row, 'product_name'))}\n"
        f"Current quantity: {_format_quantity(current_quantity)}\n"
        f"Suggested reorder quantity: {suggested_quantity}\n"
        f"Supplier: {_short(_field(row, 'supplier'))}\n"
        "Please review and send manually if appropriate."
    )
