import json
import subprocess
import sys

import pytest

from shopcsv.cli import main

from conftest import make_csv, product_row


@pytest.fixture
def good_csv(tmp_path):
    path = tmp_path / "good.csv"
    path.write_text(make_csv([product_row()]), encoding="utf-8")
    return str(path)


@pytest.fixture
def bad_csv(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(make_csv([product_row(Handle="Bad Handle", **{"Variant Price": "-2"})]), encoding="utf-8")
    return str(path)


@pytest.fixture
def warn_csv(tmp_path):
    path = tmp_path / "warn.csv"
    path.write_text(make_csv([product_row(**{"Variant Inventory Qty": "-1"})]), encoding="utf-8")
    return str(path)


def test_validate_ok(good_csv, capsys):
    assert main(["validate", good_csv]) == 0
    assert "OK - 1 products, 1 variants, 0 errors, 0 warnings" in capsys.readouterr().out


def test_validate_errors_exit_1_with_row_numbers(bad_csv, capsys):
    assert main(["validate", bad_csv]) == 1
    out = capsys.readouterr().out
    assert f"{bad_csv}:2: error: [handle-format]" in out
    assert "[price-negative]" in out
    assert "FAIL" in out


def test_warnings_do_not_fail(warn_csv, capsys):
    assert main(["validate", warn_csv]) == 0
    assert "warning: [inventory-qty-negative]" in capsys.readouterr().out


def test_strict_fails_on_warnings(warn_csv):
    assert main(["validate", "--strict", warn_csv]) == 1


def test_no_warnings_hides_warnings(warn_csv, capsys):
    main(["validate", "--no-warnings", warn_csv])
    assert "warning:" not in capsys.readouterr().out


def test_json_output(bad_csv, capsys):
    assert main(["validate", "--format", "json", bad_csv]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert {i["code"] for i in report["issues"]} >= {"handle-format", "price-negative"}


def test_multiple_files_any_failure_fails(good_csv, bad_csv):
    assert main(["validate", good_csv, bad_csv]) == 1


def test_missing_file_exit_2(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.csv")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_non_utf8_file_exit_2(tmp_path, capsys):
    path = tmp_path / "latin1.csv"
    path.write_bytes(b"Handle,Title\ncafe,Caf\xe9\n")
    assert main(["validate", str(path)]) == 2
    assert "UTF-8" in capsys.readouterr().err


def test_build_writes_valid_csv(tmp_path, capsys):
    spec = tmp_path / "p.json"
    spec.write_text(json.dumps({"title": "Lights", "price": 5, "options": {"Color": ["Red", "Blue"]}}), encoding="utf-8")
    out = tmp_path / "out.csv"
    assert main(["build", str(spec), "-o", str(out)]) == 0
    assert "1 products, 2 variants" in capsys.readouterr().err
    assert main(["validate", str(out)]) == 0


def test_build_to_stdout(tmp_path, capsys):
    spec = tmp_path / "p.json"
    spec.write_text(json.dumps({"title": "Lights", "price": 5}), encoding="utf-8")
    assert main(["build", str(spec)]) == 0
    assert capsys.readouterr().out.startswith("Handle,Title,Body (HTML)")


def test_build_spec_error_exit_1(tmp_path, capsys):
    spec = tmp_path / "p.json"
    spec.write_text(json.dumps({"title": "Lights"}), encoding="utf-8")
    assert main(["build", str(spec)]) == 1
    assert "price is required" in capsys.readouterr().err


def test_build_missing_file_exit_2(tmp_path):
    assert main(["build", str(tmp_path / "missing.yaml")]) == 2


def test_python_dash_m(good_csv):
    proc = subprocess.run([sys.executable, "-m", "shopcsv", "validate", good_csv], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "OK" in proc.stdout
