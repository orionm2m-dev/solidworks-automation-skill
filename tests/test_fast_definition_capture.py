"""Complete existing payload parity with real guards over a synthetic graph."""
from copy import deepcopy
from pathlib import Path
import ast,hashlib,os,sys
import pytest
RT=Path(os.environ['SWMCP_RUNTIME_ROOT']);ROOT=Path(__file__).resolve().parents[1]
PRE=ROOT.parent/'prebound_inventory_candidate'
if not PRE.is_dir():PRE=RT
sys.path.insert(0,str(RT))
import scripts
scripts.__path__[:0]=[str(ROOT/'scripts'),str(PRE/'scripts')]
from scripts import sw_cam_pocket_definition_fast_v1 as m
from scripts import sw_cam_dispatch_guard as baseguard
from fast_definition_graph_fixture import Graph,Node

@pytest.fixture
def case(tmp_path,monkeypatch):
    # Local copies preserve exact source bytes without making offline guards depend on network metadata latency.
    for module in (m,m.prebound):
        copied=tmp_path/Path(module.__file__).name;copied.write_bytes(Path(module.__file__).read_bytes());monkeypatch.setattr(module,'__file__',str(copied))
    graph=Graph(True);sw=Node('sw');control=dict(fault=None,snapshots=0,events=True,pid=123,dirty=False,body=1.,profile=1,configuration='configuration')
    source=tmp_path/'part.SLDPRT';source.write_bytes(b'exact saved source')
    evidence=tmp_path/'proof.json';evidence.write_bytes(b'original evidence')
    def pin(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    snap=dict(path=str(source),needs_save=False,features=['plane','profile'],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[1.])])
    spec=dict(sketch_name='profile')
    header=dict(native_id=202,owner_setup_native_id=201,suppressed=False,axis_native=[0.,0.,-1.],volume_type=2,island_count=4,depth_native=13.2,taper_angle_native=0.)
    native_read=graph.read
    def read(obj,name,*args):
        fault=control['fault']
        if obj is sw and name=='GetProcessID':return control['pid']
        if name=='GetAddInObject':return Node('addin')
        if name=='GetCWApp':return graph.app
        if name=='FeatureByName':return Node('sketch_feature')
        if name=='GetTypeName2':return 'Boss'if fault=='sketch_type'else 'ProfileFeature'
        if name=='GetSpecificFeature2':return Node('sketch')
        if name=='GetOwner':return graph.setup
        if name=='IGetIslandCount':return 4
        if name=='Depth':return 99. if fault=='header'else 13.2
        if name=='IGetTaperAngle':return 0.
        if name=='GetActiveConfigurationName'and fault=='configuration':return 'other'
        if name=='GetCWObjectID'and fault=='owner'and args[0].role=='feature_setup':return 299,True
        value=native_read(obj,name,*args)
        if name=='RecordCount':
            if fault=='event_after_getter':control['events']=False
            if fault=='source_after_getter':source.write_bytes(b'changed saved source')
            if fault=='evidence_after_getter':evidence.write_bytes(b'changed evidence')
            if fault=='pid_after_getter':control['pid']=124
            if fault=='dirty_after_getter':control['dirty']=True
            if fault=='lifetime_after_getter':control['lifetime']=False
        return value
    graph.read=read
    def identity(*args):
        if control.get('lifetime')is False:raise ValueError('owner lifetime changed')
        actual=deepcopy(doc);actual['needs_save']=control['dirty']
        return dict(document=actual,saved_file_sha256=pin(source)['sha256'])
    def events():
        if not control['events']:raise ValueError('event changed')
    def snapshot(*args):
        control['snapshots']+=1;actual=deepcopy(snap)
        if control['fault']=='body_before'or control['fault']=='body_after'and control['snapshots']>=2:actual['solids'][0]['mass_raw']=[2.]
        if control['fault']=='tree_after'and control['snapshots']>=2:actual['features'].append('unexpected')
        return actual,Node('model'),[]
    def circle(*args):
        return {'radius':2}if control['fault']=='circle_after'and control['snapshots']>=2 else {'radius':1}
    monkeypatch.setattr(baseguard,'_member',read);monkeypatch.setattr(baseguard,'_typed',lambda obj,name,tlb:graph.typed(obj,name))
    monkeypatch.setattr(baseguard,'raw_part_identity',lambda sw:identity()['document'])
    monkeypatch.setattr(m,'_member',read);monkeypatch.setattr(m,'_typed',lambda obj,name,tlb:graph.typed(obj,name))
    monkeypatch.setattr(m.parent,'identity',identity);monkeypatch.setattr(m.parent,'verify_files',lambda context:events())
    monkeypatch.setattr(m.parent,'_snapshot',snapshot);monkeypatch.setattr(m.parent,'_read_sketch',circle)
    # Complete generic expected inventory uses the actual unchanged parent reader.
    generic=m.parent.inventory.capture_import_inventory(graph.app,None,graph,{},lambda d:None)
    request=dict(process_id=123,expected_document_path=str(source),expected_cam_configuration='configuration',expected_sw_configuration='Default',owner_setup_native_id=201,source_variant='saved_cam_caps')
    context=dict(request=request,creator=dict(feature_header=header,circle_readback={'radius':1},status='uncertain'),pins=[pin(Path(x))for x in (m.__file__,m.parent.__file__,m.prebound.__file__,m.prebound.parent.__file__,m.retained.__file__,source,evidence)],expected_source_sha256=pin(source)['sha256'],expected_inventory=dict(deepcopy(generic),sw_reference={},all_solid_body_count=1),current_sketch_baseline=snap,spec=spec,sketch={'sketch_readback':{'radius':1}},evidence={'sha256':'a'*64},save_pin={'sha256':'b'*64},origin_kind='recovery')
    def run(fast=True):
        graph.trace.clear();control['snapshots']=0;diagnostic={}
        try:result=(m.capture if fast else m.parent.capture)(sw,'fixed','none.tlb',context,events,diagnostic)
        except Exception as error:error.diagnostic=diagnostic;raise
        return result,diagnostic,deepcopy(graph.trace)
    return graph,control,context,run,sw,events,source,evidence

def test_complete_payload_matches_parent_and_cad_checked_both_boundaries(case):
    g,c,context,run,*_=case
    old,old_diag,old_trace=run(False);new,diag,new_trace=run()
    assert old[0]==new[0] and set(new[1])=={'app','doc','machine','selected_feature'}
    assert c['snapshots']==2 and diag['capture_complete']is True
    assert diag['retained_inventory']['read_scope_complete']is True
    assert diag['retained_inventory']['native_call_attempted']is False
    assert diag['native_parity_qualified']is False
    assert set(diag['timing_seconds'])=={'before_cad','bootstrap','inventory_and_header','after_cad'}
    # Exclude only bootstrap/global reads and fixed retained binding observations.
    skip_reads={'IGetActiveDoc','IGetMachine','GetDocType','MachType','GetActiveConfigurationName'}
    skip_qi={'ICWDoc3','ICWPartDoc','ICWMachine'}
    trim=lambda t:[r for r in t if not (r[0]=='read'and r[2]in skip_reads or r[0]=='qi'and r[2]in skip_qi)]
    assert trim(old_trace)==trim(new_trace)

@pytest.mark.parametrize('fault',['body_before','body_after','tree_after','circle_after','sketch_type','header','owner','configuration','event_after_getter','source_after_getter','evidence_after_getter','pid_after_getter','dirty_after_getter','lifetime_after_getter'])
def test_late_context_or_native_delta_never_returns_usable_capture(case,fault):
    _,c,_,run,*_=case;c['fault']=fault
    with pytest.raises((ValueError,AssertionError))as e:run()
    assert e.value.diagnostic['capture_complete']is False

@pytest.mark.parametrize('pin_index',[0,1,2,3,4])
def test_each_new_helper_dependency_is_mandatory_before_bootstrap(case,pin_index):
    g,_,context,run,*_=case;del context['pins'][pin_index]
    with pytest.raises(ValueError,match='dependency'):run()
    assert not g.trace

def test_old_full_capture_and_frozen_retained_adapter_not_modified():
    assert hashlib.sha256(Path(m.parent.__file__).read_bytes()).hexdigest()=='a95909bd7af800fb877d19257f39f92f7795213fe610b093782dbd71829ddc58'
    assert hashlib.sha256(Path(m.prebound.__file__).read_bytes()).hexdigest()=='87a30bc0e6fc1bc0cb3cf60683fc91a238d9eeb9abd54bcae4c9469ed2a7e48d'
    source=ast.parse(Path(m.__file__).read_text())
    assert not any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in ('dispatch_once','SaveActiveDocument','GenerateToolpath','SetSaveFlag')for n in ast.walk(source))


def make_batch(case,limit=20):
    g,control,c,run,sw,events,source,evidence=case
    doc=dict(path=str(source),title=source.name,type=1,needs_save=False)
    return m.InventoryReadBatch(sw,'none.tlb',process_id=123,expected_document=doc,source_sha256=c['expected_source_sha256'],evidence_pins=c['pins'],verify_evidence=lambda:None,verify_owned_process=lambda:None,check_events=events,evidence_pin_limit=128,retained_objects=(g.doc,g.machine),verify_retained_binding=lambda:None,max_native_calls=limit)

@pytest.mark.parametrize('member,args',[('IGetActiveDoc',()),('GenerateToolpath',()),('Item',(True,))])
def test_retained_graph_forbids_global_mutator_and_boolean_index(case,member,args):
    g,*_=case;batch=make_batch(case)
    with pytest.raises(ValueError):
        with batch:batch.read(g.doc,member,*args)
    with pytest.raises(ValueError):batch.require_complete()


def test_typed_child_is_retained_and_foreign_owner_rejected(case):
    g,*_=case;batch=make_batch(case)
    with batch:
        config=batch.typed(batch.read(g.doc,'GetActiveConfiguration'),'ICWConfiguration')
        assert batch.read(config,'ConfigurationName')=='configuration'
    assert batch.require_complete()and batch.summary()['query_interface_calls']==1
    other=make_batch(case)
    with pytest.raises(ValueError,match='owner'):
        with other:other.read(Node('doc'),'GetDocType')
    with pytest.raises(ValueError):other.require_complete()


def test_read_budget_is_shared_by_getters_and_interfaces(case):
    g,*_=case;batch=make_batch(case,2)
    with pytest.raises(ValueError,match='budget'):
        with batch:
            config=batch.typed(batch.read(g.doc,'GetActiveConfiguration'),'ICWConfiguration')
            batch.read(config,'ConfigurationName')
    with pytest.raises(ValueError):batch.require_complete()
