from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import importlib.util,sys,os
import pytest

R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(R))
spec=importlib.util.spec_from_file_location('deep_fields_under_test',Path(__file__).resolve().parents[1]/'scripts/sw_cam_deep_guide_fields.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def rows():
    return [dict(operation_native_id=oid,feature_native_id=fid,operation_type=kind)
        for oid,(fid,kind) in zip((330,336,342,348),m.PAIRS)]


def test_learned_ids_are_dynamic_not_arithmetic():
    data=rows();data[0]['operation_native_id']=900;data[3]['operation_native_id']=501
    assert [x[0] for x in m.learned_targets(data)]==[900,336,342,501]
    assert len(m.select_fields(data[0],data))==len(m.fast.config.ROUGH_FIELDS)
    assert len(m.select_fields(data[1],data))==len(m.fast.config.FINISH_FIELDS)


@pytest.mark.parametrize('damage',['few','many','tuple','duplicate','protected','boolid','boolfeature','boolkind','zero','negative','huge','missing','wrongfeature','wrongkind','reordered'])
def test_bad_learned_mapping_rejected(damage):
    data=rows()
    if damage=='few':data.pop()
    elif damage=='many':data.append(deepcopy(data[-1]))
    elif damage=='tuple':data=tuple(data)
    elif damage=='duplicate':data[3]['operation_native_id']=data[0]['operation_native_id']
    elif damage=='protected':data[0]['operation_native_id']=322
    elif damage=='boolid':data[0]['operation_native_id']=True
    elif damage=='boolfeature':data[0]['feature_native_id']=True
    elif damage=='boolkind':data[0]['operation_type']=False
    elif damage=='zero':data[0]['operation_native_id']=0
    elif damage=='negative':data[0]['operation_native_id']=-1
    elif damage=='huge':data[0]['operation_native_id']=2**31
    elif damage=='missing':del data[0]['operation_native_id']
    elif damage=='wrongfeature':data[0]['feature_native_id']=82
    elif damage=='wrongkind':data[0]['operation_type']=2
    elif damage=='reordered':data.reverse()
    with pytest.raises(ValueError):m.learned_targets(data)


@pytest.mark.parametrize('target',[None,{},dict(operation_native_id=330,feature_native_id=81,operation_type=0),
    dict(operation_native_id=999,feature_native_id=80,operation_type=0),dict(operation_native_id=330,feature_native_id=80,operation_type=False)])
def test_unknown_target_rejected(target):
    with pytest.raises(ValueError):m.select_fields(target,rows())


@pytest.mark.parametrize('names',[[],(),['unknown'],['side_allowance','side_allowance'],[True],['SetTool'],['start_z']])
def test_field_whitelist_rejected(names):
    data=rows()
    with pytest.raises(ValueError):m.select_fields(data[0],data,names)


def test_requested_order_is_preserved():
    data=rows();selected=m.select_fields(data[0],data,['side_allowance','first_depth'])
    assert [v[0]for v in selected]==['side_allowance','first_depth']


class FakeBatch:
    def __init__(self):self.calls=[];self.complete=False;self.values={};self.failure=None
    def __enter__(self):self.calls.append(('enter',));return self
    def __exit__(self,*args):self.calls.append(('exit',))
    def typed(self,obj,name):self.calls.append(('typed',obj,name));return name
    def read(self,obj,name,*args):
        self.calls.append(('read',obj,name,args))
        if name in ('IGetLeadin','IGetLeadout'):return name
        return self.values.get(name,1.)
    def require_complete(self):
        if self.failure:raise ValueError(self.failure)
        self.complete=True
    def summary(self):return dict(complete=self.complete,calls=len(self.calls))


@pytest.fixture
def fake(monkeypatch):
    batch=FakeBatch();target_calls=[];doc=object()
    backend=SimpleNamespace(doc=doc,loaded={'configuration_tool':{'native_id':273,'cut_diameter_native':2.}})
    monkeypatch.setattr(m.fast,'make_configuration_check',lambda *a:lambda:None)
    monkeypatch.setattr(m.fast,'make_batch',lambda *a:batch)
    def target_binding(doc,target,batch,wanted):
        target_calls.append(deepcopy(target))
        return dict(native_id=target['operation_native_id'],feature=target['feature_native_id'],generated=False), 'raw','feature'
    monkeypatch.setattr(m.fast,'target_binding',target_binding)
    return backend,batch,target_calls


def test_narrow_scalar_reads_only_requested_fields(fake):
    backend,batch,calls=fake;data=rows();batch.values['GetStartDepth']=(False,.3)
    out=m.read_field_values(backend,data[0],targets=data,field_names=['first_depth','side_allowance'])
    assert out['field_values']=={'first_depth':[False,.3],'side_allowance':1.}
    assert out['read_complete'] is True and batch.complete and len(calls)==2
    reads=[x[2]for x in batch.calls if x[0]=='read']
    assert reads==['GetStartDepth','SideAllow']
    assert out['learned_targets']==data


def test_feature_and_lead_owners_preserved(fake):
    backend,batch,_=fake;data=rows()
    out=m.read_field_values(backend,data[1],targets=data,field_names=['previous_allowance','lead_in_angle','lead_out_angle'])
    assert out['read_complete']
    reads=[x for x in batch.calls if x[0]=='read']
    assert ('read','ICWFinishMillOp2','GetPreviousAllowance',('feature',))in reads
    assert ('read','ICWFinishMillOp','IGetLeadin',('feature',))in reads
    assert ('read','ICWFinishMillOp','IGetLeadout',('feature',))in reads
    assert len([x for x in batch.calls if x==('typed','raw','ICWFinishMillOp')])==1


@pytest.mark.parametrize('damage',['none_doc','wrongtool','booltool','wrongdiameter','booldiameter','nonemptydiagnostic'])
def test_invalid_context_fails_before_native_read(fake,damage):
    backend,batch,_=fake;data=rows();diag={}
    if damage=='none_doc':backend.doc=None
    elif damage=='wrongtool':backend.loaded['configuration_tool']['native_id']=145
    elif damage=='booltool':backend.loaded['configuration_tool']['native_id']=True
    elif damage=='wrongdiameter':backend.loaded['configuration_tool']['cut_diameter_native']=1.9
    elif damage=='booldiameter':backend.loaded['configuration_tool']['cut_diameter_native']=True
    elif damage=='nonemptydiagnostic':diag={'old':True}
    with pytest.raises(ValueError):m.read_field_values(backend,data[0],targets=data,field_names=['side_allowance'],diagnostic=diag)
    assert batch.calls==[]


def test_target_binding_drift_rejects_incomplete_result(fake,monkeypatch):
    backend,batch,_=fake;data=rows();diag={};values=iter(({'generated':False},{'generated':True}))
    monkeypatch.setattr(m.fast,'target_binding',lambda *a:(next(values),'raw','feature'))
    with pytest.raises(ValueError):m.read_field_values(backend,data[0],targets=data,field_names=['side_allowance'],diagnostic=diag)
    assert diag['read_complete'] is False and not batch.complete and 'read_batch'in diag


@pytest.mark.parametrize('value',[float('nan'),float('inf'),'1.0',object(),[1,2,3,4,5]])
def test_invalid_native_values_rejected(fake,value):
    backend,batch,_=fake;data=rows();batch.values['SideAllow']=value;diag={}
    with pytest.raises(ValueError):m.read_field_values(backend,data[0],targets=data,field_names=['side_allowance'],diagnostic=diag)
    assert diag['read_complete'] is False


def test_batch_completion_failure_is_not_success(fake):
    backend,batch,_=fake;data=rows();batch.failure='ownership changed';diag={}
    with pytest.raises(ValueError):m.read_field_values(backend,data[0],targets=data,field_names=['side_allowance'],diagnostic=diag)
    assert diag['read_complete'] is False and not batch.complete


@pytest.fixture
def parameters_fake(monkeypatch):
    data=rows()
    for r in data:r['assigned_tool']={'native_id':273,'cut_diameter_native':2.}
    calls=[]
    class ParamBatch:
        def read(self,obj,name,*args):
            calls.append(name)
            if name=='IGetEnumOpSetups':return ['setup']
            if name=='GetCWObjectFromID':return ({'fid':args[1]},True)
            return name
        def typed(self,obj,name):return obj
        def feature_dispatch(self,obj):return obj
        metadata=staticmethod(lambda *a:None)
        plane=staticmethod(lambda *a:None)
    batch=ParamBatch();rd=m.fast.reader
    monkeypatch.setattr(m,'_items',lambda value,*a:value)
    monkeypatch.setattr(m,'_object_id',lambda doc,obj,read:obj['fid'] if type(obj)is dict else 93)
    monkeypatch.setattr(rd.pocket,'read_levels',lambda *a,**kw:{'top':10.9,'depth':4.4,'floor':6.5})
    monkeypatch.setattr(rd.pocket.rough,'read_rough_entry_parameters',lambda *a,**kw:{'rough':'actual'})
    monkeypatch.setattr(rd.guide.start,'read_startpoints',lambda *a,**kw:{'point':'actual'})
    monkeypatch.setattr(rd.pocket,'read_finish_parameters',lambda *a,**kw:{'finish':'actual'})
    monkeypatch.setattr(rd.fields,'read_cached_fields',lambda *a,**kw:{'side_allowance':0.})
    monkeypatch.setattr(rd.protected,'read_protected',lambda *a,**kw:{'protected':'actual'})
    monkeypatch.setattr(rd.pocket.leads,'read_lead_details',lambda *a,**kw:{'lead':'actual'})
    monkeypatch.setattr(rd.pocket,'read_nc_settings',lambda *a,**kw:{'GetCNCComp':0,'GetTlpComp':1})
    monkeypatch.setattr(rd,'read_generic_tool',lambda *a:({'native_id':273,'cut_diameter_native':2.},'tool'))
    monkeypatch.setattr(rd,'read_tool_dimensions',lambda *a:{'generic':{'native_id':273,'cut_diameter_native':2.},'dimension_read_complete':True})
    return data,batch,calls


@pytest.mark.parametrize('indices',[[0],[1],[2],[3],[0,1,2,3]])
def test_own_post_tool_parameters_without_four_target_rescan(parameters_fake,indices):
    data,batch,calls=parameters_fake;chosen=[data[i]for i in indices];report={}
    handles={r['operation_native_id']:'raw'for r in chosen}
    m.read_parameter_groups('doc',handles,chosen,batch,report,lambda:None,learned=data)
    assert len(report['parameters'])==len(indices)
    assert report['unique_tool_dimension_reads']==1
    assert calls.count('GetCWObjectFromID')==len(indices)
    for result in report['parameters']:
        assert result['read_complete'] is True and result['levels']['depth']==4.4
        assert result['nc']=={'GetCNCComp':0,'GetTlpComp':1}
        assert result['tool']['generic']['native_id']==273
        original=next(r for r in chosen if r['operation_native_id']==result['operation_native_id'])
        assert ('startpoints'in result)==(original['operation_type']==0)
        assert ('leads'in result)==(original['operation_type']==1)


@pytest.mark.parametrize('damage',['empty','duplicate','unknown','handle','tool','reused'])
def test_parameter_subset_rejected_before_native(parameters_fake,damage):
    data,batch,calls=parameters_fake;chosen=[deepcopy(data[0])];handles={chosen[0]['operation_native_id']:'raw'};report={}
    if damage=='empty':chosen=[]
    elif damage=='duplicate':chosen.append(deepcopy(chosen[0]))
    elif damage=='unknown':chosen[0]['operation_native_id']=900
    elif damage=='handle':handles={}
    elif damage=='tool':chosen[0]['assigned_tool']['native_id']=True
    elif damage=='reused':report={'parameters':[]}
    with pytest.raises(ValueError):m.read_parameter_groups('doc',handles,chosen,batch,report,lambda:None,learned=data)
    assert calls==[]


def test_changed_tool_during_single_read_fails(parameters_fake,monkeypatch):
    data,batch,_=parameters_fake;report={}
    monkeypatch.setattr(m.fast.reader,'read_generic_tool',lambda *a:({'native_id':145},'tool'))
    with pytest.raises(ValueError):m.read_parameter_groups('doc',{data[0]['operation_native_id']:'raw'},[data[0]],batch,report,lambda:None,learned=data)
    assert report['parameters'][0]['read_complete']is False


@pytest.mark.parametrize('value',[None,True,False,0,-1,2**31,273.,'273'])
def test_invalid_actual_assigned_tool_id_rejected(parameters_fake,value):
    data,batch,calls=parameters_fake;data[0]['assigned_tool']['native_id']=value
    with pytest.raises(ValueError):m.read_parameter_groups('doc',{data[0]['operation_native_id']:'raw'},[data[0]],batch,{},lambda:None,learned=data)
    assert calls==[]


def test_actual_default_tool_before_settool_can_be_observed(parameters_fake,monkeypatch):
    data,batch,_=parameters_fake;actual={'native_id':145,'cut_diameter_native':3.}
    data[0]['assigned_tool']=deepcopy(actual);report={}
    monkeypatch.setattr(m.fast.reader,'read_generic_tool',lambda *a:(deepcopy(actual),'tool'))
    monkeypatch.setattr(m.fast.reader,'read_tool_dimensions',lambda *a:{'generic':deepcopy(actual),'dimension_read_complete':True})
    m.read_parameter_groups('doc',{data[0]['operation_native_id']:'raw'},[data[0]],batch,report,lambda:None,learned=data)
    assert report['parameters'][0]['read_complete']is True
    assert report['parameters'][0]['tool']['generic']==actual
