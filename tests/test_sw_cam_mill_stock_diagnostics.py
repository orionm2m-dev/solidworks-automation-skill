from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as N
import json
import pytest
from scripts import sw_cam_mill_stock as cam
from test_sw_cam_mill_stock import probe

@pytest.fixture
def native_stock(tmp_path,monkeypatch):
    source=tmp_path/'stock.stl';source.write_bytes(b'fixture')
    knobs=dict(raw=(0.,)*6+(False,True,False,True))
    stock=N(GetMillWorkpieceType=lambda:4,GetBoundingBoxSize=lambda:(-1.,-1.,-1.,1.,1.,1.,True),
        GetWorkpieceFromSTLParam=lambda:(str(source),0,'',True),GetSTLOffset=lambda:knobs['raw'])
    machine=N(IGetWorkpiece=lambda:stock);base=dict(current_machine=dict(machine_type=1))
    monkeypatch.setattr(cam,'_mill_snapshot',lambda *a,**k:(deepcopy(base),dict(machine=machine)))
    monkeypatch.setattr(cam,'_typed',lambda value,*_:value)
    diagnostic={}
    def run(check=lambda:None):return cam._snapshot(object(),'clsid','tlb','C:/part.sldprt',check=check,diagnostic=diagnostic)
    return N(**locals())


def test_successful_raw_offset_read_is_recorded_without_coercion(native_stock):
    state,_=native_stock.run();d=native_stock.diagnostic
    assert d['capture_complete'] and state['stock']['offsets_native']==[0.]*6
    last=d['stock_native_reads'][-1]
    assert last['method']=='GetSTLOffset' and last['native_returned'] is True
    assert last['raw']['length']==10 and last['raw']['python_type']=='tuple'
    assert last['raw']['items'][6]==dict(python_type='bool',value=False)
    assert last['raw']['items'][9]==dict(python_type='bool',value=True)

@pytest.mark.parametrize('raw',[
    (0.,)*6+(False,False,False,False),
    (0.,)*6+(False,False,False),False,None,
    (0.,)*6+(False,False,False,1),
    (float('nan'),)+(0.,)*5+(False,False,False,True),
    (False,)+(0.,)*5+(False,False,False,True),
    (0.,)*6+(1,False,False,True),
])
def test_rejected_raw_outputs_remain_rejected_and_durable_in_diagnostic(native_stock,raw):
    native_stock.knobs['raw']=raw
    with pytest.raises(ValueError):native_stock.run()
    d=native_stock.diagnostic;last=d['stock_native_reads'][-1]
    assert d['capture_complete'] is False and d['last_native_method']=='GetSTLOffset'
    assert last['native_returned'] is True and last['raw']['python_type']==type(raw).__name__
    json.dumps(d,allow_nan=False)
    if isinstance(raw,tuple):assert last['raw']['length']==len(raw)
    if isinstance(raw,tuple) and len(raw)==10 and raw[-1] is False:
        assert last['raw']['items'][-1]==dict(python_type='bool',value=False)


def test_raw_output_survives_post_read_event_guard(native_stock):
    def check():
        if native_stock.diagnostic.get('last_native_method')=='GetSTLOffset':raise RuntimeError('event after native return')
    with pytest.raises(RuntimeError):native_stock.run(check)
    assert native_stock.diagnostic['stock_native_reads'][-1]['native_returned'] is True
    assert native_stock.diagnostic['stock_native_reads'][-1]['raw']['length']==10


def test_native_exception_is_distinct_from_returned_false(native_stock,monkeypatch):
    original=cam._member
    def member(obj,name,*args):
        if name=='GetSTLOffset':raise RuntimeError('getter failed')
        return original(obj,name,*args)
    monkeypatch.setattr(cam,'_member',member)
    with pytest.raises(RuntimeError):native_stock.run()
    assert native_stock.diagnostic['stock_native_reads'][-1]==dict(method='GetSTLOffset',native_returned=False,raised_type='RuntimeError')


def test_diagnostic_is_bounded_nonrecursive_and_json_safe():
    opaque=object();value=[float('nan'),float('inf'),opaque,'x'*3000,[opaque],2**100]+[0]*50
    d=cam._bounded_read_value(value)
    assert d['length']==56 and len(d['items'])==16 and d['truncated']
    assert 'value' not in d['items'][0] and not d['items'][0]['finite']
    assert d['items'][2]==dict(python_type='object')
    assert len(d['items'][3]['value'])==2048 and d['items'][3]['truncated']
    assert d['items'][4]==dict(python_type='list')
    assert d['items'][5]['value_omitted']=='integer_exceeds_64_bits'
    json.dumps(d,allow_nan=False)


def test_failed_readonly_inspect_returns_diagnostics_without_setter(probe):
    def fail(*args,**kw):
        kw['diagnostic'].update(last_native_method='GetSTLOffset',stock_native_reads=[dict(method='GetSTLOffset',native_returned=True,raw=cam._bounded_read_value(False))])
        raise ValueError('strict parser stops')
    probe.snapshots.side_effect=fail
    result=probe.run(action='inspect')
    assert result['status']=='error' and result['failed_phase']=='before'
    assert result['snapshot_diagnostics'][0]['stock_native_reads'][0]['raw']['value'] is False
    assert not probe.state['writes'] and not result['mutation_attempted']


def test_stock_parser_preserves_units_frame_offsets_and_source_hash(native_stock):
    import hashlib
    native_stock.stock.GetWorkpieceFromSTLParam = lambda: (str(native_stock.source), 1, 'fixture_frame', True)
    native_stock.knobs['raw'] = (1., -2., 3., -4., 5., -6., True, False, True, True)
    state, _ = native_stock.run()
    assert state['stock'] == dict(
        type_raw=4, bounds_native=[-1., -1., -1., 1., 1., 1.],
        stl_path=str(native_stock.source), length_units_raw=1,
        coordinate_system='fixture_frame', offsets_native=[1., -2., 3., -4., 5., -6.],
        uniform_flags=[True, False, True],
        stl_sha256=hashlib.sha256(b'fixture').hexdigest(),
    )
