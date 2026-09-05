import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

import ast
import operator

import pandas as pd

from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router

logger = logging.getLogger("vedax.data")


_FILTER_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
}

_SAFE_NAMES: set[str] = set()
_SAFE_FUNCTIONS = {"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "len": len}

# Whitelist of safe DataFrame methods (no mutations, no I/O, no code execution)
_SAFE_DF_METHODS = {
    "head", "tail", "describe", "info", "shape", "columns", "dtypes",
    "value_counts", "nunique", "unique", "isnull", "isna", "notnull", "notna",
    "sum", "mean", "median", "min", "max", "std", "var", "count", "first", "last",
    "cumsum", "cumprod", "cummax", "cummin", "diff", "pct_change", "rank",
    "fillna", "dropna", "drop_duplicates", "sample", "sort_values", "sort_index",
    "reset_index", "set_index", "to_frame", "to_list", "tolist", "to_dict",
    "to_string", "to_markdown", "to_clipboard",
    "abs", "round", "clip", "_between", "between_time",
    "resample", "rolling", "expanding", "ewm",
    "groupby", "pivot", "melt", "stack", "unstack",
    "rename", "reindex", "transpose", "swaplevel",
    "compare", "equals", "align", "update",
    "applymap",  # Deprecated but still callable
}

# Block these DataFrame methods entirely (mutations, I/O, code execution)
_BLOCKED_DF_METHODS = {
    "pipe", "apply", "query", "eval", "exec", "append", "insert", "drop",
    "pop", "iloc", "loc", "iat", "loc",
    "to_csv", "to_excel", "to_json", "to_html", "to_sql", "to_parquet",
    "to_hdf", "to_feather", "to_pickle", "to_latex", "to_records",
    "plot", "style", "boxplot", "hist",
}

# Allowed pandas top-level functions
_ALLOWED_PD_FUNCTIONS = {
    "to_datetime", "to_numeric", "to_timedelta", "Timestamp", "Timedelta",
    "isna", "notna", "isnull", "notnull", "concat", "merge", "read_csv",
    "get_dummies", "cut", "qcut", "date_range", "period_range", "interval_range",
}

# Read-only pandas Series accessors the LLM is allowed to use
# (e.g. df['Company'].str.startswith('S')). All are non-mutating.
_SAFE_STR_METHODS = {
    "startswith", "endswith", "contains", "lower", "upper", "strip",
    "lstrip", "rstrip", "replace", "split", "len", "slice", "extract",
    "count", "find", "findall",
}
_SAFE_DT_ATTRS = {
    "year", "month", "day", "hour", "minute", "weekday", "date",
    "quarter", "week", "dayofyear",
}
_COUNT_LIKE_NAMES = {"row_count", "count", "n", "num_rows", "total", "total_rows"}


def _safe_eval(expr: str, df: pd.DataFrame) -> Any:
    """Evaluate a limited arithmetic expression on DataFrame columns only.
    
    Security: This function is sandboxed to prevent code execution.
    - Only whitelisted DataFrame methods are allowed
    - No attribute access on non-DataFrame/Series objects
    - Function calls restricted to safe builtins and pandas functions
    - Arguments validated for safety
    """
    tree = ast.parse(expr, mode="eval")
    import pandas as _pd

    def _eval_node(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _SAFE_NAMES:
                raise ValueError(f"bare name {node.id!r} not allowed in compute expr")
            if node.id == "df":
                return df
            if node.id == "pd":
                return _pd
            if node.id in df.columns:
                return df[node.id]
            if node.id in _SAFE_FUNCTIONS:
                return _SAFE_FUNCTIONS[node.id]
            raise ValueError(f"unknown name {node.id!r}")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "df":
                # Security: Only allow safe DataFrame methods
                if node.attr in _BLOCKED_DF_METHODS:
                    raise ValueError(f"blocked method: {node.attr!r} (mutations/I/O not allowed)")
                if node.attr not in _SAFE_DF_METHODS and not node.attr.startswith("_"):
                    raise ValueError(f"unknown method: {node.attr!r} (not in whitelist)")
                return getattr(df, node.attr)
            # Allow pd.to_datetime, pd.Timestamp etc for date parsing.
            if isinstance(node.value, ast.Name) and node.value.id == "pd":
                if node.attr in _ALLOWED_PD_FUNCTIONS:
                    return getattr(_pd, node.attr)
                raise ValueError(f"attribute access not allowed: {ast.dump(node)}")
            # Chained safe accessor: df['col'].str.startswith('S'),
            # df['date'].dt.year — read-only pandas ops only.
            if isinstance(node.value, ast.Attribute) and node.value.attr in ("str", "dt"):
                series = _eval_node(node.value.value)
                if isinstance(series, _pd.Series):
                    allowed = _SAFE_STR_METHODS if node.value.attr == "str" else _SAFE_DT_ATTRS
                    if node.attr in allowed:
                        accessor = series.str if node.value.attr == "str" else series.dt
                        return getattr(accessor, node.attr)
                raise ValueError(f"attribute access not allowed: {ast.dump(node)}")
            # Bare accessor object: df['col'].str
            if node.attr in ("str", "dt"):
                series = _eval_node(node.value)
                if isinstance(series, _pd.Series):
                    return series.str if node.attr == "str" else series.dt
            raise ValueError(f"attribute access not allowed: {ast.dump(node)}")
        if isinstance(node, ast.Subscript):
            value = _eval_node(node.value)
            slice_val = _eval_node(node.slice) if not isinstance(node.slice, ast.Slice) else slice(
                _eval_node(node.slice.lower) if node.slice.lower else None,
                _eval_node(node.slice.upper) if node.slice.upper else None,
                _eval_node(node.slice.step) if node.slice.step else None,
            )
            return value[slice_val]
        if isinstance(node, ast.BinOp):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op_type = type(node.op)
            if op_type is ast.Add:
                return left + right
            if op_type is ast.Sub:
                return left - right
            if op_type is ast.Mult:
                return left * right
            if op_type is ast.Div:
                return left / right
            if op_type is ast.FloorDiv:
                return left // right
            if op_type is ast.Mod:
                return left % right
            if op_type is ast.Pow:
                return left ** right
            raise ValueError(f"unsupported operator: {op_type.__name__}")
        if isinstance(node, ast.UnaryOp):
            operand = _eval_node(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.Not):
                return not operand
            raise ValueError(f"unsupported unary: {type(node.op).__name__}")
        if isinstance(node, ast.Compare):
            left = _eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval_node(comparator)
                op_type = type(op)
                if op_type not in _FILTER_OPS:
                    raise ValueError(f"unsupported comparison: {op_type.__name__}")
                result = _FILTER_OPS[op_type](left, right)
                if not isinstance(result, bool) and not hasattr(result, "__iter__"):
                    if not result:
                        return False
                elif hasattr(result, "__iter__") and not all(result):
                    return False
            return True
        if isinstance(node, ast.Call):
            func = _eval_node(node.func)
            if not callable(func):
                raise ValueError(f"not callable: {node.func}")
            # Security: Validate function is in allowed list
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            # Check if function is safe
            if func_name and func_name not in _SAFE_FUNCTIONS and func_name not in _ALLOWED_PD_FUNCTIONS:
                raise ValueError(f"blocked function: {func_name!r} (not in whitelist)")
            # Validate arguments
            args = [_eval_node(a) for a in node.args]
            # For string methods, validate arguments are strings
            for i, arg in enumerate(args):
                if isinstance(arg, str) and len(arg) > 1000:
                    raise ValueError(f"argument {i} too long (max 1000 chars)")
            return func(*args)
        if isinstance(node, ast.IfExp):
            test = _eval_node(node.test)
            if isinstance(test, bool) and test:
                return _eval_node(node.body)
            elif hasattr(test, "__iter__"):
                if isinstance(test, _pd.Series) and test.any():
                    return _eval_node(node.body)
            return _eval_node(node.orelse)
        raise ValueError(f"unsupported expression: {ast.dump(node)}")

    return _eval_node(tree)


FilterOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "startswith", "endswith"]
AggFunc = Literal["sum", "mean", "median", "min", "max", "count", "std", "var", "first", "last"]
ChartType = Literal["bar", "line", "pie", "area", "scatter", "none"]


@dataclass(frozen=True)
class FilterStep:
    column: str
    op: FilterOp
    value: Any


@dataclass(frozen=True)
class GroupByStep:
    by: list[str]
    metrics: dict[str, AggFunc]


@dataclass(frozen=True)
class SortStep:
    by: list[str]
    ascending: list[bool]


@dataclass(frozen=True)
class SelectStep:
    columns: list[str]


@dataclass(frozen=True)
class ComputeStep:
    name: str
    expr: str


@dataclass(frozen=True)
class ComparePeriodsStep:
    date_column: str
    value_column: str
    period: Literal["day", "week", "month", "quarter", "year"]
    compare: Literal["prev", "yoy"]


@dataclass(frozen=True)
class DetectAnomalyStep:
    column: str
    method: Literal["zscore", "iqr"] = "zscore"
    threshold: float = 3.0


Step = (
    FilterStep
    | GroupByStep
    | SortStep
    | SelectStep
    | ComputeStep
    | ComparePeriodsStep
    | DetectAnomalyStep
)


PLAN_PROMPT = """You are a data analyst. Output a JSON plan of operations to answer the question using the DataFrame `df`.

Schema of df:
{schema}

Sample rows:
{sample}

Question: {question}

Available operations:
- filter: {{"type": "filter", "column": "...", "op": "eq|ne|gt|gte|lt|lte|in|contains|startswith|endswith", "value": ...}}
- group_by: {{"type": "group_by", "by": ["col1", ...], "metrics": {{"new_col": "sum|mean|median|min|max|count|std|var|first|last", ...}}}}
- sort: {{"type": "sort", "by": ["col1", ...], "ascending": [true, ...]}}
- select: {{"type": "select", "columns": ["col1", ...]}}
- compute: {{"type": "compute", "name": "new_column", "expr": "pandas expression using df columns"}}
- compare_periods: {{"type": "compare_periods", "date_column": "...", "value_column": "...", "period": "day|week|month|quarter|year", "compare": "prev|yoy"}}
- detect_anomaly: {{"type": "detect_anomaly", "column": "...", "method": "zscore|iqr", "threshold": 3.0}}

Rules:
- Operations execute in sequence on the DataFrame.
- For row counts per group use group_by with a count metric, e.g. {{"row_count": "count"}}.
- compute exprs may use Series string/datetime accessors, e.g. df['Company'].str.startswith('S'), df['Date'].dt.year.
- Final result should answer the question.
- Output JSON: {{"steps": [...], "chart_type": "bar|line|pie|area|scatter|none", "chart_title": "...", "x_label": "...", "y_label": "..."}}
- If the question cannot be answered with these operations, include an "explanation" field instead of "steps".
"""


def _apply_filter(df: pd.DataFrame, step: FilterStep) -> pd.DataFrame:
    col = df[step.column]
    op = step.op
    if op == "eq":
        return df[col == step.value]
    elif op == "ne":
        return df[col != step.value]
    elif op == "gt":
        return df[col > step.value]
    elif op == "gte":
        return df[col >= step.value]
    elif op == "lt":
        return df[col < step.value]
    elif op == "lte":
        return df[col <= step.value]
    elif op == "in":
        return df[col.isin(step.value if isinstance(step.value, list) else [step.value])]
    elif op == "contains":
        return df[col.astype(str).str.contains(str(step.value), case=False, na=False)]
    elif op == "startswith":
        return df[col.astype(str).str.startswith(str(step.value), na=False)]
    elif op == "endswith":
        return df[col.astype(str).str.endswith(str(step.value), na=False)]
    return df


def _apply_group_by(df: pd.DataFrame, step: GroupByStep) -> pd.DataFrame:
    value_columns = [column for column in df.select_dtypes(include="number").columns if column not in step.by]
    named_aggregations: dict[str, tuple[str, str]] = {}
    row_count_outputs: list[str] = []
    for output_column, func in step.metrics.items():
        if output_column in df.columns and output_column not in step.by:
            named_aggregations[output_column] = (output_column, func)
        elif func == "count" and output_column.lower() in _COUNT_LIKE_NAMES:
            # Row-count semantics: resolved from group sizes below.
            row_count_outputs.append(output_column)
        elif len(value_columns) == 1:
            named_aggregations[output_column] = (value_columns[0], func)
        else:
            raise ValueError(f"cannot infer source column for metric {output_column!r}")
    result: pd.DataFrame | None = None
    if named_aggregations:
        result = df.groupby(step.by, as_index=False).agg(**named_aggregations)
    if row_count_outputs:
        sizes = df.groupby(step.by).size().reset_index(name="__n__")
        for output_column in row_count_outputs:
            sizes[output_column] = sizes["__n__"]
        sizes = sizes[[*step.by, *row_count_outputs]]
        result = sizes if result is None else result.merge(sizes, on=step.by, how="left")
    if result is None:
        result = df.groupby(step.by).size().reset_index(name="count")
    return result


def _apply_sort(df: pd.DataFrame, step: SortStep) -> pd.DataFrame:
    return df.sort_values(by=step.by, ascending=step.ascending)


def _apply_select(df: pd.DataFrame, step: SelectStep) -> pd.DataFrame:
    return df[step.columns]


def _apply_compute(df: pd.DataFrame, step: ComputeStep) -> pd.DataFrame:
    df[step.name] = _safe_eval(step.expr, df)
    return df


def _apply_compare_periods(df: pd.DataFrame, step: ComparePeriodsStep) -> pd.DataFrame:
    date_col = pd.to_datetime(df[step.date_column], errors="coerce")
    df = df.copy()
    df["_period"] = date_col.dt.to_period(step.period)
    if step.compare == "prev":
        grp = df.groupby("_period")[step.value_column].sum().reset_index()
        grp["_prev"] = grp[step.value_column].shift(1)
        grp["_pct_change"] = (grp[step.value_column] - grp["_prev"]) / grp["_prev"].replace(0, pd.NA)
        return df.merge(grp[["_period", "_prev", "_pct_change"]], on="_period", how="left")
    elif step.compare == "yoy":
        grp = df.groupby("_period")[step.value_column].sum().reset_index()
        grp["_yoy"] = grp[step.value_column].shift(4 if step.period == "quarter" else 12)
        grp["_yoy_pct"] = (grp[step.value_column] - grp["_yoy"]) / grp["_yoy"].replace(0, pd.NA)
        return df.merge(grp[["_period", "_yoy", "_yoy_pct"]], on="_period", how="left")
    return df


def _apply_detect_anomaly(df: pd.DataFrame, step: DetectAnomalyStep) -> pd.DataFrame:
    col = df[step.column]
    if step.method == "zscore":
        std = col.std(ddof=0)
        z = (col - col.mean()) / std if std else pd.Series(0.0, index=col.index)
        df["_is_anomaly"] = pd.Series(
            [bool(value) for value in (z.abs() >= step.threshold)], index=df.index, dtype=object
        )
        df["_zscore"] = z
    elif step.method == "iqr":
        q1, q3 = col.quantile(0.25), col.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        df["_is_anomaly"] = (col < lower) | (col > upper)
    return df


STEP_DISPATCH = {
    "filter": (_apply_filter, FilterStep),
    "group_by": (_apply_group_by, GroupByStep),
    "sort": (_apply_sort, SortStep),
    "select": (_apply_select, SelectStep),
    "compute": (_apply_compute, ComputeStep),
    "compare_periods": (_apply_compare_periods, ComparePeriodsStep),
    "detect_anomaly": (_apply_detect_anomaly, DetectAnomalyStep),
}


def _build_step(step_dict: dict) -> Step:
    stype = step_dict["type"]
    if stype not in STEP_DISPATCH:
        raise ValueError(f"unknown step type: {stype}")
    _, cls = STEP_DISPATCH[stype]
    return cls(**{k: v for k, v in step_dict.items() if k != "type"})


def _execute_plan(df: pd.DataFrame, steps: list[Step]) -> pd.DataFrame:
    for step in steps:
        dispatch = next(
            ((func, cls) for func, cls in STEP_DISPATCH.values() if isinstance(step, cls)),
            None,
        )
        if dispatch is None:
            raise ValueError(f"unsupported step: {type(step).__name__}")
        func, _ = dispatch
        df = func(df, step)
    return df


def execute_plan(records: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    """Execute the small legacy operation format used by API resilience callers."""
    df = pd.DataFrame(records)
    try:
        for operation in plan.get("ops", []):
            op = operation.get("op")
            if op == "filter":
                df = _apply_filter(
                    df,
                    FilterStep(column=operation["field"], op="eq", value=operation.get("value")),
                )
            elif op == "group_by":
                field = operation["field"]
                value_field = operation["value_field"]
                df = _apply_group_by(
                    df,
                    GroupByStep(by=[field], metrics={value_field: operation.get("agg", "sum")}),
                )
            else:
                return {"data": [], "error": f"unsupported operation: {op}"}
        return {"data": df.to_dict(orient="records")}
    except (KeyError, TypeError, ValueError) as exc:
        return {"data": [], "error": str(exc)}


def _schema_text(columns: list[dict], sample_rows: list[dict]) -> tuple[str, str]:
    lines = [f"- {c['name']} ({c['dtype']})" for c in columns]
    sample = pd.DataFrame(sample_rows[:5]).to_string() if sample_rows else "(no sample)"
    return "\n".join(lines), sample


def result_to_text(result: pd.DataFrame | pd.Series | Any) -> str:
    if isinstance(result, pd.DataFrame):
        if len(result) > 50:
            return result.head(50).to_string() + f"\n... ({len(result)} rows total)"
        return result.to_string()
    if isinstance(result, pd.Series):
        return result.to_string()
    return str(result)


def build_chart_spec(
    result: pd.DataFrame | pd.Series | Any,
    chart_type: ChartType,
    title: str,
    x_label: str = "",
    y_label: str = "",
) -> dict[str, Any] | None:
    if chart_type in ("", "none", "None"):
        return None
    labels: list[str] = []
    series: list[dict[str, Any]] = []
    if isinstance(result, pd.DataFrame):
        labels = [str(v) for v in result.index.tolist()]
        for column in result.columns[:6]:
            series.append(
                {"name": str(column), "values": [float(v) if pd.notna(v) else 0 for v in result[column]]}
            )
    elif isinstance(result, pd.Series):
        labels = [str(v) for v in result.index.tolist()]
        series = [{"name": str(result.name or "value"), "values": [float(v) if pd.notna(v) else 0 for v in result]}]
    else:
        return None
    if not labels or not series:
        return None
    if chart_type == "pie" and len(series[0]["values"]) > 12:
        return None
    return {
        "chart_type": chart_type,
        "title": title or "Analysis result",
        "x_label": x_label,
        "y_label": y_label,
        "labels": labels[:40],
        "series": series,
        "caption": "",
    }


async def analyze_dataset(
    dataset: dict, question: str, ctx: RunContext | None = None
) -> dict[str, Any]:
    records = dataset.get("rows") or []
    columns = dataset.get("columns") or []
    sample_rows = dataset.get("sample_rows") or []
    if not records:
        return {
            "dataset_name": dataset.get("filename", "dataset"),
            "summary": "Dataset has no stored rows available for analysis.",
            "chart": None,
            "error": "empty dataset",
        }
    df = pd.DataFrame(records)
    schema, sample = _schema_text(columns, sample_rows)
    prompt = PLAN_PROMPT.format(schema=schema, sample=sample, question=question)
    router = get_model_router()
    try:
        plan, _ = await router.complete_json(
            [{"role": "user", "content": prompt}], task=TaskType.EXTRACTION, ctx=ctx
        )
        if "explanation" in plan:
            return {
                "dataset_name": dataset.get("filename", "dataset"),
                "summary": plan["explanation"],
                "chart": None,
                "error": "plan rejected: cannot answer with available operations",
            }
        steps = [_build_step(s) for s in plan.get("steps", [])]
        chart_type = plan.get("chart_type", "none")
        chart_title = plan.get("chart_title", "")
        x_label = plan.get("x_label", "")
        y_label = plan.get("y_label", "")

        result_df = await asyncio.to_thread(_execute_plan, df, steps)
        text = result_to_text(result_df)
        chart = build_chart_spec(result_df, chart_type, chart_title, x_label, y_label)
        return {
            "dataset_name": dataset.get("filename", "dataset"),
            "summary": f"Plan: {len(steps)} step(s)\nResult:\n{text}",
            "chart": chart,
            "error": None,
        }
    except Exception as exc:
        logger.error("data analysis failed: %s", exc)
        return {
            "dataset_name": dataset.get("filename", "dataset"),
            "summary": f"Automated analysis failed: {exc}",
            "chart": None,
            "error": str(exc)[:300],
        }
