"""原生局部预览 MCP 参数和默认行为兼容性；无 CAD。"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'mcp-server') not in sys.path:sys.path.insert(0,str(ROOT/'mcp-server'))
import server
from scripts import sw_review


@pytest.fixture
def h(tmp_path,monkeypatch):
    path=tmp_path/'part.sldprt';path.write_bytes(b'part')
    model=N(GetPathName=str(path),GetTitle=path.name,GetType=1)
    sw=N(ActiveDoc=model)
    active=Mock(return_value=(sw,model));legacy=Mock(return_value=({'checks':{},'evaluation':{}},'legacy.json'))
    core=Mock(return_value=({'checks':{},'evaluation':{},'view_review':{'model_saved':False}},'view.json'))
    monkeypatch.setattr(server,'_active_model_required',active)
    monkeypatch.setattr(server,'_model_summary',lambda m:{'path':str(path)})
    monkeypatch.setattr(server,'run_review',legacy,raising=False)
    monkeypatch.setattr(sw_review,'run_closeup_review',core)
    monkeypatch.setattr(server,'_selected_process_id',123)
    def locked(op,response_format,**kwargs):
        try:return json.dumps(op())
        except Exception as exc:return json.dumps({'status':'error','message':str(exc)})
    monkeypatch.setattr(server,'_run_locked',locked)
    values=dict(output_dir=str(tmp_path/'out'),expected_document_path=str(path),process_id=123,
                views=['isometric','front','right'],zoom_box_mm=[26,-5,3,31,5,6])
    return N(**locals())


def invoke(values):return json.loads(server.solidworks_review_active(server.SolidWorksReviewInput(**values)))


def test_new_mode_routes_exact_guards_and_arguments(h):
    result=invoke(h.values)
    assert result['status']=='ok' and result['view_review']=={'model_saved':False}
    h.core.assert_called_once_with(h.sw,h.model,h.values['output_dir'],process_id=123,
        expected_document_path=str(h.path),basename='mcp_review',views=h.values['views'],zoom_box_mm=h.values['zoom_box_mm'])
    h.legacy.assert_not_called()


def test_legacy_route_and_result_unchanged(h):
    values=dict(output_dir=h.values['output_dir'])
    result=invoke(values)
    h.legacy.assert_called_once_with(h.model,values['output_dir'],basename='mcp_review')
    h.core.assert_not_called();assert 'view_review' not in result


@pytest.mark.parametrize('pid',[None,456,True,'123'])
def test_wrong_selected_pid_blocks_connection(h,monkeypatch,pid):
    monkeypatch.setattr(server,'_selected_process_id',pid)
    assert invoke(h.values)['status']=='error'
    h.active.assert_not_called();h.core.assert_not_called()


@pytest.mark.parametrize('patch',[{'process_id':None},{'process_id':True},{'process_id':'123'},
    {'expected_document_path':None},{'expected_document_title':'other'},
    {'views':[]},{'views':['front','front']},{'views':['iso']},
    {'zoom_box_mm':[26,-5,3,26,5,6]}, {'zoom_box_mm':[26,-5,3,31,5]},
    {'zoom_box_mm':['26',-5,3,31,5,6]},{'zoom_box_mm':[True,-5,3,31,5,6]},
    {'zoom_box_mm':[26,-5,3,float('inf'),5,6]}, {'zoom_box_mm':[26,-5,3,float('nan'),5,6]},
    {'basename':'../other'},{'output_dir':'relative'}])
def test_strict_new_mode_schema(h,patch):
    with pytest.raises(ValueError):server.SolidWorksReviewInput(**(h.values|patch))
    h.active.assert_not_called()


def test_process_without_new_mode_rejected(h):
    with pytest.raises(ValueError):server.SolidWorksReviewInput(output_dir=h.values['output_dir'],process_id=123)


def test_box_without_views_uses_core_defaults(h):
    values=h.values|{'views':None}
    invoke(values)
    assert h.core.call_args.kwargs['views'] is None
