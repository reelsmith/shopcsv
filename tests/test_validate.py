import pytest

from shopcsv import validate_file, validate_text
from shopcsv.schema import HEADERS

from conftest import make_csv, product_row

BOM = chr(0xFEFF)


def codes(result, level=None):
    return {i.code for i in result.issues if level is None or i.level == level}


def variant_row(handle="lights", **kw):
    row = {
        "Handle": handle,
        "Variant SKU": kw.pop("sku", ""),
        "Variant Price": "10.00",
        "Variant Inventory Policy": "deny",
    }
    row.update(kw)
    return row


def multi_variant(*variants, **first):
    base = product_row(Handle="lights", Title="Lights")
    base.update({"Option1 Name": "Color", "Option1 Value": "Red", "Variant SKU": "L-R"})
    base.update(first)
    return [base] + list(variants)


# ------------------------------------------------------------------ happy path

def test_valid_single_product():
    result = validate_text(make_csv([product_row()]))
    assert result.ok
    assert result.issues == []
    assert (result.products, result.variants, result.rows) == (1, 1, 1)


def test_valid_multi_variant_with_image_rows():
    rows = multi_variant(
        variant_row(**{"Option1 Value": "Blue", "sku": "L-B"}),
        {"Handle": "lights", "Image Src": "https://cdn.example.com/b.jpg", "Image Position": "2"},
    )
    result = validate_text(make_csv(rows))
    assert result.ok, [i.format() for i in result.issues]
    assert result.variants == 2  # the image-only row is not a variant


def test_minimal_header_is_enough():
    assert validate_text("Handle,Title,Variant Price\nmug,Mug,5\n").ok


def test_bom_is_accepted(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(BOM + make_csv([product_row()]), encoding="utf-8")
    assert validate_file(str(path)).ok
    assert validate_text(BOM + make_csv([product_row()])).ok


def test_multiline_body_html_keeps_row_numbers():
    rows = [
        product_row(**{"Body (HTML)": "<p>one</p>\n<p>two</p>"}),
        product_row(Handle="Bad Handle", Title="X", **{"Variant SKU": "B"}),
    ]
    result = validate_text(make_csv(rows))
    [issue] = [i for i in result.errors if i.code == "handle-format"]
    assert issue.row == 3


def test_blank_lines_are_skipped():
    text = make_csv([product_row()]) + ",,,\n\n"
    assert validate_text(text).ok


# ------------------------------------------------------------------ file / header

def test_empty_file():
    assert codes(validate_text("")) == {"empty-file"}


def test_header_only():
    assert "no-rows" in codes(validate_text(",".join(HEADERS) + "\n"))


@pytest.mark.parametrize("missing", ["Handle", "Title"])
def test_missing_required_column(missing):
    header = [h for h in HEADERS if h != missing]
    result = validate_text(make_csv([product_row()], header=header))
    assert any(i.code == "missing-column" and i.column == missing for i in result.errors)


def test_duplicate_column():
    assert "duplicate-column" in codes(validate_text("Handle,Title,Title\nx,X,X\n"), "error")


def test_unknown_column_is_warning_only():
    text = ("Handle,Title,Variant Price,Colour Code,Google Shopping / Gender,"
            "Material (product.metafields.custom.material)\nx,X,1,red,male,wool\n")
    result = validate_text(text)
    assert result.ok
    assert [i.column for i in result.warnings if i.code == "unknown-column"] == ["Colour Code"]


def test_row_too_long_is_error():
    assert "row-length" in codes(validate_text("Handle,Title,Variant Price\nx,X,1,extra\n"), "error")


def test_row_too_short_is_warning():
    result = validate_text("Handle,Title,Variant Price\nx,X\n")
    assert "row-length" in codes(result, "warning")


# ------------------------------------------------------------------ handle / title

@pytest.mark.parametrize("handle", ["LED-Lights", "led lights", "led--lights", "-led", "led!", "led-"])
def test_bad_handles(handle):
    result = validate_text(make_csv([product_row(Handle=handle)]))
    assert "handle-format" in codes(result, "error")


def test_handle_with_underscore_is_warning():
    result = validate_text(make_csv([product_row(Handle="led_lights")]))
    assert result.ok and "handle-format" in codes(result, "warning")


def test_missing_handle():
    result = validate_text(make_csv([product_row(), product_row(Handle="")]))
    assert "handle-missing" in codes(result, "error")


def test_title_required_on_first_row():
    result = validate_text(make_csv([product_row(Title="")]))
    [issue] = [i for i in result.errors if i.code == "title-missing"]
    assert issue.row == 2


def test_title_not_required_on_later_rows():
    rows = multi_variant(variant_row(**{"Option1 Value": "Blue", "sku": "L-B"}))
    assert validate_text(make_csv(rows)).ok


def test_conflicting_title_is_warning():
    rows = multi_variant(variant_row(Title="Other", **{"Option1 Value": "Blue", "sku": "L-B"}))
    result = validate_text(make_csv(rows))
    assert result.ok and "title-conflict" in codes(result)


def test_non_contiguous_handle_warns():
    rows = multi_variant() + [product_row(Handle="other", **{"Variant SKU": "O"})] + [
        variant_row(**{"Option1 Value": "Blue", "sku": "L-B"})
    ]
    assert "handle-not-contiguous" in codes(validate_text(make_csv(rows)), "warning")


# ------------------------------------------------------------------ options / variants

def test_duplicate_variant_combo():
    rows = multi_variant(variant_row(**{"Option1 Value": "red", "sku": "L-R2"}))
    result = validate_text(make_csv(rows))
    [issue] = [i for i in result.errors if i.code == "duplicate-variant"]
    assert issue.row == 3
    assert "row 2" in issue.message


def test_duplicate_variant_combo_two_options():
    rows = multi_variant(
        variant_row(**{"Option1 Value": "Red", "Option2 Value": "M", "sku": "a"}),
        variant_row(**{"Option1 Value": "Red", "Option2 Value": "S", "sku": "b"}),
        **{"Option2 Name": "Size", "Option2 Value": "S"},
    )
    result = validate_text(make_csv(rows))
    assert [i.row for i in result.errors if i.code == "duplicate-variant"] == [4]


def test_same_combo_in_different_products_is_fine():
    rows = [product_row(), product_row(Handle="other", **{"Variant SKU": "O"})]
    assert validate_text(make_csv(rows)).ok


def test_option_value_without_name():
    row = product_row(**{"Option1 Name": "", "Option1 Value": "Red"})
    assert "option-name-missing" in codes(validate_text(make_csv([row])), "error")


def test_option2_value_without_option2_name():
    rows = multi_variant(variant_row(**{"Option1 Value": "Blue", "Option2 Value": "L", "sku": "x"}))
    result = validate_text(make_csv(rows))
    assert any(i.code == "option-name-missing" and i.column == "Option2 Name" for i in result.errors)


def test_option2_name_without_option1_name():
    row = product_row(**{"Option1 Name": "", "Option1 Value": "", "Option2 Name": "Size"})
    assert "option-order" in codes(validate_text(make_csv([row])), "error")


def test_variant_missing_option_value():
    rows = multi_variant(variant_row(sku="x"))
    assert "option-value-missing" in codes(validate_text(make_csv(rows)), "error")


def test_multiple_variants_without_option_name():
    rows = [product_row(**{"Option1 Name": "", "Option1 Value": ""}), variant_row(handle="led-lights", sku="x")]
    assert "option-name-missing" in codes(validate_text(make_csv(rows)), "error")


def test_duplicate_option_names():
    row = product_row(**{"Option1 Name": "Size", "Option1 Value": "S", "Option2 Name": "size", "Option2 Value": "M"})
    assert "option-name-duplicate" in codes(validate_text(make_csv([row])), "error")


def test_option_name_on_later_row_differs_warns():
    rows = multi_variant(variant_row(**{"Option1 Name": "Colour", "Option1 Value": "Blue", "sku": "x"}))
    result = validate_text(make_csv(rows))
    assert result.ok and "option-name-conflict" in codes(result)


# ------------------------------------------------------------------ prices

@pytest.mark.parametrize("price", ["abc", "1,99", "$5", "nan", "inf"])
def test_price_not_numeric(price):
    result = validate_text(make_csv([product_row(**{"Variant Price": price, "Variant Compare At Price": ""})]))
    assert "price-invalid" in codes(result, "error")


def test_price_negative():
    result = validate_text(make_csv([product_row(**{"Variant Price": "-1", "Variant Compare At Price": ""})]))
    assert "price-negative" in codes(result, "error")


def test_price_zero_ok():
    assert validate_text(make_csv([product_row(**{"Variant Price": "0", "Variant Compare At Price": ""})])).ok


def test_price_missing_is_warning():
    result = validate_text(make_csv([product_row(**{"Variant Price": "", "Variant Compare At Price": ""})]))
    assert result.ok and "price-missing" in codes(result, "warning")


def test_compare_at_below_price():
    result = validate_text(make_csv([product_row(**{"Variant Price": "20", "Variant Compare At Price": "19.99"})]))
    assert "compare-at-below-price" in codes(result, "error")


def test_compare_at_equal_price_warns():
    result = validate_text(make_csv([product_row(**{"Variant Price": "20", "Variant Compare At Price": "20.00"})]))
    assert result.ok and "compare-at-equals-price" in codes(result, "warning")


@pytest.mark.parametrize("value", ["cheap", "-5"])
def test_compare_at_invalid(value):
    result = validate_text(make_csv([product_row(**{"Variant Compare At Price": value})]))
    assert "compare-at-invalid" in codes(result, "error")


def test_cost_per_item_invalid():
    text = make_csv([product_row(**{"Cost per item": "-2"})], header=HEADERS + ["Cost per item"])
    assert "cost-invalid" in codes(validate_text(text), "error")


# ------------------------------------------------------------------ inventory / fulfillment

@pytest.mark.parametrize("policy", ["Deny", "CONTINUE", "block", "yes"])
def test_inventory_policy_invalid(policy):
    result = validate_text(make_csv([product_row(**{"Variant Inventory Policy": policy})]))
    assert "inventory-policy-invalid" in codes(result, "error")


@pytest.mark.parametrize("policy", ["deny", "continue", ""])
def test_inventory_policy_valid(policy):
    assert validate_text(make_csv([product_row(**{"Variant Inventory Policy": policy})])).ok


@pytest.mark.parametrize("qty", ["1.5", "ten"])
def test_inventory_qty_invalid(qty):
    result = validate_text(make_csv([product_row(**{"Variant Inventory Qty": qty})]))
    assert "inventory-qty-invalid" in codes(result, "error")


def test_inventory_qty_negative_warns():
    result = validate_text(make_csv([product_row(**{"Variant Inventory Qty": "-3"})]))
    assert result.ok and "inventory-qty-negative" in codes(result)


def test_qty_without_tracker_warns():
    result = validate_text(make_csv([product_row(**{"Variant Inventory Tracker": ""})]))
    assert result.ok and "inventory-tracker" in codes(result)


def test_grams_invalid():
    result = validate_text(make_csv([product_row(**{"Variant Grams": "-1"})]))
    assert "grams-invalid" in codes(result, "error")


def test_weight_unit_invalid():
    text = make_csv([product_row(**{"Variant Weight Unit": "stone"})], header=HEADERS + ["Variant Weight Unit"])
    assert "weight-unit-invalid" in codes(validate_text(text), "error")


def test_unknown_fulfillment_service_warns():
    result = validate_text(make_csv([product_row(**{"Variant Fulfillment Service": "acme-3pl"})]))
    assert result.ok and "fulfillment-service" in codes(result)


def test_duplicate_sku_warns():
    result = validate_text(make_csv([product_row(), product_row(Handle="other")]))
    assert result.ok and "sku-duplicate" in codes(result)


# ------------------------------------------------------------------ status / booleans

@pytest.mark.parametrize("status", ["active", "draft", "archived", "Active", ""])
def test_status_valid(status):
    assert validate_text(make_csv([product_row(Status=status)])).ok


@pytest.mark.parametrize("status", ["live", "published", "yes"])
def test_status_invalid(status):
    assert "status-invalid" in codes(validate_text(make_csv([product_row(Status=status)])), "error")


@pytest.mark.parametrize("col", ["Published", "Variant Requires Shipping", "Variant Taxable"])
def test_boolean_columns(col):
    assert validate_text(make_csv([product_row(**{col: "false"})])).ok
    result = validate_text(make_csv([product_row(**{col: "yes"})]))
    assert any(i.code == "boolean-invalid" and i.column == col for i in result.errors)


# ------------------------------------------------------------------ images

@pytest.mark.parametrize("src", ["cdn.example.com/a.jpg", "ftp://example.com/a.jpg", "/images/a.jpg",
                                 "https://example.com/a b.jpg"])
def test_image_src_must_be_http(src):
    result = validate_text(make_csv([product_row(**{"Image Src": src})]))
    assert "image-url" in codes(result, "error")


def test_image_src_http_ok():
    assert validate_text(make_csv([product_row(**{"Image Src": "http://example.com/a.jpg"})])).ok


@pytest.mark.parametrize("pos", ["0", "-1", "first", "1.5"])
def test_image_position_invalid(pos):
    result = validate_text(make_csv([product_row(**{"Image Position": pos})]))
    assert "image-position" in codes(result, "error")


def test_duplicate_image_position_warns():
    rows = [product_row(), {"Handle": "led-lights", "Image Src": "https://cdn.example.com/b.jpg", "Image Position": "1"}]
    result = validate_text(make_csv(rows))
    assert result.ok and "image-position" in codes(result, "warning")


def test_alt_text_without_image_warns():
    result = validate_text(make_csv([product_row(**{"Image Src": "", "Image Position": ""})]))
    assert result.ok and "image-alt" in codes(result, "warning")


# ------------------------------------------------------------------ issue formatting

def test_issue_format_and_dict():
    [issue] = validate_text(make_csv([product_row(Status="live")])).errors
    assert issue.format("p.csv") == (
        "p.csv:2: error: [status-invalid] (Status) Status must be one of active, draft, archived (got 'live')"
    )
    assert issue.to_dict()["row"] == 2
