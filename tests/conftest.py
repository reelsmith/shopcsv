import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from shopcsv.schema import HEADERS  # noqa: E402


def make_csv(rows, header=None):
    """Build CSV text from row dicts; missing columns are blank."""
    header = header or HEADERS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in header})
    return buf.getvalue()


def product_row(**overrides):
    """A valid first row of a single-variant product."""
    row = {
        "Handle": "led-lights",
        "Title": "LED Lights",
        "Body (HTML)": "<p>Bright.</p>",
        "Vendor": "Acme",
        "Published": "TRUE",
        "Option1 Name": "Title",
        "Option1 Value": "Default Title",
        "Variant SKU": "LED-1",
        "Variant Grams": "100",
        "Variant Inventory Tracker": "shopify",
        "Variant Inventory Qty": "5",
        "Variant Inventory Policy": "deny",
        "Variant Fulfillment Service": "manual",
        "Variant Price": "19.99",
        "Variant Compare At Price": "29.99",
        "Variant Requires Shipping": "TRUE",
        "Variant Taxable": "TRUE",
        "Image Src": "https://cdn.example.com/a.jpg",
        "Image Position": "1",
        "Image Alt Text": "Lights",
        "Status": "active",
    }
    row.update(overrides)
    return row
