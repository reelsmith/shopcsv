"""Shopify product CSV column definitions and allowed values."""

from __future__ import annotations

# The column set written by ``shopcsv build``, in Shopify's order.
HEADERS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Product Category",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Option3 Name",
    "Option3 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Image Src",
    "Image Position",
    "Image Alt Text",
    "Status",
]

# Other columns Shopify's importer understands. Unknown columns only produce
# a warning, because Shopify ignores them rather than failing the import.
EXTRA_KNOWN_HEADERS = [
    "Standardized Product Type",
    "Custom Product Type",
    "Variant Barcode",
    "Variant Image",
    "Variant Weight Unit",
    "Variant Tax Code",
    "Cost per item",
    "Gift Card",
    "SEO Title",
    "SEO Description",
    "Included / International",
    "Price / International",
    "Compare At Price / International",
    "Option1 Linked To",
    "Option2 Linked To",
    "Option3 Linked To",
]

KNOWN_HEADERS = frozenset(HEADERS) | frozenset(EXTRA_KNOWN_HEADERS)

# Prefixes of column families Shopify accepts (metafields, Google Shopping, markets).
KNOWN_HEADER_PREFIXES = ("Google Shopping /", "Included /", "Price /", "Compare At Price /")
KNOWN_HEADER_MARKERS = ("metafields.", "(product.metafields", "(variant.metafields")

# Columns that only make sense on a variant row.
VARIANT_COLUMNS = [
    "Option1 Value",
    "Option2 Value",
    "Option3 Value",
    "Variant SKU",
    "Variant Grams",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Variant Barcode",
    "Variant Image",
    "Variant Weight Unit",
    "Cost per item",
]

INVENTORY_POLICIES = {"deny", "continue"}
STATUSES = {"active", "draft", "archived"}
BOOLEANS = {"true", "false"}
BOOLEAN_COLUMNS = ["Published", "Variant Requires Shipping", "Variant Taxable", "Gift Card"]
WEIGHT_UNITS = {"g", "kg", "lb", "oz"}

# Shopify's per-product limits.
MAX_OPTIONS = 3
MAX_VARIANTS = 2048
MAX_ALT_TEXT = 512

DEFAULT_OPTION_NAME = "Title"
DEFAULT_OPTION_VALUE = "Default Title"


def is_known_header(name: str) -> bool:
    if name in KNOWN_HEADERS:
        return True
    if name.startswith(KNOWN_HEADER_PREFIXES):
        return True
    return any(marker in name for marker in KNOWN_HEADER_MARKERS)
