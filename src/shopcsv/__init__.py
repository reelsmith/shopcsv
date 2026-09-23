"""shopcsv - validate and generate Shopify product import CSVs."""

from .validate import Issue, Result, validate_file, validate_records, validate_text

__version__ = "0.1.0"

__all__ = ["Issue", "Result", "validate_file", "validate_records", "validate_text", "__version__"]
