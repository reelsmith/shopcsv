"""Expand a friendly YAML/JSON product spec into a Shopify product CSV."""

from __future__ import annotations

import csv
import io
import itertools
import json
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from . import schema


class BuildError(ValueError):
    """Raised when the product spec is invalid."""


PRODUCT_KEYS = {
    "title", "handle", "description", "body_html", "vendor", "product_category", "category", "type",
    "tags", "published", "status", "price", "compare_at", "grams", "inventory_qty", "inventory_policy",
    "inventory_tracker", "fulfillment_service", "requires_shipping", "taxable", "sku_prefix", "sku",
    "images", "options", "overrides",
}
VARIANT_KEYS = {"price", "compare_at", "grams", "inventory_qty", "inventory_policy", "requires_shipping",
                "taxable", "sku"}


# ---------------------------------------------------------------- loading

def load_spec(path: str) -> Any:
    """Load a spec file. ``.json`` is parsed with the stdlib; anything else needs PyYAML."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        text = fh.read()
    if os.path.splitext(path)[1].lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise BuildError(f"{path}: invalid JSON: {exc}") from exc
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            return json.loads(text)  # JSON is valid YAML, so accept it without PyYAML
        except json.JSONDecodeError:
            raise BuildError("reading YAML needs PyYAML: pip install pyyaml (or use a .json spec)") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BuildError(f"{path}: invalid YAML: {exc}") from exc


# ---------------------------------------------------------------- helpers

def slugify(text: str) -> str:
    """Make a Shopify-style handle: lowercase ASCII words joined by hyphens."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def sku_part(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "", text).upper()


def _sku_prefix(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return text.strip("-").upper()


def _money(value: Any, field: str, where: str) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        raise BuildError(f"{where}: {field} must be a number, got {value!r}")
    try:
        d = Decimal(str(value).strip().lstrip("$"))
    except InvalidOperation:
        raise BuildError(f"{where}: {field} must be a number, got {value!r}") from None
    if not d.is_finite() or d < 0:
        raise BuildError(f"{where}: {field} must be a non-negative number, got {value!r}")
    return str(d.quantize(Decimal("0.01")))


def _int(value: Any, field: str, where: str) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        raise BuildError(f"{where}: {field} must be a whole number, got {value!r}")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise BuildError(f"{where}: {field} must be a whole number, got {value!r}") from None
    if not d.is_finite() or d != d.to_integral_value():
        raise BuildError(f"{where}: {field} must be a whole number, got {value!r}")
    return str(int(d))


def _bool(value: Any, field: str, where: str) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
        return "TRUE" if value.strip().lower() in ("true", "yes") else "FALSE"
    raise BuildError(f"{where}: {field} must be true or false, got {value!r}")


def _tags(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(t).strip() for t in value]
    else:
        items = [t.strip() for t in str(value).split(",")]
    seen, out = set(), []
    for t in items:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return ", ".join(out)


def _images(value: Any, title: str, where: str) -> List[Dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, (str, dict)):
        value = [value]
    out = []
    for n, img in enumerate(value, start=1):
        if isinstance(img, str):
            src, alt = img, ""
        elif isinstance(img, dict) and "src" in img:
            src, alt = str(img["src"]), str(img.get("alt") or "")
        else:
            raise BuildError(f"{where}: images[{n - 1}] must be a URL or {{src, alt}}")
        src = src.strip()
        if not re.match(r"^https?://\S+$", src, re.IGNORECASE):
            raise BuildError(f"{where}: image {src!r} must be an http(s) URL")
        out.append({"src": src, "alt": alt or title})
    return out


def _options(value: Any, where: str) -> List[tuple]:
    """Return [(name, [values...]), ...] from a mapping or a list of {name: values} / {name, values}."""
    if not value:
        return []
    pairs: List[tuple] = []
    if isinstance(value, dict):
        pairs = list(value.items())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and "name" in item and "values" in item:
                pairs.append((item["name"], item["values"]))
            elif isinstance(item, dict) and len(item) == 1:
                pairs.extend(item.items())
            else:
                raise BuildError(f"{where}: each option must be {{Name: [values]}} or {{name, values}}")
    else:
        raise BuildError(f"{where}: options must be a mapping like {{Color: [Red, Blue]}}")
    if len(pairs) > schema.MAX_OPTIONS:
        raise BuildError(f"{where}: Shopify allows at most {schema.MAX_OPTIONS} options, got {len(pairs)}")
    out, names = [], set()
    for name, values in pairs:
        name = str(name).strip()
        if not name:
            raise BuildError(f"{where}: option names cannot be empty")
        if name.lower() in names:
            raise BuildError(f"{where}: duplicate option name {name!r}")
        names.add(name.lower())
        if isinstance(values, (str, int, float)):
            values = [values]
        if not isinstance(values, list) or not values:
            raise BuildError(f"{where}: option {name!r} needs a non-empty list of values")
        vals = [str(v).strip() for v in values]
        lowered = [v.lower() for v in vals]
        if "" in vals:
            raise BuildError(f"{where}: option {name!r} has an empty value")
        if len(set(lowered)) != len(lowered):
            raise BuildError(f"{where}: option {name!r} has duplicate values")
        out.append((name, vals))
    return out


def _normalize_spec(spec: Any) -> tuple:
    """Accept a single product, a list of products, or {defaults, products}."""
    defaults: Dict[str, Any] = {}
    if isinstance(spec, dict) and "products" in spec:
        defaults = spec.get("defaults") or {}
        products = spec["products"]
        unknown = set(spec) - {"products", "defaults"}
        if unknown:
            raise BuildError(f"unknown top-level keys: {', '.join(sorted(unknown))}")
    elif isinstance(spec, dict):
        products = [spec]
    elif isinstance(spec, list):
        products = spec
    else:
        raise BuildError("spec must be a product, a list of products, or {products: [...]}")
    if not isinstance(defaults, dict):
        raise BuildError("defaults must be a mapping")
    if not isinstance(products, list) or not products:
        raise BuildError("spec contains no products")
    return defaults, products


# ---------------------------------------------------------------- building

def build_rows(spec: Any) -> List[Dict[str, str]]:
    """Expand a spec into a list of CSV row dicts keyed by :data:`schema.HEADERS`."""
    defaults, products = _normalize_spec(spec)
    rows: List[Dict[str, str]] = []
    used_handles: Dict[str, int] = {}
    used_skus: set = set()
    for i, raw in enumerate(products):
        if not isinstance(raw, dict):
            raise BuildError(f"products[{i}] must be a mapping")
        product = {**defaults, **raw}
        rows.extend(_build_product(product, i, used_handles, used_skus))
    return rows


def _build_product(p: Dict[str, Any], index: int, used_handles: Dict[str, int], used_skus: set):
    title = str(p.get("title") or "").strip()
    where = f"products[{index}]" + (f" ({title})" if title else "")
    unknown = set(p) - PRODUCT_KEYS
    if unknown:
        raise BuildError(f"{where}: unknown keys: {', '.join(sorted(unknown))}")
    if not title:
        raise BuildError(f"{where}: title is required")
    if p.get("price") is None:
        raise BuildError(f"{where}: price is required")

    handle = slugify(p["handle"]) if p.get("handle") else slugify(title)
    if not handle:
        raise BuildError(f"{where}: could not derive a handle from the title; set handle explicitly")
    if handle in used_handles:
        if p.get("handle"):
            raise BuildError(f"{where}: handle {handle!r} is already used by another product")
        used_handles[handle] += 1
        candidate = f"{handle}-{used_handles[handle]}"
        while candidate in used_handles:
            used_handles[handle] += 1
            candidate = f"{handle}-{used_handles[handle]}"
        handle = candidate
    used_handles[handle] = 1

    status = str(p.get("status", "active")).strip().lower()
    if status not in schema.STATUSES:
        raise BuildError(f"{where}: status must be one of active, draft, archived")
    policy = str(p.get("inventory_policy", "deny")).strip().lower()
    if policy not in schema.INVENTORY_POLICIES:
        raise BuildError(f"{where}: inventory_policy must be 'deny' or 'continue'")

    options = _options(p.get("options"), where)
    images = _images(p.get("images"), title, where)
    sku_prefix = _sku_prefix(p.get("sku_prefix") or p.get("sku") or handle) or "SKU"

    base = {
        "price": p.get("price"),
        "compare_at": p.get("compare_at"),
        "grams": p.get("grams", 0),
        "inventory_qty": p.get("inventory_qty", 0),
        "inventory_policy": policy,
        "requires_shipping": p.get("requires_shipping", True),
        "taxable": p.get("taxable", True),
    }

    overrides = p.get("overrides") or []
    if not isinstance(overrides, list):
        raise BuildError(f"{where}: overrides must be a list")
    option_names = [n for n, _ in options]
    for k, ov in enumerate(overrides):
        if not isinstance(ov, dict) or not isinstance(ov.get("match"), dict):
            raise BuildError(f"{where}: overrides[{k}] needs a 'match' mapping, e.g. match: {{Size: L}}")
        bad = set(ov) - VARIANT_KEYS - {"match"}
        if bad:
            raise BuildError(f"{where}: overrides[{k}] has unknown keys: {', '.join(sorted(bad))}")
        for name, val in ov["match"].items():
            if name not in option_names:
                raise BuildError(f"{where}: overrides[{k}] matches unknown option {name!r}")
            values = dict(options)[name]
            if str(val) not in values:
                raise BuildError(f"{where}: overrides[{k}] matches unknown value {val!r} for option {name!r}")

    combos = list(itertools.product(*[vals for _, vals in options])) if options else [()]
    if len(combos) > schema.MAX_VARIANTS:
        raise BuildError(f"{where}: {len(combos)} variants exceeds Shopify's limit of {schema.MAX_VARIANTS}")

    rows = []
    for v_index, combo in enumerate(combos):
        chosen = dict(zip(option_names, combo))
        fields = dict(base)
        for ov in overrides:
            if all(chosen.get(n) == str(val) for n, val in ov["match"].items()):
                fields.update({k: v for k, v in ov.items() if k != "match"})
        vwhere = where + (" [" + " / ".join(combo) + "]" if combo else "")

        price = _money(fields["price"], "price", vwhere)
        compare_at = _money(fields.get("compare_at"), "compare_at", vwhere)
        if compare_at and Decimal(compare_at) < Decimal(price):
            raise BuildError(f"{vwhere}: compare_at ({compare_at}) must be >= price ({price})")
        vpolicy = str(fields["inventory_policy"]).strip().lower()
        if vpolicy not in schema.INVENTORY_POLICIES:
            raise BuildError(f"{vwhere}: inventory_policy must be 'deny' or 'continue'")

        sku = fields.get("sku")  # only set by an override; product-level `sku` is a prefix alias
        explicit = bool(sku)
        if not sku:
            parts = [sku_prefix] + [sku_part(v) for v in combo]
            sku = "-".join(x for x in parts if x)
        sku = str(sku).strip()
        if sku in used_skus and explicit:
            raise BuildError(f"{vwhere}: sku {sku!r} is already used by another variant")
        if sku in used_skus:
            n = 2
            while f"{sku}-{n}" in used_skus:
                n += 1
            sku = f"{sku}-{n}"
        used_skus.add(sku)

        row = {h: "" for h in schema.HEADERS}
        row["Handle"] = handle
        for n in range(schema.MAX_OPTIONS):
            if n < len(combo):
                row[f"Option{n + 1} Value"] = combo[n]
        if not options:
            row["Option1 Value"] = schema.DEFAULT_OPTION_VALUE
        row.update({
            "Variant SKU": sku,
            "Variant Grams": _int(fields["grams"], "grams", vwhere),
            "Variant Inventory Tracker": "shopify",
            "Variant Inventory Qty": _int(fields["inventory_qty"], "inventory_qty", vwhere),
            "Variant Inventory Policy": vpolicy,
            "Variant Fulfillment Service": str(p.get("fulfillment_service") or "manual"),
            "Variant Price": price,
            "Variant Compare At Price": compare_at,
            "Variant Requires Shipping": _bool(fields["requires_shipping"], "requires_shipping", vwhere),
            "Variant Taxable": _bool(fields["taxable"], "taxable", vwhere),
        })
        if v_index == 0:
            row.update({
                "Title": title,
                "Body (HTML)": str(p.get("body_html") or _description_html(p.get("description"))),
                "Vendor": str(p.get("vendor") or ""),
                "Product Category": str(p.get("product_category") or p.get("category") or ""),
                "Type": str(p.get("type") or ""),
                "Tags": _tags(p.get("tags")),
                "Published": _bool(p.get("published", True), "published", where),
                "Status": status,
            })
            if options:
                for n, name in enumerate(option_names):
                    row[f"Option{n + 1} Name"] = name
            else:
                row["Option1 Name"] = schema.DEFAULT_OPTION_NAME
        rows.append(row)

    # First image rides on the first variant row; the rest get image-only rows.
    for pos, img in enumerate(images, start=1):
        if pos == 1:
            target = rows[0]
        else:
            target = {h: "" for h in schema.HEADERS}
            target["Handle"] = handle
            rows.append(target)
        target["Image Src"] = img["src"]
        target["Image Position"] = str(pos)
        target["Image Alt Text"] = img["alt"]
    return rows


def _description_html(desc: Any) -> str:
    """Plain-text descriptions become <p> paragraphs; text that already looks like HTML is kept."""
    if not desc:
        return ""
    desc = str(desc).strip()
    if re.search(r"<[a-zA-Z][^>]*>", desc):
        return desc
    # Blank lines separate paragraphs; single newlines are soft wraps.
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", desc) if p.strip()]
    esc = [p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for p in paras]
    return "".join(f"<p>{p}</p>" for p in esc)


def rows_to_csv(rows: Sequence[Dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=schema.HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def build_csv(spec: Any) -> str:
    """Build CSV text from an already-loaded spec."""
    return rows_to_csv(build_rows(spec))


def build_file(input_path: str, output_path: Optional[str] = None) -> str:
    """Build from a spec file; writes ``output_path`` (UTF-8) if given and returns the CSV text."""
    text = build_csv(load_spec(input_path))
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    return text
