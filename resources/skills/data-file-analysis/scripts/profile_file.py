#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _json_default(value: Any) -> str:
    return str(value)


def _safe_import(module: str):
    try:
        return __import__(module)
    except Exception as e:
        return {"error": f"failed to import {module}: {e}"}


def _read_text(path: Path, limit: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "kind": "text",
        "line_count": len(lines),
        "char_count": len(text),
        "preview": "\n".join(lines[:limit]),
    }


def _read_markdown(path: Path, limit: int) -> dict[str, Any]:
    result = _read_text(path, limit)
    headings = [
        line.strip()
        for line in result["preview"].splitlines()
        if line.lstrip().startswith("#")
    ]
    result["kind"] = "markdown"
    result["preview_heading_count"] = len(headings)
    result["preview_headings"] = headings
    markdown_it = _safe_import("markdown_it")
    if isinstance(markdown_it, dict):
        result["markdown_parser"] = markdown_it
    else:
        result["markdown_parser"] = {"available": True}
    return result


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "kind": "json",
        "top_level_type": type(data).__name__,
    }
    if isinstance(data, list):
        result["item_count"] = len(data)
        result["sample"] = data[:limit]
    elif isinstance(data, dict):
        result["keys"] = list(data.keys())
        result["sample"] = dict(list(data.items())[:limit])
    else:
        result["value"] = data
    return result


def _read_csv_without_pandas(path: Path, limit: int) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = []
        count = 0
        for row in reader:
            count += 1
            if len(rows) < limit:
                rows.append(row)
    return {
        "kind": "csv",
        "parser": "csv",
        "columns": reader.fieldnames or [],
        "row_count": count,
        "preview": rows,
    }


def _read_csv(path: Path, limit: int) -> dict[str, Any]:
    pandas = _safe_import("pandas")
    if isinstance(pandas, dict):
        result = _read_csv_without_pandas(path, limit)
        result["pandas"] = pandas
        return result

    df = pandas.read_csv(path)
    numeric = df.select_dtypes(include="number")
    return {
        "kind": "csv",
        "parser": "pandas",
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {name: str(dtype) for name, dtype in df.dtypes.items()},
        "missing": df.isna().sum().to_dict(),
        "numeric_summary": numeric.describe().to_dict() if not numeric.empty else {},
        "preview": df.head(limit).to_dict(orient="records"),
    }


def _read_excel(path: Path, limit: int) -> dict[str, Any]:
    pandas = _safe_import("pandas")
    if isinstance(pandas, dict):
        return {"kind": "excel", "error": pandas["error"]}

    sheets = pandas.read_excel(path, sheet_name=None)
    sheet_profiles = {}
    for name, df in sheets.items():
        sheet_profiles[name] = {
            "shape": list(df.shape),
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing": df.isna().sum().to_dict(),
            "preview": df.head(limit).to_dict(orient="records"),
        }
    return {
        "kind": "excel",
        "sheets": list(sheets.keys()),
        "sheet_profiles": sheet_profiles,
    }


def _read_pdf(path: Path, limit: int) -> dict[str, Any]:
    fitz = _safe_import("fitz")
    if isinstance(fitz, dict):
        return {"kind": "pdf", "error": fitz["error"]}

    doc = fitz.open(path)
    pages = []
    for page_index in range(min(len(doc), limit)):
        text = doc[page_index].get_text("text")
        pages.append(
            {
                "page": page_index + 1,
                "char_count": len(text),
                "preview": text[:1000],
            }
        )
    return {
        "kind": "pdf",
        "page_count": len(doc),
        "metadata": doc.metadata,
        "pages": pages,
    }


def profile_file(path: Path, limit: int) -> dict[str, Any]:
    suffix = path.suffix.lower()
    base = {
        "path": str(path),
        "file_name": path.name,
        "size_bytes": path.stat().st_size,
    }

    try:
        if suffix == ".csv":
            detail = _read_csv(path, limit)
        elif suffix in (".xlsx", ".xls"):
            detail = _read_excel(path, limit)
        elif suffix == ".json":
            detail = _read_json(path, limit)
        elif suffix == ".pdf":
            detail = _read_pdf(path, limit)
        elif suffix in (".md", ".markdown"):
            detail = _read_markdown(path, limit)
        else:
            detail = _read_text(path, limit)
    except Exception as e:
        detail = {
            "kind": suffix.removeprefix(".") or "unknown",
            "error": str(e),
        }

    return {**base, **detail}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")

    result = profile_file(path, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
