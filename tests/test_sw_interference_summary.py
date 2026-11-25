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


def test_group_box_is_union_of_item_boxes():
    a = item(0, 2.0, "A-1", "B-1"); a["box_mm"] = [0, 0, 0, 10, 10, 10]
    b = item(1, 1.0, "B-1", "A-1"); b["box_mm"] = [-5, 2, 1, 4, 20, 3]; b["is_fastener"] = True
    s = summarize_interference(result([a, b]))
    assert s["groups"][0]["box_mm"] == [-5, 0, 0, 10, 20, 10]
    assert s["groups"][0]["fastener_count"] == 1


class FakeBody:
    def GetBodyBox(self):
        return (0.01, 0.02, 0.0, 0.03, 0.04, 0.0075)

    def GetMassProperties(self, density):
        return (0.02, 0.03, 0.00375, 1e-6, 0.0, 0.0)


class FakeItem:
    def __init__(self, body=FakeBody(), fail=False):
        self.body, self.fail = body, fail

    def IsFastener(self):
        return False

    def GetInterferenceBody(self):
        if self.fail:
            raise RuntimeError("no body")
        return self.body


def test_location_from_interference_body():
    from scripts.sw_measure import _interference_location
    loc = _interference_location(FakeItem())
    assert loc["box_mm"] == [10.0, 20.0, 0.0, 30.0, 40.0, 7.5]
    assert loc["center_mm"] == [20.0, 30.0, 3.75]
    assert loc["centroid_mm"] == [20.0, 30.0, 3.75]
    assert loc["is_fastener"] is False


def test_location_failure_is_reported_not_raised():
    from scripts.sw_measure import _interference_location
    loc = _interference_location(FakeItem(fail=True))
    assert "location_error" in loc and "box_mm" not in loc
