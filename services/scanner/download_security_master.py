#!/usr/bin/env python3
"""
ICICI Direct Breeze Security Master downloader + stock_lot.csv updater.

Lot-size logic:
    Series     == OPTION
    OptionType == PE
    STOCK      = ShortName
    LOT        = LotSize

The existing stock_lot.csv is NOT merged. If valid mappings are found,
the existing file is backed up and a completely fresh STOCK,LOT file is
created.
"""

import argparse
import csv
import io
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

SECURITY_MASTER_URL = (
    "https://directlink.icicidirect.com/"
    "NewSecurityMaster/SecurityMaster.zip"
)


def normalize_header(value):
    return (
        str(value)
        .strip()
        .strip('"')
        .replace("\ufeff", "")
        .replace(" ", "")
        .replace("_", "")
        .lower()
    )


def detect_delimiter(sample):
    candidates = [",", "|", "\t", ";"]
    return max(candidates, key=sample.count)


def download_file(url, destination):
    print("=" * 80)
    print("ICICI DIRECT BREEZE SECURITY MASTER")
    print("=" * 80)
    print()
    print(f"URL        : {url}")
    print(f"Destination: {destination.resolve()}")
    print()

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        },
    )

    with urlopen(request, timeout=60) as response:
        data = response.read()

    if not data:
        raise RuntimeError("Download returned an empty file.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    print(f"Downloaded : {len(data):,} bytes")
    print()


def extract_zip(zip_path, output_dir):
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError(
            f"Downloaded file is not a valid ZIP archive: {zip_path}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        zf.extractall(output_dir)

    return [
        output_dir / name
        for name in names
        if name and not name.endswith("/")
    ]


def read_table(path, max_rows=None):
    """Read a delimited Security Master table."""
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error = None

    for encoding in encodings:
        try:
            with open(
                path,
                "r",
                encoding=encoding,
                errors="replace",
                newline="",
            ) as f:
                first_line = f.readline()

                if not first_line:
                    raise RuntimeError("File is empty.")

                delimiter = detect_delimiter(first_line)

                f.seek(0)
                reader = csv.DictReader(f, delimiter=delimiter)

                fields = reader.fieldnames or []
                rows = []

                for row in reader:
                    rows.append(row)
                    if max_rows is not None and len(rows) >= max_rows:
                        break

                return fields, rows

        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Unable to read {path}: {last_error}")


def inspect_text_file(path):
    if path.suffix.lower() not in {".csv", ".txt", ".tsv", ".dat"}:
        return

    try:
        fields, rows = read_table(path, max_rows=1)
    except Exception as exc:
        print(f"  Could not parse: {exc}")
        return

    print(f"  Columns ({len(fields)}):")
    print("   " + " | ".join(str(x) for x in fields))

    lot_candidates = [
        h for h in fields
        if any(
            token in normalize_header(h)
            for token in (
                "lot",
                "lotsize",
                "lotsize",
                "quantity",
            )
        )
    ]

    if lot_candidates:
        print("  Possible lot-size columns:")
        for col in lot_candidates:
            print(f"    - {col}")

    if rows:
        first = rows[0]
        print("  First data row:")
        print(
            "   "
            + " | ".join(str(first.get(h, "")) for h in fields[:20])
        )


def find_security_master_table(extract_dir):
    """
    Select the NSE F&O master.

    FONSEScripMaster.txt is explicitly preferred. Other files are considered
    only if they contain the required F&O fields AND actual OPTION/PE data.
    """
    files = [
        p for p in Path(extract_dir).rglob("*")
        if p.is_file()
        and p.suffix.lower() in {".txt", ".csv", ".tsv", ".dat"}
    ]

    if not files:
        raise RuntimeError("No Security Master table files were found.")

    # Strong preference for the NSE F&O master.
    fno_files = [
        p for p in files
        if "fonsescripmaster" in p.name.lower()
    ]

    for path in sorted(fno_files):
        try:
            fields, _ = read_table(path, max_rows=1)
            normalized = {normalize_header(x) for x in fields}

            required = {
                "series",
                "optiontype",
                "shortname",
                "lotsize",
            }

            if required.issubset(normalized):
                return path
        except Exception:
            pass

    # Safe fallback: only select a file with actual OPTION/PE records.
    required = {"series", "optiontype", "shortname", "lotsize"}

    for path in sorted(files):
        try:
            fields, rows = read_table(path, max_rows=500)
            field_map = {
                normalize_header(x): x for x in fields
            }

            if not required.issubset(field_map):
                continue

            series_col = field_map["series"]
            option_col = field_map["optiontype"]

            for row in rows:
                if (
                    str(row.get(series_col, "")).strip().upper() == "OPTION"
                    and
                    str(row.get(option_col, "")).strip().upper() == "PE"
                ):
                    return path

        except Exception:
            pass

    raise RuntimeError(
        "Could not find an NSE F&O Security Master containing "
        "Series=OPTION and OptionType=PE."
    )


def update_stock_lot_csv(security_master_path, output_dir):
    """
    Create a fresh stock_lot.csv using ONLY OPTION/PE records.

    Existing stock_lot.csv is not used as an input.
    """
    output_dir = Path(output_dir)
    stock_lot_path = Path(__file__).resolve().parent / "stock_lot.csv"

    print()
    print("=" * 80)
    print("UPDATING STOCK LOT CSV")
    print("=" * 80)
    print()
    print(f"Security Master: {security_master_path}")
    print(f"Stock lot CSV  : {stock_lot_path}")
    print()
    print("Filter logic   : Series=OPTION AND OptionType=PE")
    print("Stock key      : ShortName")
    print("Lot size source: LotSize")

    fields, _ = read_table(security_master_path, max_rows=1)
    field_map = {
        normalize_header(x): x for x in fields
    }

    required = {
        "series",
        "optiontype",
        "shortname",
        "lotsize",
    }
    missing = required - set(field_map)

    if missing:
        raise RuntimeError(
            "Missing required Security Master columns: "
            + ", ".join(sorted(missing))
        )

    series_col = field_map["series"]
    option_col = field_map["optiontype"]
    stock_col = field_map["shortname"]
    lot_col = field_map["lotsize"]

    lot_map = {}
    option_count = 0
    pe_count = 0
    invalid_lot_count = 0

    # Read the complete F&O master, not just the preview.
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    processed = False
    last_error = None

    for encoding in encodings:
        try:
            with open(
                security_master_path,
                "r",
                encoding=encoding,
                errors="replace",
                newline="",
            ) as f:
                first_line = f.readline()
                if not first_line:
                    raise RuntimeError("Security Master is empty.")

                delimiter = detect_delimiter(first_line)
                f.seek(0)

                reader = csv.DictReader(f, delimiter=delimiter)

                for row in reader:
                    series = (
                        str(row.get(series_col, ""))
                        .strip()
                        .upper()
                    )

                    if series != "OPTION":
                        continue

                    option_count += 1

                    option_type = (
                        str(row.get(option_col, ""))
                        .strip()
                        .upper()
                    )

                    if option_type != "PE":
                        continue

                    pe_count += 1

                    stock = (
                        str(row.get(stock_col, ""))
                        .strip()
                        .upper()
                    )
                    lot_raw = (
                        str(row.get(lot_col, ""))
                        .strip()
                    )

                    if not stock or not lot_raw:
                        invalid_lot_count += 1
                        continue

                    try:
                        lot = float(lot_raw)
                    except ValueError:
                        invalid_lot_count += 1
                        continue

                    if lot <= 0:
                        invalid_lot_count += 1
                        continue

                    if lot.is_integer():
                        lot = int(lot)

                    # Same stock appears at multiple strikes/expiries.
                    # LotSize should be identical; one valid value is enough.
                    if stock not in lot_map:
                        lot_map[stock] = lot

                processed = True
                break

        except Exception as exc:
            last_error = exc

    if not processed:
        raise RuntimeError(
            f"Unable to read F&O Security Master: {last_error}"
        )

    print(f"Rows with Series=OPTION : {option_count}")
    print(f"Rows with OptionType=PE : {pe_count}")
    print(f"Invalid/missing lot rows : {invalid_lot_count}")
    print(f"Unique PE stock lots     : {len(lot_map)}")

    # Never destroy a working CSV if the source did not produce valid data.
    if not lot_map:
        raise RuntimeError(
            "No stock lot sizes were found using "
            "Series=OPTION and OptionType=PE. "
            "stock_lot.csv was NOT changed."
        )

    # Existing file is ONLY a backup; its values are never merged.
    if stock_lot_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = stock_lot_path.with_name(
            f"stock_lot_{stamp}.csv.bak"
        )
        shutil.copy2(stock_lot_path, backup_path)
        print(f"Existing CSV backed up to: {backup_path}")

    # Atomic replacement.
    tmp_path = stock_lot_path.with_name("stock_lot.csv.tmp")

    with open(
        tmp_path,
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["STOCK", "LOT"])

        for stock in sorted(lot_map):
            writer.writerow([stock, lot_map[stock]])

    tmp_path.replace(stock_lot_path)

    print(f"Created fresh stock_lot.csv entries: {len(lot_map)}")
    print("Header: STOCK,LOT")
    print("No existing lot-size values were merged.")
    print("Updated successfully.")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Download ICICI Direct Security Master and create "
            "stock_lot.csv from OPTION/PE records."
        )
    )
    parser.add_argument(
        "--output-dir",
        default="security_master",
        help="Directory for ZIP, extracted Security Master and stock_lot.csv",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    zip_path = output_dir / "SecurityMaster.zip"

    try:
        download_file(SECURITY_MASTER_URL, zip_path)
        extracted = extract_zip(zip_path, output_dir)

        print("=" * 80)
        print("EXTRACTION COMPLETE")
        print("=" * 80)
        print(f"Folder: {output_dir}")
        print()

        if not extracted:
            raise RuntimeError("No files were found inside the ZIP.")

        print("Files:")
        for path in extracted:
            print(f"  - {path.relative_to(output_dir)}")

        print()
        print("=" * 80)
        print("SECURITY MASTER STRUCTURE")
        print("=" * 80)

        for path in extracted:
            print()
            print(f"[{path.relative_to(output_dir)}]")
            inspect_text_file(path)

        security_master_path = find_security_master_table(output_dir)

        print()
        print(f"Selected Security Master table: {security_master_path.name}")

        # This is intentionally called BEFORE DONE.
        update_stock_lot_csv(security_master_path, output_dir)

        print()
        print("=" * 80)
        print("DONE")
        print("=" * 80)
        print(f"ZIP retained at: {zip_path}")
        print(f"Extracted to   : {output_dir}")

    except Exception as exc:
        print()
        print("=" * 80)
        print("ERROR")
        print("=" * 80)
        print(str(exc))
        raise


if __name__ == "__main__":
    main()
