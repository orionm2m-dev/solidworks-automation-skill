from pathlib import Path
from copy import deepcopy
import importlib,json,os,sys,hashlib
import pytest
R=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',str(Path(__file__).resolve().parents[1]))).resolve();sys.path.insert(0,str(R));import scripts
importlib.import_module('scripts.sw_cam_deep_guide_preflight')
S=Path(os.environ['SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT']).resolve()if os.environ.get('SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')else None
C=Path(os.environ.get('SW_CAM_DEEP_GUIDE_MODULE_ROOT',str(R/'scripts'))).resolve()
scripts.__path__.insert(0,str(C))
m=importlib.import_module('scripts.sw_cam_deep_guide_group');cl=m.cl

@pytest.fixture
def saved():
    if S is None or not (S/'ACTUAL_DEEP_INSPECT_NATIVE.json').is_file():pytest.skip('Optional actual CAM receipt fixture requires SW_CAM_DEEP_GUIDE_EVIDENCE_ROOT')
    inspect=json.loads((S/'ACTUAL_DEEP_INSPECT_NATIVE.json').read_text(encoding='utf-8'))
    source_path=Path(inspect['request']['corrected_receipt_path'])
    source=json.loads(source_path.read_text(encoding='utf-8'));cp=source['saved_checkpoint_context']
    plan=m.inspect.compile_definition_plan(inspect,{r['key']:{'name':'Default','default_operation_id':79 if r['operation_type']==0 else 87}for r in inspect['preflight']['rows']})
    for row in plan['rows']:
        original=next(x for x in source['saved']['parameters']if x['operation_native_id']==row['reference_operation_native_id'])
        row['expected_levels']=deepcopy(original['levels']);row['expected_levels']['levels']['machining_depth_native']=4.4
    return {'source_backup_pin':{'path':'independent_backup.SLDPRT','sha256':'a'*64},'pins':[],'checkpoint_pins':[],'guide_parameters':{'expected_parameters':deepcopy(source['saved']),'baseline':deepcopy(source['saved']['binding']),
      'targets':deepcopy(source['recipe']),'configuration':deepcopy(cp['configuration']),'document':deepcopy(cp['document'])},
      'deep_headers':deepcopy(inspect['deep_headers_before']),'deep_plan':plan,'configuration_tool':deepcopy(source['recipe'][0]['assigned_tool'])}

class FakeBackend:
    def __init__(self,l,r,failure=None):
        self.l,self.report,self.failure=l,r,failure;self.state=m.projected_baseline(l);self.learned=[];self.calls=[];self.closed=False;self.session=None
    def start(self):self.calls.append('start')
    def finish(self):self.calls.append('finish')
    def close(self):self.closed=True
    def boundary(self):pass
    def refresh_dirty(self):pass
    def event(self,key,pending):
        pending();self.calls.append(key)
        if self.failure==key:raise OSError('unknown native outcome: '+key)
    def capture(self,label,full=False,own=None):
        if self.failure==label:raise ValueError('capture rejected: '+label)
        value=deepcopy(self.state)
        if not full:value['parameters']=[]if own is None else[x for x in value['parameters']if x['operation_native_id']==own['operation_native_id']]
        if self.failure=='changed_protected'and label=='configured':value['parameters'][0]['nc']['feeds_compensation']['XYFeed']+=1
        if self.failure=='wrong_depth'and label=='definitions':value['parameters'][-1]['levels']['levels']['machining_depth_native']=1.
        return value
    def capture_binding(self,label):return self.capture(label)['binding']
    def insert(self,target,anchor,pending,returned):
        self.event('insert:'+target['key'],pending);returned(object());oid=401+2*len(self.learned)
        template=deepcopy(next(x for x in self.state['binding']['operations']if x['native_id']==target['reference_operation_native_id']))
        template.update(native_id=oid,operation_index=len(self.state['binding']['operations']),linked_feature_ids=[target['feature_native_id']],toolpath_generated=False,toolpath_record_counts=[])
        self.state['binding']['operations'].append(template);self.state['binding']['operation_setups'][0]['operation_count']+=1
        param=deepcopy(next(x for x in self.state['parameters']if x['operation_native_id']==target['reference_operation_native_id']))
        param.update(operation_native_id=oid,feature_native_id=target['feature_native_id']);param['levels']=deepcopy(target['expected_levels'])
        param['nc']['feeds_compensation']['GetCNCComp']=1
        if 'protected_finish'in param:param['protected_finish']['compensation'][1]=1
        self.state['parameters'].append(param);return oid
    def assign(self,target,pending):self.event('SetTool:'+str(target['operation_native_id']),pending);return 0
    def field(self,target,spec):return m.config.field_value(next(x for x in self.state['parameters']if x['operation_native_id']==target['operation_native_id']),spec)
    def set_field(self,*args):raise AssertionError('fixture already at explicit field values')
    def read_nc(self,target):return deepcopy(next(x for x in self.state['parameters']if x['operation_native_id']==target['operation_native_id'])['nc']['feeds_compensation'])
    def set_nc(self,target,expected,pending):
        self.event('CNC0:'+str(target['operation_native_id']),pending)
        row=next(x for x in self.state['parameters']if x['operation_native_id']==target['operation_native_id']);row['nc']['feeds_compensation']['GetCNCComp']=0
        if 'protected_finish'in row:row['protected_finish']['compensation'][1]=0
        return 0
    def generate(self,target,pending):
        assert self.read_nc(target)==target['reference_nc'];self.event('GTP:'+str(target['operation_native_id']),pending)
        row=next(x for x in self.state['binding']['operations']if x['native_id']==target['operation_native_id']);row.update(toolpath_generated=True,toolpath_record_counts=[100+target['operation_native_id']]);return 0
    def outcome(self,target):
        row=next(x for x in self.state['binding']['operations']if x['native_id']==target['operation_native_id'])
        return dict(operation_native_id=target['operation_native_id'],feature_native_id=target['feature_native_id'],background_over_before=True,background_over_after=True,
          generated=row['toolpath_generated'],generated_for_feature=row['toolpath_generated'],record_counts=deepcopy(row['toolpath_record_counts']))
    def export(self,label,binding):
        rows=cl.contract(binding)
        if self.failure==label+'_cl':raise ValueError('CL verification failed')
        return {'label':label,'expected_generated_operations':rows,'output':{'path':'export.cl','sha256':'d'*64,'bytes':100}}
    def save(self):
        self.calls.append('SaveActiveDocument')
        if self.failure=='SaveActiveDocument':raise OSError('save unknown')
        return 0
    def saved_hash(self,stage):
        assert stage['native_call_returned']is True and stage['native_return_value']==0
        self.report['source_transition']={'source_before_sha256':'a'*64,'source_after_sha256':'b'*64,'document':dict(self.l['guide_parameters']['document'],needs_save=False)}
        return 'b'*64

def run(saved,tmp_path,monkeypatch,failure=None):
    report={'source_path':str(tmp_path/'source.SLDPRT'),'source_sha256':'a'*64,'request':{'process_id':123},'ownership':{'process_id':123},'inspect_receipt_pin':{'sha256':'c'*64}}
    b=FakeBackend(saved,report,failure);j=m.Journal(report,tmp_path/'receipt.json',tmp_path/'marker.json')
    monkeypatch.setattr(cl,'_verified',lambda a:{'operation_blocks':[{}]*14})
    monkeypatch.setattr(cl.review,'block_signature',lambda parsed,i:['signature',i])
    monkeypatch.setattr(cl,'verify_protected',lambda a,b:{'verified':True})
    monkeypatch.setattr(cl,'verify_no_new_cutcom',lambda a:{'verified':True})
    monkeypatch.setattr(cl,'verify_all',lambda a,b:{'verified':True})
    return m.run_backend(b,j,saved),b,j

def test_complete_four_packet_once_saves_checkpoint(saved,tmp_path,monkeypatch):
    out,b,j=run(saved,tmp_path,monkeypatch)
    assert out['status']=='saved_deep_guides_review_required',out.get('issue')
    assert out['readback_verified']and out['model_saved']and b.closed
    assert len(out['saved']['binding']['operations'])==17
    assert len([x for x in out['saved']['binding']['operations']if x['toolpath_generated']])==14
    assert out['actual_new_ids']==[401,403,405,407]
    assert sum(x.startswith('insert:')for x in b.calls)==4
    assert sum(x.startswith('SetTool:')for x in b.calls)==4
    assert sum(x.startswith('GTP:')for x in b.calls)==4 and b.calls.count('SaveActiveDocument')==1
    assert out['saved_checkpoint_context']['source_backup_pin']==saved['source_backup_pin']
    assert out['saved_checkpoint_context']['saved_snapshot']==out['saved']
    assert len(out['saved_checkpoint_context']['saved_CL_block_signature_sha256'])==14
    assert len(out['saved_checkpoint_context']['learned_targets'])==4
    assert out['saved_checkpoint_context']['source_sha256']=='b'*64
    assert out['saved_checkpoint_context']['prior_source_sha256']=='a'*64
    assert out['saved_checkpoint_context']['snapshot_sha256']==m.group._digest(out['saved'])
    assert j.marker.exists() and not out['persistence_after_reopen_verified'] and not out['geometry_accepted']

@pytest.mark.parametrize('failure',['insert:guide80_rough','insert:guide81_finish','SetTool:401','SetTool:407','CNC0:401','GTP:401','GTP:407','SaveActiveDocument'])
def test_unknown_native_action_stops_no_replay(saved,tmp_path,monkeypatch,failure):
    out,b,j=run(saved,tmp_path,monkeypatch,failure)
    assert out['status']=='uncertain'and not out['readback_verified']and b.closed
    assert b.calls[-1]==failure and j.marker.exists()
    marker=json.loads(j.marker.read_text());assert marker['native_dispatch_pending']is True
    second=m.Journal({},tmp_path/'renamed_receipt.json',j.marker)
    with pytest.raises(ValueError):second.create()

@pytest.mark.parametrize('failure',['before','before_cl','definitions','wrong_depth','after_tools','configured','changed_protected','generated','generated_cl','saved','saved_cl'])
def test_failed_milestone_stops_before_next_native_stage(saved,tmp_path,monkeypatch,failure):
    out,b,j=run(saved,tmp_path,monkeypatch,failure)
    assert out['status']in('error','uncertain')and not out['readback_verified']and b.closed
    if failure in ('before','before_cl'):assert not out['mutation_attempted']
    if failure in ('definitions','wrong_depth'):assert not any(x.startswith('SetTool:')for x in b.calls)
    if failure in ('after_tools','configured','changed_protected'):assert not any(x.startswith('GTP:')for x in b.calls)
    if failure in ('generated','generated_cl'):assert 'SaveActiveDocument'not in b.calls

@pytest.mark.parametrize('damage',['order','count','feature','setup'])
def test_protected13_projection_rejects_drift(saved,damage):
    b=m.projected_baseline(saved)['binding'];a=deepcopy(b)
    if damage=='order':a['operations'].reverse()
    elif damage=='count':a['operations'][-1]['toolpath_record_counts']=[116]
    elif damage=='feature':a['features']['80']['depth_native']=1.
    elif damage=='setup':a['operation_setups'][0]['native_id']=94
    with pytest.raises(ValueError):m.protected_binding(b,a)

@pytest.mark.parametrize('damage',['duplicate','deep_link','old_empty','old_count','missing_path'])
def test_cl_inventory_exact14_contract(saved,damage):
    b=m.projected_baseline(saved)['binding']
    for index,(fid,kind)in enumerate(m.PAIRS):
        row=deepcopy(b['operations'][9+index]);row.update(native_id=401+index,operation_index=13+index,linked_feature_ids=[fid],mill_operation_type=kind,toolpath_generated=True,toolpath_record_counts=[200+index]);b['operations'].append(row)
    b['operation_setups'][0]['operation_count']=17
    assert len(cl.contract(b))==14
    if damage=='duplicate':b['operations'][-1]['native_id']=401
    elif damage=='deep_link':b['operations'][-1]['linked_feature_ids']=[83]
    elif damage=='old_empty':b['operations'][0].update(toolpath_generated=True,toolpath_record_counts=[1])
    elif damage=='old_count':b['operations'][2]['toolpath_record_counts']=[False]
    elif damage=='missing_path':b['operations'][-1].update(toolpath_generated=False,toolpath_record_counts=[])
    with pytest.raises(ValueError):cl.contract(b)

def test_cl_complete_signatures_required_even_equal_counts(monkeypatch):
    a={'declared_units':['MM'],'commands':[]};b={'declared_units':['MM'],'commands':[]}
    old=[{'operation_native_id':i,'toolpath_record_counts':[100]}for i in cl.OLD]
    before={'expected_generated_operations':old};after={'expected_generated_operations':old+[{'operation_native_id':401+i,'toolpath_record_counts':[100]}for i in range(4)]}
    monkeypatch.setattr(cl,'_verified',lambda v:a if v is before else b)
    monkeypatch.setattr(cl.review,'block_signature',lambda p,i:(i if p is a else(99 if i==4 else i)))
    with pytest.raises(ValueError):cl.verify_protected(before,after)

@pytest.mark.parametrize('damage',['command','record','state','empty'])
def test_cl_cutcom_checks_global_parser_fields(monkeypatch,damage):
    parsed={'operation_blocks':[{}]*14,'commands':[],'cutcom_records':[],'motions':[{'block':i,'cutcom_state':{'status':'not_declared'}}for i in range(10,14)]}
    if damage=='command':parsed['commands']=[{'block':11,'name':'CUTCOM'}]
    elif damage=='record':parsed['cutcom_records']=[{'block':11}]
    elif damage=='state':parsed['motions'][0]['cutcom_state']['status']='active'
    elif damage=='empty':parsed['motions'].pop()
    monkeypatch.setattr(cl,'_verified',lambda r:parsed)
    with pytest.raises(ValueError):cl.verify_no_new_cutcom({})


@pytest.mark.parametrize('damage',['action','extra','pid','ack','digest','module','backup_alias','backup_digest'])
def test_request_rejected_before_authority_or_native(tmp_path,monkeypatch,damage):
    p={k:str(tmp_path/(k+'.json')) if k.endswith('_path')else 'a'*64 if k.endswith('_sha256')else None for k in m.PARAMS}
    p.update(process_id=123,choices={},acknowledgement='create4_configure4_generate4_save1_preserve13_10_no_replay')
    r={'action':'apply_deep_guide_group','params':p};calls=[]
    monkeypatch.setattr(m,'_file_hash',lambda p:'a'*64)
    monkeypatch.setattr(m,'read_pin',lambda *a:calls.append(a))
    if damage=='action':r['action']='anything_else'
    elif damage=='extra':p['unexpected']=True
    elif damage=='pid':p['process_id']=True
    elif damage=='ack':p['acknowledgement']='save'
    elif damage=='digest':p['inspect_receipt_sha256']='A'*64
    elif damage=='module':p['module_sha256']='b'*64
    elif damage=='backup_alias':p['source_backup_path']=p['expected_document_path']
    elif damage=='backup_digest':p['source_backup_sha256']='b'*64
    with pytest.raises(ValueError):m.prepare_request(r)
    assert calls==[]
