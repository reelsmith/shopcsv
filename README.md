# shopcsv

Validate and generate Shopify product import CSVs from the command line.

Shopify's product importer is strict. A handle with a capital letter, a
`Deny` where it wants `deny`, a compare-at price below the price, or two
variants with the same options can fail the import, or import products
that are quietly wrong. Hand-writing one row per variant for a product with
3 colors x 4 sizes is also slow and easy to get wrong.

`shopcsv` does two things:

- **`shopcsv validate`** checks an existing product CSV against the importer's
  rules before you upload it, and reports every problem with its row number.
- **`shopcsv build`** turns a short YAML or JSON product description into a
  correct Shopify CSV, with one row per variant, generated handles and SKUs,
  and image rows.

It has no required dependencies. PyYAML is only needed to read YAML specs.

## Install

```sh
pip install git+https://github.com/reelsmith/shopcsv.git
# with YAML support:
pip install "shopcsv[yaml] @ git+https://github.com/reelsmith/shopcsv.git"
```

Requires Python 3.9 or newer. You can also run it as `python -m shopcsv`.

## Usage

### Validate a CSV

```console
$ shopcsv validate products.csv
products.csv:2: error: [handle-format] (Handle) handle 'LED Lights' contains spaces; use hyphens
products.csv:2: error: [compare-at-below-price] (Variant Compare At Price) Variant Compare At Price (19.99) must be >= Variant Price (24.99)
products.csv:2: error: [inventory-policy-invalid] (Variant Inventory Policy) Variant Inventory Policy must be 'deny' or 'continue' (got 'Deny') (must be lowercase)
products.csv:2: error: [image-url] (Image Src) Image Src must be an http(s) URL (got 'cdn.example.com/a.jpg')
products.csv:3: error: [duplicate-variant] duplicate option combination 'Red' for handle 'LED Lights' (first seen on row 2)
products.csv:3: warning: [sku-duplicate] (Variant SKU) Variant SKU 'LED-R' is also used on row 2
products.csv:4: error: [price-negative] (Variant Price) Variant Price cannot be negative (got '-5')
products.csv:4: warning: [sku-duplicate] (Variant SKU) Variant SKU 'LED-R' is also used on row 2
products.csv: FAIL - 1 products, 3 variants, 6 errors, 2 warnings
$ echo $?
1
```

Row numbers match what you see in a spreadsheet: the header is row 1. They
stay correct when a `Body (HTML)` cell spans several lines.

| Option | Effect |
| --- | --- |
| `--strict` | Warnings also fail (exit 1). Useful in CI. |
| `--no-warnings` | Print errors only. |
| `--format json` | Print a machine-readable report. |

Exit codes: `0` valid (warnings allowed), `1` errors found, `2` file missing
or not UTF-8. You can pass several files at once.

### Build a CSV from YAML or JSON

```console
$ shopcsv build examples/products.yaml -o examples/products.csv
wrote examples/products.csv: 2 products, 7 variants, 9 rows
```

Without `-o`, the CSV goes to stdout. Before writing, `build` runs the
validator on its own output and refuses to write a CSV with errors.

The input is [`examples/products.yaml`](examples/products.yaml), and the output
is [`examples/products.csv`](examples/products.csv). Part of the input:

```yaml
products:
  - title: Christmas LED String Lights
    price: 24.99
    compare_at: 39.99
    sku_prefix: XMAS-LED
    options:
      Color: [Warm White, Cool White, Multicolor]
      Length: [10m, 20m]
    overrides:
      - match: {Length: 20m}
        price: 34.99
        compare_at: 54.99
```

That expands to 6 variants (3 colors x 2 lengths), with handle
`christmas-led-string-lights` and SKUs such as `XMAS-LED-WARMWHITE-10M`, and
the 20m variants priced at 34.99.

## Spec format reference

A spec file can be:

- one product (a mapping),
- a list of products, or
- a mapping with `products:` (a list) and optional `defaults:`. Every key in
  `defaults` applies to each product unless that product sets it itself.

Files ending in `.json` are read with the standard library. Other files are
read as YAML, which needs PyYAML. Without PyYAML, a YAML file that is also
valid JSON still works.

### Product keys

| Key | Required | Default | Notes |
| --- | --- | --- | --- |
| `title` | yes | | Product title. |
| `price` | yes | | Variant price. Written with two decimals. |
| `handle` | | slug of `title` | Lowercase, hyphenated, ASCII. Handles generated from duplicate titles get `-2`, `-3`, and so on. |
| `description` | | | Plain text: blank lines start new paragraphs (`<p>`), HTML is escaped. If it already contains HTML tags, it is used as is. |
| `body_html` | | | Raw HTML. Takes priority over `description`. |
| `compare_at` | | | Must be >= `price`. |
| `vendor`, `type` | | | |
| `product_category` (or `category`) | | | Shopify taxonomy path or ID. |
| `tags` | | | A list, or a comma-separated string. Duplicates are removed. |
| `options` | | none | Up to 3 options: `{Color: [Red, Blue], Size: [S, M]}`, or a list of `{name: Color, values: [...]}`. Every combination becomes a variant. With no options, the product gets Shopify's `Title` / `Default Title` variant. |
| `overrides` | | | A list of `{match: {Option: value, ...}, <variant keys>}`. Applies to every variant that matches all listed options. Later overrides win. |
| `sku_prefix` (or `sku`) | | the handle, uppercased | SKU = prefix + each option value, uppercased with spaces and punctuation removed, joined by `-`. Colliding SKUs get `-2`, `-3`, and so on. |
| `images` | | | A list of URLs or `{src, alt}`. The first image goes on the first variant row and extra images get their own rows. Alt text defaults to the title. |
| `grams` | | `0` | Whole number. |
| `inventory_qty` | | `0` | Whole number. Inventory is tracked by `shopify`. |
| `inventory_policy` | | `deny` | `deny` or `continue` (whether to keep selling when out of stock). |
| `requires_shipping`, `taxable` | | `true` | |
| `published` | | `true` | |
| `status` | | `active` | `active`, `draft` or `archived`. |
| `fulfillment_service` | | `manual` | |

### Variant keys usable in `overrides`

`price`, `compare_at`, `grams`, `inventory_qty`, `inventory_policy`,
`requires_shipping`, `taxable`, `sku`. An explicit `sku` must be unique.

`build` rejects unknown keys, bad values, more than 3 options, duplicate
option values and more than 2048 variants, and names the product and variant
at fault.

### Output columns

`Handle, Title, Body (HTML), Vendor, Product Category, Type, Tags, Published,
Option1 Name, Option1 Value, Option2 Name, Option2 Value, Option3 Name,
Option3 Value, Variant SKU, Variant Grams, Variant Inventory Tracker, Variant
Inventory Qty, Variant Inventory Policy, Variant Fulfillment Service, Variant
Price, Variant Compare At Price, Variant Requires Shipping, Variant Taxable,
Image Src, Image Position, Image Alt Text, Status`

The output is UTF-8 without a BOM. As in Shopify's own exports, product-level
fields (title, body, vendor, tags, option names, status and so on) appear only
on each product's first row.

## Validation rules

**Errors** make the command exit with status 1. **Warnings** are printed but
do not affect the exit code unless you pass `--strict`.

| Code | Level | Rule |
| --- | --- | --- |
| `empty-file`, `no-rows`, `csv-malformed` | error | The file must have a header row and at least one product row, and must parse as CSV. |
| `missing-column` | error | The `Handle` and `Title` columns must exist. |
| `duplicate-column` | error | A column name appears twice. |
| `unknown-column` | warning | A column that is not a Shopify column. Metafield, Google Shopping and market columns are recognized. |
| `row-length` | error / warning | A row has more cells than the header (error) or fewer (warning). |
| `handle-missing` | error | Every row needs a Handle. |
| `handle-format` | error | Handles must be lowercase `a-z`, `0-9` and single hyphens, with no spaces, at most 255 characters. Underscores are a warning. |
| `handle-not-contiguous` | warning | A product's rows are split up by other products. |
| `title-missing` | error | A product's first row must have a Title. |
| `title-conflict` | warning | A later row has a different Title, which Shopify ignores. |
| `option-name-missing` | error | An `OptionN Value` is set but the product has no `OptionN Name`, or a product has several variants but no `Option1 Name`. |
| `option-value-missing` | error | In a product with several variants, a variant has no value for one of the product's options. |
| `option-order` | error | Option2 is used without Option1, or Option3 without Option2. |
| `option-name-duplicate` | error | Two options of a product have the same name. |
| `option-name-conflict` | warning | A later row repeats an option name with a different value. |
| `duplicate-variant` | error | Two variants of the same handle have the same option values (case-insensitive). |
| `too-many-variants` | error | More than 2048 variants in one product. |
| `price-invalid`, `price-negative` | error | `Variant Price` must be a plain non-negative number (no `$`, no thousands separator). |
| `price-missing` | warning | A variant has no price, so it would import as 0.00. |
| `compare-at-invalid` | error | `Variant Compare At Price` must be a non-negative number. |
| `compare-at-below-price` | error | Compare-at price must be >= price. |
| `compare-at-equals-price` | warning | Compare-at price equals the price, so no sale is shown. |
| `cost-invalid` | error | `Cost per item` must be a non-negative number. |
| `grams-invalid` | error | `Variant Grams` must be a non-negative number. |
| `weight-unit-invalid` | error | `Variant Weight Unit` must be `g`, `kg`, `lb` or `oz`. |
| `inventory-qty-invalid` | error | `Variant Inventory Qty` must be a whole number. |
| `inventory-qty-negative` | warning | The inventory quantity is negative. |
| `inventory-policy-invalid` | error | `Variant Inventory Policy` must be exactly `deny` or `continue`. |
| `inventory-tracker` | warning | The tracker is not `shopify`, or a quantity is set with no tracker. |
| `fulfillment-service` | warning | The value is not `manual`. It must match the handle of an installed fulfillment app. |
| `sku-duplicate` | warning | The same SKU appears on more than one variant. |
| `status-invalid` | error | `Status` must be `active`, `draft` or `archived`. |
| `boolean-invalid` | error | `Published`, `Variant Requires Shipping`, `Variant Taxable` and `Gift Card` must be `TRUE` or `FALSE`. |
| `image-url` | error | `Image Src` and `Variant Image` must be `http(s)://` URLs with no spaces. |
| `image-position` | error / warning | Image Position must be a positive whole number (error). A position repeated within a product, or a position with no image, is a warning. |
| `image-alt` | warning | Alt text has no image, or is longer than 512 characters. |

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/pytest
```

After you change `examples/products.yaml`, regenerate the example CSV. A test
checks that the two stay in sync:

```sh
shopcsv build examples/products.yaml -o examples/products.csv
```

## License

MIT. See [LICENSE](LICENSE).
