"""AFR 前的只读毛坯/FCS 检查；所有 COM 均为替身。"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import sw_cam_generation as cam


@pytest.fixture
def probe(monkeypatch):
    before = {"path": "C:/calibration.sldprt", "title": "calibration.sldprt", "type": 1, "needs_save": False}
    inventory = {"feature_count": 0, "operation_count": 0, "operation_setup_count": 0,
                 "operations": [], "stock": {"type": 3}}
    stock = SimpleNamespace(GetTurnWorkpieceType=Mock(return_value=3),
        GetMinBarStockParams=Mock(return_value=(-2.0, 15.0, 20.0)),
        GetBarStockParameters=Mock(return_value=(1.0, 2.0, 3.0, 0.0, 1)))
    machine = SimpleNamespace(IGetWorkpiece=Mock(return_value=stock))
    machine5 = SimpleNamespace(GetCoordinateSystemName=Mock(return_value="StockCS"),
                              GetFCS=Mock(return_value=("StockCS", 1, 2, 3, None, object())))
    sw = SimpleNamespace(ActiveDoc=SimpleNamespace(GetUnits=Mock(return_value=(0, 0, 2, 3, 0))))
    monkeypatch.setattr(cam, "_context", Mock(return_value=(before, object(), object(), machine, object())))
    monkeypatch.setattr(cam, "_inventory", Mock(side_effect=lambda *_: deepcopy(inventory)))
    monkeypatch.setattr(cam, "document_snapshot", Mock(side_effect=lambda *_: deepcopy(before)))
    monkeypatch.setattr(cam, "_typed", Mock(side_effect=lambda obj,name,path: stock if name=="ICWTurnWorkpiece" else machine5))
    return SimpleNamespace(run=lambda:cam.inspect_turn_stock(sw,"clsid","registered.tlb"), before=before,
                           stock=stock, machine5=machine5, sw=sw, inventory=inventory)


def test_inspects_raw_stock_and_fcs_without_operations_or_units_assumption(probe):
    report = probe.run()
    assert report["status"] == "ok" and report["inventory_before"]["operation_count"] == 0
    assert report["minimum_bar_stock_native"] == {"bounding_startZ":-2.0,"bounding_length":15.0,"bounding_OD":20.0}
    assert report["bar_parameters_native"] == {"startZ":1.0,"length":2.0,"odOff":3.0,"idOff":0.0,"attribute":1}
    assert report["solidworks_document_units_raw"] == [0,0,2,3,0]
    assert report["fcs_definition_raw"] is None and not report["fcs_probe_performed"]
    probe.machine5.GetFCS.assert_not_called()
    assert not report["document_units_are_cam_units_proof"] and not report["frame_orientation_verified"]
    assert not report["mutation_attempted"] and not report["stock_parameters_modified"]
    assert report["active_document_unchanged"] and report["inventory_unchanged"]


def test_non_bar_stock_does_not_read_bar_parameters(probe):
    probe.stock.GetTurnWorkpieceType.return_value = 2
    report = probe.run()
    assert report["status"] == "ok" and report["bar_parameters_native"] is None
    probe.stock.GetBarStockParameters.assert_not_called()


@pytest.mark.parametrize("method,result", [("GetMinBarStockParams",(1,2)),("GetMinBarStockParams",(1,float("nan"),3)),
    ("GetBarStockParameters",(0,0,0,0,True)),("GetBarStockParameters",(0,True,0,0,1)),
    ("GetBarStockParameters",(0,0,0,0)),("GetBarStockParameters",(0,0,float("inf"),0,1))])
def test_bad_native_arrays_are_reported_without_inventing_values(probe,method,result):
    getattr(probe.stock,method).return_value=result
    report=probe.run()
    assert report["status"]=="review_required" and not report["diagnostics_complete"]
    assert report["diagnostics"][0]["field"]==method


@pytest.mark.parametrize("field", ["GetCoordinateSystemName"])
def test_missing_frame_getter_is_explicitly_unavailable(probe,field):
    getattr(probe.machine5,field).side_effect=AttributeError("unavailable")
    report=probe.run()
    assert report["status"]=="review_required" and report["diagnostics"][0]["field"]==field
    assert not report["frame_orientation_verified"]


def test_document_change_during_readback_blocks_result(probe,monkeypatch):
    monkeypatch.setattr(cam,"document_snapshot",Mock(return_value={**probe.before,"path":"C:/other.sldprt"}))
    report=probe.run()
    assert report["status"]=="review_required" and not report["active_document_unchanged"]


def test_context_failure_does_not_touch_stock(probe,monkeypatch):
    monkeypatch.setattr(cam,"_context",Mock(side_effect=ValueError("not turning")))
    assert probe.run()["status"]=="error"
    probe.stock.GetMinBarStockParams.assert_not_called()


@pytest.mark.parametrize("name", [None, ""])
def test_unset_coordinate_name_is_not_an_error_or_identity_frame(probe,name):
    probe.machine5.GetCoordinateSystemName.return_value=name
    probe.machine5.GetFCS.side_effect=AssertionError("Unqualified native getter must not run")
    report=probe.run()
    assert report["status"]=="ok" and report["coordinate_system_name_state"]=="unset"
    assert not report["frame_orientation_verified"] and not report["fcs_probe_performed"]
    probe.machine5.GetFCS.assert_not_called()
