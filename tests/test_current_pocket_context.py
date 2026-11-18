"""Portable callback tests; no COM/application calls."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
from scripts import sw_cam_current_pocket_context as c


def write(path,value):
    path.write_text(json.dumps(value,allow_nan=False),encoding='utf-8');return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

@pytest.fixture
def probe(tmp_path):
    target=tmp_path/'part.sldprt';target.write_bytes(b'before');old=hashlib.sha256(target.read_bytes()).hexdigest()
    root=write(tmp_path/'root.json',{'frozen':'root'})
    previous=dict(scope=c.pair.SCOPE,status='observed',phase='finished',**{k:True for k in c.pair.FLAGS})
    predecessor=write(tmp_path/'read.json',previous)
    doc=dict(path=str(target),title=target.name,type=1,needs_save=False)
    header=dict(native_id=10,owner_setup_native_id=20,island_count=4)
    rows=[dict(native_id=i,assigned_tool={'native_id':t})for i,t in [(30,50),(31,51)]]
    state=dict(document=doc,saved_file_sha256=old,operations=rows,selected_feature=header,feature_setups=[{'origin_native':[0,0,0]}],operation_setups=[{'native_id':21}])
    params=[dict(operation_native_id=i,read_complete=True,levels={'setup':{'origin_native':[0,0,26]}},tool={'native_id':t})for i,t in [(30,50),(31,51)]]
    d=dict(scope=c.definition.SCOPE,process_id=123,expected_document_path=str(target),expected_source_sha256=old,expected_feature_native_id=10,
        evidence=root,save_pin=root,saved_transition={'document':deepcopy(doc)},expected_inventory={'features':[header]},current_sketch_baseline={'saved_file_sha256':old,'needs_save':False,'features':[],'solids':[]},
        spec={'circle':8},request=dict(process_id=123,expected_process_create_time=12.,expected_document_path=str(target),expected_sw_configuration='Default',expected_cam_configuration='Mill',owner_setup_native_id=20),
        creator=dict(status='uncertain',feature_header=header),sketch={'sketch_readback':{'circle':8}},pins=[root,predecessor,dict(path=str(target),sha256=old)])
    previous.update(request={'expected_document_path':str(target)},evidence_pins=[root],after=deepcopy(state),before_diagnostic={'actual_sketch_snapshot':dict(deepcopy(d['current_sketch_baseline']),needs_save=False)})
    predecessor=write(tmp_path/'read.json',previous);d['pins']=[root,predecessor,dict(path=str(target),sha256=old)]
    bundle=dict(context=d,state=state,parameters=params,receipt_pin=predecessor,root_pins=[root,predecessor],pins=d['pins'],lineage_pins=[predecessor])
    calls=[];observed=dict(inventory=deepcopy(state),parameters=deepcopy(params));report={};persisted=[]
    def capture(label):calls.append('capture:'+label);return deepcopy(observed)
    def save():calls.append('save');target.write_bytes(b'after');return 0
    def adopt(new):calls.append('adopt');observed['inventory']['saved_file_sha256']=new['expected_source_sha256'];observed['inventory']['document']['needs_save']=False
    def persist():persisted.append(deepcopy(report))
    kw=dict(capture=capture,save=save,guard=lambda:calls.append('guard'),claim=lambda:calls.append('claim'),persist=persist,adopt_context=adopt)
    return dict(target=target,bundle=bundle,expected=deepcopy(observed),observed=observed,report=report,calls=calls,kw=kw,persisted=persisted)


def run(p):return c.save_current_baseline(p['report'],p['bundle'],p['expected'],**p['kw'])


def terminal(p,out,name='changed.json'):
    r=p['report'];r.update(status='review_required',phase='finished',current_context_verified=True,inventory_delta_verified=True,parameter_delta_verified=True,runtime_unchanged=True,
        GOP_attempted=False,GTP_attempted=False,Import_attempted=False,automatic_replay=False,production_qualified=False,
        messages=dict(policy='vendor_default',response='default_unknown',subscribed=True,disconnected=True,active=False,event_count=0,events=[],overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[]),
        after_cleanup_identity=dict(document=deepcopy(out['state']['document']),saved_file_sha256=out['state']['saved_file_sha256']))
    pin=write(p['target'].parent/name,r);v=deepcopy(out['payload']['identity']);v.update(current_context_receipt_path=pin['path'],current_context_receipt_sha256=pin['sha256']);return v


def test_one_Save_false_to_false_records_new_hash_and_reusable_context(probe,monkeypatch):
    p=probe;out=run(p);r=p['report']
    assert p['calls'].count('save')==1 and p['calls'].index('claim')<p['calls'].index('save')<p['calls'].index('adopt')<p['calls'].index('capture:after')
    assert r['save_readback_verified'] and not r['current_context_verified'] and r['Save_attempted']
    assert r['native_save']['native_return_value']==0 and r['saved_file_sha256_after_native_return']!=p['bundle']['context']['expected_source_sha256']
    assert out['parameters']==p['expected']['parameters'] and out['payload']['limitations']==c.LIMITS
    assert any(x.get('saved_file_sha256_after_native_return')for x in p['persisted'])
    v=terminal(p,out)
    monkeypatch.setattr(c.definition,'load_saved_plan',lambda *a,**k:pytest.fail('Historical validator must not run'))
    loaded=c.load_current_baseline(v)
    assert loaded['state']==out['state'] and loaded['parameters']==out['parameters'] and loaded['context']['creator']['status']=='uncertain'
    assert len(loaded['root_pins'])==2 and len(loaded['lineage_pins'])==2

@pytest.mark.parametrize('result',[True,False,None,1,-1,'0'])
def test_unqualified_native_result_stops_without_replay(probe,result):
    p=probe;p['kw']['save']=lambda:result
    with pytest.raises(ValueError):run(p)
    assert p['report']['native_save']['native_call_returned'] and p['report']['native_save']['native_return_value']==result
    assert not p['report']['current_context_verified'] and 'current_context'not in p['report']


def test_unchanged_source_is_rejected_even_when_Save_returns_zero(probe):
    probe['kw']['save']=lambda:0
    with pytest.raises(ValueError):run(probe)
    assert probe['report']['saved_file_sha256_after_native_return']==probe['bundle']['context']['expected_source_sha256']

@pytest.mark.parametrize('field',['tool','operation_setup_origin','feature_origin','parameters','dirty','source'])
def test_postsave_delta_cannot_be_hidden(probe,field):
    p=probe;old=p['kw']['capture']
    def capture(label):
        out=old(label)
        if label=='after':
            if field=='tool':out['inventory']['operations'][1]['assigned_tool']['native_id']=99
            elif field=='operation_setup_origin':out['parameters'][1]['levels']['setup']['origin_native'][2]=0
            elif field=='feature_origin':out['inventory']['feature_setups'][0]['origin_native'][2]=26
            elif field=='parameters':out['parameters'][0]['new']=1
            elif field=='dirty':out['inventory']['document']['needs_save']=True
            elif field=='source':out['inventory']['saved_file_sha256']='0'*64
        return out
    p['kw']['capture']=capture
    with pytest.raises(ValueError):run(p)
    assert p['report']['native_save']['native_return_value']==0 and p['report']['saved_file_sha256_after_native_return']!=p['bundle']['context']['expected_source_sha256']
    assert 'current_context'not in p['report']


def test_failure_after_native_return_retains_raw_and_hash(probe):
    p=probe
    def guard():
        if 'saved_file_sha256_after_native_return'in p['report']:raise ValueError('event')
    p['kw']['guard']=guard
    with pytest.raises(ValueError):run(p)
    assert p['report']['native_save']['native_return_value']==0 and p['report']['saved_file_sha256_after_native_return']
    assert not p['report']['current_context_verified']

@pytest.mark.parametrize('damage',['status','terminal_flag','native_result','runtime','current_source','predecessor','cleanup','parameters','root_file','target','root_pin_omitted','limitation','root_geometry'])
def test_current_loader_rejects_unqualified_or_tampered_state(probe,damage):
    p=probe;out=run(p);v=terminal(p,out);r=p['report']
    if damage=='status':r['status']='uncertain'
    elif damage=='terminal_flag':r['current_context_verified']=False
    elif damage=='native_result':r['native_save']['native_return_value']=True
    elif damage=='runtime':r['runtime_unchanged']=False
    elif damage=='current_source':v['expected_source_sha256']='0'*64
    elif damage=='predecessor':r['current_context']['predecessor_pin']['sha256']='0'*64
    elif damage=='cleanup':r['after_cleanup_identity']['document']['title']='other'
    elif damage=='parameters':r['current_context']['snapshot']['parameters'][1]['tool']['native_id']=99
    elif damage=='root_file':Path(p['bundle']['root_pins'][0]['path']).write_text('{}',encoding='utf-8')
    elif damage=='target':p['target'].write_bytes(b'changed')
    elif damage=='root_pin_omitted':r['current_context']['root_pins']=r['current_context']['root_pins'][1:]
    elif damage=='limitation':r['current_context']['limitations']['persistence_verified']=True
    elif damage=='root_geometry':r['current_context']['capture_context']['current_sketch_baseline']['features']=[{'changed':True}]
    if damage not in ('current_source','root_file','target'):
        pin=write(Path(v['current_context_receipt_path']),r);v['current_context_receipt_sha256']=pin['sha256']
    with pytest.raises(ValueError):c.load_current_baseline(v)


def test_successive_current_receipts_accept_new_tool_without_recursive_history(probe,monkeypatch):
    p=probe;first=run(p);v=terminal(p,first);loaded=c.load_current_baseline(v)
    monkeypatch.setattr(c.definition,'load_saved_plan',lambda *a,**k:pytest.fail('No recursive historical validation'))
    p['bundle']=loaded;p['expected']={'inventory':deepcopy(loaded['state']),'parameters':deepcopy(loaded['parameters'])}
    p['expected']['inventory']['operations'][0]['assigned_tool']['native_id']=70
    p['expected']['parameters'][0]['tool']['native_id']=70
    p['observed'].clear();p['observed'].update(deepcopy(p['expected']));p['report'].clear()
    def save():p['target'].write_bytes(b'next saved change');return 0
    p['kw']['save']=save
    second=run(p);v2=terminal(p,second,'changed_again.json');out=c.load_current_baseline(v2)
    assert out['state']['operations'][0]['assigned_tool']['native_id']==70
    assert out['context']['expected_source_sha256']!=loaded['context']['expected_source_sha256']
    assert len(out['root_pins'])==len(loaded['root_pins'])==2 and len(out['lineage_pins'])==2
