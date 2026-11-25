"""Сводка анализа пересечений: порядок по объёму, группы по паре компонентов, усечение."""
from scripts.sw_measure import summarize_interference


def item(index, volume, a, b):
    return {"index": index, "volume_mm3": volume,
            "components": [{"name": a, "path": f"C:\\p\\{a}.SLDPRT"}, {"name": b, "path": f"C:\\p\\{b}.SLDPRT"}]}


def result(items):
    return {"status": "warn", "interference_count": len(items), "items": items, "max_volume_mm3": max(i["volume_mm3"] for i in items)}


def test_items_sorted_by_volume_and_truncated():
    data = result([item(i, float(i), "A-1", "B-1") for i in range(10)])
    s = summarize_interference(data, max_items=3)
    assert [i["volume_mm3"] for i in s["items"]] == [9.0, 8.0, 7.0]
    assert s["items_total"] == 10 and s["items_truncated"] == 7
    assert len(data["items"]) == 10  # исходный результат не меняется


def test_groups_by_unordered_component_pair():
    data = result([item(0, 5.0, "A-1", "B-1"), item(1, 1.0, "B-1", "A-1"), item(2, 20.0, "C-1", "A-1")])
    s = summarize_interference(data)
    assert s["groups"][0] == {"components": ["A-1", "C-1"], "count": 1, "total_volume_mm3": 20.0, "max_volume_mm3": 20.0}
    assert s["groups"][1] == {"components": ["A-1", "B-1"], "count": 2, "total_volume_mm3": 6.0, "max_volume_mm3": 5.0}
    assert s["groups_total"] == 2 and s["groups_truncated"] == 0


def test_no_interferences():
    s = summarize_interference({"status": "pass", "interference_count": 0, "items": []})
    assert s["items"] == [] and s["groups"] == [] and s["items_truncated"] == 0
