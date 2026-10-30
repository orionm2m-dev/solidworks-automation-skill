"""Synthetic direct-contour failure classification; no CAD or COM dispatch."""
from copy import deepcopy
from types import SimpleNamespace as N
import pytest
from test_sw_cam_mill_inventory import native,probe
from test_sw_cam_mill_inventory_recovery import recovery
from test_mcp_cam_mill_inventory import probe as schema_probe,MODEL,TOOL
from scripts import sw_cam_mill_inventory as cam

class COMError(Exception):
    def __init__(self,hresult=-2147467259):
        self.hresult=hresult
        super().__init__('synthetic native failure')

def install(native,*,method='IGetTopSegChain',hresult=-2147467259):
    calls=[]
    def fail():
        calls.append(method);raise COMError(hresult)
    setattr(native.features[0],method,fail)
    def decoder(raw,**kw):
        row=dict(native_id=raw.id,volume_type=11,subtype_raw=1,shape_raw=2,
            bounds_native=[-9999000.,-9999000.,13.7],depth_native=13.7,
            physical_depth_verified=False,contours={},islands={})
        kw['diagnostic'].update(state=row,capture_complete=False,stage=method)
        if raw.id==101:kw['read'](raw,method)
        kw['diagnostic']['capture_complete']=True
        return row
    native.decoder.side_effect=decoder
    return calls

def run(native,**kw):
    check=kw.pop('check',lambda:None)
    return cam.capture_mill_inventory(native.sw,'clsid','tlb','C:/part.sldprt',
        check=check,diagnostic=native.diagnostic,**kw)

def test_direct_contour_failure_stops_by_default(native):
    calls=install(native)
    with pytest.raises(COMError):run(native)
    assert calls==['IGetTopSegChain'] and native.decoder.call_count==1

@pytest.mark.parametrize('method',['IGetTopSegChain','IGetBottomSegChain','IGetWallSegChain'])
def test_explicit_contour_diagnostic_records_native_origin_and_preserves_raw_sentinel(native,method):
    calls=install(native,method=method)
    out=run(native,diagnostic_contour_errors=True)
    assert calls==[method] and len(out['features'])==2
    first=out['features'][0]['geometry']
    assert first['bounds_native']==[-9999000.,-9999000.,13.7]
    assert first['physical_depth_verified'] is False
    error=out['feature_errors'][0]
    assert error['stage']==method and error['category']=='native_contour_getter_E_FAIL'
    diag=native.diagnostic['features'][0]
    assert diag['known_contour_error_continued'] is True
    assert diag['native_failure_origin']['method']==method
    assert diag['bounds_physical_verified'] is False
    assert native.diagnostic['capture_complete'] is False

@pytest.mark.parametrize('hresult',[-2147418111,-2147417848,-2147023174,-2147467262,-2147352573,0])
def test_rpc_unexpected_interface_and_other_hresult_never_continued(native,hresult):
    install(native,hresult=hresult)
    with pytest.raises(COMError):run(native,diagnostic_contour_errors=True)
    assert native.decoder.call_count==1

def test_e_fail_other_getter_never_continued(native):
    install(native,method='GetDepth')
    with pytest.raises(COMError):run(native,diagnostic_contour_errors=True)
    assert native.decoder.call_count==1

def test_guard_e_fail_before_getter_is_not_mistaken_for_contour_failure(native):
    calls=install(native)
    def guard():
        if native.diagnostic.get('features') and native.diagnostic['features'][-1].get('stage')=='IGetTopSegChain':
            raise COMError()
    with pytest.raises(COMError):run(native,diagnostic_contour_errors=True,check=guard)
    assert calls==[] and 'last_native_failure' not in native.diagnostic

def test_guard_e_fail_after_successful_getter_is_not_native_contour_error(native):
    install(native);returned=[]
    def getter():returned.append(True);return object()
    native.features[0].IGetTopSegChain=getter
    def guard():
        if returned:raise COMError()
    with pytest.raises(COMError):run(native,diagnostic_contour_errors=True,check=guard)
    assert returned==[True] and 'last_native_failure' not in native.diagnostic

@pytest.mark.parametrize('key,value',[('volume_type',None),('subtype_raw',True),('shape_raw','2'),('native_id',True)])
def test_contour_skip_requires_captured_typed_metadata(native,key,value):
    install(native);original=native.decoder.side_effect
    def decoder(raw,**kw):
        try:return original(raw,**kw)
        except COMError:
            kw['diagnostic']['state'][key]=value
            raise
    native.decoder.side_effect=decoder
    with pytest.raises(COMError):run(native,diagnostic_contour_errors=True)

def test_diagnostic_contour_flag_does_not_enable_island_skip(native,monkeypatch):
    from test_sw_cam_inventory_diagnostics import partial_error,KnownError
    partial_error(native,monkeypatch)
    with pytest.raises(KnownError):run(native,diagnostic_contour_errors=True)

def test_contour_diagnostics_cannot_feed_operation_reader(native):
    with pytest.raises(ValueError,match='operation reader'):
        run(native,diagnostic_contour_errors=True,operation_reader=lambda *a:None)

def test_partial_contour_diagnostics_never_promote_recovery(recovery):
    recovery.probe.state['feature_errors']=[dict(feature_native_id=64,category='native_contour_getter_E_FAIL')]
    recovery.proof.summary.return_value={'saved_process_rebind_required':True}
    out=recovery.run(allow_saved_process_rebind=True,batched_identity_checks=True,diagnostic_contour_errors=True)
    assert len(recovery.probe.calls)==2 and out['diagnostic_enumeration_complete'] is True
    recovery.proof.verify_inventory.assert_not_called()
    assert out['status']=='error'
    assert not any(out[x] for x in ('readback_verified','inventory_read_complete','recovery_delta_verified',
        'saved_process_rebind_verified','may_continue','mutation_attempted'))

@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_public_flag_is_strict(probe,value):
    out=probe.run(diagnostic_contour_errors=value)
    assert out['status']=='error' and not probe.calls

def test_schema_default_and_explicit_forwarding(schema_probe):
    assert MODEL(**schema_probe.data).diagnostic_contour_errors is False
    model=MODEL(**(schema_probe.data|{'diagnostic_contour_errors':True}))
    schema_probe.ns[TOOL](model)
    assert schema_probe.core.call_args.kwargs['diagnostic_contour_errors'] is True

@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_schema_rejects_coerced_flag(schema_probe,value):
    with pytest.raises(ValueError):MODEL(**(schema_probe.data|{'diagnostic_contour_errors':value}))
