"""Command line interface: ``shopcsv validate`` and ``shopcsv build``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .build import BuildError, build_csv, load_spec
from .validate import validate_file, validate_text


def _cmd_validate(args: argparse.Namespace) -> int:
    exit_code = 0
    reports = []
    for path in args.files:
        try:
            result = validate_file(path)
        except OSError as exc:
            print(f"shopcsv: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        except UnicodeDecodeError as exc:
            print(f"shopcsv: {path} is not valid UTF-8 ({exc}); re-save it as UTF-8", file=sys.stderr)
            return 2
        issues = result.errors if args.no_warnings else result.issues
        failed = bool(result.errors) or (args.strict and bool(result.warnings))
        if failed:
            exit_code = 1
        if args.format == "json":
            reports.append({
                "file": path,
                "ok": not failed,
                "products": result.products,
                "variants": result.variants,
                "rows": result.rows,
                "errors": len(result.errors),
                "warnings": len(result.warnings),
                "issues": [i.to_dict() for i in issues],
            })
            continue
        for issue in sorted(issues, key=lambda i: (i.row or 0, i.level != "error")):
            print(issue.format(path))
        status = "FAIL" if failed else "OK"
        print(f"{path}: {status} - {result.products} products, {result.variants} variants, "
              f"{len(result.errors)} errors, {len(result.warnings)} warnings")
    if args.format == "json":
        json.dump(reports if len(reports) != 1 else reports[0], sys.stdout, indent=2)
        sys.stdout.write("\n")
    return exit_code


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        text = build_csv(load_spec(args.input))
    except OSError as exc:
        print(f"shopcsv: cannot read {args.input}: {exc}", file=sys.stderr)
        return 2
    except BuildError as exc:
        print(f"shopcsv: {exc}", file=sys.stderr)
        return 1

    # Safety net: never hand the user a CSV that our own validator rejects.
    result = validate_text(text)
    if result.errors:
        for issue in result.errors:
            print(issue.format("<built csv>"), file=sys.stderr)
        return 1

    if args.output and args.output != "-":
        with open(args.output, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"wrote {args.output}: {result.products} products, {result.variants} variants, "
              f"{result.rows} rows", file=sys.stderr)
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy codepage
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shopcsv", description="Validate and generate Shopify product import CSVs.")
    parser.add_argument("--version", action="version", version=f"shopcsv {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    v = sub.add_parser("validate", help="check a Shopify product CSV for import errors")
    v.add_argument("files", nargs="+", metavar="CSV", help="product CSV file(s) to check")
    v.add_argument("--strict", action="store_true", help="treat warnings as errors (exit 1)")
    v.add_argument("--no-warnings", action="store_true", help="only print errors")
    v.add_argument("--format", choices=["text", "json"], default="text", help="output format")
    v.set_defaults(func=_cmd_validate)

    b = sub.add_parser("build", help="expand a YAML/JSON product spec into a Shopify CSV")
    b.add_argument("input", metavar="SPEC", help="products.yaml / products.yml / products.json")
    b.add_argument("-o", "--output", metavar="CSV", help="output file (default: stdout)")
    b.set_defaults(func=_cmd_build)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
