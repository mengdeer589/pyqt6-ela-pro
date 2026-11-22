"""dataset / encode / transform 展开回归。"""

from __future__ import annotations

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, option) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(520, 400)
    chart.setOption({"animation": False, **option})
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


SOURCE = [
    ["month", "sales", "cost"],
    ["Jan", 120, 80],
    ["Feb", 180, 90],
    ["Mar", 150, 70],
]


def test_dataset_expands_axes_and_series(make):
    chart = _chart(
        make,
        {
            "dataset": {"source": SOURCE},
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "name": "sales",
                    "encode": {"x": "month", "y": "sales"},
                },
                {"type": "line", "name": "cost", "encode": {"x": 0, "y": 2}},
            ],
        },
    )
    option = chart.getOptionDict()
    assert option["xAxis"]["data"] == ["Jan", "Feb", "Mar"]
    assert option["series"][0]["data"] == [120, 180, 150]
    assert option["series"][1]["data"] == [80, 90, 70]
    assert [len(r.data()) for r in chart.seriesRenderers] == [3, 3]


def test_dataset_object_rows_and_value_pair(make):
    chart = _chart(
        make,
        {
            "dataset": {
                "source": [
                    {"x": 1, "y": 4},
                    {"x": 2, "y": 7},
                    {"x": 3, "y": 5},
                ]
            },
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "scatter", "encode": {"x": "x", "y": "y"}}],
        },
    )
    assert chart.getOptionDict()["series"][0]["data"] == [
        [1, 4],
        [2, 7],
        [3, 5],
    ]


def test_dataset_filter_sort_and_aggregate(make):
    chart = _chart(
        make,
        {
            "dataset": {
                "source": SOURCE,
                "transform": [
                    {"type": "filter", "dimension": "sales", "gt": 130},
                    {"type": "sort", "dimension": "sales", "order": "desc"},
                ],
            },
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "encode": {"x": "month", "y": "sales"}}],
        },
    )
    assert chart.getOptionDict()["xAxis"]["data"] == ["Feb", "Mar"]
    assert chart.getOptionDict()["series"][0]["data"] == [180, 150]

    chart = _chart(
        make,
        {
            "dataset": {
                "source": [
                    ["month", "kind", "value"],
                    ["Jan", "A", 10],
                    ["Jan", "B", 20],
                    ["Feb", "A", 30],
                    ["Feb", "B", 40],
                ],
                "transform": [
                    {
                        "type": "aggregate",
                        "groupBy": "month",
                        "dimension": "value",
                        "method": "sum",
                    }
                ],
            },
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "encode": {"x": "month", "y": "value_sum"}}],
        },
    )
    assert chart.getOptionDict()["series"][0]["data"] == [30.0, 70.0]


def test_dataset_series_layout_by_column_and_row(make):
    source = [
        ["product", "2015", "2016"],
        ["A", 10, 20],
        ["B", 15, 25],
    ]
    column = _chart(
        make,
        {
            "dataset": {"source": source, "seriesLayoutBy": "column"},
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar"}],
        },
    )
    option = column.getOptionDict()
    assert option["xAxis"]["data"] == ["A", "B"]
    assert [(s["name"], s["data"]) for s in option["series"]] == [
        ("2015", [10, 15]),
        ("2016", [20, 25]),
    ]

    row = _chart(
        make,
        {
            "dataset": {"source": source, "seriesLayoutBy": "row"},
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar"}],
        },
    )
    option = row.getOptionDict()
    assert option["xAxis"]["data"] == ["2015", "2016"]
    assert [(s["name"], s["data"]) for s in option["series"]] == [
        ("A", [10, 20]),
        ("B", [15, 25]),
    ]


def test_dataset_series_name_splits_series(make):
    chart = _chart(
        make,
        {
            "dataset": {
                "source": [
                    ["month", "kind", "value"],
                    ["Jan", "A", 10],
                    ["Jan", "B", 20],
                    ["Feb", "A", 30],
                    ["Feb", "B", 40],
                ]
            },
            "xAxis": {"type": "category"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "encode": {"x": "month", "y": "value", "seriesName": "kind"},
                }
            ],
        },
    )
    assert [(r.name, list(r.data())) for r in chart.seriesRenderers] == [
        ("A", [10, 30]),
        ("B", [20, 40]),
    ]


def test_dataset_pie_encode(make):
    chart = _chart(
        make,
        {
            "dataset": {
                "source": [
                    ["name", "value"],
                    ["A", 3],
                    ["B", 5],
                ]
            },
            "series": [
                {
                    "type": "pie",
                    "encode": {"itemName": "name", "value": "value"},
                }
            ],
        },
    )
    assert chart.getOptionDict()["series"][0]["data"] == [
        {"name": "A", "value": 3},
        {"name": "B", "value": 5},
    ]
