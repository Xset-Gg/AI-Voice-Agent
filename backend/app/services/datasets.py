"""Tabular datasets the voice agent can answer questions about.

Uploaded CSV/Excel files are normalised to CSV, profiled (column types, value lists, ranges) and queried
with a small structured query language (metric + column + group_by + filters). The LLM never writes code
or SQL: it fills in `QueryArgs`, and every column name, operator and formula is validated here. All the
arithmetic happens in pandas over every row, so answers are exact rather than estimated by the model.
"""

import io
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from app.core.errors import AppError

SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx"}
MAX_ROWS = 500_000
MAX_COLUMNS = 200
MAX_LISTED_VALUES = 30  # text columns with at most this many distinct values get them listed for the agent
DATE_PARTS = ("day", "week", "month", "quarter", "year", "weekday")
_ID_NAME = re.compile(r"(^|_)(id|code|sku|number|no)$", re.I)
_FORMULA_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|([-+*/()]))")


class DatasetError(AppError):
    def __init__(self, message: str):
        super().__init__(message, code="dataset_error", status_code=400)


# ---------------------------------------------------------------- loading & profiling

def _clean_name(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]+", "_", str(name).strip()).strip("_")
    return name or "column"


def parse_upload(filename: str, data: bytes) -> pd.DataFrame:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise DatasetError(f"Unsupported file type '{ext}'. Upload CSV or Excel (.xlsx).")
    try:
        if ext == ".xlsx":
            df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
        else:
            df = pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig")
    except Exception as e:
        raise DatasetError(f"Couldn't read the file: {e}") from e
    if df.empty:
        raise DatasetError("The file has no rows.")
    if len(df) > MAX_ROWS or len(df.columns) > MAX_COLUMNS:
        raise DatasetError(f"Datasets are limited to {MAX_ROWS:,} rows and {MAX_COLUMNS} columns.")

    names, seen = [], set()
    for c in df.columns:
        n = _clean_name(c)
        while n.lower() in seen:
            n += "_2"
        seen.add(n.lower())
        names.append(n)
    df.columns = names
    return df.dropna(how="all")


def _as_dates(s: pd.Series) -> pd.Series | None:
    if s.dtype != object:
        return None
    sample = s.dropna().astype(str)
    if sample.empty or not sample.str.contains(r"\d{1,4}[-/.]\d{1,2}").mean() > 0.9:
        return None
    parsed = pd.to_datetime(s, errors="coerce", format="mixed")
    return parsed if parsed.notna().mean() >= 0.95 else None


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce types the same way at upload and at query time."""
    df = df.copy()
    for col in df.columns:
        if _ID_NAME.search(col):
            df[col] = df[col].astype("string")
            continue
        dates = _as_dates(df[col])
        if dates is not None:
            df[col] = dates
        elif df[col].dtype == object:
            num = pd.to_numeric(df[col], errors="coerce")
            if num.notna().sum() and num.notna().mean() >= 0.98:
                df[col] = num
            else:
                df[col] = df[col].astype("string").str.strip()
    return df


def _num(v) -> float | int | None:
    if v is None or pd.isna(v):
        return None
    v = float(v)
    return int(v) if v.is_integer() else round(v, 2)


def profile(df: pd.DataFrame) -> list[dict]:
    cols = []
    for col in df.columns:
        s = df[col]
        info: dict[str, Any] = {"name": col, "missing": int(s.isna().sum())}
        if pd.api.types.is_datetime64_any_dtype(s):
            info |= {"type": "date", "min": s.min().date().isoformat(), "max": s.max().date().isoformat()}
        elif pd.api.types.is_numeric_dtype(s):
            info |= {"type": "number", "min": _num(s.min()), "max": _num(s.max()), "mean": _num(s.mean())}
        else:
            distinct = s.dropna().unique()
            info |= {"type": "text", "distinct": int(len(distinct))}
            if len(distinct) <= MAX_LISTED_VALUES:
                info["values"] = sorted(str(v) for v in distinct)
            else:
                info["examples"] = [str(v) for v in distinct[:5]]
        cols.append(info)
    return cols


def suggest_computed(columns: list[dict]) -> list[dict]:
    """Offer an estimated profit column when price, cost and quantity columns are present."""
    numeric = [c["name"] for c in columns if c["type"] == "number"]

    def find(*words):
        return next((c for c in numeric if any(w in c.lower() for w in words)), None)

    price, cost, qty = find("price"), find("cost"), find("quantity", "qty", "units")
    if price and cost and price != cost:
        out = [{"name": "Unit_Margin", "formula": f"{price} - {cost}", "description": f"{price} minus {cost} (per unit)"}]
        if qty:
            out.append({"name": "Estimated_Profit", "formula": f"({price} - {cost}) * {qty}",
                        "description": f"({price} - {cost}) x {qty}. An estimate from unit price and cost."})
        return out
    return []


def validate_formula(formula: str, columns: set[str]) -> str:
    """Arithmetic over existing numeric columns only: names, numbers, + - * / and parentheses."""
    pos, out = 0, []
    formula = formula.strip()
    if not formula or len(formula) > 300:
        raise DatasetError("Formula must be 1-300 characters")
    while pos < len(formula):
        m = _FORMULA_TOKEN.match(formula, pos)
        if not m or m.end() == pos:
            raise DatasetError(f"Formula has an invalid character near '{formula[pos:pos + 10]}'")
        number, name, op = m.groups()
        if name is not None:
            if name not in columns:
                raise DatasetError(f"Formula uses unknown numeric column '{name}'")
            out.append(f"`{name}`")
        else:
            out.append(number or op)
        pos = m.end()
    return " ".join(out)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# ---------------------------------------------------------------- querying

class Filter(BaseModel):
    column: str = Field(max_length=100)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "between"] = "eq"
    value: str | float | int | None = None
    values: list[str | float | int] | None = Field(default=None, max_length=50)


class QueryArgs(BaseModel):
    dataset: str | None = Field(default=None, max_length=200)
    metric: Literal["sum", "avg", "count", "min", "max", "median", "count_distinct", "rows"] = "sum"
    column: str | None = Field(default=None, max_length=100)
    group_by: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    sort: Literal["desc", "asc"] = "desc"
    limit: int = Field(default=10, ge=1, le=25)


def with_computed(df: pd.DataFrame, computed: list[dict]) -> pd.DataFrame:
    numeric = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
    for c in computed:
        df[c["name"]] = df.eval(validate_formula(c["formula"], numeric))
    return df


def _resolve(df: pd.DataFrame, name: str) -> str:
    if name in df.columns:
        return name
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    for c in df.columns:
        if re.sub(r"[^a-z0-9]", "", c.lower()) == key:
            return c
    raise DatasetError(f"Unknown column '{name}'. Columns: {', '.join(df.columns)}")


def _coerce(series: pd.Series, v):
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            return pd.Timestamp(str(v))
        except ValueError:
            raise DatasetError(f"'{v}' is not a date (use YYYY-MM-DD)")
    if pd.api.types.is_numeric_dtype(series):
        try:
            return float(v)
        except (TypeError, ValueError):
            raise DatasetError(f"'{v}' is not a number")
    return str(v)


def _date_end(series: pd.Series, v) -> Any:
    """Inclusive upper bound: a bare date means the whole day."""
    ts = _coerce(series, v)
    if pd.api.types.is_datetime64_any_dtype(series) and len(str(v).strip()) <= 10:
        return ts + timedelta(days=1) - timedelta(microseconds=1)
    return ts


def _apply_filter(df: pd.DataFrame, f: Filter) -> pd.DataFrame:
    col = _resolve(df, f.column)
    s = df[col]
    is_text = not (pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s))
    values = f.values if f.values is not None else ([f.value] if f.value is not None else [])
    if not values:
        raise DatasetError(f"Filter on '{col}' needs a value")

    if f.op in ("eq", "ne", "in", "not_in"):
        if is_text:
            wanted = {str(v).strip().lower() for v in values}
            mask = s.str.lower().isin(wanted)
        else:
            mask = s.isin([_coerce(s, v) for v in values])
        return df[mask if f.op in ("eq", "in") else ~mask]
    if f.op == "contains":
        if not is_text:
            raise DatasetError(f"'contains' only works on text columns; '{col}' is not text")
        return df[s.str.contains(re.escape(str(values[0])), case=False, na=False)]
    if f.op == "between":
        if len(values) != 2:
            raise DatasetError("'between' needs exactly two values: [from, to]")
        return df[(s >= _coerce(s, values[0])) & (s <= _date_end(s, values[1]))]
    if is_text:
        raise DatasetError(f"'{f.op}' needs a number or date column; '{col}' is text")
    bound = _date_end(s, values[0]) if f.op == "lte" else _coerce(s, values[0])
    return df[{"gt": s > bound, "gte": s >= bound, "lt": s < bound, "lte": s <= bound}[f.op]]


def _group_key(df: pd.DataFrame, spec: str) -> tuple[str, pd.Series]:
    name, _, part = spec.partition(":")
    col = _resolve(df, name.strip())
    s = df[col]
    part = part.strip().lower()
    if not pd.api.types.is_datetime64_any_dtype(s):
        if part:
            raise DatasetError(f"'{col}' is not a date column, so it can't be grouped by {part}")
        return col, s
    part = part or "month"
    if part not in DATE_PARTS:
        raise DatasetError(f"Date grouping must be one of {', '.join(DATE_PARTS)}")
    label = f"{col}:{part}"
    if part == "day":
        return label, s.dt.strftime("%Y-%m-%d")
    if part == "week":
        return label, s.dt.to_period("W").dt.start_time.dt.strftime("week of %Y-%m-%d")
    if part == "month":
        return label, s.dt.strftime("%Y-%m")
    if part == "quarter":
        return label, s.dt.year.astype(str) + "-Q" + s.dt.quarter.astype(str)
    if part == "year":
        return label, s.dt.year.astype(str)
    return label, s.dt.day_name()


def _aggregate(series: pd.Series, metric: str):
    if metric == "count":
        return len(series)
    if metric == "count_distinct":
        return series.nunique()
    return {"sum": series.sum, "avg": series.mean, "min": series.min, "max": series.max, "median": series.median}[metric]()


def _jsonable(v):
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date().isoformat() if v == v.normalize() else v.isoformat()
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)) or hasattr(v, "item"):
        return _num(v)
    return str(v)


def run_query(df: pd.DataFrame, args: QueryArgs) -> dict:
    total_rows = len(df)
    for f in args.filters:
        df = _apply_filter(df, f)
    matched = len(df)
    applied = [f.model_dump(exclude_none=True) for f in args.filters]

    if args.metric == "rows":
        sort_col = _resolve(df, args.column) if args.column else None
        if sort_col:
            df = df.sort_values(sort_col, ascending=args.sort == "asc")
        return {
            "ok": True, "metric": "rows", "sorted_by": sort_col, "rows_matched": matched, "rows_in_dataset": total_rows,
            "filters": applied,
            "rows": [{k: _jsonable(v) for k, v in r.items()} for r in df.head(args.limit).to_dict("records")],
        }

    if args.metric in ("count",):
        col = None
    else:
        if not args.column:
            raise DatasetError(f"metric '{args.metric}' needs a column")
        col = _resolve(df, args.column)
        if args.metric != "count_distinct" and not pd.api.types.is_numeric_dtype(df[col]):
            raise DatasetError(f"'{col}' isn't numeric, so it can't be used with '{args.metric}'")
    values = df[col] if col else df.index.to_series()
    result: dict[str, Any] = {
        "ok": True, "metric": args.metric, "column": col, "rows_matched": matched, "rows_in_dataset": total_rows,
        "filters": applied, "overall": _jsonable(_aggregate(values, args.metric)) if matched else None,
    }
    if not args.group_by or not matched:
        return result

    keys = [_group_key(df, g) for g in args.group_by]
    grouped = values.groupby([k for _, k in keys], dropna=True)
    agg = grouped.size() if args.metric == "count" else grouped.nunique() if args.metric == "count_distinct" else grouped.agg(args.metric.replace("avg", "mean"))
    is_time = any(":" in label for label, _ in keys) and len(keys) == 1
    agg = agg.sort_index() if is_time else agg.sort_values(ascending=args.sort == "asc")
    shares = args.metric in ("sum", "count") and result["overall"]
    groups = []
    for idx, v in agg.head(args.limit if not is_time else 60).items():
        idx = idx if isinstance(idx, tuple) else (idx,)
        g = {"group": {label: _jsonable(i) for (label, _), i in zip(keys, idx)}, "value": _jsonable(v)}
        if shares:
            g["share_pct"] = round(float(v) / float(result["overall"]) * 100, 1)
        groups.append(g)
    result |= {"group_by": [label for label, _ in keys], "groups_total": int(len(agg)), "groups": groups}
    if is_time:
        result["note"] = "Groups are in time order."
    return result


# ---------------------------------------------------------------- dataset cache & prompt

_cache: dict[tuple[uuid.UUID, datetime], pd.DataFrame] = {}


def frame_for(dataset_id: uuid.UUID, updated_at: datetime, csv_bytes: bytes, computed: list[dict]) -> pd.DataFrame:
    key = (dataset_id, updated_at)
    if key not in _cache:
        for k in [k for k in _cache if k[0] == dataset_id]:
            _cache.pop(k)
        if len(_cache) > 32:
            _cache.pop(next(iter(_cache)))
        df = normalise(pd.read_csv(io.BytesIO(csv_bytes)))
        _cache[key] = with_computed(df, computed or [])
    return _cache[key]


def prompt_section(datasets: list) -> str:
    if not datasets:
        return "## Data\nNo datasets have been uploaded yet. If asked about data, say none is available."
    lines = [
        "## Data you can analyse (critical rules)",
        "- For ANY question about figures in these datasets (totals, averages, counts, rankings, trends, comparisons), "
        "call query_dataset. Never estimate, invent or do your own arithmetic across rows; only report numbers the tool returned.",
        "- Use one query per figure you need. For comparisons (e.g. two regions or two quarters) use group_by rather than separate guesses.",
        "- Speak numbers naturally and round sensibly (\"about one point two million\", \"forty-two percent\"). "
        "Don't read out tables: give the headline, then the top two or three items, and offer more detail.",
        "- Use exact values from the column's listed values in filters. Dates are YYYY-MM-DD.",
        "- Relative dates like \"last month\" refer to the latest period in the data unless the caller says otherwise; say which period you used.",
        "- If a question can't be answered from the columns available, say so plainly.",
    ]
    for d in datasets:
        lines.append(f"\n### Dataset \"{d.name}\" ({d.row_count:,} rows)")
        if d.description:
            lines.append(d.description)
        if d.notes:
            lines.append(f"Notes from the business: {d.notes}")
        for c in d.columns:
            if c["type"] == "number":
                desc = f"number, {c['min']} to {c['max']}, average {c['mean']}"
            elif c["type"] == "date":
                desc = f"date, {c['min']} to {c['max']} (group by {c['name']}:month / :quarter / :year / :week / :day / :weekday)"
            elif "values" in c:
                desc = "text, one of: " + ", ".join(c["values"])
            else:
                desc = f"text, {c['distinct']} distinct values, e.g. " + ", ".join(c.get("examples", []))
            lines.append(f"- {c['name']}: {desc}")
        for c in d.computed or []:
            lines.append(f"- {c['name']}: number, computed as {c['description']}")
    return "\n".join(lines)
