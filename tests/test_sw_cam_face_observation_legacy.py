"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import importlib.util,json,sys,types
import pytest
from scripts import sw_cam_raw_mill_face_observation as m


@pytest.mark.parametrize('value,kind',[(True,'int'),(1,'bool'),(1,'float'),(float('nan'),'float'),(float('inf'),'float'),((False,1.0),'pair'),((1.0,1),'pair'),((1,False),'pair'),((1.0,False,1),'pair'),(None,'pair')])
def test_wrong_native_type_fails(value,kind):
    with pytest.raises(ValueError):m.decode(value,kind)

def test_percentage_output_order():
    assert m.decode((3.2,False),'pair')==dict(raw=[3.2,False],value=3.2,percentage=False,output_order='DOUBLE,VARIANT_BOOL')

class Pointer:
    def __bool__(self):return True

def calls(monkeypatch,nc='nonnull',bad=None):
    op,feature,native_nc=Pointer(),Pointer(),Pointer()
    log=[];snap=[];report={}
    monkeypatch.setattr(m,'_is_comtypes_pointer',lambda value:isinstance(value,Pointer))
    def typed(obj,name):
        assert obj in (op,feature,native_nc);log.append(('qi',name));return (obj,name)
    def dispatch(obj):assert obj==(feature,'ICWFeature');return feature
    def read(obj,name,*args):
        log.append((obj[1],name,args))
        if bad==name:return (False,3.2)
        if name in m.FEATURE_PAIRS or name in m.FEATURE_INTS or name in ('GetMachiningDepth','GetOverrideMachiningDepth'):
            assert args==(feature,)
        else:assert args==()
        if name in m.PROPERTIES:kind=m.PROPERTIES[name]
        elif name in m.SCALARS:kind=m.SCALARS[name]
        elif name in m.PAIRS+m.FEATURE_PAIRS:return (3.2,False)
        elif name in m.FEATURE_INTS:kind='int'
        elif name=='GetMachiningDepth':kind='float'
        elif name=='GetOverrideMachiningDepth':kind='bool'
        elif name=='IGetNCParam':return native_nc if nc=='nonnull' else (None if nc=='null' else 0)
        else:kind=dict(m.NC_FIELDS,XYFeed='float')[name]
        return {'int':0,'float':2.0,'bool':False}[kind]
    def persist():snap.append(deepcopy(report))
    return op,feature,read,typed,dispatch,report,persist,log,snap

@pytest.mark.parametrize('nc',['nonnull','null'])
def test_documented_getters_use_real_feature_and_optional_nc(monkeypatch,nc):
    op,feature,read,typed,dispatch,report,persist,log,snap=calls(monkeypatch,nc)
    m.read_parameters(op,feature,read=read,typed=typed,feature_dispatch=dispatch,report=report,persist=persist)
    assert all(v['read_complete'] for v in report['face_parameters'].values())
    assert report['face_parameters']['GetMachiningDepth']['raw']==2.0
    assert report['nc_parameters']['available'] is (nc=='nonnull')
    assert not any(item[1] in ('GetClrPlanePrms','GetRpdPlnPrms','SetTool','GenerateToolpath') for item in log)
    assert any(not v['read_complete'] for snapshot in snap for v in snapshot.get('face_parameters',{}).values())
    if nc=='nonnull':assert report['nc_parameters']['fields']['XYFeed']['raw']==2.0

def test_partial_raw_kept_before_decode_failure(monkeypatch):
    op,feature,read,typed,dispatch,report,persist,log,snap=calls(monkeypatch,bad='GetMaxStepOver')
    with pytest.raises(ValueError):m.read_parameters(op,feature,read=read,typed=typed,feature_dispatch=dispatch,report=report,persist=persist)
    assert report['face_parameters']['GetMaxStepOver']['raw']==[False,3.2]
    assert report['face_parameters']['GetMaxStepOver']['read_complete'] is False
    assert snap[-1]['face_parameters']['GetMaxStepOver']['raw']==[False,3.2]
    assert 'GetMinSideOffset' not in report['face_parameters']

def test_scalar_nc_is_not_null(monkeypatch):
    op,feature,read,typed,dispatch,report,persist,log,snap=calls(monkeypatch,nc='scalar')
    with pytest.raises(ValueError,match='real native pointer'):m.read_parameters(op,feature,read=read,typed=typed,feature_dispatch=dispatch,report=report,persist=persist)

def request(tmp_path):
    return dict(action='inspect_new_face_parameters',params=dict(recovery_receipt_path=str(tmp_path/'creator.json'),recovery_receipt_sha256='a'*64,
      process_id=23824,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='b'*64,
      expected_operation_native_id=266,expected_feature_native_id=265,receipt_path=str(tmp_path/'observation.json'),
      addin_clsid='{CCAC6208-0E19-6455-2022-2026CEB541FA}',module_sha256=m._self_pin()['sha256']))

def test_exact_readonly_request(tmp_path):assert m.validate_request(request(tmp_path))['process_id']==23824

@pytest.mark.parametrize('key,value',[('process_id',True),('expected_operation_native_id',False),('expected_feature_native_id',0),('module_sha256','a'*64),('addin_clsid','random')])
def test_invalid_identity_rejected(tmp_path,key,value):
    r=request(tmp_path);r['params'][key]=value
    with pytest.raises(ValueError):m.validate_request(r)

def test_no_mutation_parameter(tmp_path):
    r=request(tmp_path);r['params']['assign_tool']=249
    with pytest.raises(ValueError):m.validate_request(r)

def test_read_scope_forbids_mutators_pointer_getters_and_old_route_enumeration():
    assert not m.READ_MEMBERS.intersection({'SetTool','GenerateToolpath','InsertOperation','Save','GetClrPlanePrms','GetRpdPlnPrms','IGetEnumOpSetups','IGetEnumOperations','IGetToolcrib','GetAllTools'})

def test_existing_output_preserved(tmp_path):
    out=tmp_path/'observation.json';out.write_text('previous evidence')
    with pytest.raises(ValueError):m.inspect_face_parameters(None,None,None,loaded={'pins':[],'full_creator_proof_verified':True},
      process_id=23824,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='a'*64,
      expected_operation_native_id=266,expected_feature_native_id=265,receipt_path=str(out))
    assert out.read_text()=='previous evidence'

def test_invalid_parent_stops_before_native_connection(tmp_path,monkeypatch):
    def fail(*a,**kw):raise ValueError('no completed parent')
    monkeypatch.setattr(m,'load_recovered_face_checkpoint',fail)
    with pytest.raises(ValueError,match='no completed parent'):m.dispatch_request(request(tmp_path))


def test_actual_collection_helper_signature_and_bound():
    rows=[object()]
    def typed(raw,name):assert raw is rows and name=='ICWDispatchCollection';return rows
    def read(raw,name,*args):
        assert raw is rows
        return len(rows) if name=='Count' else rows[args[0]]
    assert m._items(rows,typed,read,2)==rows
    rows.extend([object(),object()])
    with pytest.raises(ValueError):m._items(rows,typed,read,2)



def test_read_scope_pins_transitive_file_guard():
    assert 'sw_cam_mill_feature_context.py' in m.RUNTIME_NAMES
    assert 'sw_cam_comtypes.py' in m.RUNTIME_NAMES and 'sw_cam_circle_lifecycle_evidence.py' in m.RUNTIME_NAMES

def test_only_completed_recovery_loader_is_accepted(monkeypatch,tmp_path):
    seen=[]
    def load(path,digest,**args):seen.append((path,digest,args));raise ValueError('not completed')
    from scripts import sw_cam_raw_mill_face_operation_append_recovery as recovery
    monkeypatch.setattr(recovery,'load_completed_face_operation_recovery',load)
    with pytest.raises(ValueError,match='not completed'):m.load_recovered_face_checkpoint(str(tmp_path/'pending.json'),'a'*64,
      process_id=23824,expected_document_path=str(tmp_path/'part.sldprt'),expected_source_sha256='b'*64,expected_operation_native_id=266,expected_feature_native_id=265)
    assert len(seen)==1 and seen[0][2]['expected_operation_native_id']==266
