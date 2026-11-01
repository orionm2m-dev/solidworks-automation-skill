import importlib.util,os,sys
from pathlib import Path
from copy import deepcopy
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).parents[1])))
sys.path.insert(0,str(ROOT))
P=Path(__file__).parents[1]/'scripts/sw_cam_turn_tool_reference_repair.py'
spec=importlib.util.spec_from_file_location('repair_under_test',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture():
    p={'process_id':101,'expected_document_path':'C:/review/part.sldprt','expected_source_sha256':'a'*64,'assignments':[{'operation_native_id':10,'operation_type':1,'feature_native_id':6,'tool_native_id':31},{'operation_native_id':11,'operation_type':2,'feature_native_id':6,'tool_native_id':32}]}
    rows=[{'native_id':i,'turn_operation_type':7,'setup_index':0,'operation_index':i-1,'linked_feature_ids':[4],'suppressed':False} for i in range(1,10)]
    rows += [dict(native_id=a['operation_native_id'],turn_operation_type=a['operation_type'],setup_index=0,operation_index=a['operation_native_id']-1,linked_feature_ids=[6],suppressed=False) for a in p['assignments']]
    inventory=[dict(setup_index=0,operation_index=i,turn_operation_type=x['turn_operation_type'],toolpath_generated=i<4,toolpath_record_counts=[i+10] if i<4 else []) for i,x in enumerate(rows)]
    state=dict(document={'path':p['expected_document_path'],'title':'part.sldprt','type':1,'needs_save':False},saved_file_sha256='a'*64,operations=rows,inventory={'operation_count':11,'operations':inventory},feature_header={'turn_feature_type_raw':2})
    tools=[dict(native_id=i,complete=True,candidate=True,tool_type_raw=15,turn_tool_type_raw=1,insert_type_raw=1,holder_present=True,holder_type_raw=2,holder_id_raw=i-29,insert_dimensions_native={'NoseRadius':.4,'IncludedAngle':80. if i==31 else 55.},holder_dimensions_native={'BoringBarDiameter':20.,'ShankLength':250.,'Protrusion':0.}) for i in (31,32)]
    events={'subscribed':True,'disconnected':True,'active':False,'event_count':0}
    observed=dict(scope=m.reader.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,mutation_attempted=False,model_saved=False,GTP_attempted=False,persistence_qualified=False,physical_tool_qualified=False,production_qualified=False,messages=events,request=deepcopy(p),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],before=deepcopy(state),after=deepcopy(state),tools=tools,tool_ids=[31,32])
    plan={'reference':state,'observed':observed,'tools':{x['native_id']:x for x in tools}}
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',request=deepcopy(p),source_path=p['expected_document_path'],source_sha256=p['expected_source_sha256'],actions={},mutation_attempted=False,native_dispatch_pending=False,readback_verified=False,model_saved=False,GTP_attempted=False,GOP_attempted=False,tool_geometry_changed=False,operation_inserted=False,automatic_retry=False,automatic_replay=False,persistence_qualified=False,physical_tool_qualified=False,production_qualified=False,messages=deepcopy(events),accepted_candidate_rows=deepcopy(tools))
    return p,plan,r


class Fake:
    def __init__(self,plan,fail=None):self.plan=plan;self.fail=fail;self.log=[];self.mutated=False;self.reads={}
    def step(self,k):
        self.log.append(k)
        if self.fail==k:raise ValueError('injected '+k)
    def start(self):self.step('start')
    def capture(self,label):
        self.step(label);v=deepcopy(self.plan['reference']);v['document']['needs_save']=self.mutated
        if self.fail=='delta_'+label:v['inventory']['operations'][0]['toolpath_record_counts']=[999]
        return v
    def tool_snapshot(self,label):
        self.step('tools_'+label);v=deepcopy(self.plan['observed']['tools'])
        if self.fail=='tools_'+label+'_drift':v[0]['holder_dimensions_native']['Protrusion']=1.
        return v
    def assign(self,a,pending):
        self.step('assign_'+str(a['operation_native_id'])+'_before');pending();self.mutated=True;self.step('assign_'+str(a['operation_native_id']))
        if self.fail=='return_'+str(a['operation_native_id']):return 1
        if self.fail=='bool_return':return False
        return 0
    def assigned(self,a):
        i=a['operation_native_id'];n=self.reads[i]=self.reads.get(i,0)+1;self.step('read_'+str(i)+'_'+str(n))
        v=m.expected_reference(a,self.plan['tools'][a['tool_native_id']])
        if self.fail=='wrong_'+str(i)+'_'+str(n):v['tool_native_id']+=1
        return v
    def finish(self):self.step('finish')
    def close(self):self.step('close')


def execute(fail=None):
    p,plan,r=fixture();b=Fake(plan,fail);claims=[];durable=[]
    m.run_backend(b,p,plan,r,lambda:durable.append(deepcopy(r)),lambda:claims.append('claimed'))
    return p,plan,r,b,claims,durable


def test_success_exact_two_setters_and_ram_only():
    p,plan,r,b,claims,records=execute()
    assert r['status']=='repaired_ram_no_save' and r['readback_verified']
    assert claims==['claimed'] and len(r['actions'])==2
    assert b.log.index('read_10_1')<b.log.index('assign_11')
    assert r['after']['document']['needs_save'] and r['after']['saved_file_sha256']=='a'*64
    assert r['tools_before']==r['tools_after']==plan['observed']['tools']
    assert not r['model_saved'] and not r['GTP_attempted'] and not r['persistence_qualified']
    assert m.validate_repaired(r,plan['observed'])==plan['tools']
    assert records[-1]['phase']=='finished'

@pytest.mark.parametrize('fail',['start','before','tools_before','tools_before_drift','delta_before','assign_10_before','assign_10','return_10','bool_return','read_10_1','wrong_10_1','SetTool_10_readback','delta_SetTool_10_readback','assign_11_before','assign_11','return_11','read_11_1','wrong_11_1','SetTool_11_readback','delta_SetTool_11_readback','read_10_2','wrong_11_2','tools_after','tools_after_drift','after','delta_after','finish','close'])
def test_failure_stops_without_save_generation_or_retry(fail):
    _,_,r,b,claims,_=execute(fail)
    assert r['status'] in ('error','uncertain') and not r['readback_verified']
    assert b.log[-1]=='close' and len(claims)<=1
    assert b.log.count('assign_10')<=1 and b.log.count('assign_11')<=1
    assert not {'Save','GTP','InsertOperation'} & set(b.log)
    if fail in ('start','before','tools_before','tools_before_drift','delta_before','assign_10_before'):
        assert not r['mutation_attempted'] and not claims
    if fail in ('assign_10','return_10','bool_return','read_10_1','wrong_10_1','SetTool_10_readback','delta_SetTool_10_readback'):
        assert 'assign_11' not in b.log and r['status']=='uncertain'


def test_marker_ignores_candidate_remapping(monkeypatch,tmp_path):
    p,_,_=fixture();monkeypatch.setattr(m.common,'local_evidence_root',lambda:tmp_path)
    first=m.marker_path(p);p['assignments'][0]['tool_native_id']=77;p['assignments'][1]['tool_native_id']=88
    assert m.marker_path(p)==first
    p['assignments'][0]['operation_native_id']=12
    assert m.marker_path(p)!=first

@pytest.mark.parametrize('mutate',[lambda r:r.update(model_saved=True),lambda r:r.update(GTP_attempted=True),lambda r:r.update(persistence_qualified=True),lambda r:r['actions']['SetTool_10'].update(native_return=True),lambda r:r['actions']['SetTool_11'].update(readback_verified=False),lambda r:r['references_after'][0].update(tool_native_id=99),lambda r:r['tools_after'][0]['holder_dimensions_native'].update(Protrusion=1.),lambda r:r['after']['inventory']['operations'][0].update(toolpath_record_counts=[99]),lambda r:r['messages'].update(active=True),lambda r:r.update(issue={'message':'failure'})])
def test_completed_validator_rejects_tampered_or_overclaimed_results(mutate):
    _,plan,r,_,_,_=execute();mutate(r)
    with pytest.raises(ValueError):m.validate_repaired(r,plan['observed'])

@pytest.mark.parametrize('mutate',[lambda p:p['assignments'].pop(),lambda p:p['assignments'][0].update(operation_native_id=True),lambda p:p['assignments'][1].update(operation_type=1),lambda p:p['assignments'][1].update(feature_native_id=8),lambda p:p['assignments'][1].update(operation_native_id=10)])
def test_assignment_scope_strict(mutate):
    p,_,_=fixture();mutate(p)
    with pytest.raises(ValueError):m.validate_assignments(p['assignments'])

@pytest.mark.parametrize('mutate',[lambda o:o.update(status='error'),lambda o:o.update(persistence_qualified=True),lambda o:o['tools'][0].update(holder_type_raw=1),lambda o:o['tools'][0].update(candidate=False),lambda o:o['after']['inventory']['operations'][9].update(toolpath_generated=True),lambda o:o['before']['document'].update(needs_save=True)])
def test_invalid_crib_baseline_rejected(mutate):
    p,plan,_=fixture();mutate(plan['observed'])
    with pytest.raises(ValueError):m.observed_crib(plan['observed'],p)
