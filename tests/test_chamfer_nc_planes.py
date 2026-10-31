"""Narrow NC/lead reader tests through the actual retained read guard."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as Node
import os
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT', STAGE))
sys.path.insert(0,str(ROOT))
import scripts
scripts.__path__.insert(0,str(STAGE/'scripts'))
from scripts import sw_cam_chamfer_nc_planes as m


def collection(values):
    return Node(Count=len(values),Item=lambda index:values[index])


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'saved')
    proof=tmp_path/'proof.json';proof.write_text('{}')
    ident=dict(path=str(source),title=source.name,type=1,needs_save=False)
    model=Node(GetPathName=lambda:ident['path'],GetTitle=lambda:ident['title'],
               GetType=lambda:ident['type'],GetSaveFlag=lambda:ident['needs_save'])
    sw=Node(GetProcessID=lambda:123,ActiveDoc=model)
    feature=Node(ident=264,Suppressed=False)
    tool=Node(ident=269,IsMillTool=True,ToolType=8,CutDiameter=.6,Protrusion=20.)
    nc=Node(FeedPlaneType=2,FeedPlaneDistance=1.,GetUseCurrentMachiningDepthForFeedPlane=False,
            GetClrPlaneUseSetupStatus=True)
    paths=collection([Node(RecordCount=22)])
    lead=Node(**{n:(4 if kind=='int' else False if kind=='bool' else 0. if kind=='number'
                else (1.,False,0.) if kind=='number_bool_number' else (2.,False))
               for n,kind in m.leads.LEAD_FIELDS.items()})
    mill=Node(ident=271,OpernType=1,IGetNCParam=lambda:nc,
              IGetLeadin=lambda f:lead,IGetLeadout=lambda f:lead)
    op=Node(ident=271,OpernType=0,Suppressed=False,GetIsToolpathGenerated=True,
            IGetAllFeatures=lambda:collection([feature]),IGetTool=lambda:tool,IGetEnumToolpaths=lambda:paths)
    doc=Node(GetDocType=lambda:1,GetCWObjectID=lambda obj:(obj.ident,True),
             GetCWObjectFromID=lambda kind,ident:({(3,271):op,(1,264):feature}[(kind,ident)],True))
    def typed(obj,name,*unused):
        if obj is op and name in ('ICWMillOperation','ICWFinishMillOp'):return mill
        return obj
    monkeypatch.setattr(m,'query_interface',typed)
    expected=dict(native_id=271,linked_feature_ids=[264],mill_operation_type=1,base_operation_type=0,
        suppressed=False,toolpath_generated=True,toolpath_record_counts=[22],
        assigned_tool=dict(native_id=269,is_mill_tool=True,native_read_complete=True,
            units_verified=False,holder_geometry_verified=False,tool_type_raw=8,
            cut_diameter_native=.6,protrusion_native=20.))
    rows=[]
    for oid in m.parent.PREFIX+[271]:
        count={267:760,247:191,248:74,271:22}.get(oid)
        rows.append(dict(native_id=oid,suppressed=False,toolpath_generated=count is not None,
                         toolpath_record_counts=[] if count is None else [count]))
    rows[-1].update(expected,setup_native_id=93,setup_index=0,operation_index=7)
    loaded=dict(configured_contour=dict(native_id=271,feature_native_id=264,tool_native_id=269,
        generated=True,operation_type=1,record_counts=[22]),local_tool_candidate=dict(native_id=269),
        state=dict(features=[{}]*21,operation_count=8,operations=rows,document=ident))
    def batch(**overrides):
        args=dict(process_id=123,expected_document=deepcopy(ident),source_sha256=m._file_hash(source),
            evidence_pins=[m.common._pin(proof)],verify_evidence=lambda:None,verify_owned_process=lambda:None,
            check_events=lambda:None,retained_objects=(doc,),verify_retained_binding=lambda:None,
            max_native_calls=m.MAX_CALLS,generated_pin={})
        args.update(overrides)
        return m.PlaneReadBatch(sw,'unused',**args)
    return Node(source=source,proof=proof,ident=ident,doc=doc,op=op,mill=mill,feature=feature,
                tool=tool,nc=nc,paths=paths,lead=lead,loaded=loaded,batch=batch,typed=typed)


def test_full_single_batch_reads_exact_fields_and_leads(case):
    b=case.batch();diagnostic={}
    with b:
        before,handles=m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)
        planes=m.read_planes(handles['operation'],read=b.read,typed=b.typed,diagnostic=diagnostic)
        leads=m.leads.read_lead_details(handles['operation'],handles['feature_dispatch'],
            read=b.read,typed=b.typed,lead_typed=lambda obj:b.typed(obj,'ICWLeadInOut'))
        after,_=m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)
    assert b.require_complete() and before==after
    assert [v['member'] for v in diagnostic['fields']]==[v[1] for v in m.FIELDS]
    assert planes['values']['GetUseCurrentMachiningDepthForFeedPlane'] is False
    assert set(leads)=={'lead_in','lead_out'}
    assert leads['lead_in']['GetFeedRate']['decoded']=={'value_raw':2.,'percent':False}
    assert b.summary()['getter_calls']+b.summary()['query_interface_calls']<m.MAX_CALLS
    assert planes['model_updated'] is planes['pointer_plane_getters_called'] is False


@pytest.mark.parametrize('field,value', [('FeedPlaneType',True),('FeedPlaneType',2**31),
    ('FeedPlaneDistance',1),('FeedPlaneDistance',float('nan')),
    ('GetUseCurrentMachiningDepthForFeedPlane',1),('GetClrPlaneUseSetupStatus',0)])
def test_strict_scalar_rejection(case,field,value):
    setattr(case.nc,field,value);b=case.batch();diag={}
    with pytest.raises(ValueError):
        with b:
            _,h=m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)
            m.read_planes(h['operation'],read=b.read,typed=b.typed,diagnostic=diag)
    assert diag['complete'] is False
    with pytest.raises(ValueError):b.require_complete()


@pytest.mark.parametrize('change', ['tool','feature','count','generated','suppressed'])
def test_target_drift_stops_before_plane_fields(case,change):
    if change=='tool':case.tool.ident=270
    elif change=='feature':case.feature.ident=265
    elif change=='count':case.paths.Item=lambda i:Node(RecordCount=23)
    elif change=='generated':case.op.GetIsToolpathGenerated=False
    else:case.op.Suppressed=True
    b=case.batch()
    with pytest.raises(ValueError):
        with b:m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)
    assert b.summary()['read_scope_complete'] is False


def test_after_binding_detects_drift(case):
    b=case.batch()
    with pytest.raises(ValueError):
        with b:
            _,h=m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)
            m.read_planes(h['operation'],read=b.read,typed=b.typed,diagnostic={})
            case.op.GetIsToolpathGenerated=False
            m.read_target(case.doc,case.loaded,read=b.read,typed=b.typed)


@pytest.mark.parametrize('member',['Save','GenerateToolpath','FeedPlaneDistance_set','GetRpdPlnPrms'])
def test_mutation_and_unqualified_pointer_members_rejected(case,member):
    b=case.batch()
    with pytest.raises(ValueError):
        with b:b.read(case.doc,member)
    assert b.summary()['getter_calls']==0


def test_budget_and_unretained_owner_fail(case):
    b=case.batch(max_native_calls=1)
    with pytest.raises(ValueError):
        with b:
            b.read(case.doc,'GetDocType');b.read(case.doc,'GetDocType')
    b=case.batch()
    with pytest.raises(ValueError):
        with b:b.read(Node(GetDocType=1),'GetDocType')


@pytest.mark.parametrize('drift',['file','dirty','event'])
def test_exit_guard_rejects_drift(case,drift):
    called=[False]
    def events():
        if called[0]:raise RuntimeError('event')
    b=case.batch(check_events=events)
    with pytest.raises((ValueError,RuntimeError)):
        with b:
            b.read(case.doc,'GetDocType')
            if drift=='file':case.proof.write_text('changed')
            elif drift=='dirty':case.ident['needs_save']=True
            else:called[0]=True
    with pytest.raises(ValueError):b.require_complete()


def test_read_exception_preserves_completed_prefix_without_retry(case):
    calls=[]
    def read(obj,name,*args):
        calls.append(name)
        if name=='FeedPlaneDistance':raise RuntimeError('failed read')
        return m._member(obj,name,*args)
    diag={}
    with pytest.raises(RuntimeError):m.read_planes(case.op,read=read,typed=case.typed,diagnostic=diag)
    assert calls==['IGetNCParam','FeedPlaneType','FeedPlaneDistance']
    assert diag['fields'][0]['validated'] is True
    assert diag['fields'][1]['returned'] is False


def test_generated_registry_not_extended_by_module():
    from scripts.sw_cam_comtypes import _INTERFACES
    assert 'ICWNCParam3' not in _INTERFACES and 'ICWNCParam4' not in _INTERFACES
    assert m.EXTENSION_IIDS['ICWNCParam3']=='{32880B43-2E9A-4143-9C71-8053A1336CA5}'


@pytest.mark.parametrize('failure',[None,'observe','finish','close'])
def test_run_persists_success_or_failure_without_mutation(tmp_path,monkeypatch,failure):
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'saved')
    receipt=tmp_path/'result.json'
    identity=dict(path=str(source),title=source.name,type=1,needs_save=False)
    loaded=dict(configured_contour=dict(native_id=271,feature_native_id=264,tool_native_id=269),
        ownership={'process_id':123,'create_time':10.},parent_pin={'path':'parent','sha256':'a'*64},
        pins=[],offline_export_proof_pins=[],bootstrap_export_pins=[],state={'document':identity})
    args=dict(receipt_path=str(receipt),process_id=123,expected_document_path=str(source),
              expected_source_sha256=m._file_hash(source))
    order=[]
    class Backend:
        def __init__(self,*a):self.ctx=Node(identity=lambda:deepcopy(identity));self.report=a[-2]
        def start(self):order.append('start')
        def observe(self):
            order.append('observe')
            self.report['plane_diagnostic']={'complete':failure!='observe'}
            if failure=='observe':raise RuntimeError('read failed')
        def finish(self):
            order.append('finish')
            if failure=='finish':raise RuntimeError('disconnect failed')
        def close(self):
            order.append('close')
            if failure=='close':raise RuntimeError('cleanup failed')
    monkeypatch.setattr(m,'NativeBackend',Backend)
    r=m.run(None,'clsid','tlb',loaded=loaded,args=args,audit={'all_resolved':True})
    assert r['readback_verified'] is (failure is None)
    assert r['status']==('observed' if failure is None else 'error')
    assert r['mutation_attempted'] is r['save_attempted'] is r['GTP_attempted'] is False
    assert order[-1]=='close' and order.count('observe')==1
    import json
    assert json.loads(receipt.read_text())['readback_verified'] is (failure is None)
    assert source.read_bytes()==b'saved'


def test_no_runtime_or_unknown_field_request():
    with pytest.raises(ValueError):m.validate_request({'action':'save','params':{}})
    with pytest.raises(ValueError):m.validate_request({'action':'read_nc_planes_and_leads','params':{'method':'SetFeedPlane'}})
