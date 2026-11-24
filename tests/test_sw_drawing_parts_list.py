"""Перечень составных частей и выноски: спецификация и работа с таблицей на поддельных объектах."""
import pytest
from pydantic import ValidationError

from scripts import sw_drawing_parts_list as m


def test_default_columns_follow_the_requested_order():
    spec = m.PartsListSpec(sheet="Лист2", position_mm=(415, 60))
    assert [c.title for c in spec.columns] == ["Поз.", "Обозначение", "Наименование", "Кол.", "Примечание"]
    assert [c.property for c in spec.columns if c.source == "property"] == ["PartNumber", "Title", "MPN"]
    assert spec.header_at_bottom is True


@pytest.mark.parametrize("change", [
    dict(manual_rows=[{"Нет такой": "x"}]),
    dict(columns=[dict(title="A", source="property")]),
    dict(columns=[dict(title="A", source="item", property="X")]),
    dict(columns=[dict(title="A", source="item"), dict(title="A", source="quantity")]),
    dict(columns=[dict(title="A", source="item"), dict(title="B", source="item")]),
    dict(template_path="relative.sldbomtbt"),
    dict(template_path="C:\\t\\bom.xlsx"),
])
def test_bad_specs_are_refused(change):
    with pytest.raises(ValidationError):
        m.PartsListSpec(sheet="Лист2", position_mm=(0, 0), **change)


class FakeTable:
    def __init__(self, titles, rows=2):
        self.titles = list(titles)
        self.rows = rows
        self.types, self.props, self.widths = {}, {}, {}

    @property
    def ColumnCount(self):
        return len(self.titles)

    @property
    def RowCount(self):
        return self.rows

    def InsertColumn2(self, _where, index, name, _style):
        self.titles.insert(index + 1, name)
        return True

    def DeleteColumn(self, index):
        del self.titles[index]
        return True

    def SetColumnType(self, index, code):
        self.types[index] = code
        return True

    def SetColumnCustomProperty(self, index, name):
        self.props[index] = name
        return True

    def GetColumnCustomProperty(self, index):
        return self.props.get(index, "")

    def GetColumnType2(self, index, _include_hidden):
        return self.types.get(index)

    def SetColumnTitle(self, index, title):
        self.titles[index] = title
        return True

    def SetColumnWidth(self, index, width, _options):
        self.widths[index] = width
        return width


def test_columns_are_reshaped_typed_and_titled():
    table = FakeTable(["ITEM", "PART", "DESC", "QTY", "EXTRA", "MORE"])
    plan = m._shape_columns(table, table, m.PartsListSpec(sheet="s", position_mm=(0, 0)).columns)
    assert table.titles == ["Поз.", "Обозначение", "Наименование", "Кол.", "Примечание"]
    assert table.types == {0: m.COL_ITEM, 1: m.COL_PROPERTY, 2: m.COL_PROPERTY, 3: m.COL_QUANTITY, 4: m.COL_PROPERTY}
    assert table.props == {1: "PartNumber", 2: "Title", 4: "MPN"}
    assert plan[1]["width_mm"] == 60.0 and all(p["type_set"] and p["title_set"] for p in plan)


def test_columns_are_added_when_template_has_fewer():
    table = FakeTable(["ITEM", "QTY"])
    m._shape_columns(table, table, m.PartsListSpec(sheet="s", position_mm=(0, 0)).columns)
    assert len(table.titles) == 5


def test_header_row_is_found_by_titles():
    grid = [["1", "A-1", "Корпус", "1", ""], ["Поз.", "Обозначение", "Наименование", "Кол.", "Примечание"]]
    assert m._header_row(grid, ["Поз.", "Обозначение", "Наименование", "Кол.", "Примечание"]) == 1
    assert m._header_row(grid, ["x"]) is None


class FakeNote:
    def __init__(self, text, balloon, nxt=None):
        self.text, self.balloon, self.nxt = text, balloon, nxt

    def IsBomBalloon(self):
        return self.balloon

    def GetText(self):
        return self.text

    def GetNext(self):
        return self.nxt


class FakeView:
    def __init__(self, first):
        self.first = first

    def GetFirstNote(self):
        return self.first


def test_balloon_texts_skip_plain_notes():
    view = FakeView(FakeNote("1", True, FakeNote("примечание", False, FakeNote("2", True))))
    assert m._balloon_texts(view) == ["1", "2"]


def test_new_row_index_by_grid_difference():
    before = [["Поз.", "Наим."], ["1", "Корпус"]]
    assert m._new_row_index(before, [["Поз.", "Наим."], ["1", "Корпус"], ["3", ""]]) == 2
    assert m._new_row_index(before, [["", ""], ["Поз.", "Наим."], ["1", "Корпус"]]) == 0
    with pytest.raises(RuntimeError):
        m._new_row_index(before, before)


def test_column_type_that_does_not_stick_is_reported():
    class Stubborn(FakeTable):
        def SetColumnType(self, index, code):
            return True  # claims success, readback stays unchanged

    table = Stubborn(["A", "B"])
    plan = m._shape_columns(table, table, [m.PartsListColumn(title="Поз.", source="item"),
                                           m.PartsListColumn(title="Кол.", source="quantity")])
    assert [p["type_set"] for p in plan] == [False, False]
