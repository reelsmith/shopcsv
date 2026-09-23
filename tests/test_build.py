import csv
import io
import json
import os

import pytest

from shopcsv import BuildError, build_csv, build_file, build_rows, load_spec, validate_text
from shopcsv.build import slugify
from shopcsv.schema import HEADERS

EXAMPLES = os.path.join(os.path.dirname(__file__), os.pardir, "examples")


def parse(text):
    return list(csv.DictReader(io.StringIO(text)))


def lights(**kw):
    spec = {
        "title": "Christmas LED String Lights",
        "price": 24.99,
        "compare_at": 39.99,
        "sku_prefix": "XMAS-LED",
        "options": {"Color": ["Warm White", "Multicolor"], "Length": ["10m", "20m", "30m"]},
        "images": ["https://cdn.example.com/1.jpg", {"src": "https://cdn.example.com/2.jpg", "alt": "Balcony"}],
        "tags": ["christmas", "led", "Christmas"],
    }
    spec.update(kw)
    return spec


# ------------------------------------------------------------------ expansion

def test_cartesian_product_of_options():
    rows = build_rows(lights(images=None))
    combos = [(r["Option1 Value"], r["Option2 Value"]) for r in rows]
    assert combos == [
        ("Warm White", "10m"), ("Warm White", "20m"), ("Warm White", "30m"),
        ("Multicolor", "10m"), ("Multicolor", "20m"), ("Multicolor", "30m"),
    ]


def test_three_options():
    spec = lights(options={"A": ["1", "2"], "B": ["x", "y"], "C": ["p", "q", "r"]}, images=None)
    rows = build_rows(spec)
    assert len(rows) == 12
    assert rows[0]["Option3 Name"] == "C"
    assert len({(r["Option1 Value"], r["Option2 Value"], r["Option3 Value"]) for r in rows}) == 12


def test_product_fields_only_on_first_row():
    rows = build_rows(lights(images=None))
    first, rest = rows[0], rows[1:]
    assert first["Title"] == "Christmas LED String Lights"
    assert first["Option1 Name"] == "Color" and first["Option2 Name"] == "Length"
    assert first["Status"] == "active" and first["Published"] == "TRUE"
    for r in rest:
        assert r["Title"] == "" and r["Option1 Name"] == "" and r["Status"] == ""
        assert r["Handle"] == first["Handle"]


def test_variant_defaults():
    row = build_rows(lights(images=None))[0]
    assert row["Variant Price"] == "24.99"
    assert row["Variant Compare At Price"] == "39.99"
    assert row["Variant Inventory Policy"] == "deny"
    assert row["Variant Inventory Tracker"] == "shopify"
    assert row["Variant Inventory Qty"] == "0"
    assert row["Variant Fulfillment Service"] == "manual"
    assert row["Variant Requires Shipping"] == "TRUE"
    assert row["Variant Taxable"] == "TRUE"


def test_no_options_gives_default_title_variant():
    rows = build_rows({"title": "Tree Topper", "price": "14.5"})
    assert len(rows) == 1
    assert rows[0]["Option1 Name"] == "Title"
    assert rows[0]["Option1 Value"] == "Default Title"
    assert rows[0]["Variant Price"] == "14.50"


def test_options_as_list_forms():
    a = build_rows({"title": "T", "price": 1, "options": [{"Size": ["S", "M"]}, {"name": "Color", "values": ["Red"]}]})
    assert [(r["Option1 Value"], r["Option2 Value"]) for r in a] == [("S", "Red"), ("M", "Red")]
    assert a[0]["Option2 Name"] == "Color"


def test_numeric_option_values_become_strings():
    rows = build_rows({"title": "Rug", "price": 1, "options": {"Width": [60, 90]}})
    assert [r["Option1 Value"] for r in rows] == ["60", "90"]


# ------------------------------------------------------------------ handles & skus

def test_handle_generated_from_title():
    assert build_rows(lights())[0]["Handle"] == "christmas-led-string-lights"


@pytest.mark.parametrize("title,expected", [
    ("Cafe Creme Mug", "cafe-creme-mug"),
    ("Caf" + chr(0xE9) + " Cr" + chr(0xE8) + "me Mug", "cafe-creme-mug"),
    ("  Lights & Tinsel!! 2026 ", "lights-and-tinsel-2026"),
    ("100% Wool -- Scarf", "100-wool-scarf"),
])
def test_slugify(title, expected):
    assert slugify(title) == expected


def test_explicit_handle_is_slugified():
    assert build_rows({"title": "X", "handle": "My Handle", "price": 1})[0]["Handle"] == "my-handle"


def test_duplicate_generated_handles_get_suffix():
    rows = build_rows([{"title": "Lights", "price": 1}, {"title": "Lights", "price": 2}, {"title": "lights", "price": 3}])
    assert [r["Handle"] for r in rows] == ["lights", "lights-2", "lights-3"]


def test_duplicate_explicit_handle_is_error():
    with pytest.raises(BuildError, match="already used"):
        build_rows([{"title": "A", "handle": "x", "price": 1}, {"title": "B", "handle": "x", "price": 1}])


def test_skus_generated_from_prefix_and_options():
    skus = [r["Variant SKU"] for r in build_rows(lights(images=None))]
    assert skus[0] == "XMAS-LED-WARMWHITE-10M"
    assert skus[-1] == "XMAS-LED-MULTICOLOR-30M"
    assert len(set(skus)) == len(skus)


def test_sku_prefix_defaults_to_handle():
    rows = build_rows({"title": "Star Topper", "price": 1, "options": {"Size": ["S"]}})
    assert rows[0]["Variant SKU"] == "STAR-TOPPER-S"


def test_colliding_generated_skus_are_made_unique():
    # "A B" and "AB" normalise to the same SKU part.
    rows = build_rows({"title": "T", "price": 1, "sku_prefix": "T", "options": {"Style": ["A B", "AB"]}})
    assert [r["Variant SKU"] for r in rows] == ["T-AB", "T-AB-2"]


# ------------------------------------------------------------------ overrides

def test_overrides_apply_to_matching_variants():
    spec = lights(images=None, overrides=[
        {"match": {"Length": "30m"}, "price": 39.99, "compare_at": 59.99},
        {"match": {"Color": "Multicolor", "Length": "30m"}, "inventory_qty": 0, "inventory_policy": "continue"},
    ])
    rows = {(r["Option1 Value"], r["Option2 Value"]): r for r in build_rows(spec)}
    assert rows[("Warm White", "10m")]["Variant Price"] == "24.99"
    assert rows[("Warm White", "30m")]["Variant Price"] == "39.99"
    assert rows[("Multicolor", "30m")]["Variant Compare At Price"] == "59.99"
    assert rows[("Multicolor", "30m")]["Variant Inventory Policy"] == "continue"
    assert rows[("Warm White", "30m")]["Variant Inventory Policy"] == "deny"


def test_override_explicit_sku():
    spec = lights(images=None, overrides=[{"match": {"Color": "Warm White", "Length": "10m"}, "sku": "WW10"}])
    assert build_rows(spec)[0]["Variant SKU"] == "WW10"


def test_override_explicit_sku_duplicate_is_error():
    spec = lights(images=None, overrides=[{"match": {"Color": "Warm White"}, "sku": "WW"}])
    with pytest.raises(BuildError, match="already used"):
        build_rows(spec)


@pytest.mark.parametrize("override,msg", [
    ({"match": {"Size": "L"}, "price": 1}, "unknown option"),
    ({"match": {"Color": "Purple"}, "price": 1}, "unknown value"),
    ({"price": 1}, "match"),
    ({"match": {"Color": "Multicolor"}, "colour": "x"}, "unknown keys"),
])
def test_bad_overrides(override, msg):
    with pytest.raises(BuildError, match=msg):
        build_rows(lights(overrides=[override]))


# ------------------------------------------------------------------ images, tags, body

def test_first_image_on_first_row_rest_on_image_rows():
    rows = build_rows(lights())
    assert len(rows) == 6 + 1
    assert rows[0]["Image Src"] == "https://cdn.example.com/1.jpg"
    assert rows[0]["Image Position"] == "1"
    assert rows[0]["Image Alt Text"] == "Christmas LED String Lights"  # defaults to title
    img = rows[-1]
    assert img["Image Src"] == "https://cdn.example.com/2.jpg"
    assert img["Image Position"] == "2" and img["Image Alt Text"] == "Balcony"
    assert img["Variant SKU"] == "" and img["Option1 Value"] == "" and img["Variant Price"] == ""
    assert all(r["Image Src"] == "" for r in rows[1:-1])


def test_image_must_be_http():
    with pytest.raises(BuildError, match="http"):
        build_rows(lights(images=["cdn.example.com/a.jpg"]))


def test_tags_deduplicated_case_insensitively():
    assert build_rows(lights())[0]["Tags"] == "christmas, led"
    assert build_rows({"title": "T", "price": 1, "tags": "a, b,,a"})[0]["Tags"] == "a, b"


def test_description_becomes_paragraphs():
    rows = build_rows({"title": "T", "price": 1, "description": "Line one\nwraps here.\n\nSecond & last: 1 < 2 > 0."})
    assert rows[0]["Body (HTML)"] == "<p>Line one wraps here.</p><p>Second &amp; last: 1 &lt; 2 &gt; 0.</p>"


def test_html_description_kept_and_body_html_wins():
    assert build_rows({"title": "T", "price": 1, "description": "<b>Hi</b>"})[0]["Body (HTML)"] == "<b>Hi</b>"
    row = build_rows({"title": "T", "price": 1, "description": "x", "body_html": "<p>y</p>"})[0]
    assert row["Body (HTML)"] == "<p>y</p>"


def test_defaults_merge_under_products():
    spec = {"defaults": {"vendor": "Acme", "inventory_qty": 7, "status": "draft"},
            "products": [{"title": "A", "price": 1}, {"title": "B", "price": 1, "vendor": "Other"}]}
    rows = build_rows(spec)
    assert [r["Vendor"] for r in rows] == ["Acme", "Other"]
    assert rows[0]["Variant Inventory Qty"] == "7" and rows[0]["Status"] == "draft"


# ------------------------------------------------------------------ spec errors

@pytest.mark.parametrize("spec,msg", [
    ({"price": 1}, "title is required"),
    ({"title": "T"}, "price is required"),
    ({"title": "T", "price": -1}, "non-negative"),
    ({"title": "T", "price": "free"}, "must be a number"),
    ({"title": "T", "price": 10, "compare_at": 5}, "compare_at"),
    ({"title": "T", "price": 1, "status": "live"}, "status"),
    ({"title": "T", "price": 1, "inventory_policy": "block"}, "inventory_policy"),
    ({"title": "T", "price": 1, "inventory_qty": 1.5}, "whole number"),
    ({"title": "T", "price": 1, "published": "maybe"}, "true or false"),
    ({"title": "T", "price": 1, "colour": "red"}, "unknown keys"),
    ({"title": "T", "price": 1, "options": {"A": [1], "B": [1], "C": [1], "D": [1]}}, "at most 3"),
    ({"title": "T", "price": 1, "options": {"Size": ["S", "s"]}}, "duplicate values"),
    ({"title": "T", "price": 1, "options": {"Size": []}}, "non-empty"),
    ({"title": "!!!", "price": 1}, "handle"),
    ([], "no products"),
    ("nope", "spec must be"),
])
def test_spec_errors(spec, msg):
    with pytest.raises(BuildError, match=msg):
        build_rows(spec)


def test_too_many_variants():
    spec = {"title": "T", "price": 1, "options": {"A": list(range(20)), "B": list(range(20)), "C": list(range(6))}}
    with pytest.raises(BuildError, match="2048"):
        build_rows(spec)


# ------------------------------------------------------------------ output & round trip

def test_csv_header_matches_shopify_order():
    text = build_csv(lights())
    assert text.splitlines()[0].split(",") == HEADERS


def test_round_trip_build_then_validate():
    spec = [lights(overrides=[{"match": {"Length": "30m"}, "price": 30}]),
            {"title": "Tree Topper", "price": 9.5, "images": ["https://cdn.example.com/t.jpg"]}]
    result = validate_text(build_csv(spec))
    assert result.ok and result.issues == [], [i.format() for i in result.issues]
    assert (result.products, result.variants) == (2, 7)


def test_json_spec_without_yaml(tmp_path, monkeypatch):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"products": [lights()]}), encoding="utf-8")
    import builtins
    real_import = builtins.__import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    assert len(parse(build_file(str(path)))) == 7


def test_yaml_file_needs_pyyaml_message(tmp_path, monkeypatch):
    path = tmp_path / "p.yaml"
    path.write_text("title: T\nprice: 1\n", encoding="utf-8")
    import builtins
    real_import = builtins.__import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    with pytest.raises(BuildError, match="PyYAML"):
        load_spec(str(path))


def test_unicode_survives_file_round_trip(tmp_path):
    pytest.importorskip("yaml")
    title = "Cr" + chr(0xE8) + "che Lights " + chr(0x2744)
    spec = tmp_path / "p.yaml"
    spec.write_text(f"title: \"{title}\"\nprice: 5\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    build_file(str(spec), str(out))
    rows = parse(out.read_text(encoding="utf-8"))
    assert rows[0]["Title"] == title
    assert rows[0]["Handle"] == "creche-lights"


def test_example_csv_is_up_to_date():
    pytest.importorskip("yaml")
    spec = os.path.join(EXAMPLES, "products.yaml")
    with open(os.path.join(EXAMPLES, "products.csv"), encoding="utf-8", newline="") as fh:
        committed = fh.read()
    built = build_csv(load_spec(spec))
    assert built == committed, "regenerate with: shopcsv build examples/products.yaml -o examples/products.csv"
    assert validate_text(built).issues == []
