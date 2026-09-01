import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from app.providers.base import RunContext, TaskType
from app.providers.registry import get_model_router

logger = logging.getLogger("vedax.data")


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
    agg_map = {col: func for col, func in step.metrics.items()}
    return df.groupby(step.by, as_index=False).agg(agg_map)


def _apply_sort(df: pd.DataFrame, step: SortStep) -> pd.DataFrame:
    return df.sort_values(by=step.by, ascending=step.ascending)


def _apply_select(df: pd.DataFrame, step: SelectStep) -> pd.DataFrame:
    return df[step.columns]


def _apply_compute(df: pd.DataFrame, step: ComputeStep) -> pd.DataFrame:
    allowed = {"df": df, "pd": pd}
    df[step.name] = eval(step.expr, {"__builtins__": {}}, allowed)
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
        z = (col - col.mean()) / col.std(ddof=0).replace(0, pd.NA)
        df["_is_anomaly"] = z.abs() > step.threshold
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
        stype = step.__class__.__name__.replace("Step", "").lower()
        func, _ = STEP_DISPATCH[stype]
        df = func(df, step)
    return df


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