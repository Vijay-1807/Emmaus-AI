import pandas as pd
import pytest

from app.data.analysis import (
    FilterStep,
    GroupByStep,
    SortStep,
    SelectStep,
    ComputeStep,
    ComparePeriodsStep,
    DetectAnomalyStep,
    _apply_filter,
    _apply_group_by,
    _apply_sort,
    _apply_select,
    _apply_compute,
    _apply_detect_anomaly,
    _execute_plan,
    build_chart_spec,
    result_to_text,
    PLAN_PROMPT,
)


def test_filter_eq():
    df = pd.DataFrame({"region": ["north", "south", "north"], "revenue": [10, 20, 30]})
    step = FilterStep(column="region", op="eq", value="north")
    result = _apply_filter(df, step)
    assert len(result) == 2
    assert all(result["region"] == "north")


def test_filter_gt():
    df = pd.DataFrame({"x": [1, 5, 10, 15]})
    step = FilterStep(column="x", op="gt", value=7)
    result = _apply_filter(df, step)
    assert list(result["x"]) == [10, 15]


def test_filter_contains():
    df = pd.DataFrame({"name": ["Alice", "Bob", "Alicia"]})
    step = FilterStep(column="name", op="contains", value="ali")
    result = _apply_filter(df, step)
    assert len(result) == 2


def test_group_by_sum():
    df = pd.DataFrame({"region": ["north", "south", "north"], "revenue": [10, 20, 30]})
    step = GroupByStep(by=["region"], metrics={"total": "sum"})
    result = _apply_group_by(df, step)
    assert result.set_index("region")["total"]["north"] == 40
    assert result.set_index("region")["total"]["south"] == 20


def test_sort_ascending():
    df = pd.DataFrame({"x": [3, 1, 2]})
    step = SortStep(by=["x"], ascending=[True])
    result = _apply_sort(df, step)
    assert list(result["x"]) == [1, 2, 3]


def test_select_columns():
    df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
    step = SelectStep(columns=["a", "c"])
    result = _apply_select(df, step)
    assert list(result.columns) == ["a", "c"]


def test_compute_new_column():
    df = pd.DataFrame({"x": [1, 2, 3]})
    step = ComputeStep(name="doubled", expr="df['x'] * 2")
    result = _apply_compute(df, step)
    assert list(result["doubled"]) == [2, 4, 6]


def test_detect_anomaly_zscore():
    df = pd.DataFrame({"x": [1, 1, 1, 1, 100]})
    step = DetectAnomalyStep(column="x", method="zscore", threshold=2.0)
    result = _apply_detect_anomaly(df, step)
    assert result["_is_anomaly"].sum() == 1
    assert result.iloc[-1]["_is_anomaly"] is True


def test_execute_plan():
    df = pd.DataFrame({"region": ["north", "south", "north"], "revenue": [10, 20, 30]})
    steps = [
        FilterStep(column="region", op="eq", value="north"),
        GroupByStep(by=["region"], metrics={"total": "sum"}),
    ]
    result = _execute_plan(df, steps)
    assert len(result) == 1
    assert result.iloc[0]["total"] == 40


def test_build_chart_spec_from_series():
    series = pd.Series({"north": 40, "south": 20}, name="revenue")
    chart = build_chart_spec(series, "bar", "Revenue by region")
    assert chart is not None
    assert chart["labels"] == ["north", "south"]
    assert chart["series"][0]["values"] == [40.0, 20.0]


def test_build_chart_spec_none_type():
    assert build_chart_spec(pd.Series([1, 2]), "none", "") is None


def test_result_to_text_truncates():
    df = pd.DataFrame({"a": range(100), "b": range(100)})
    text = result_to_text(df)
    assert "rows total" in text


def test_result_to_text_scalar():
    assert result_to_text(42) == "42"


def test_compute_percent_string_cleaning():
    # Exact production failure: "77.0%" strings must clean to numbers.
    df = pd.DataFrame({"Percentage": ["77.0%", "100.0%", "64.0%"]})
    step = ComputeStep(name="pct", expr="df['Percentage'].str.rstrip('%').astype(float)")
    result = _apply_compute(df, step)
    assert list(result["pct"]) == [77.0, 100.0, 64.0]


def test_compute_chained_methods():
    df = pd.DataFrame({"x": [None, 2.345, 3.0]})
    step = ComputeStep(name="y", expr="df['x'].fillna(0).round(1).astype(float)")
    result = _apply_compute(df, step)
    assert list(result["y"]) == [0.0, 2.3, 3.0]


def test_compute_str_predicate_still_works():
    df = pd.DataFrame({"Company": ["Sunrise", "Moon"]})
    step = ComputeStep(name="flag", expr="df['Company'].str.startswith('S')")
    result = _apply_compute(df, step)
    assert list(result["flag"]) == [True, False]


def test_compute_still_blocks_dangerous_calls():
    df = pd.DataFrame({"x": [1]})
    for expr in (
        "df['x'].apply(lambda v: v)",
        "__import__('os').system('x')",
        "df.to_csv('/tmp/x.csv')",
    ):
        with pytest.raises(ValueError):
            _apply_compute(df, ComputeStep(name="bad", expr=expr))


def test_chart_spec_mixed_frame_uses_text_labels():
    # Production case: Metric text column + cleaned numeric column.
    df = pd.DataFrame(
        {"Metric": ["A", "B"], "pct_num": [77.0, 100.0]},
    )
    chart = build_chart_spec(df, "bar", "Performance %")
    assert chart is not None
    assert chart["labels"] == ["A", "B"]
    assert chart["series"][0]["values"] == [77.0, 100.0]


def test_chart_spec_skips_text_columns():
    df = pd.DataFrame({"Metric": ["A", "B"], "note": ["x", "y"]})
    assert build_chart_spec(df, "bar", "t") is None


def test_plan_prompt_formats_without_key_error():
    # Every literal {...} in the template must be doubled, or .format()
    # blows up at runtime (production KeyError: '"type"').
    rendered = PLAN_PROMPT.format(schema="s", sample="r", question="q")
    assert "77.0%" in rendered
    assert "{schema}" not in rendered
