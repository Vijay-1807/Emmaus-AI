import pandas as pd
import pytest

from app.data.analysis import (
    build_chart_spec,
    _execute,
    _guard_code,
    result_to_text,
)


def test_guard_rejects_dangerous_code():
    for bad in ["import os", "open('/etc/passwd')", "x = a.__class__", "exec('1')", "while True:\n    pass"]:
        with pytest.raises(ValueError):
            _guard_code(bad)


def test_guard_allows_normal_pandas():
    _guard_code("result = df.groupby('region')['revenue'].sum()")


def test_execute_groupby():
    df = pd.DataFrame(
        {"region": ["north", "south", "north"], "revenue": [10, 20, 30]}
    )
    code = "result = df.groupby('region')['revenue'].sum()"
    result = _execute(code, df)
    assert result["north"] == 40
    assert result["south"] == 20


def test_execute_missing_result_raises():
    df = pd.DataFrame({"a": [1]})
    with pytest.raises(ValueError):
        _execute("x = df['a'].sum()", df)


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
