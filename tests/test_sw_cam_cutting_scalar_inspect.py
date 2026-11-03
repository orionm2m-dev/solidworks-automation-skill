"""Selected scalar reads do not require material or unrelated tool parameters."""
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from scripts import sw_cam_cutting_conditions as cam
from scripts import sw_cam_events as events
from test_sw_cam_cutting_conditions import graph, ref


def forbid_material(graph):
    graph.machine.IGetWorkpiece.side_effect = AssertionError("Material object is not scalar-read scope")
    for param in (graph.pa, graph.pb):
        param.GetCurrentTurnStockMaterial.side_effect = AssertionError("No material getter")
        param.GetAllStockMaterialsList.side_effect = AssertionError("No material catalogue")


def test_selected_scalars_read_with_missing_material_and_unrelated_drill(graph):
    forbid_material(graph)
    graph.tools[0].turn_subtype = 2
    state, native = cam._snapshot(object(), 'clsid', 'tlb', ref(2), scalar_inspect=True)
    assert native['parameter'] is graph.pb and native['workpiece'] is None
    assert [u['operation_native_id'] for u in state['operation_uses']] == [101, 102, 103]
    assert [u['cutting_group'] for u in state['operation_uses']] == [None, None, 0]
    assert len(state['cutting_groups']) == 1
    values = state['cutting_groups'][0]['values_native']
    assert values == dict(SMM=100., MAXRPM=2500., SpindleSpeed=700., FPR=.1, FPM=70.,
        IsSMM=True, IsFPR=True, IsAssociateWithStockMaterial=False)
    assert state['material_raw'] is None and state['material_catalogue_raw'] is None
    assert state['parameter_scope'] == 'selected_turn_tool_cutting_scalars_only'
    assert state['material_scope'] == 'not_requested_for_scalar_inspection'
    assert not state['all_parameter_aliases_inspected'] and not state['write_preparation_qualified']
    graph.machine.IGetWorkpiece.assert_not_called()
    graph.pa.GetIsSMM.assert_not_called()
    graph.tools[0].IGetActiveTurnCuttingParam.assert_not_called()
    for param in (graph.pa, graph.pb):
        param.GetCurrentTurnStockMaterial.assert_not_called()
        param.GetAllStockMaterialsList.assert_not_called()


def test_default_snapshot_still_requires_material_getter(graph):
    graph.pa.GetCurrentTurnStockMaterial.return_value = None
    with pytest.raises(ValueError, match='BSTR'):
        graph.snapshot()
    graph.pa.GetCurrentTurnStockMaterial.assert_called_once()


@pytest.mark.parametrize('selected', [None, ref(9), ref(0, 5)])
def test_scalar_snapshot_requires_exact_existing_selected_operation(graph, selected):
    with pytest.raises(ValueError):
        cam._snapshot(object(), 'clsid', 'tlb', selected, scalar_inspect=True)


def test_selected_drill_subtype_is_not_guessed_or_probed(graph):
    graph.tools[0].turn_subtype = 2
    with pytest.raises(ValueError):
        cam._snapshot(object(), 'clsid', 'tlb', ref(0), scalar_inspect=True)
    graph.tools[0].IGetActiveTurnCuttingParam.assert_not_called()


@pytest.mark.parametrize('field,value', [('SMM', True), ('MAXRPM', float('nan')), ('IsSMM', 1)])
def test_selected_scalar_type_failures_remain_fatal(graph, field, value):
    setattr(graph.pa, 'Get'+field, Mock(return_value=value))
    with pytest.raises(ValueError):
        cam._snapshot(object(), 'clsid', 'tlb', ref(0), scalar_inspect=True)


def test_scalar_getter_error_is_not_swallowed_as_optional_material(graph):
    graph.pa.GetIsSMM.side_effect = RuntimeError('scalar failed')
    with pytest.raises(RuntimeError, match='scalar failed'):
        cam._snapshot(object(), 'clsid', 'tlb', ref(0), scalar_inspect=True)
    graph.pa.GetCurrentTurnStockMaterial.assert_not_called()


@pytest.mark.parametrize('drift', ['file', 'inventory', 'tool_type', 'duplicate_operation'])
def test_scalar_inspection_retains_metadata_binding_guards(graph, monkeypatch, drift):
    if drift == 'file':
        monkeypatch.setattr(cam, '_file_sha', Mock(side_effect=['a'*64, 'b'*64]))
    if drift == 'inventory':
        monkeypatch.setattr(cam, '_inventory', Mock(side_effect=[deepcopy(graph.inv), {'operations':[]}]))
    if drift == 'tool_type':
        graph.tools[1].native_id = graph.tools[0].native_id
        graph.tools[1].ToolType = 14
    if drift == 'duplicate_operation': graph.ops[1].native_id = graph.ops[0].native_id
    with pytest.raises(ValueError):
        cam._snapshot(object(), 'clsid', 'tlb', ref(2), scalar_inspect=True)


@pytest.fixture
def routed(graph, monkeypatch, tmp_path):
    class Session:
        def __init__(self, *args): self.active = False; self.entered = False
        def __enter__(self): self.active = self.entered = True; return self
        def __exit__(self, *args): self.active = False
        def summary(self): return dict(subscribed=self.entered, active=self.active,
            disconnected=self.entered and not self.active, event_count=0, overflow=0,
            callback_errors=[], callback_error_count=0, subscription_error=None, disconnect_errors=[])
    monkeypatch.setattr(events, 'CamMessageSession', Session)
    monkeypatch.setattr(cam, '_bootstrap', lambda *args: object())
    params = dict(expected_document_path=graph.document['path'], field='IsSMM',
        selected_operation=ref(0), qualification_only=True, message_policy='vendor_default')
    def run(action, **extra):
        return cam.configure_cutting_conditions(object(), 'clsid', 'tlb', **(params | dict(action=action) | extra))
    return NS(**locals())


def test_public_inspect_works_without_material_and_never_grants_write_authority(routed):
    forbid_material(routed.graph)
    r = routed.run('inspect')
    assert r['status'] == 'ok', r
    assert not r['apply_eligible'] and not r['mutation_attempted']
    assert r['inspection_scope'] == 'selected_turn_tool_scalars_no_material_or_alias_authority'
    assert r['before']['cutting_groups'][0]['values_native']['IsSMM'] is True
    assert r['messages']['disconnected'] and not r['post_cleanup_CAM_getters']
    assert not r['native_units_independently_verified'] and not r['physical_cutting_conditions_qualified']


@pytest.mark.parametrize('action', ['prepare', 'apply', 'material_inspect'])
def test_prepare_apply_and_material_inspect_keep_strict_material_requirements(routed, action):
    routed.graph.pa.GetCurrentTurnStockMaterial.return_value = None
    args = {}
    if action == 'apply':
        args = dict(value_native=False, expected_state_sha256='a'*64,
            allowed_affected_operations=[ref(0), ref(1), ref(2)],
            receipt_path=str(routed.tmp_path/'strict.json'))
    if action == 'material_inspect':
        action = 'inspect'; args = dict(field='Material', selected_operation=None)
    r = routed.run(action, **args)
    assert r['status'] == 'error' and not r['mutation_attempted'], r
    routed.graph.pa.GetCurrentTurnStockMaterial.assert_called_once()
    assert r['inspection_scope'] == 'complete_material_and_cutting_parameter_scope'


def test_inspect_rejects_mutation_payload(routed):
    with pytest.raises(ValueError, match='reject mutation inputs'):
        routed.run('inspect', value_native=False)
    routed.graph.pa.GetIsSMM.assert_not_called()


@pytest.mark.parametrize('selected_index', [0, 2])
def test_same_tool_id_different_parameter_identity_is_not_scalar_read_authority(graph, selected_index):
    graph.tools[1].native_id = graph.tools[0].native_id
    graph.tools[1].IGetActiveTurnCuttingParam.return_value = graph.pb
    # Both parameter objects have identical scalar/material data, distinct COM tokens.
    with pytest.raises(ValueError, match='Shared tool identity maps'):
        graph.snapshot()
    state, native = cam._snapshot(object(), 'clsid', 'tlb', ref(selected_index), scalar_inspect=True)
    assert [u['tool_native_id'] for u in state['operation_uses']] == [201, 201, 203]
    assert native['parameter'] is (graph.pa if selected_index == 0 else graph.pb)
    assert not state['all_parameter_aliases_inspected'] and not state['write_preparation_qualified']
    assert len(state['cutting_groups']) == 1
