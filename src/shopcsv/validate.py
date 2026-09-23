"""Validate a Shopify product CSV against the product importer's rules.

Row numbers follow spreadsheet convention: the header is row 1 and the first
product row is row 2. Each issue carries a stable ``code`` so it can be
filtered or looked up in the README.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import schema

ERROR = "error"
WARNING = "warning"

HANDLE_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
INT_RE = re.compile(r"^-?\d+$")


@dataclass(frozen=True)
class Issue:
    level: str
    row: Optional[int]
    code: str
    message: str
    column: Optional[str] = None

    def format(self, source: str = "") -> str:
        where = source
        if self.row is not None:
            where = f"{where}:{self.row}" if where else f"row {self.row}"
        prefix = f"{where}: " if where else ""
        col = f" ({self.column})" if self.column else ""
        return f"{prefix}{self.level}: [{self.code}]{col} {self.message}"

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "row": self.row,
            "code": self.code,
            "column": self.column,
            "message": self.message,
        }


@dataclass
class Result:
    issues: List[Issue]
    products: int = 0
    variants: int = 0
    rows: int = 0

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors


class _Collector:
    def __init__(self) -> None:
        self.issues: List[Issue] = []

    def error(self, row, code, message, column=None):
        self.issues.append(Issue(ERROR, row, code, message, column))

    def warn(self, row, code, message, column=None):
        self.issues.append(Issue(WARNING, row, code, message, column))


def _get(row: Dict[str, str], col: str) -> str:
    value = row.get(col)
    return value.strip() if isinstance(value, str) else ""


def _parse_decimal(value: str) -> Optional[Decimal]:
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _is_variant_row(row: Dict[str, str]) -> bool:
    return any(_get(row, c) for c in schema.VARIANT_COLUMNS)


def validate_file(path: str, encoding: str = "utf-8-sig") -> Result:
    """Validate a CSV file on disk."""
    with open(path, "r", encoding=encoding, newline="") as fh:
        return validate_text(fh.read())


def validate_text(text: str) -> Result:
    """Validate CSV content given as a string."""
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        records = list(reader)
    except csv.Error as exc:
        return Result([Issue(ERROR, reader.line_num or None, "csv-malformed", f"could not parse CSV: {exc}")])
    if not records or not any(cell.strip() for cell in records[0]):
        return Result([Issue(ERROR, None, "empty-file", "file is empty or has no header row")])
    header = [h.strip() for h in records[0]]
    return validate_records(header, records[1:])


def validate_records(header: Sequence[str], records: Iterable[Sequence[str]]) -> Result:
    """Validate parsed CSV records (the header plus data rows as lists)."""
    out = _Collector()
    header = list(header)

    # ---- header checks -------------------------------------------------
    seen = set()
    for name in header:
        if name in seen:
            out.error(1, "duplicate-column", f"column '{name}' appears more than once", name)
        seen.add(name)
    for required in ("Handle", "Title"):
        if required not in seen:
            out.error(1, "missing-column", f"required column '{required}' is missing", required)
    for name in header:
        if name and not schema.is_known_header(name):
            out.warn(1, "unknown-column", f"column '{name}' is not a Shopify column and will be ignored", name)
        elif not name:
            out.warn(1, "unknown-column", "header has an empty column name")
    if "Handle" not in seen:
        return Result(out.issues)

    # ---- row parsing ---------------------------------------------------
    rows: List[Tuple[int, Dict[str, str]]] = []
    for idx, rec in enumerate(records, start=2):
        if not any(cell.strip() for cell in rec):
            continue
        if len(rec) > len(header):
            out.error(idx, "row-length", f"row has {len(rec)} cells but header has {len(header)} columns")
        elif len(rec) < len(header):
            out.warn(idx, "row-length", f"row has {len(rec)} cells but header has {len(header)} columns; missing cells treated as blank")
        row = {name: (rec[i] if i < len(rec) else "") for i, name in enumerate(header)}
        rows.append((idx, row))

    if not rows:
        out.error(None, "no-rows", "file has a header but no product rows")
        return Result(out.issues)

    # ---- group rows by handle -------------------------------------------
    groups: Dict[str, List[Tuple[int, Dict[str, str]]]] = {}
    order: List[str] = []
    last_handle = None
    for idx, row in rows:
        handle = _get(row, "Handle")
        if not handle:
            out.error(idx, "handle-missing", "every row needs a Handle", "Handle")
            continue
        if handle in groups and handle != last_handle:
            out.warn(idx, "handle-not-contiguous",
                     f"rows for handle '{handle}' are not contiguous; keep a product's rows together", "Handle")
        if handle not in groups:
            groups[handle] = []
            order.append(handle)
        groups[handle].append((idx, row))
        last_handle = handle

    sku_rows: Dict[str, int] = {}
    total_variants = 0
    for handle in order:
        total_variants += _validate_product(handle, groups[handle], out, sku_rows)

    return Result(out.issues, products=len(order), variants=total_variants, rows=len(rows))


def _validate_product(handle, group, out: _Collector, sku_rows: Dict[str, int]) -> int:
    first_idx, first = group[0]

    # Handle format
    if any(ch.isspace() for ch in handle):
        out.error(first_idx, "handle-format", f"handle '{handle}' contains spaces; use hyphens", "Handle")
    elif handle != handle.lower():
        out.error(first_idx, "handle-format", f"handle '{handle}' must be lowercase", "Handle")
    elif not HANDLE_RE.match(handle):
        out.error(first_idx, "handle-format",
                  f"handle '{handle}' may only contain a-z, 0-9 and single hyphens, and cannot start or end with a hyphen",
                  "Handle")
    elif "_" in handle:
        out.warn(first_idx, "handle-format", f"handle '{handle}' contains underscores; Shopify convention is hyphens", "Handle")
    if len(handle) > 255:
        out.error(first_idx, "handle-format", "handle is longer than 255 characters", "Handle")

    # Product-level fields live on the first row
    if not _get(first, "Title"):
        out.error(first_idx, "title-missing", f"first row of product '{handle}' must have a Title", "Title")
    for idx, row in group[1:]:
        title = _get(row, "Title")
        if title and title != _get(first, "Title"):
            out.warn(idx, "title-conflict",
                     "Title differs from the product's first row; Shopify only uses the first row's Title", "Title")

    status = _get(first, "Status")
    if status and status.lower() not in schema.STATUSES:
        out.error(first_idx, "status-invalid",
                  f"Status must be one of active, draft, archived (got '{status}')", "Status")
    for idx, row in group[1:]:
        s = _get(row, "Status")
        if s and s.lower() not in schema.STATUSES:
            out.error(idx, "status-invalid", f"Status must be one of active, draft, archived (got '{s}')", "Status")

    for idx, row in group:
        for col in schema.BOOLEAN_COLUMNS:
            v = _get(row, col)
            if v and v.lower() not in schema.BOOLEANS:
                out.error(idx, "boolean-invalid", f"{col} must be TRUE or FALSE (got '{v}')", col)

    # Options defined by the first row
    option_names: List[str] = []
    for n in range(1, schema.MAX_OPTIONS + 1):
        option_names.append(_get(first, f"Option{n} Name"))
    names_lower = [n.lower() for n in option_names if n]
    if len(names_lower) != len(set(names_lower)):
        out.error(first_idx, "option-name-duplicate", "option names must be unique within a product")
    for n in range(2, schema.MAX_OPTIONS + 1):
        if option_names[n - 1] and not option_names[n - 2]:
            out.error(first_idx, "option-order",
                      f"Option{n} Name is set but Option{n - 1} Name is empty", f"Option{n} Name")
    for idx, row in group[1:]:
        for n in range(1, schema.MAX_OPTIONS + 1):
            name = _get(row, f"Option{n} Name")
            if name and name != option_names[n - 1]:
                out.warn(idx, "option-name-conflict",
                         f"Option{n} Name '{name}' differs from the first row ('{option_names[n - 1]}'); "
                         "Shopify uses the first row's option names", f"Option{n} Name")

    # Variants
    variant_rows = [(idx, row) for i, (idx, row) in enumerate(group) if i == 0 or _is_variant_row(row)]
    combos: Dict[Tuple[str, ...], int] = {}
    for idx, row in variant_rows:
        values = [_get(row, f"Option{n} Value") for n in range(1, schema.MAX_OPTIONS + 1)]
        for n in range(1, schema.MAX_OPTIONS + 1):
            v, name = values[n - 1], option_names[n - 1]
            if v and not name:
                out.error(idx, "option-name-missing",
                          f"Option{n} Value '{v}' is set but the product has no Option{n} Name "
                          "(option names go on the product's first row)", f"Option{n} Name")
            if name and not v and len(variant_rows) > 1:
                out.error(idx, "option-value-missing",
                          f"variant is missing Option{n} Value for option '{name}'", f"Option{n} Value")
            if n > 1 and v and not values[n - 2]:
                out.error(idx, "option-order", f"Option{n} Value is set but Option{n - 1} Value is empty",
                          f"Option{n} Value")
        key = tuple(v.lower() for v in values)
        if any(values):
            if key in combos:
                label = " / ".join(v for v in values if v)
                out.error(idx, "duplicate-variant",
                          f"duplicate option combination '{label}' for handle '{handle}' (first seen on row {combos[key]})")
            else:
                combos[key] = idx
        _validate_variant_fields(idx, row, out, sku_rows)

    if len(variant_rows) > 1 and not option_names[0]:
        out.error(first_idx, "option-name-missing",
                  f"product '{handle}' has {len(variant_rows)} variants but no Option1 Name", "Option1 Name")
    if len(variant_rows) > schema.MAX_VARIANTS:
        out.error(first_idx, "too-many-variants",
                  f"product '{handle}' has {len(variant_rows)} variants; Shopify allows at most {schema.MAX_VARIANTS}")

    # Images
    positions: Dict[int, int] = {}
    for idx, row in group:
        for col in ("Image Src", "Variant Image"):
            src = _get(row, col)
            if src and not re.match(r"^https?://\S+$", src, re.IGNORECASE):
                out.error(idx, "image-url", f"{col} must be an http(s) URL (got '{src}')", col)
        pos = _get(row, "Image Position")
        if pos:
            if not INT_RE.match(pos) or int(pos) < 1:
                out.error(idx, "image-position", f"Image Position must be a positive whole number (got '{pos}')",
                          "Image Position")
            else:
                if not _get(row, "Image Src"):
                    out.warn(idx, "image-position", "Image Position is set but Image Src is empty", "Image Position")
                p = int(pos)
                if p in positions:
                    out.warn(idx, "image-position",
                             f"Image Position {p} is already used on row {positions[p]} for this product",
                             "Image Position")
                else:
                    positions[p] = idx
        alt = _get(row, "Image Alt Text")
        if alt and not _get(row, "Image Src"):
            out.warn(idx, "image-alt", "Image Alt Text is set but Image Src is empty", "Image Alt Text")
        if len(alt) > schema.MAX_ALT_TEXT:
            out.warn(idx, "image-alt", f"Image Alt Text is longer than {schema.MAX_ALT_TEXT} characters",
                     "Image Alt Text")

    return len(variant_rows)


def _validate_variant_fields(idx, row, out: _Collector, sku_rows: Dict[str, int]) -> None:
    price_raw = _get(row, "Variant Price")
    price = None
    if not price_raw:
        out.warn(idx, "price-missing", "Variant Price is empty; Shopify will import it as 0.00", "Variant Price")
    else:
        price = _parse_decimal(price_raw)
        if price is None:
            out.error(idx, "price-invalid", f"Variant Price must be a number (got '{price_raw}')", "Variant Price")
        elif price < 0:
            out.error(idx, "price-negative", f"Variant Price cannot be negative (got '{price_raw}')", "Variant Price")

    cap_raw = _get(row, "Variant Compare At Price")
    if cap_raw:
        cap = _parse_decimal(cap_raw)
        if cap is None:
            out.error(idx, "compare-at-invalid", f"Variant Compare At Price must be a number (got '{cap_raw}')",
                      "Variant Compare At Price")
        elif cap < 0:
            out.error(idx, "compare-at-invalid", f"Variant Compare At Price cannot be negative (got '{cap_raw}')",
                      "Variant Compare At Price")
        elif price is not None and price >= 0:
            if cap < price:
                out.error(idx, "compare-at-below-price",
                          f"Variant Compare At Price ({cap_raw}) must be >= Variant Price ({price_raw})",
                          "Variant Compare At Price")
            elif cap == price:
                out.warn(idx, "compare-at-equals-price",
                         "Variant Compare At Price equals Variant Price, so no sale will be shown",
                         "Variant Compare At Price")

    cost_raw = _get(row, "Cost per item")
    if cost_raw:
        cost = _parse_decimal(cost_raw)
        if cost is None or cost < 0:
            out.error(idx, "cost-invalid", f"Cost per item must be a non-negative number (got '{cost_raw}')",
                      "Cost per item")

    grams = _get(row, "Variant Grams")
    if grams:
        g = _parse_decimal(grams)
        if g is None or g < 0:
            out.error(idx, "grams-invalid", f"Variant Grams must be a non-negative number (got '{grams}')",
                      "Variant Grams")

    unit = _get(row, "Variant Weight Unit")
    if unit and unit.lower() not in schema.WEIGHT_UNITS:
        out.error(idx, "weight-unit-invalid", f"Variant Weight Unit must be one of g, kg, lb, oz (got '{unit}')",
                  "Variant Weight Unit")

    qty = _get(row, "Variant Inventory Qty")
    if qty:
        if not INT_RE.match(qty):
            out.error(idx, "inventory-qty-invalid", f"Variant Inventory Qty must be a whole number (got '{qty}')",
                      "Variant Inventory Qty")
        elif int(qty) < 0:
            out.warn(idx, "inventory-qty-negative", f"Variant Inventory Qty is negative ({qty})",
                     "Variant Inventory Qty")

    policy = _get(row, "Variant Inventory Policy")
    if policy and policy not in schema.INVENTORY_POLICIES:
        hint = " (must be lowercase)" if policy.lower() in schema.INVENTORY_POLICIES else ""
        out.error(idx, "inventory-policy-invalid",
                  f"Variant Inventory Policy must be 'deny' or 'continue' (got '{policy}'){hint}",
                  "Variant Inventory Policy")

    tracker = _get(row, "Variant Inventory Tracker")
    if tracker and tracker.lower() != "shopify":
        out.warn(idx, "inventory-tracker",
                 f"Variant Inventory Tracker '{tracker}' is not 'shopify'; leave blank to not track inventory",
                 "Variant Inventory Tracker")
    if qty and not tracker:
        out.warn(idx, "inventory-tracker",
                 "Variant Inventory Qty is set but Variant Inventory Tracker is blank, so quantity will not be tracked",
                 "Variant Inventory Tracker")

    fulfillment = _get(row, "Variant Fulfillment Service")
    if fulfillment and fulfillment.lower() != "manual":
        out.warn(idx, "fulfillment-service",
                 f"Variant Fulfillment Service '{fulfillment}' must match an installed fulfillment app's handle; "
                 "use 'manual' otherwise", "Variant Fulfillment Service")

    sku = _get(row, "Variant SKU")
    if sku:
        if sku in sku_rows:
            out.warn(idx, "sku-duplicate", f"Variant SKU '{sku}' is also used on row {sku_rows[sku]}", "Variant SKU")
        else:
            sku_rows[sku] = idx
