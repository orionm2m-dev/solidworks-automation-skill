from copy import deepcopy
import pytest
from scripts import sw_cam_shared_cutter_geometry as g
from scripts.sw_cam_shared_cutter_config import apply_property_batch

TARGET=dict(CutDiameter=2.,EffCutlength=7.,ShankDia=3.,OverallLen=39.,NoOfFlutes=4,
 MillToolShankType=1,ShoulderLength=7.,ShoulderDia=2.,ShankLength=8.86602542655,Protrusion=20.)
OLD=dict(CutDiameter=20.,EffCutlength=38.,ShankDia=20.,OverallLen=100.,NoOfFlutes=2,
 MillToolShankType=0,ShoulderLength=38.,ShoulderDia=20.,ShankLength=38.,Protrusion=60.)


def profile(lines):
    curves=[dict(index=i,read_complete=True,curve_type=0,start_native=[a[0],0.,a[1]],
                 end_native=[b[0],0.,b[1]]) for i,(a,b) in enumerate(lines)]
    return dict(status='observed',declared_chain_count=1,chains=[dict(index=0,read_complete=True,
                declared_curve_count=len(curves),curves=curves)])


def correct_profile(shank=False):
    lines=g.expected_segments(TARGET,shank_only=shank)
    if not shank:lines=[((0.,0.),(1.,0.))]+lines+[((0.,7.),(1.,7.))]
    return profile(lines)


def full():
    f=dict(tool_native_id=145,tool_type_raw=1,geometry_read_complete=True,profile_complete=True,
           mill_tool=dict(type_raw=1,subtype_raw=3,end_radius_native=0.),
           holder=dict(holder_id_raw=20,number='TEST',name='old.mh',holder_protrusion_native=20.,
                       bottom_diameter_native=25.),profiles={},profile_budget=dict(curves=8,chains=3,islands=0))
    for prop,section,key in g.FIELDS:(f[section] if section else f)[key]=TARGET[prop]
    f['profiles']=dict(tool=correct_profile(),shank=correct_profile(True),
                      holder=profile([((0.,20.),(20.955,20.)),((20.955,20.),(20.955,80.))]))
    return f


def old_full():
    f=full()
    for prop,section,key in g.FIELDS:(f[section] if section else f)[key]=OLD[prop]
    f['holder']['holder_protrusion_native']=60.
    for chain in f['profiles']['holder']['chains']:
        for c in chain['curves']:
            for p in ('start_native','end_native'):c[p][2]+=40.
    return f


def test_correct_taper_and_holder_shift():
    result=g.verify_full_delta(old_full(),full(),TARGET)
    assert result['nominal_raw_cutter_profile_verified'] is True
    assert result['physical_holder_qualified'] is False and result['production_qualified'] is False


@pytest.mark.parametrize('key,value',[
 ('MillToolShankType',0),('MillToolShankType',True),('NoOfFlutes',4.),('NoOfFlutes',0),
 ('CutDiameter',True),('CutDiameter',0),('CutDiameter',float('nan')),
 ('ShoulderDia',3),('ShoulderLength',8),('ShankLength',7),('ShankLength',40),
 ('Protrusion',7),('Protrusion',39),('EffCutlength',38),('OverallLen',8)
])
def test_invalid_target(key,value):
    target=dict(TARGET);target[key]=value
    with pytest.raises(ValueError):g.validate_target(target)


def test_extra_field_rejected():
    with pytest.raises(ValueError):g.validate_target(dict(TARGET,OtherSetter=2))


def test_split_reversed_profile_coverage():
    p=profile([((1.,3.),(1.,0.)),((1.,7.),(1.,3.)),((1.5,8.86602542655),(1.,7.)),
               ((1.5,39.),(1.5,8.86602542655)),((1.,7.),(1.,7.))])
    assert g.verify_profile(p,TARGET)['status']=='PASS'


@pytest.mark.parametrize('mode',['gap','wrong_radius','off_plane','negative_radius','extra_line',
                                'arc','missing_shank','missing_taper','missing_cutting','too_long','missing_count'])
def test_profile_faults(mode):
    p=correct_profile();curves=p['chains'][0]['curves']
    if mode=='gap':curves[1]['end_native'][2]=6.9
    if mode=='wrong_radius':curves[2]['end_native'][0]=1.6
    if mode=='off_plane':curves[1]['start_native'][1]=.1
    if mode=='negative_radius':curves[1]['start_native'][0]=-1
    if mode=='extra_line':curves[4]['end_native']=[2.,0.,7.]
    if mode=='arc':curves[2]['curve_type']=1
    if mode=='missing_shank':curves.pop(3)
    if mode=='missing_taper':curves.pop(2)
    if mode=='missing_cutting':curves.pop(1)
    if mode=='too_long':curves[3]['end_native'][2]=39.01
    if mode=='missing_count':p['declared_chain_count']=2
    p['chains'][0]['declared_curve_count']=len(curves)
    with pytest.raises(ValueError):g.verify_profile(p,TARGET)


def test_native_rounding_within_declared_tolerance():
    f=full();f['mill_tool']['shank_length_native']=8.8660254
    for name in ('tool','shank'):
        for c in f['profiles'][name]['chains'][0]['curves']:
            for pt in ('start_native','end_native'):
                if c[pt][2]==8.86602542655:c[pt][2]=8.8660254
    assert g.verify_full_delta(old_full(),f,TARGET)['nominal_raw_cutter_profile_verified']


@pytest.mark.parametrize('mode',['holder_id','holder_diameter','holder_wrong_shift','holder_shape',
 'unrelated_type','end_radius','wrong_tool_id','partial','target_scalar','flute_float'])
def test_full_delta_rejects_undeclared_changes(mode):
    f=full()
    if mode=='holder_id':f['holder']['holder_id_raw']=21
    if mode=='holder_diameter':f['holder']['bottom_diameter_native']=3
    if mode=='holder_wrong_shift':f['profiles']['holder']['chains'][0]['curves'][0]['start_native'][2]+=1
    if mode=='holder_shape':f['profiles']['holder']['chains'][0]['curves'][0]['end_native'][0]=30
    if mode=='unrelated_type':f['mill_tool']['subtype_raw']=1
    if mode=='end_radius':f['mill_tool']['end_radius_native']=.01
    if mode=='wrong_tool_id':f['tool_native_id']=146
    if mode=='partial':f['profile_complete']=False
    if mode=='target_scalar':f['mill_tool']['shank_diameter_native']=20
    if mode=='flute_float':f['mill_tool']['flute_count_raw']=4.
    with pytest.raises(ValueError):g.verify_full_delta(old_full(),f,TARGET)


class Pointer:
    def __init__(self,values,events,mode='normal'):
        object.__setattr__(self,'data',values);object.__setattr__(self,'events',events)
        object.__setattr__(self,'mode',mode)
    def __setattr__(self,key,value):
        self.events.append(('setter',key,value))
        if self.mode=='exception' and key=='ShankDia':raise RuntimeError('native failure')
        if self.mode=='no_effect' and key=='CutDiameter':return
        self.data[key]=value
        if self.mode=='coupled_target' and key=='EffCutlength':self.data['ShoulderLength']=TARGET['ShoulderLength']
        if self.mode=='coupled_bad' and key=='EffCutlength':self.data['ShoulderLength']=9.
        if self.mode=='rounding' and key=='ShankLength':self.data[key]=8.8660254


def run_batch(mode='normal',fail_guard=False,fail_persist=False):
    data=dict(OLD);events=[];pointer=Pointer(data,events,mode)
    report=dict(field_attempts=[],mutation_attempted=False)
    def guard():
        events.append(('guard',))
        if fail_guard and any(e[0]=='setter' for e in events):raise ValueError('identity changed')
    def persist():
        events.append(('persist',deepcopy(report)))
        if fail_persist and report['mutation_attempted']:raise OSError('receipt unavailable')
    try:
        out=apply_property_batch(targets=dict(ICWTool=pointer,ICWMillTool=pointer),old_values=OLD,
            target=TARGET,read=lambda obj,name:obj.data[name],guard=guard,persist=persist,report=report)
        return out,report,events,None
    except Exception as exc:return data,report,events,exc


@pytest.mark.parametrize('mode',['normal','coupled_target','rounding'])
def test_property_batch_writes_once_and_immediate_readback(mode):
    out,report,events,error=run_batch(mode)
    assert error is None,error
    setters=[e for e in events if e[0]=='setter']
    assert len(setters)==(9 if mode=='coupled_target' else 10)
    assert [e[1] for e in setters]==[x[0] for x in g.FIELDS if not(mode=='coupled_target' and x[0]=='ShoulderLength')]
    assert all(r['readback_verified'] is True for r in report['field_attempts'])
    for index,event in enumerate(events):
        if event[0]=='setter':
            persisted=next(e[1] for e in reversed(events[:index]) if e[0]=='persist')
            assert persisted['mutation_attempted'] is True
            assert persisted['field_attempts'][-1]['native_dispatch_pending'] is True
    assert [e[1] for e in setters].index('EffCutlength')<[e[1] for e in setters].index('Protrusion')
    assert [e[1] for e in setters].index('Protrusion')<[e[1] for e in setters].index('OverallLen')


@pytest.mark.parametrize('mode',['exception','no_effect','coupled_bad'])
def test_property_batch_stops_without_replay(mode):
    out,report,events,error=run_batch(mode)
    assert error is not None
    calls=[e[1] for e in events if e[0]=='setter']
    assert len(calls)==len(set(calls))
    assert len(calls)<10
    if mode=='exception':assert report['native_dispatch_pending'] is True


def test_failed_durable_marker_prevents_native_put():
    _,report,events,error=run_batch(fail_persist=True)
    assert error is not None and not any(e[0]=='setter' for e in events)


def test_identity_failure_after_first_put_stops_batch():
    _,report,events,error=run_batch(fail_guard=True)
    assert error is not None and len([e for e in events if e[0]=='setter'])==1


def test_every_supported_field_has_expected_com_interface():
    assert [x[0] for x in g.FIELDS]==['EffCutlength','ShoulderLength','ShankLength','NoOfFlutes',
      'CutDiameter','ShoulderDia','ShankDia','MillToolShankType','Protrusion','OverallLen']
    assert {x[0] for x in g.FIELDS if x[1] is None}=={'CutDiameter','Protrusion'}


@pytest.fixture
def evidence_case(tmp_path,monkeypatch):
    from scripts import sw_cam_shared_cutter_evidence as e
    import hashlib,json
    part=tmp_path/'Qualification.SLDPRT';part.write_bytes(b'saved')
    source=hashlib.sha256(part.read_bytes()).hexdigest()
    doc=dict(path=str(part),title=part.name,type=1,needs_save=False)
    operations=[dict(native_id=143+i,setup_native_id=93,linked_feature_ids=[79],
        assigned_tool=dict(native_id=145,tool_type_raw=1,is_mill_tool=True,
            native_read_complete=True,cut_diameter_native=20.,protrusion_native=60.)) for i in range(2)]
    state=dict(document=doc,saved_file_sha256=source,operations=operations,sw_reference=dict(solids=[],feature_tree=[]))
    class Base:
        selected=dict(feature_native_id=79,owner_setup_native_id=69)
        operation_ids=[143,144];tool_id=145;pins=[]
        def __init__(self):self.state=deepcopy(state)
        def verify(self,actual):
            if not e._same_inventory(self.state,actual):raise ValueError('base context changed')
        def check_files(self):pass
        def read_stock(self,*a):raise AssertionError('no actual stock reader in synthetic test')
        def summary(self):return dict(scope='saved-test')
    base=Base()
    def detail(f):
        return dict(items=[dict(operation_native_id=i,status='observed',tool_metadata_complete=True,
            full_tool=deepcopy(f)) for i in (143,144)],metadata_read_complete=True,profile_complete=True,
            generic_operation_context_unchanged=True,canonical_state_changed=False)
    old=old_full();details=detail(old)
    report=dict(scope='MILL_SAVED_PLAN_TOOLS_V1',status='review_required',phase='finished',process_id=16516,
        saved_file_sha256=source,anchor=base.summary(),before=deepcopy(state),after=deepcopy(state),
        state_sha256=e._digest(state),before_tool_details=deepcopy(details),after_tool_details=deepcopy(details),
        tool_details_sha256=e._digest(details),
        messages=dict(subscribed=True,disconnected=True,active=False,event_count=0))
    for key in ('read_only','readback_verified','tools_readback_verified','tool_geometry_read_complete','tool_profile_complete'):report[key]=True
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved','save_attempted',
        'tool_assignment_attempted','stock_edit_attempted','material_edit_attempted','TechDB_write_attempted',
        'post_cleanup_CAM_getters','production_qualified'):report[key]=False
    nominal=dict(status='PRIMARY_DOCUMENTED_COHERENT_CUTTER_MAPPING_CANDIDATE_NOT_NATIVE_APPLIED',
        complete_nominal_cutter_candidate=dict(TARGET,EndRadius=0.,MillToolType=1,MillToolSubType=3),
        limits=dict(production_qualified=False))
    paths={}
    for key in ('saved','tools','nominal'):
        p=tmp_path/(key+'.json');p.write_text('{}');paths[key]=str(p)
    def read_pin(path,sha):
        data=report if path==paths['tools'] else nominal
        return deepcopy(data),dict(path=path,sha256=sha)
    monkeypatch.setattr(e,'load_saved_plan_tools_evidence',lambda *a,**kw:base)
    monkeypatch.setattr(e,'read_pin',read_pin)
    args=dict(saved_plan_receipt_path=paths['saved'],saved_plan_receipt_sha256='a'*64,
        tools_receipt_path=paths['tools'],tools_receipt_sha256='b'*64,
        nominal_geometry_receipt_path=paths['nominal'],nominal_geometry_receipt_sha256='c'*64,
        target_geometry=dict(TARGET),process_id=16516,expected_document_path=str(part),
        expected_source_sha256=source,expected_feature_native_id=79,expected_operation_native_ids=[143,144],
        expected_operation_setup_native_id=93,expected_tool_native_id=145)
    return dict(e=e,base=base,report=report,nominal=nominal,args=args,part=part,state=state,detail=detail)


def test_scoped_evidence_load_and_context_delta(evidence_case):
    c=evidence_case;e=c['e'].load_cutter_evidence(**c['args'])
    state=deepcopy(c['state']);state['document']['needs_save']=True
    for op in state['operations']:
        op['assigned_tool']['cut_diameter_native']=2.;op['assigned_tool']['protrusion_native']=20.
    e.verify_after_context(state)
    state['operations'][1]['assigned_tool']['tool_type_raw']=2
    with pytest.raises(ValueError):e.verify_after_context(state)


@pytest.mark.parametrize('key,value',[
 ('tools_readback_verified',False),('tool_profile_complete',False),('process_id',49032),
 ('production_qualified',True),('GOP_attempted',True),('model_saved',True),('state_sha256','x'*64),
 ('tool_details_sha256','x'*64),('saved_file_sha256','x'*64),('issue',{})])
def test_tool_evidence_fail_closed(evidence_case,key,value):
    c=evidence_case;c['report'][key]=value
    with pytest.raises(ValueError):c['e'].load_cutter_evidence(**c['args'])


def test_target_nominal_proof_mismatch(evidence_case):
    c=evidence_case;c['nominal']['complete_nominal_cutter_candidate']['ShankLength']=9.
    with pytest.raises(ValueError):c['e'].load_cutter_evidence(**c['args'])


class Session:
    last=None
    def __init__(self,*a):self.active=False;self.closed=False;self.event=False;self.disconnect_error=False;Session.last=self
    def __enter__(self):self.active=True;return self
    def __exit__(self,*a):self.active=False;self.closed=True
    def summary(self):
        return dict(subscribed=True,active=self.active,disconnected=self.closed,event_count=int(self.event),
                    disconnect_errors=['bad'] if self.disconnect_error else [])


def lifecycle(c,monkeypatch,mode='ok',holder_case=None,save=False):
    from scripts import sw_cam_shared_cutter_config as w
    from scripts import sw_cam_events
    from types import SimpleNamespace
    e=c['e'].load_cutter_evidence(**c['args'])
    monkeypatch.setattr(w,'load_cutter_evidence',lambda **kw:e)
    monkeypatch.setattr(sw_cam_events,'CamMessageSession',Session)
    if mode=='save_cleanup':
        original_exit=Session.__exit__
        def bad_exit(self,*args):
            original_exit(self,*args)
            self.disconnect_error=True
        monkeypatch.setattr(Session,'__exit__',bad_exit)
    current_doc=deepcopy(c['state']['document'])
    if mode=='dirty_before':current_doc['needs_save']=True
    pointer=Pointer(dict(OLD),[],mode='exception' if mode=='native_exception' else 'normal')
    object.__setattr__(pointer,'id',145)
    pointer.data['IsMillTool']=True
    holder=None
    if holder_case is not None:
        holder=SimpleNamespace(name=e.full['holder']['name'])
        holder.GetName=lambda:holder.name
        def set_holder(path):
            pointer.events.append(('holder_setter',path))
            holder.name=path
            return 0
        holder.SetFilePathForUserDefinedHolder=set_holder
        pointer.data['IGetMillToolHolder']=holder
    operations={i:SimpleNamespace(id=i,IGetTool=lambda:pointer) for i in (143,144)}
    def member(obj,name,*args):
        if name=='SaveActiveDocument':
            pointer.events.append(('save',))
            c['part'].write_bytes(b'saved tool state')
            current_doc['needs_save']=False
            return 1 if mode=='save_hresult' else 0
        if name=='GetProcessID':
            if any(x[0]=='setter' for x in pointer.events) and not any(x[0]=='save' for x in pointer.events):current_doc['needs_save']=True
            return 49032 if mode=='pid_before' else 16516
        if isinstance(obj,Pointer):
            if name in pointer.data:return pointer.data[name]
        value=getattr(obj,name)
        return value(*args) if callable(value) else value
    monkeypatch.setattr(w,'_member',member)
    monkeypatch.setattr(w,'_typed',lambda raw,name,path:raw)
    monkeypatch.setattr(w,'_object_id',lambda doc,obj,read:obj.id)
    monkeypatch.setattr(w,'raw_part_identity',lambda sw:deepcopy(current_doc))
    monkeypatch.setattr(w,'_bootstrap',lambda *a:'app')
    def capture(*args,**kwargs):
        kwargs['check']()
        after=any(x[0]=='setter' for x in pointer.events)
        state=deepcopy(c['state'])
        state['document']=deepcopy(current_doc)
        import hashlib
        state['saved_file_sha256']=hashlib.sha256(c['part'].read_bytes()).hexdigest()
        f=full() if after else old_full()
        for prop,section,key in g.FIELDS:(f[section] if section else f)[key]=pointer.data[prop]
        for row in state['operations']:
            row['assigned_tool']['cut_diameter_native']=pointer.data['CutDiameter']
            row['assigned_tool']['protrusion_native']=pointer.data['Protrusion']
        if after and mode=='wrong_profile':f['profiles']['tool']['chains'][0]['curves'][1]['end_native'][0]=9
        if after and mode=='holder_changed':f['holder']['holder_id_raw']=999
        if after and mode=='neighbor_changed':state['sw_reference']['feature_tree']=['new feature']
        if after and mode=='event_after':Session.last.event=True
        if after and mode=='cleanup':Session.last.disconnect_error=True
        if after and holder_case is not None:
            recipe,profile=holder_case
            f['holder']['name']=holder.name
            f['profiles']['holder']=deepcopy(profile)
            if mode=='holder_sweep':
                f['profiles']['holder']['chains'][0]['curves'][1]['mid_native']=[0.2928932188134525,0,21.707106781186546]
        if mode=='save_context' and any(x[0]=='save' for x in pointer.events):
            f['holder']['holder_id_raw']=999
        details=c['detail'](f)
        if after and mode=='partial_after':details['profile_complete']=False
        if not after and mode=='stale_before':details['items'][0]['full_tool']['mill_tool']['overall_length_native']=101
        kwargs['diagnostic']['operation_details']=dict(selected_tool_details=details)
        return state,dict(operations=operations,doc='doc')
    monkeypatch.setattr(w,'capture_selected_plan',capture)
    extra={}
    if holder_case is not None:
        recipe,_=holder_case;a,b=recipe['pins']
        extra=dict(holder_file_path=a['path'],holder_file_sha256=a['sha256'],
                   holder_recipe_path=b['path'],holder_recipe_sha256=b['sha256'])
    result=w.configure_shared_cutter('sw','clsid','tlb',**c['args'],**extra,save_after_verified=save,qualification_only=True,
        acknowledge_disposable_copy=True,receipt_path=str(c['part'].with_name('attempt.json')))
    return result,pointer


def test_complete_batch_verifies_cutter_but_never_holder_or_save(evidence_case,monkeypatch):
    result,pointer=lifecycle(evidence_case,monkeypatch)
    assert result['status']=='review_required',result
    assert result['readback_verified'] is True and result['cutter_profile_readback_verified'] is True
    assert len([x for x in pointer.events if x[0]=='setter'])==10
    for field in ('model_saved','GOP_attempted','GTP_attempted','holder_assignment_performed',
                  'physical_holder_qualified','assembled_tool_qualified','production_qualified'):
        assert result[field] is False
    assert Session.last.closed


@pytest.mark.parametrize('mode',['dirty_before','pid_before','stale_before'])
def test_lifecycle_preflight_failures_make_no_put(evidence_case,monkeypatch,mode):
    result,pointer=lifecycle(evidence_case,monkeypatch,mode)
    assert result['status']=='error'
    assert not any(x[0]=='setter' for x in pointer.events)


@pytest.mark.parametrize('mode',['native_exception','wrong_profile','holder_changed',
                                 'neighbor_changed','event_after','cleanup','partial_after'])
def test_lifecycle_failure_after_put_is_uncertain_no_save(evidence_case,monkeypatch,mode):
    result,pointer=lifecycle(evidence_case,monkeypatch,mode)
    assert result['status']=='uncertain',result
    assert result['readback_verified'] is False and result['cutter_profile_readback_verified'] is False
    assert result['model_saved'] is False and result['GTP_attempted'] is False
    assert Session.last.closed
    names=[x[1] for x in pointer.events if x[0]=='setter']
    assert len(names)==len(set(names))


def test_explicit_rebind_preserves_historical_tool_proof(evidence_case,monkeypatch):
    c=evidence_case;base=c['base'];old_summary=base.summary()
    base.historical_process_id=16516;base.bound_process_id=13484
    base.historical_summary=lambda:old_summary
    base.summary=lambda:dict(scope='new-session',historical=old_summary)
    seen={}
    def loader(*args,**kwargs):seen.update(kwargs);return base
    monkeypatch.setattr(c['e'],'load_saved_plan_tools_evidence',loader)
    args=dict(c['args'],process_id=13484,session_rebind_receipt_path='rebind.json',
              session_rebind_receipt_sha256='d'*64)
    result=c['e'].load_cutter_evidence(**args)
    assert result.tools['process_id']==16516 and seen['process_id']==13484
    assert seen['session_rebind_receipt_path']=='rebind.json'
    c['report']['process_id']=13484
    with pytest.raises(ValueError):c['e'].load_cutter_evidence(**args)


def test_incomplete_rebind_pair_rejected(evidence_case):
    c=evidence_case
    with pytest.raises(ValueError):
        c['e'].load_cutter_evidence(**dict(c['args'],session_rebind_receipt_path='rebind.json'))


def test_new_package_contains_no_save_or_toolpath_dispatch():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    forbidden={'Save','Save3','SaveAs','GOP','GTP','EMF','GenerateToolpath','WriteInLibrary'}
    for name in ('sw_cam_shared_cutter_config.py','sw_cam_shared_cutter_evidence.py','sw_cam_shared_cutter_geometry.py'):
        tree=ast.parse((root/'scripts'/name).read_text(encoding='utf-8'))
        for call in [n for n in ast.walk(tree) if isinstance(n,ast.Call)]:
            func=call.func.attr if isinstance(call.func,ast.Attribute) else call.func.id if isinstance(call.func,ast.Name) else ''
            assert func not in forbidden
            if func in ('_member','read'):
                assert not any(isinstance(a,ast.Constant) and isinstance(a.value,str) and a.value in forbidden for a in call.args)


def test_actual_server_import_and_schema(evidence_case):
    import ast,json,os,subprocess,sys,scripts
    from pathlib import Path
    c=evidence_case;root=Path(__file__).resolve().parents[1]
    server=root/'mcp-server/server.py'
    tree=ast.parse(server.read_text(encoding='utf-8'))
    assert len([n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SolidWorksCamSharedCutterConfigInput'])==1
    payload=dict(c['args'],addin_clsid='{00000000-0000-0000-0000-000000000001}',
                 qualification_only=True,acknowledge_disposable_copy=True,
                 receipt_path=str(c['part'].with_name('schema_attempt.json')))
    code="""import sys,runpy,json
sys.path[:]=json.loads(sys.argv[2])
import scripts
scripts.__path__[:]=json.loads(sys.argv[3])
n=runpy.run_path(sys.argv[1],run_name='cutter_schema_import')
assert n['_automation_loaded'] is False and n['_selected_process_id'] is None
assert 'solidworks_cam_configure_saved_shared_cutter' in n['mcp']._tool_manager._tools
schema=n['SolidWorksCamSharedCutterConfigInput'];p=json.loads(sys.argv[4])
schema.model_validate(p)
schema.model_validate(dict(p,save_after_verified=True))
for bad_save in ('true',1,None):
    try:schema.model_validate(dict(p,save_after_verified=bad_save))
    except ValueError:pass
    else:raise AssertionError('save policy must be strict bool')
for key,value in [('Protrusion',60),('NoOfFlutes',True),('MillToolShankType',0),('ShankLength',0),('ShoulderDia',20)]:
    bad=dict(p);bad['target_geometry']=dict(p['target_geometry']);bad['target_geometry'][key]=value
    try:schema.model_validate(bad)
    except ValueError:pass
    else:raise AssertionError('schema accepted '+key)
print('FULL_SERVER_SCHEMA_PASS')
"""
    result=subprocess.run([sys.executable,'-c',code,str(server),json.dumps(sys.path),
        json.dumps(list(scripts.__path__)),json.dumps(payload)],capture_output=True,text=True,timeout=45,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'FULL_SERVER_SCHEMA_PASS' in result.stdout


def test_runtime_identity_delegated_to_saved_session(evidence_case):
    c=evidence_case;calls=[]
    c['base'].check_runtime_identity=lambda:calls.append('checked')
    evidence=c['e'].load_cutter_evidence(**c['args'])
    evidence.check_runtime_identity()
    assert calls==['checked']

def test_changed_owned_session_rejected_before_first_put(evidence_case,monkeypatch):
    c=evidence_case
    def fail():
        raise ValueError('Owned process creation identity changed')
    c['base'].check_runtime_identity=fail
    result,pointer=lifecycle(c,monkeypatch)
    assert result['status']=='error' and result['mutation_attempted'] is False
    assert not any(x[0]=='setter' for x in pointer.events)


@pytest.mark.parametrize('mode',['ok','holder_sweep'])
def test_complete_cutter_and_holder_batch(evidence_case,monkeypatch,mode):
    from test_sw_cam_shared_holder_geometry import build_case
    case=build_case(evidence_case['part'].parent)
    out,pointer=lifecycle(evidence_case,monkeypatch,mode,holder_case=case)
    assert len([x for x in pointer.events if x[0]=='setter'])==10
    assert len([x for x in pointer.events if x[0]=='holder_setter'])==1
    assert out['holder_assignment_performed'] is True
    assert out['model_saved'] is False and out['GTP_attempted'] is False
    assert Session.last.closed
    if mode=='ok':
        assert out['readback_verified'] is True,out
        assert out['profile_comparison']['holder_profile_comparison']['native_holder_shape_verified']
    else:
        assert out['status']=='uncertain' and out['readback_verified'] is False,out


@pytest.mark.parametrize('mode',['ok','save_hresult','save_context','save_cleanup','holder_sweep'])
def test_combined_batch_native_save_gate(evidence_case,monkeypatch,mode):
    from test_sw_cam_shared_holder_geometry import build_case
    case=build_case(evidence_case['part'].parent)
    out,pointer=lifecycle(evidence_case,monkeypatch,mode,holder_case=case,save=True)
    saves=[x for x in pointer.events if x[0]=='save']
    assert len(saves)==(0 if mode=='holder_sweep' else 1)
    assert out['GTP_attempted'] is False and Session.last.closed
    if mode=='ok':
        assert out['status']=='review_required' and out['save_readback_verified'] and out['model_saved'],out
        assert out['continuation_state']['document']['needs_save'] is False
        assert out['source_after_sha256']!=out['source_before_sha256']
    else:
        assert out['status']=='uncertain' and not out['model_saved'],out
