"""TURN NC uses the verified standard bridge registry without arbitrary QI."""
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_comtypes as bridge
from scripts.sw_cam_configuration_binding import read_nc
from scripts.sw_cam_generation import _typed
from scripts.sw_cam import _member

IID = "{908023A2-B845-4C64-A395-5EF667E7DE68}"


def test_exact_turn_nc_registry_and_existing_pointer_path(monkeypatch):
    declared=N(_iid_=IID)
    loader=Mock(return_value=N(ICWTurnNCParam=declared))
    monkeypatch.setattr(bridge,'_load_type_library',loader)
    monkeypatch.setattr(bridge,'_is_comtypes_pointer',lambda _:True)
    nc=N(GetSpndlSpeed=Mock(return_value=500.),GetFeedRateIPM=Mock(return_value=35.))
    raw=N(QueryInterface=Mock(return_value=nc))
    operation=N(IGetTurnNCParam=Mock(return_value=raw))
    marshal=Mock(side_effect=AssertionError('No remarshal for an existing pointer'))
    monkeypatch.setattr(bridge,'_marshal_pywin32_unknown',marshal)
    assert bridge._INTERFACES['ICWTurnNCParam']==IID
    rows=read_nc([127],{127:operation},read=_member,
        typed=lambda obj,name:_typed(obj,name,'verified.tlb'))
    assert rows==[dict(operation_native_id=127,status='observed',stage='finished',
                      spindle_speed_native=500.,feed_rate_ipm_native=35.)]
    operation.IGetTurnNCParam.assert_called_once_with()
    loader.assert_called_once_with('verified.tlb');raw.QueryInterface.assert_called_once_with(declared)
    nc.GetSpndlSpeed.assert_called_once_with();nc.GetFeedRateIPM.assert_called_once_with()
    marshal.assert_not_called()


def test_turn_nc_wrong_generated_iid_never_reaches_query(monkeypatch):
    monkeypatch.setattr(bridge,'_load_type_library',Mock(return_value=N(
        ICWTurnNCParam=N(_iid_='{00000000-0000-0000-0000-000000000000}'))))
    raw=N(QueryInterface=Mock())
    with pytest.raises(ValueError):bridge.query_cam_interface(raw,'ICWTurnNCParam','verified.tlb')
    raw.QueryInterface.assert_not_called()


def test_only_named_turn_nc_interface_is_enabled(monkeypatch):
    loader=Mock(side_effect=AssertionError('Unknown name must stop before loading'))
    monkeypatch.setattr(bridge,'_load_type_library',loader)
    with pytest.raises(ValueError):bridge._interface_class('ICWTurnNCParamUnverified','unused.tlb')
    loader.assert_not_called()
