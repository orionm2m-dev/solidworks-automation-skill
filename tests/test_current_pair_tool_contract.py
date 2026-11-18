"""Independent tool-only contract tests. All objects are synthetic; no application."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import pytest

STAGE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('SWMCP_RUNTIME_ROOT', STAGE))
sys.path.insert(0,str(RUNTIME))
import scripts
for candidate in (STAGE/'scripts',STAGE.parent/'cam_current_pocket_context_20261111'/'scripts'):
    if candidate.is_dir(): scripts.__path__.insert(0,str(candidate))
from scripts import sw_cam_current_pair_tool as core
from scripts import sw_cam_current_pocket_context as current


def snapshot():
    inventory={'document':{'path':'fixture.SLDPRT','type':1,'needs_save':False},'saved_file_sha256':'b'*64,
      'feature_setups':[{'native_id':64,'axis_native':[0.,0.,-1.],'origin_native':[0.,0.,0.]}],
      'operation_setups':[{'native_id':65,'operation_count':2}], 'selected_feature':{'native_id':66,'island_count':4},
      'operations':[{'native_id':oid,'setup_native_id':65,'linked_feature_ids':[66],'mill_operation_type':kind,
          'suppressed':False,'toolpath_generated':False,'toolpath_record_counts':[],
          'assigned_tool':{'native_id':116,'cut_diameter_native':20.,'protrusion_native':60.}}
          for oid,kind in [(114,0),(115,1)]], 'unique_tool_count':1,'feature_count':1,'operation_count':2}
    parameters=[{'operation_native_id':oid,'operation_type':kind,'feature_native_id':66,'read_complete':True,
        'levels':{'setup':{'origin_native':[0.,0.,26.],'axis_native':[0.,0.,-1.]},'depth':13.2},
        'nc':{'S':3322.964,'XY':742.749},'tool':{'generic':{'native_id':116},'dimension_read_complete':True},
        'body':{'entry_raw':0,'depths':[10.,10.]}} for oid,kind in [(114,0),(115,1)]]
    return {'inventory':inventory,'parameters':parameters}


def assigned(base=None):
    s=copy.deepcopy(base or snapshot()); s['inventory']['operations'][0]['assigned_tool']={'native_id':202,'cut_diameter_native':8.,'protrusion_native':25.}
    s['inventory']['unique_tool_count']=2;s['parameters'][0]['tool']['generic']['native_id']=202
    s['parameters'][0]['nc']={'S':900.,'XY':200.}
    return s


def test_exact_unchanged_before_assignment():
    s=snapshot(); assert core.verify_pair_delta(s,copy.deepcopy(s),selected_id=114)['unselected_parameters_unchanged']


def test_selected_automatic_defaults_observed_not_qualified():
    proof=core.verify_pair_delta(snapshot(),assigned(),selected_id=114,new_tool_id=202)
    assert proof['selected_automatic_defaults_observed'] and proof['automatic_defaults_qualified'] is False
    assert proof['operation_parameter_setters_attempted'] is False


@pytest.mark.parametrize('fault', ['source','feature_origin','feature_axis','operation_origin','operation_axis','depth','selected_feature','operation_order','feature_link','generated','unselected_tool','unselected_nc','unselected_level','unselected_read_complete','new_id','selected_read_complete','dirty_type'])
def test_protected_delta_rejected(fault):
    s=assigned();i=s['inventory'];p=s['parameters']
    if fault=='source':i['saved_file_sha256']='c'*64
    elif fault=='feature_origin':i['feature_setups'][0]['origin_native'][2]=26.
    elif fault=='feature_axis':i['feature_setups'][0]['axis_native'][2]=1.
    elif fault=='operation_origin':p[0]['levels']['setup']['origin_native'][2]=0.
    elif fault=='operation_axis':p[0]['levels']['setup']['axis_native'][2]=1.
    elif fault=='depth':p[0]['levels']['depth']=13.3
    elif fault=='selected_feature':i['selected_feature']['island_count']=3
    elif fault=='operation_order':p.reverse()
    elif fault=='feature_link':i['operations'][0]['linked_feature_ids']=[99]
    elif fault=='generated':i['operations'][0]['toolpath_generated']=True
    elif fault=='unselected_tool':i['operations'][1]['assigned_tool']['native_id']=202
    elif fault=='unselected_nc':p[1]['nc']['S']=900.
    elif fault=='unselected_level':p[1]['levels']['depth']=13.3
    elif fault=='unselected_read_complete':p[1]['read_complete']=False
    elif fault=='new_id':p[0]['tool']['generic']['native_id']=116
    elif fault=='selected_read_complete':p[0]['read_complete']=False
    elif fault=='dirty_type':i['document']['needs_save']=1
    with pytest.raises(Exception):core.verify_pair_delta(snapshot(),s,selected_id=114,new_tool_id=202)


def data_and_report(tmp_path):
    s=snapshot();target={'OverallLen':64.,'EffCutlength':21.,'NoOfFlutes':4,'CutDiameter':8.,'ShankDia':8.,'MillToolShankType':0,
      'ShoulderDia':8.,'ShoulderLength':21.,'ShankLength':21.,'Protrusion':25.}
    identity={'ToolIdentifier':'404-315011','ToolVendor':'OSG','ToolDescription':'D8 test'}
    proposed=dict(target,**identity)
    data={'bundle':{'state':s['inventory'],'parameters':s['parameters'],'context':{'expected_source_sha256':'b'*64},'receipt_pin':{'path':'fixture','sha256':'a'*64}},
      'recipe':{'target':target,'identity':identity,'accepted_identity_aliases':[]},'holder':{'file_path':'fixture.mh'},'proposed':proposed,
      'request':{'selected_operation_native_id':114,'expected_feature_native_id':66},'receipt':tmp_path/'result.json','marker':tmp_path/'once.json'}
    r={'scope':core.SCOPE,'phase':'prepared','source_path':str(tmp_path/'fixture.SLDPRT'),'initial_source_sha256':'b'*64,'actions':{},'mutation_attempted':False,
       'assignment_attempted':False,'model_saved':False,'Save_attempted':False,'save_readback_verified':False,
       **{k:False for k in core.ACCEPTANCE}}
    return data,r


class FakeBackend:
    def __init__(self,data,r,fault=None):
        self.data=data;self.report=r;self.fault=fault;self.calls=[];self.created=False;self.assigned=False;self.saved=False;self.closed=False
        self.d={'expected_source_sha256':'b'*64};self.expected_document=copy.deepcopy(data['bundle']['state']['document'])
        self.fields={k: ('old' if isinstance(v,str) else v+1) for k,v in data['proposed'].items()}
    def start(self):self.calls.append('start')
    def capture_current(self,label):
        self.calls.append('capture:'+label);s=assigned() if self.assigned else snapshot()
        if self.saved:s['inventory']['saved_file_sha256']='c'*64
        if self.fault=='unassigned_drift' and label=='configured_unassigned':s['parameters'][1]['nc']['S']=0.
        if self.fault=='selected_level' and label=='assigned':s['parameters'][0]['levels']['depth']=20.
        return s
    def initial_tools(self):return self.catalogue()
    def catalogue(self):
        rows=[{'native_id':116,'tool_type_raw':1,'CutDiameter':20.,'Protrusion':60.}]
        if self.created:rows.append({'native_id':202,'tool_type_raw':1,'CutDiameter':self.fields['CutDiameter'],'Protrusion':self.fields['Protrusion']})
        return rows
    def full_existing(self,tid,label):
        value={'native_id':tid,'profile':'original','holder':'original'}
        if self.fault=='protected_profile' and label=='after_assignment':value['profile']='changed'
        return value
    def create(self,pending,returned):
        pending();self.calls.append('create');self.created=True;self.report['new_tool_native_id']=202
        if self.fault=='create':raise RuntimeError('native creation uncertain')
        returned(object());return 202
    def created_classification(self):
        return {'MillToolType':1,'MillToolSubType':0 if self.fault=='classification' else 3,'EndRadius':0.}
    def field(self,name):
        if self.fault=='field_readback' and name=='OverallLen' and 'property:OverallLen' in self.calls:return 500.
        return self.fields[name]
    def property(self,name,value,pending):
        pending();self.calls.append('property:'+name);self.fields[name]=value
        return 0 if self.fault=='property_return' else None
    def attach_holder(self,path,pending):pending();self.calls.append('holder');return True if self.fault=='holder_return' else 0
    def refresh_dirty(self):self.calls.append('refresh')
    def candidate(self,label):
        self.calls.append('candidate:'+label)
        if self.fault=='after_save_profile' and label=='saved':raise RuntimeError('profile read failed after Save')
        return {'full_tool':{'id':202},'identity':self.data['recipe']['identity']}
    def assign_selected(self,pending):
        pending();self.calls.append('assign');self.assigned=True
        return True if self.fault=='assign_return' else 0
    def boundary(self):self.calls.append('boundary')
    def save(self):self.calls.append('save');self.saved=True;self.report['Save_attempted']=True;return 0
    def adopt_context(self,context):self.d=context
    def close(self):
        if self.closed:return
        self.closed=True;self.calls.append('close');self.report['messages']={'test_clean':True}
        if self.fault=='cleanup':raise RuntimeError('cleanup failed')
    def runtime_check(self):
        if self.fault=='runtime':raise RuntimeError('runtime changed')
    def identity(self):return self.expected_document
    def files(self):
        if self.fault=='final_files':raise RuntimeError('protected file changed')


@pytest.fixture
def flow(monkeypatch,tmp_path):
    data,r=data_and_report(tmp_path)
    monkeypatch.setattr(core.geometry,'verify_candidate',lambda *a:{'profile_verified':True})
    monkeypatch.setattr(core.reuse,'require_new_exact_cutter',lambda *a,**kw:{'new_allowed':True})
    monkeypatch.setattr(core.reader.shared,'event_health',lambda m,active=False:0 if m.get('test_clean') else 1)
    def save_contract(report,bundle,expected_after,*,capture,guard,claim,persist,save,adopt_context):
        guard();capture('save_before');claim();assert save()==0
        report['native_save']={'native_call_returned':True,'native_return_type':'int','native_return_value':0,'save_readback_verified':True}
        report['saved_file_sha256_after_native_return']='c'*64;persist();context={'expected_source_sha256':'c'*64};adopt_context(context)
        after=capture('save_after');report['save_readback_verified']=True
        payload={'snapshot':after,'scope':'synthetic current baseline'}
        report['current_context']=payload
        return {'context':context,'state':after['inventory'],'parameters':after['parameters'],'payload':payload}
    monkeypatch.setattr(current,'save_current_baseline',save_contract)
    return data,r


def test_real_run_backend_success_return_contract_and_once_order(flow):
    data,r=flow;b=FakeBackend(data,r);j=core.Journal(r,data['receipt'],data['marker'])
    result=core.run_backend(b,j,data)
    assert result['status']=='review_required',result
    assert all(result[k] is True for k in core.ACCEPTANCE)
    assert result['model_saved'] and result['save_readback_verified']
    assert result['current_context']['snapshot']['inventory']['saved_file_sha256']=='c'*64
    assert result['after_cleanup_identity']['saved_file_sha256']=='c'*64
    for action in ('create','assign','save'):assert b.calls.count(action)==1
    assert b.calls.index('candidate:configured')<b.calls.index('assign')<b.calls.index('save')
    assert result['automatic_defaults_qualified'] is False
    assert data['marker'].is_file()
    assert set(result['actions'])<=core.ACTIONS


@pytest.mark.parametrize('fault',['create','classification','holder_return','property_return','field_readback','unassigned_drift','assign_return','selected_level','protected_profile','after_save_profile','cleanup','runtime','final_files'])
def test_real_run_backend_failure_stops_no_replay_and_preserves_save_fact(flow,fault):
    data,r=flow;b=FakeBackend(data,r,fault);j=core.Journal(r,data['receipt'],data['marker'])
    result=core.run_backend(b,j,data)
    assert result['status']=='uncertain',result
    assert all(result[k] is False for k in core.ACCEPTANCE)
    for action in ('create','assign','save'):assert b.calls.count(action)<=1
    assert b.closed and data['marker'].is_file()
    if fault in {'after_save_profile','cleanup','runtime','final_files'}:
        assert b.calls.count('save')==1 and result['native_save']['native_return_value']==0
        assert result['saved_file_sha256_after_native_return']=='c'*64 and result['model_saved'] is True
    else:assert 'save' not in b.calls


def test_journal_consumed_attempt_rejects_same_and_other_marker_replay(tmp_path):
    data,r=data_and_report(tmp_path);j=core.Journal(r,data['receipt'],data['marker']);j.pending('AddNewTool3')
    with pytest.raises(Exception):j.pending('AddNewTool3')
    _,fresh=data_and_report(tmp_path);other=core.Journal(fresh,tmp_path/'other.json',data['marker'])
    with pytest.raises(Exception):other.pending('AddNewTool3')
    assert data['marker'].exists()


@pytest.mark.parametrize('label',['GTP','GOP','SetSpndlSpeed','SetDepth','ImportCAMData','property:EndRadius'])
def test_journal_forbids_unrequested_actions(tmp_path,label):
    data,r=data_and_report(tmp_path);j=core.Journal(r,data['receipt'],data['marker'])
    with pytest.raises(Exception):j.pending(label)
    assert not data['marker'].exists() and not r['mutation_attempted']


def test_consumed_prepared_bundle_rejected_before_any_backend(monkeypatch):
    monkeypatch.setattr(core,'preflight',lambda *a:pytest.fail('No preflight after consumed preparation'))
    with pytest.raises(Exception):core.run_tool(None,None,None,{},prepared={'consumed':True,'request':{}})


def test_save_return_and_changed_hash_preserved_if_helper_postcheck_fails(flow,monkeypatch):
    data,r=flow;b=FakeBackend(data,r);j=core.Journal(r,data['receipt'],data['marker'])
    def partial_save(report,bundle,expected_after,*,capture,guard,claim,persist,save,adopt_context):
        guard();claim();assert save()==0
        report['native_save']={'native_call_returned':True,'native_return_type':'int','native_return_value':0,'save_readback_verified':False}
        report['saved_file_sha256_after_native_return']='c'*64;persist()
        raise RuntimeError('after-Save capture failed')
    monkeypatch.setattr(current,'save_current_baseline',partial_save)
    result=core.run_backend(b,j,data)
    assert result['status']=='uncertain' and all(result[k] is False for k in core.ACCEPTANCE)
    assert result['native_save']['native_return_value']==0 and result['saved_file_sha256_after_native_return']=='c'*64
    assert result['Save_attempted'] is True and result['save_readback_verified'] is False
    assert 'current_context' not in result and b.calls.count('save')==1 and data['marker'].is_file()
