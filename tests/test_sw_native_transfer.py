"""限定原生副本迁移的离线回归；不连接 SOLIDWORKS。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_native_transfer as transfer


@pytest.fixture
def graph(tmp_path, monkeypatch):
    source=tmp_path/'source.sldprt'; source.write_bytes(b'original native')
    donor=tmp_path/'donor.step'; donor.write_bytes(b'approved donor')
    anchor_path=tmp_path/'anchor.sldprt'; anchor_path.write_bytes(b'anchor')
    template=tmp_path/'template.prtdot'; template.write_bytes(b'template')
    output=tmp_path/'output.sldprt'; step=tmp_path/'roundtrip.step'; receipt=tmp_path/'receipt.json'
    state=dict(donor_volume=6., on_insert=None, on_boolean=None, fail_save=False, disk={}, calls=[])
    class Body:
        def __init__(self, volume, model=None): self.volume=volume; self.model=model; self.Check3=N(Count=0)
        def GetMassProperties(self, density): return [0.,0.,0.,self.volume]+[0.]*8
        def GetBodyBox(self): return [0.,0.,0.,1.,1.,1.]
        def Copy(self): return Body(self.volume)
        def Select2(self, append, data):
            assert append is False and data.Mark==0
            self.model.selected=self; return True
    class Model:
        def __init__(self,path,volume=10.,features=None):
            self.path=str(path); self.Visible=False; self.dirty=False; self.selected=None
            self.bodies=[Body(volume,self)]; self.features=features or ['original datum','original geometry']
            self.FeatureManager=N(InsertDeleteBody2=self.delete,InsertCombineFeature=self.combine)
            self.SelectionManager=N(CreateSelectData=lambda:N(Mark=None),
                GetSelectedObjectCount2=lambda mark:int(self.selected is not None),
                GetSelectedObject6=lambda index,mark:self.selected)
        def GetPathName(self): return self.path
        def GetTitle(self): return Path(self.path).name
        def GetSaveFlag(self): return self.dirty
        def GetType(self): return 1
        def GetBodies2(self, kind, visible): return self.bodies if kind==0 else []
        def FirstFeature(self):
            items=[N(Name=name,GetTypeName2=lambda:'native feature') for name in self.features]
            for i,item in enumerate(items): item.GetNextFeature=lambda i=i:items[i+1] if i+1<len(items) else None
            return items[0] if items else None
        def CreateFeatureFromBody3(self, body, surface, options):
            assert surface is False and options==1
            state['calls'].append('insert'); body.model=self; self.bodies.append(body)
            self.features.append('donor insertion'); self.dirty=True
            if state['on_insert']:return state['on_insert'](self)
            return N(Name='donor insertion')
        def delete(self, keep):
            assert keep is False and self.selected is self.bodies[0]
            state['calls'].append('delete'); self.bodies.remove(self.selected); self.features.append('delete original body')
            if state['on_boolean']:state['on_boolean'](self)
            return object()
        def combine(self, kind, main, tools):
            state['calls'].append(('combine',kind,main,tools.value))
            if kind==15902:
                assert main is self.bodies[0] and tools.value==tuple(self.bodies[1:])
                value=main.volume-sum(body.volume for body in tools.value)
            else:
                assert kind==15903 and main.value is None and tools.value==tuple(self.bodies)
                value=sum(body.volume for body in tools.value)
            self.bodies=[Body(value,self)]; self.features.append('local boolean')
            if state['on_boolean']:state['on_boolean'](self)
            return object()
        def ClearSelection2(self, all): self.selected=None
        def ForceRebuild3(self, top): return False
    anchor=Model(anchor_path); anchor.Visible=True
    prefs={(kind,num):value for kind,num,value in transfer._IMPORT_PREFS}
    prefs['Toggle',691]=True
    sw=N(pid=71,UserControl=True,ActiveDoc=anchor,docs=[anchor])
    sw.GetProcessID=lambda:sw.pid; sw.GetDocuments=lambda:list(sw.docs)
    sw.GetUserPreferenceStringValue=lambda num:str(template)
    for kind in ('Toggle','IntegerValue'):
        setattr(sw,'GetUserPreference'+kind,lambda num,kind=kind:prefs[kind,num])
        setattr(sw,'SetUserPreference'+kind,lambda num,value,kind=kind:prefs.__setitem__((kind,num),value))
    sw.IsSame=lambda a,b:1 if a is b else 0
    sw.GetOpenDocumentByName=lambda path:next((m for m in sw.docs if m.path==str(path)),None)
    def close(title):
        model=next(m for m in sw.docs if m.GetTitle()==title);sw.docs.remove(model)
        if sw.ActiveDoc is model:sw.ActiveDoc=anchor
    sw.CloseDoc=close
    def open_model(sw_arg,path,step=False,observed=None,import_settings_observed=None):
        assert sw_arg is sw
        if step:volume=state['donor_volume'];features=None
        else:volume,features=state['disk'].get(str(path),(10.,None))
        model=Model(path,volume,deepcopy(features))
        if step and state.get('donor_volumes') is not None:
            model.bodies=[Body(value,model) for value in state['donor_volumes']]
        sw.docs.append(model)
        metadata=dict(errors=0,warnings=0,path=str(path),title=model.GetTitle())
        if observed:observed(metadata)
        return model,metadata
    def save(model,path=None):
        state['calls'].append('save' if path is None else 'export')
        if state['fail_save']:raise RuntimeError('native save failed')
        if path is None:
            Path(model.path).write_text('native '+str(model.bodies[0].volume));model.dirty=False
            state['disk'][model.path]=(model.bodies[0].volume,deepcopy(model.features))
        else:Path(path).write_bytes(b'roundtrip STEP')
        return dict(native_return=True,errors=0,warnings=0)
    import scripts.sw_assembly as assembly
    def activate(sw_arg,model):sw_arg.ActiveDoc=model;return True
    monkeypatch.setattr(assembly,'_activate_model_document',activate)
    monkeypatch.setattr(transfer,'_open',open_model);monkeypatch.setattr(transfer,'_save',save)
    import win32com.client
    monkeypatch.setattr(win32com.client,'VARIANT',lambda kind,value:N(value=value))
    defaults=dict(process_id=71,expected_document_path=str(anchor_path),action='prepare',mode='replace_body',
        source_path=str(source),source_sha256=transfer._file_hash(source),donor_step_path=str(donor),
        donor_sha256=transfer._file_hash(donor),output_path=str(output),roundtrip_step_path=str(step),qualification_only=True)
    def run(**kw):return transfer.qualify_part_transfer(sw,**(defaults|kw))
    def apply(**kw):
        prepared=run(**kw);assert prepared['status']=='ok',prepared
        return run(**(kw|dict(action='apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(receipt))))
    return N(**locals())


def test_prepare_has_no_file_or_geometry_mutation(graph):
    p=graph;result=p.run()
    assert result['apply_eligible'] and result['status']=='ok'
    assert not p.output.exists() and not p.receipt.exists() and not p.state['calls']
    assert p.sw.docs==[p.anchor] and p.prefs['Toggle',691] is True


def test_replace_body_preserves_source_and_deletes_only_original_after_insert(graph):
    p=graph;result=p.apply()
    assert result['status']=='review_required' and result['body_transfer_verified'],result
    assert result['reopened_verified'] and result['source_files_unchanged']
    assert result['copied_source_sha256']==p.defaults['source_sha256']
    assert p.state['calls']==['insert','delete','save','export']
    assert result['body_reopened']['bodies'][0]['volume_m3']==6.
    assert not result['internal_document_id_verified'] and not result['independent_geometry_equivalence_verified']
    assert p.source.read_bytes()==b'original native' and p.donor.read_bytes()==b'approved donor'
    assert p.sw.docs==[p.anchor] and p.anchor.Visible and p.prefs['Toggle',691] is True
    assert json.loads(p.receipt.read_text())['body_transfer_verified']


@pytest.mark.parametrize('mode,kind,volume',[('add_delta',15903,12.),('subtract_delta',15902,8.)])
def test_local_boolean_has_exact_enum_main_and_tool_bodies(graph,mode,kind,volume):
    p=graph;p.state['donor_volume']=2.
    result=p.apply(mode=mode,acknowledge_delta_only=True)
    assert result['body_transfer_verified'],result
    assert result['local_volume_delta_verified'] and result['body_after']['bodies'][0]['volume_m3']==volume
    assert p.state['calls'][1][0:2]==('combine',kind)


@pytest.mark.parametrize('change',['pid','dirty','usercontrol','source_open','wrong_anchor','source_hash','donor_hash','existing_output','wrong_ack','invalid_mode','bool_pid'])
def test_preflight_rejects_before_copy_or_native_mutation(graph,change):
    p=graph;kw={}
    if change=='pid':p.sw.pid=72
    elif change=='dirty':p.anchor.dirty=True
    elif change=='usercontrol':p.sw.UserControl=False
    elif change=='source_open':p.sw.docs.append(p.Model(p.source))
    elif change=='wrong_anchor':p.sw.ActiveDoc=p.Model(p.source)
    elif change=='source_hash':kw['source_sha256']='0'*64
    elif change=='donor_hash':kw['donor_sha256']='0'*64
    elif change=='existing_output':p.output.write_bytes(b'keep')
    elif change=='wrong_ack':kw['mode']='subtract_delta'
    elif change=='invalid_mode':kw['mode']='raw'
    else:kw['process_id']=True
    result=p.run(**kw)
    assert result['status']=='error' and not result['mutation_attempted']
    assert not p.state['calls'] and not p.receipt.exists()
    if change=='existing_output':assert p.output.read_bytes()==b'keep'


def test_changed_prepared_hash_does_not_create_output(graph):
    p=graph;result=p.run(action='apply',expected_state_sha256='0'*64,receipt_path=str(p.receipt))
    assert not result['mutation_attempted'] and not p.output.exists()


def test_existing_receipt_is_never_overwritten(graph):
    p=graph;p.receipt.write_bytes(b'keep')
    result=p.apply();assert not result['mutation_attempted'] and p.receipt.read_bytes()==b'keep'


def test_null_insert_stops_no_boolean_save_or_retry_and_restores_preferences(graph):
    p=graph;p.state['on_insert']=lambda model:None
    result=p.apply()
    assert result['status']=='uncertain' and p.state['calls']==['insert']
    assert not result['body_transfer_verified'] and p.output.exists()
    assert p.prefs['Toggle',691] is True and p.source.read_bytes()==b'original native'
    durable=json.loads(p.receipt.read_text())
    insertion=next(row for row in durable['native_calls'] if row['name']=='CreateFeatureFromBody3')
    assert insertion==dict(name='CreateFeatureFromBody3',attempted=True,returned=True)


def test_wrong_boolean_volume_stops_before_save(graph):
    p=graph;p.state['donor_volume']=2.;p.state['on_boolean']=lambda model:setattr(model.bodies[0],'volume',11.)
    result=p.apply(mode='add_delta',acknowledge_delta_only=True)
    assert result['status']=='uncertain' and 'save' not in p.state['calls']


def test_save_failure_keeps_new_copy_and_never_closes_or_retries(graph):
    p=graph;p.state['fail_save']=True;result=p.apply()
    assert result['status']=='uncertain' and p.state['calls'].count('save')==1
    assert len(p.sw.docs)==3 and p.source.read_bytes()==b'original native'


def test_durable_intent_precedes_native_insertion(graph):
    p=graph
    def after_insert(model):
        value=json.loads(p.receipt.read_text())
        row=value['native_calls'][-1]
        assert row==dict(name='CreateFeatureFromBody3',attempted=True,returned=False)
        return object()
    p.state['on_insert']=after_insert
    assert p.apply()['body_transfer_verified']


def reference_args(graph):
    p=graph;source=p.tmp_path/'source.sldasm';source.write_bytes(b'original assembly')
    old=p.source;new=p.tmp_path/'new_part.sldprt';new.write_bytes(b'qualified copied part')
    output=p.tmp_path/'new_assembly.sldasm'
    args=dict(process_id=71,expected_document_path=str(p.anchor_path),action='prepare',source_path=str(source),
        source_sha256=transfer._file_hash(source),output_path=str(output),qualification_only=True,
        replacements=[dict(old_path=str(old),old_sha256=transfer._file_hash(old),new_path=str(new),new_sha256=transfer._file_hash(new))])
    return source,output,args


def test_closed_copy_replaces_only_explicit_refs_and_does_not_claim_animation(graph):
    p=graph;source,output,args=reference_args(p)
    def replace(path,old,new):
        durable=json.loads(p.receipt.read_text());assert durable['replacements'][-1]['attempted'] and not durable['replacements'][-1]['returned']
        assert path==str(output) and source.read_bytes()==b'original assembly'
        output.write_bytes(b'relinked assembly');return True
    p.sw.ReplaceReferencedDocument=Mock(side_effect=replace)
    ready=transfer.qualify_reference_copy(p.sw,**args)
    result=transfer.qualify_reference_copy(p.sw,**(args|dict(action='apply',expected_state_sha256=ready['state_sha256'],receipt_path=str(p.receipt))))
    assert result['native_reference_calls_returned'] and not result['reference_replacements_verified']
    assert not result['animation_verified'] and not result['assembly_identity_verified']
    assert result['status']=='review_required' and p.sw.ReplaceReferencedDocument.call_count==1
    assert p.sw.docs==[p.anchor]


def test_false_closed_replacement_stops_remaining_calls(graph):
    p=graph;source,output,args=reference_args(p)
    second_old=p.tmp_path/'old2.sldprt';second_old.write_bytes(b'old2')
    second_new=p.tmp_path/'new2.sldprt';second_new.write_bytes(b'new2')
    args['replacements'].append(dict(old_path=str(second_old),old_sha256=transfer._file_hash(second_old),new_path=str(second_new),new_sha256=transfer._file_hash(second_new)))
    p.sw.ReplaceReferencedDocument=Mock(return_value=False)
    ready=transfer.qualify_reference_copy(p.sw,**args)
    result=transfer.qualify_reference_copy(p.sw,**(args|dict(action='apply',expected_state_sha256=ready['state_sha256'],receipt_path=str(p.receipt))))
    assert result['status']=='uncertain' and p.sw.ReplaceReferencedDocument.call_count==1
    assert len(result['replacements'])==1 and result['replacements'][0]['returned']


@pytest.mark.parametrize('invalid',['old_hash','new_hash','source_open','replacement_open','duplicate','chain','type','zero'])
def test_closed_copy_guards_before_mutation(graph,invalid):
    p=graph;source,output,args=reference_args(p)
    if invalid=='old_hash':args['replacements'][0]['old_sha256']='0'*64
    elif invalid=='new_hash':args['replacements'][0]['new_sha256']='0'*64
    elif invalid=='source_open':p.sw.docs.append(p.Model(source))
    elif invalid=='replacement_open':p.sw.docs.append(p.Model(args['replacements'][0]['new_path']))
    elif invalid=='duplicate':args['replacements']*=2
    elif invalid=='chain':args['replacements'].append({**args['replacements'][0], 'old_path':args['replacements'][0]['new_path'], 'old_sha256':args['replacements'][0]['new_sha256'],'new_path':str(p.anchor_path),'new_sha256':transfer._file_hash(p.anchor_path)})
    elif invalid=='type':args['replacements'][0]['new_path']=str(source)
    else:args['replacements']=[]
    p.sw.ReplaceReferencedDocument=Mock()
    result=transfer.qualify_reference_copy(p.sw,**args)
    assert result['status']=='error' and not output.exists()
    p.sw.ReplaceReferencedDocument.assert_not_called()


@pytest.mark.parametrize('mode,volume',[('add_delta',12.),('subtract_delta',8.)])
def test_two_delta_solids_are_both_inserted_and_used_by_one_boolean(graph,mode,volume):
    p=graph;p.state['donor_volumes']=[.75,1.25]
    result=p.apply(mode=mode,acknowledge_delta_only=True)
    assert result['body_transfer_verified'],result
    assert result['inserted_bodies']['solid_count']==3 and result['body_after']['bodies'][0]['volume_m3']==volume
    assert p.state['calls'].count('insert')==2
    combines=[row for row in p.state['calls'] if isinstance(row,tuple)]
    assert len(combines)==1


def test_second_delta_step_reuses_only_receipt_bound_copy_and_retains_prior_receipt(graph):
    p=graph;p.state['donor_volume']=2.
    first=p.apply(mode='subtract_delta',acknowledge_delta_only=True)
    assert first['body_transfer_verified'], first
    previous=p.receipt.read_bytes();previous_sha=transfer._file_hash(p.receipt)
    donor2=p.tmp_path/'delta_add.step';donor2.write_bytes(b'approved second local delta')
    p.state['donor_volumes']=[.75,1.25]
    options=dict(mode='add_delta',acknowledge_delta_only=True,donor_step_path=str(donor2),
        donor_sha256=transfer._file_hash(donor2),roundtrip_step_path=str(p.tmp_path/'roundtrip2.step'),
        prior_transfer_receipt_path=str(p.receipt),prior_transfer_receipt_sha256=previous_sha)
    ready=p.run(**options);assert ready['status']=='ok',ready
    result=p.run(**(options|dict(action='apply',expected_state_sha256=ready['state_sha256'],receipt_path=str(p.tmp_path/'receipt2.json'))))
    assert result['body_transfer_verified'] and result['body_after']['bodies'][0]['volume_m3']==10.,result
    assert result['continuation_of_verified_copy']['input_sha256']==first['output_sha256']
    assert p.receipt.read_bytes()==previous and p.source.read_bytes()==b'original native'
    assert len(list(p.tmp_path.glob('output*.sldprt')))==1


@pytest.mark.parametrize('bad',['receipt_hash','output_hash','wrong_source','unverified','missing_sha'])
def test_continuation_rejects_unproven_lineage_before_native_changes(graph,bad):
    p=graph;p.state['donor_volume']=2.
    first=p.apply(mode='subtract_delta',acknowledge_delta_only=True)
    assert first['body_transfer_verified'], first
    prior=json.loads(p.receipt.read_text())
    if bad=='unverified':prior['body_transfer_verified']=False;p.receipt.write_text(json.dumps(prior))
    if bad=='wrong_source':prior['before']['config']['source_path']=str(p.donor);p.receipt.write_text(json.dumps(prior))
    if bad=='output_hash':p.output.write_bytes(b'foreign modification')
    donor2=p.tmp_path/'donor2.step';donor2.write_bytes(b'new delta')
    options=dict(mode='add_delta',acknowledge_delta_only=True,donor_step_path=str(donor2),donor_sha256=transfer._file_hash(donor2),
        roundtrip_step_path=str(p.tmp_path/'roundtrip2.step'),prior_transfer_receipt_path=str(p.receipt),
        prior_transfer_receipt_sha256=None if bad=='missing_sha' else '0'*64 if bad=='receipt_hash' else transfer._file_hash(p.receipt))
    calls=list(p.state['calls']);result=p.run(**options)
    assert result['status']=='error' and not result['mutation_attempted']
    assert p.state['calls']==calls


def _saved_pending_export(p, monkeypatch):
    """构造与活体同阶段的保存/重开成功、STEP 未尝试回执。"""
    import scripts.sw_assembly as assembly
    original = assembly._activate_model_document
    counter = [0]
    def activate(sw, model):
        counter[0] += 1
        return False if counter[0] == 2 else original(sw, model)
    monkeypatch.setattr(assembly, '_activate_model_document', activate)
    partial = p.apply(mode='add_delta', acknowledge_delta_only=True)
    assert partial['status'] == 'uncertain' and partial['output_sha256']
    assert not p.step.exists() and p.state['calls'].count('save') == 1
    assert not any(row['name'] == 'export_roundtrip_step' for row in partial['native_calls'])
    monkeypatch.setattr(assembly, '_activate_model_document', original)
    args = dict(process_id=71, expected_document_path=str(p.anchor_path),
        transfer_receipt_path=str(p.receipt), transfer_receipt_sha256=transfer._file_hash(p.receipt),
        expected_output_sha256=partial['output_sha256'], expected_anchor_sha256=transfer._file_hash(p.anchor_path),
        receipt_path=str(p.tmp_path/'finalize.json'))
    return partial, args


def test_finalize_saved_copy_exports_without_geometry_or_save_replay(graph, monkeypatch):
    p=graph;partial,args=_saved_pending_export(p,monkeypatch)
    original_receipt=p.receipt.read_bytes(); original_output=p.output.read_bytes()
    calls=list(p.state['calls'])
    for model in p.sw.docs:
        model.CreateFeatureFromBody3=Mock(side_effect=AssertionError('no insert replay'))
        model.FeatureManager.InsertCombineFeature=Mock(side_effect=AssertionError('no boolean replay'))
        model.ForceRebuild3=Mock(side_effect=AssertionError('no rebuild'))
    save=transfer._save
    def export_only(model,path=None):
        assert path == p.step
        durable=json.loads(Path(args['receipt_path']).read_text())
        assert durable['native_calls'][-1]==dict(name='export_roundtrip_step',attempted=True,returned=False)
        return save(model,path)
    monkeypatch.setattr(transfer,'_save',export_only)
    result=transfer.finalize_part_transfer(p.sw,**args)
    assert result['status']=='review_required' and result['finalization_verified'],result
    assert result['body_transfer_verified'] and not result['geometry_mutation_attempted']
    assert p.state['calls']==calls+['export']
    assert p.receipt.read_bytes()==original_receipt and p.output.read_bytes()==original_output
    assert p.sw.docs==[p.anchor] and p.anchor.Visible
    assert not result['independent_geometry_equivalence_verified']


@pytest.mark.parametrize('bad',['receipt_sha','output_sha','anchor_sha','save_proof','reopen_proof',
    'export_attempted','dirty_output','volume','features','existing_step','wrong_pid','foreign_active'])
def test_finalize_rejects_unverified_checkpoint_before_export(graph,monkeypatch,bad):
    p=graph;partial,args=_saved_pending_export(p,monkeypatch)
    model=p.sw.GetOpenDocumentByName(str(p.output))
    if bad=='receipt_sha':args['transfer_receipt_sha256']='0'*64
    elif bad=='output_sha':args['expected_output_sha256']='0'*64
    elif bad=='anchor_sha':args['expected_anchor_sha256']='0'*64
    elif bad in ('save_proof','reopen_proof','export_attempted'):
        data=json.loads(p.receipt.read_text())
        if bad=='export_attempted':data['native_calls'].append(dict(name='export_roundtrip_step',attempted=True,returned=False))
        else:
            name='Save3' if bad=='save_proof' else 'reopen_saved_copy'
            next(row for row in data['native_calls'] if row['name']==name)['returned']=False
        p.receipt.write_text(json.dumps(data));args['transfer_receipt_sha256']=transfer._file_hash(p.receipt)
    elif bad=='dirty_output':model.dirty=True
    elif bad=='volume':model.bodies[0].volume+=1.
    elif bad=='features':model.features.append('unexpected feature')
    elif bad=='existing_step':p.step.write_bytes(b'keep existing export')
    elif bad=='wrong_pid':p.sw.pid=72
    else:p.sw.ActiveDoc=p.Model(p.source)
    calls=list(p.state['calls']);original=p.receipt.read_bytes()
    result=transfer.finalize_part_transfer(p.sw,**args)
    assert result['status']=='error' and not result['mutation_attempted'],result
    assert p.state['calls']==calls and p.receipt.read_bytes()==original
    assert not Path(args['receipt_path']).exists()


def test_finalize_reopens_only_exact_hash_bound_absent_anchor(graph,monkeypatch):
    p=graph;partial,args=_saved_pending_export(p,monkeypatch)
    p.sw.docs.remove(p.anchor);p.sw.ActiveDoc=p.sw.GetOpenDocumentByName(str(p.output))
    args['expected_document_path']=str(p.output)
    result=transfer.finalize_part_transfer(p.sw,**args)
    assert result['finalization_verified'],result
    assert p.sw.ActiveDoc.path==str(p.anchor_path) and p.sw.ActiveDoc is not p.anchor
    assert sum(row['name']=='reopen_exact_anchor' for row in result['native_calls'])==1
    assert p.state['calls'].count('save')==1 and p.state['calls'].count('insert')==1


def test_normal_transfer_reacquires_anchor_and_donor_after_document_lifecycle(graph,monkeypatch):
    p=graph;close=p.sw.CloseDoc;expired=[]
    old_set=p.Model.__setattr__;old_path=p.Model.GetPathName
    def setattr_checked(model,name,value):
        if name=='Visible' and getattr(model,'expired',False):raise RuntimeError('stale COM visibility')
        return old_set(model,name,value)
    def path_checked(model):
        if getattr(model,'expired',False):raise RuntimeError('stale COM document')
        return old_path(model)
    monkeypatch.setattr(p.Model,'__setattr__',setattr_checked)
    monkeypatch.setattr(p.Model,'GetPathName',path_checked)
    def lifecycle(title):
        close(title)
        if title==p.output.name:
            replacements=[]
            for model in p.sw.docs:
                fresh=p.Model(model.path,model.bodies[0].volume,deepcopy(model.features))
                fresh.Visible=model.Visible;fresh.dirty=model.dirty
                model.expired=True;expired.append(model);replacements.append(fresh)
                if p.sw.ActiveDoc is model:p.sw.ActiveDoc=fresh
            p.sw.docs=replacements
    p.sw.CloseDoc=lifecycle
    result=p.apply()
    assert result['body_transfer_verified'],result
    assert len(expired)>=3 and all(model not in p.sw.docs for model in expired)
    assert p.sw.ActiveDoc.path==str(p.anchor_path) and p.sw.ActiveDoc.Visible


def test_finalize_exclusive_receipt_race_never_overwrites_existing_file(graph,monkeypatch):
    p=graph;partial,args=_saved_pending_export(p,monkeypatch)
    writer=transfer._write_receipt;target=Path(args['receipt_path'])
    def collide(path,report,create=False):
        if create and Path(path)==target:
            target.write_bytes(b'concurrent receipt must survive')
            raise FileExistsError('receipt created concurrently')
        return writer(path,report,create=create)
    monkeypatch.setattr(transfer,'_write_receipt',collide)
    calls=list(p.state['calls']);result=transfer.finalize_part_transfer(p.sw,**args)
    assert result['status']=='error' and not result['mutation_attempted']
    assert p.state['calls']==calls and target.read_bytes()==b'concurrent receipt must survive'


def test_diagnostic_volume_keeps_strict_tolerance_and_requires_step_proof(graph):
    p=graph;p.state['donor_volume']=2.;p.state['on_boolean']=lambda model:setattr(model.bodies[0],'volume',11.)
    result=p.apply(mode='add_delta',acknowledge_delta_only=True,delta_volume_policy='diagnostic')
    assert result['body_transfer_verified'],result
    assert result['local_volume_delta_verified'] is False
    assert result['volume_comparison_relative_tolerance']==1e-7
    assert result['delta_volume_diagnostic']==dict(policy='diagnostic',before_m3=10.,donor_m3=[2.],
        after_m3=11.,expected_m3=12.,relative_error=1/12)
    assert result['independent_step_comparison_required'] and not result['independent_geometry_equivalence_verified']
    assert result['may_continue'] is False and result['production_release'] is False


def _saved_cut_cleanup(p):
    p.state['donor_volume']=2.;p.state['on_boolean']=lambda model:setattr(model.bodies[0],'volume',7.9)
    failed=p.apply(mode='subtract_delta',acknowledge_delta_only=True)
    assert failed['status']=='uncertain' and not any(row['name']=='Save3' for row in failed['native_calls'])
    model=p.sw.GetOpenDocumentByName(str(p.output));assert model.dirty
    p.save(model)  # 模拟调用方明确单独执行的保存，不由 cleanup 触发。
    args=dict(process_id=71,transfer_receipt_path=str(p.receipt),
        transfer_receipt_sha256=transfer._file_hash(p.receipt),expected_output_current_sha256=transfer._file_hash(p.output),
        receipt_path=str(p.tmp_path/'cleanup.json'))
    return model,args


def test_cleanup_closes_only_saved_owned_copy_and_unsaved_donor_with_no_active_doc(graph,monkeypatch):
    p=graph;model,args=_saved_cut_cleanup(p)
    prior=json.loads(p.receipt.read_text());donor=p.sw.GetOpenDocumentByName(prior['donor_stage_path'])
    title=donor.GetTitle();donor.path='';donor.GetTitle=lambda:title
    prior['open_donor']['path']='';p.receipt.write_text(json.dumps(prior))
    args['transfer_receipt_sha256']=transfer._file_hash(p.receipt)
    p.sw.ActiveDoc=None;original=p.receipt.read_bytes();saved=p.output.read_bytes();calls=list(p.state['calls'])
    monkeypatch.setattr(transfer,'_save',Mock(side_effect=AssertionError('cleanup must not save/export')))
    result=transfer.cleanup_part_transfer(p.sw,**args)
    assert result['cleanup_verified'] and result['status']=='review_required',result
    assert not result['geometry_verified'] and not result['geometry_mutation_attempted']
    assert p.state['calls']==calls and p.receipt.read_bytes()==original and p.output.read_bytes()==saved
    assert p.sw.docs==[p.anchor] and p.sw.ActiveDoc is p.anchor and p.anchor.Visible
    assert [row['name'] for row in result['native_calls']]==['close_saved_owned_output','close_owned_donor','restore_exact_anchor']


@pytest.mark.parametrize('bad',['dirty','output_sha','receipt_sha','anchor_sha','pid','unknown_copy','preferences'])
def test_cleanup_guards_before_any_close(graph,bad):
    p=graph;model,args=_saved_cut_cleanup(p)
    if bad=='dirty':model.dirty=True
    elif bad=='output_sha':args['expected_output_current_sha256']='0'*64
    elif bad=='receipt_sha':args['transfer_receipt_sha256']='0'*64
    elif bad=='anchor_sha':p.anchor_path.write_bytes(b'changed anchor')
    elif bad=='pid':p.sw.pid=72
    else:
        prior=json.loads(p.receipt.read_text())
        if bad=='unknown_copy':prior['native_source_copied_before_mutation']=False
        else:prior['preference_restore_errors']=[{'type':'failure'}]
        p.receipt.write_text(json.dumps(prior));args['transfer_receipt_sha256']=transfer._file_hash(p.receipt)
    documents=list(p.sw.docs);calls=list(p.state['calls']);result=transfer.cleanup_part_transfer(p.sw,**args)
    assert result['status']=='error' and not result['mutation_attempted'],result
    assert p.sw.docs==documents and p.state['calls']==calls


def test_cleanup_does_not_reopen_already_closed_output_and_donor(graph):
    p=graph;model,args=_saved_cut_cleanup(p)
    p.sw.docs=[p.anchor];p.sw.ActiveDoc=None
    result=transfer.cleanup_part_transfer(p.sw,**args)
    assert result['cleanup_verified'] and result['output_already_closed'] and result['donor_already_closed'],result
    assert [row['name'] for row in result['native_calls']]==['restore_exact_anchor']


def test_readonly_document_inventory_without_active_model(graph):
    p=graph;p.sw.ActiveDoc=None
    p.sw.docs.append(p.Model(p.output));p.sw.docs[-1].dirty=True
    result=transfer.inspect_open_documents(p.sw,process_id=71)
    assert result['active_document'] is None and result['document_count']==2
    assert result['documents'][1]['needs_save'] is True
    assert result['mutation_attempted'] is False and p.state['calls']==[]


@pytest.mark.parametrize('pid',[True,72,0])
def test_readonly_document_inventory_pid_guard_precedes_document_reads(graph,pid):
    p=graph;p.sw.GetDocuments=Mock(side_effect=AssertionError('not our process'))
    with pytest.raises(ValueError):transfer.inspect_open_documents(p.sw,process_id=pid)
    p.sw.GetDocuments.assert_not_called()


def test_native_open_records_actual_assembly_before_rejecting_expected_part(tmp_path,monkeypatch):
    import win32com.client
    model=N(Visible=True,GetPathName=lambda:'',GetTitle=lambda:'actual staged donor',GetType=lambda:2)
    sw=N(GetDocuments=lambda:[],DocumentVisible=Mock(),GetImportFileData=lambda path:N(MapConfigurationData=True),
        LoadFile4=lambda path,args,data,error:model)
    monkeypatch.setattr(win32com.client,'VARIANT',lambda kind,value:N(value=value))
    seen=[]
    with pytest.raises(ValueError,match='document type'):
        transfer._open(sw,tmp_path/'donor.step',step=True,observed=lambda value:seen.append(deepcopy(value)))
    assert seen==[dict(errors=0,warnings=0,path='',title='actual staged donor',type=2,
        expected_type=1,native_open_returned=True)]
    assert model.Visible is False
    assert sw.DocumentVisible.call_args_list[-1].args==(True,1)


def _unexpected_assembly_checkpoint(p,monkeypatch):
    original=transfer._open;children=[];imported=[]
    def open_assembly(sw,path,step=False,observed=None,import_settings_observed=None):
        if not step:return original(sw,path,step=step,observed=observed)
        assembly=p.Model(path);assembly.path='';assembly.GetType=lambda:2
        assembly.GetTitle=lambda:Path(path).with_suffix('.SLDASM').name
        assembly.dirty=True
        for index in range(2):
            child=p.Model(p.tmp_path/f'never_saved_child_{index}.sldprt');child.dirty=True
            children.append(child);p.sw.docs.append(child)
        assembly.GetComponents=lambda top:[N(GetModelDoc2=lambda child=child:child) for child in children]
        p.sw.docs.append(assembly);imported.append(assembly)
        if observed:observed(dict(path='',title=assembly.GetTitle(),type=2,errors=0,warnings=0,
            expected_type=1,native_open_returned=True))
        raise ValueError('Opened document type differs from the explicit file')
    monkeypatch.setattr(transfer,'_open',open_assembly)
    result=p.apply(mode='add_delta',acknowledge_delta_only=True)
    assert result['status']=='uncertain' and p.state['calls']==[]
    # 兼容旧回执：旧导入错误丢失 open_donor，仍用 staged 名称和实际组件关系证明归属。
    prior=json.loads(p.receipt.read_text());prior.pop('open_donor',None)
    p.receipt.write_text(json.dumps(prior))
    args=dict(process_id=71,transfer_receipt_path=str(p.receipt),transfer_receipt_sha256=transfer._file_hash(p.receipt),
        expected_output_current_sha256=transfer._file_hash(p.output),receipt_path=str(p.tmp_path/'unexpected_cleanup.json'),
        acknowledge_discard_unexpected_import=True)
    return imported[0],children,args


def test_cleanup_unexpected_assembly_and_actual_unsaved_children_without_save(graph,monkeypatch):
    p=graph;assembly,children,args=_unexpected_assembly_checkpoint(p,monkeypatch)
    original=p.receipt.read_bytes();output=p.output.read_bytes()
    monkeypatch.setattr(transfer,'_save',Mock(side_effect=AssertionError('must not save import documents')))
    result=transfer.cleanup_part_transfer(p.sw,**args)
    assert result['cleanup_verified'],result
    assert [row['name'] for row in result['native_calls']]==[
        'close_saved_owned_output','close_owned_donor','close_owned_import_child','close_owned_import_child','restore_exact_anchor']
    assert len(result['unexpected_import_children'])==2 and p.sw.docs==[p.anchor]
    assert p.receipt.read_bytes()==original and p.output.read_bytes()==output
    assert not any(Path(child.path).exists() for child in children) and p.state['calls']==[]


@pytest.mark.parametrize('bad',['child_saved','preexisting_child','unknown_child','assembly_title','output_changed','geometry_attempt','no_ack'])
def test_unexpected_assembly_cleanup_requires_strict_import_ownership(graph,monkeypatch,bad):
    p=graph;assembly,children,args=_unexpected_assembly_checkpoint(p,monkeypatch)
    if bad=='child_saved':Path(children[0].path).write_bytes(b'must not close existing file')
    elif bad=='preexisting_child':
        prior=json.loads(p.receipt.read_text())
        prior['before']['session']['documents'].append(dict(path=children[0].path,title=children[0].GetTitle()))
        p.receipt.write_text(json.dumps(prior));args['transfer_receipt_sha256']=transfer._file_hash(p.receipt)
    elif bad=='unknown_child':p.sw.docs.remove(children[0])
    elif bad=='assembly_title':assembly.GetTitle=lambda:'different imported assembly.SLDASM'
    elif bad=='output_changed':
        p.output.write_bytes(b'unexpected geometry change');args['expected_output_current_sha256']=transfer._file_hash(p.output)
    elif bad=='geometry_attempt':
        prior=json.loads(p.receipt.read_text());prior['native_calls'].append(dict(name='CreateFeatureFromBody3',attempted=True,returned=False))
        p.receipt.write_text(json.dumps(prior));args['transfer_receipt_sha256']=transfer._file_hash(p.receipt)
    else:args['acknowledge_discard_unexpected_import']=False
    docs=list(p.sw.docs);result=transfer.cleanup_part_transfer(p.sw,**args)
    assert result['status']=='error' and not result['mutation_attempted'],result
    assert p.sw.docs==docs and p.state['calls']==[]


@pytest.mark.parametrize('slash_style', ['forward', 'native'])
def test_anchor_lookup_normalizes_native_slashes_without_reopen(tmp_path, monkeypatch, slash_style):
    path=tmp_path/'same-anchor.sldprt';path.write_bytes(b'untouched anchor')
    requested=path.as_posix() if slash_style=='forward' else str(path)
    model=N(GetPathName=lambda:str(path),GetSaveFlag=lambda:False)
    lookup=Mock(side_effect=lambda value:model if value==str(path) else None)
    sw=N(GetOpenDocumentByName=lookup)
    native=Mock(side_effect=AssertionError('Existing exact anchor must not reopen'))
    monkeypatch.setattr(transfer,'_open',Mock(side_effect=AssertionError('No OpenDoc fallback')))
    result=transfer._anchor_document(sw,requested,transfer._file_hash(path),native)
    assert result is model
    lookup.assert_called_once_with(str(path))
    native.assert_not_called();transfer._open.assert_not_called()
    assert path.read_bytes()==b'untouched anchor'


def test_normalized_lookup_still_rejects_different_full_path_same_title(tmp_path):
    expected=tmp_path/'one'/'same.sldprt';other=tmp_path/'two'/'same.sldprt'
    model=N(GetPathName=lambda:str(other),GetTitle=Mock(side_effect=AssertionError('No title fallback')))
    lookup=Mock(return_value=model);sw=N(GetOpenDocumentByName=lookup)
    with pytest.raises(ValueError,match='different path'):
        transfer._find_document(sw,expected.as_posix())
    lookup.assert_called_once_with(str(expected));model.GetTitle.assert_not_called()


def test_missing_normalized_lookup_does_not_search_title_or_open(tmp_path):
    path=tmp_path/'missing.sldprt'
    sw=N(GetOpenDocumentByName=Mock(return_value=None),
        GetDocuments=Mock(side_effect=AssertionError('No enumeration fallback')),
        OpenDoc6=Mock(side_effect=AssertionError('Lookup must not open documents')))
    assert transfer._find_document(sw,path.as_posix()) is None
    sw.GetOpenDocumentByName.assert_called_once_with(str(path))
    sw.GetDocuments.assert_not_called();sw.OpenDoc6.assert_not_called()


@pytest.mark.parametrize('failure,code', [
    ('check3', 'NATIVE_CHECK3_FAULTS'),
    ('zero_volume', 'NATIVE_VOLUME_NONPOSITIVE'),
    ('negative_volume', 'NATIVE_VOLUME_NONPOSITIVE'),
    ('nan_mass', 'NATIVE_MASS_PROPERTY_NONFINITE_OR_TYPE'),
    ('short_mass', 'NATIVE_MASS_PROPERTY_COUNT_INVALID'),
    ('absent_mass', 'NATIVE_MASS_PROPERTIES_UNAVAILABLE'),
])
def test_donor_failure_is_distinguished_and_durable_before_any_insert(graph, monkeypatch, failure, code):
    p=graph;original=transfer._open;mass_calls=[]
    def open_bad_donor(sw,path,step=False,observed=None,import_settings_observed=None):
        model,metadata=original(sw,path,step=step,observed=observed)
        if step:
            body=model.bodies[0]
            if failure=='check3':body.Check3.Count=2
            def mass(density):
                mass_calls.append(density)
                durable=json.loads(p.receipt.read_text())
                assert durable['phase']=='body_stats_donor_read_mass_properties'
                assert durable['body_diagnostics']['donor']['bodies'][0]['check3']==0
                values=[0.,0.,0.,6.]+[0.]*8
                if failure=='zero_volume':values[3]=0.
                elif failure=='negative_volume':values[3]=-1.
                elif failure=='nan_mass':values[7]=float('nan')
                elif failure=='short_mass':values=values[:-1]
                elif failure=='absent_mass':return None
                return values
            body.GetMassProperties=mass
        return model,metadata
    monkeypatch.setattr(transfer,'_open',open_bad_donor)
    result=p.apply();durable=json.loads(p.receipt.read_text())
    assert result['status']=='uncertain' and not result['body_transfer_verified']
    assert result['issue']['code']==code and durable['issue']['code']==code
    diagnostic=durable['body_diagnostics']['donor']
    assert diagnostic['failure_code']==code and diagnostic['solid_count']==1
    assert diagnostic['sheet_count']==0 and diagnostic['bodies'][0]['body_index']==0
    assert p.state['calls']==[] and p.source.read_bytes()==b'original native'
    assert p.output.read_bytes()==p.source.read_bytes() and not p.step.exists()
    assert len(mass_calls)==(0 if failure=='check3' else 1)
    if failure=='check3':
        assert diagnostic['bodies'][0]['check3']==2
        assert diagnostic['bodies'][0]['mass_properties_native'] is None
    elif failure=='nan_mass':
        assert diagnostic['bodies'][0]['invalid_mass_property_indices']==[7]
        assert diagnostic['bodies'][0]['mass_properties_native'][7]=='nan'
    elif failure in ('zero_volume','negative_volume'):
        assert diagnostic['bodies'][0]['volume_m3']==(0. if failure=='zero_volume' else -1.)


def test_read_failure_retains_stage_and_prior_check_without_retry(graph, monkeypatch):
    p=graph;original=transfer._open;reads=[]
    class TransportFailure(RuntimeError):hresult=-2147023174
    def open_bad_donor(sw,path,step=False,observed=None,import_settings_observed=None):
        model,metadata=original(sw,path,step=step,observed=observed)
        if step:
            def mass(density):
                reads.append(density)
                assert json.loads(p.receipt.read_text())['phase']=='body_stats_donor_read_mass_properties'
                raise TransportFailure('native transport lost')
            model.bodies[0].GetMassProperties=mass
        return model,metadata
    monkeypatch.setattr(transfer,'_open',open_bad_donor)
    result=p.apply();d=json.loads(p.receipt.read_text())['body_diagnostics']['donor']
    assert reads==[1] and p.state['calls']==[]
    assert d['status']=='read_failed' and d['stage']=='read_mass_properties'
    assert d['bodies'][0]['check3']==0 and d['bodies'][0]['volume_m3'] is None
    assert d['issue']['hresult']==-2147023174 and result['failed_phase']=='body_stats_donor_read_mass_properties'


def test_second_faulty_body_keeps_first_measurements_and_does_not_read_its_mass():
    good=N(Check3=N(Count=0),GetMassProperties=Mock(return_value=[0.,0.,0.,2.]+[0.]*8),
        GetBodyBox=Mock(return_value=[0.,0.,0.,1.,1.,1.]))
    bad=N(Check3=N(Count=1),GetMassProperties=Mock(side_effect=AssertionError('No mass read after Check3 fault')))
    model=N(GetBodies2=lambda kind,visible:[good,bad] if kind==0 else [])
    snapshots=[]
    with pytest.raises(transfer.NativeBodyValidationError) as caught:
        transfer._stats(model,observed=snapshots.append)
    assert caught.value.code=='NATIVE_CHECK3_FAULTS'
    diagnostic=caught.value.diagnostics
    assert diagnostic['bodies'][0]['volume_m3']==2.
    assert diagnostic['bodies'][1]['body_index']==1 and diagnostic['bodies'][1]['check3']==1
    assert snapshots[-1]==diagnostic and snapshots[0]['bodies']==[]
    bad.GetMassProperties.assert_not_called()


@pytest.mark.parametrize('solids,sheets', [(0,0),(10,0),(1,1)])
def test_invalid_body_set_records_counts_without_inspecting_bodies(solids,sheets):
    body=N(Check3=Mock(side_effect=AssertionError('Invalid set must not inspect bodies')))
    model=N(GetBodies2=lambda kind,visible:[body]*(solids if kind==0 else sheets))
    with pytest.raises(transfer.NativeBodyValidationError) as caught:transfer._stats(model)
    assert caught.value.code=='NATIVE_BODY_SET_INVALID'
    assert caught.value.diagnostics['solid_count']==solids
    assert caught.value.diagnostics['sheet_count']==sheets
    assert caught.value.diagnostics['bodies']==[]


@pytest.fixture
def absent_module_guard(graph, monkeypatch):
    from scripts import sw_plastics_session_isolation as isolation
    p=graph;path=p.tmp_path/'SimpoeWorks.dll';path.write_bytes(b'fixed installed add-in')
    modules=[];enumeration=Mock(side_effect=lambda pid:list(modules))
    monkeypatch.setattr(isolation,'process_modules',enumeration)
    return N(graph=p,path=path,modules=modules,enumeration=enumeration)


def test_empty_module_guard_preserves_existing_route_without_os_enumeration(absent_module_guard):
    q=absent_module_guard;q.enumeration.side_effect=AssertionError('Empty default must not enumerate OS modules')
    assert q.graph.apply()['body_transfer_verified']
    q.enumeration.assert_not_called()


def test_required_modules_absent_are_recorded_during_prepare_and_before_import(absent_module_guard):
    q=absent_module_guard;p=q.graph;paths=[str(q.path)]
    prepared=p.run(required_absent_module_paths=paths)
    assert prepared['status']=='ok' and prepared['module_absence_checks'][0]['stage']=='prepare'
    assert prepared['module_absence_checks'][0]['all_required_absent']
    result=p.run(action='apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(p.receipt),required_absent_module_paths=paths)
    assert result['body_transfer_verified']
    assert [x['stage'] for x in result['module_absence_checks']]==['apply_preflight','before_step_import']
    assert all(x['all_required_absent'] for x in result['module_absence_checks'])
    assert q.enumeration.call_count==3 and all(c.args==(71,) for c in q.enumeration.call_args_list)


@pytest.mark.parametrize('other_path',[False,True])
def test_present_or_same_name_module_blocks_prepare_before_copy(absent_module_guard,other_path):
    q=absent_module_guard;p=q.graph
    q.modules.append(str(p.tmp_path/'other'/'SimpoeWorks.dll') if other_path else str(q.path))
    result=p.run(required_absent_module_paths=[str(q.path)])
    assert result['status']=='error' and not result['mutation_attempted']
    assert result['issue']['code']=='NATIVE_IMPORT_REQUIRED_MODULE_NOT_ABSENT'
    assert not result['module_absence_checks'][0]['all_required_absent']
    assert not p.output.exists() and p.state['calls']==[]


def test_source_reloads_module_and_import_is_never_attempted(absent_module_guard,monkeypatch):
    q=absent_module_guard;p=q.graph;original=transfer._open;opens=[]
    def open_source(sw,path,step=False,observed=None,import_settings_observed=None):
        opens.append((str(path),step));assert not step,'STEP import must not occur after module reappears'
        result=original(sw,path,step=step,observed=observed);q.modules.append(str(q.path));return result
    monkeypatch.setattr(transfer,'_open',open_source)
    result=p.apply(required_absent_module_paths=[str(q.path)])
    assert result['status']=='uncertain' and not result['body_transfer_verified']
    assert result['issue']['code']=='NATIVE_IMPORT_REQUIRED_MODULE_NOT_ABSENT'
    durable=json.loads(p.receipt.read_text());last=durable['module_absence_checks'][-1]
    assert last['stage']=='before_step_import' and not last['all_required_absent']
    assert last['mapped_required_modules']==[str(q.path)]
    assert not any(x['name']=='import_staged_step' for x in durable['native_calls'])
    assert len(opens)==1 and not opens[0][1] and p.state['calls']==[]
    assert p.output.read_bytes()==p.source.read_bytes() and not p.step.exists()


def test_module_enumeration_failure_before_import_is_durable_and_not_retried(absent_module_guard,monkeypatch):
    q=absent_module_guard;p=q.graph;original=transfer._open;opens=[]
    def source_open(sw,path,step=False,observed=None,import_settings_observed=None):
        opens.append(step);assert not step
        value=original(sw,path,step=step,observed=observed)
        q.enumeration.side_effect=RuntimeError('OS module enumeration failed')
        return value
    monkeypatch.setattr(transfer,'_open',source_open)
    result=p.apply(required_absent_module_paths=[str(q.path)])
    assert result['status']=='uncertain' and result['failed_phase']=='module_absence_before_step_import_pending'
    assert q.enumeration.call_count==3 and opens==[False]
    assert p.state['calls']==[] and not p.step.exists()
    assert not any(x['name']=='import_staged_step' for x in json.loads(p.receipt.read_text())['native_calls'])


@pytest.mark.parametrize('invalid',['not-a-list',['relative.dll'],['C:/folder/file.step'],[True],['C:/a/x.dll','C:/a/x.dll'],['C:/a/x.dll']*9])
def test_invalid_required_absent_paths_rejected_before_mutation(graph,invalid):
    result=graph.run(required_absent_module_paths=invalid)
    assert result['status']=='error' and not result['mutation_attempted']
    assert not graph.output.exists() and graph.state['calls']==[]


def test_step_import_uses_geometry_only_override_before_native_load(tmp_path, monkeypatch):
    import win32com.client
    data = N(MapConfigurationData=True)
    model = N(Visible=True, GetPathName=lambda: '', GetTitle=lambda: 'donor', GetType=lambda: 1)
    seen = []
    def load(path, options, incoming, error):
        assert incoming is data and data.MapConfigurationData is False
        assert seen[-1]['stage'] == 'configuration_override_readback'
        assert seen[-1]['map_configuration_data_before'] is True
        return model
    sw = N(GetDocuments=lambda: [], DocumentVisible=Mock(), GetImportFileData=lambda path: data,
        LoadFile4=Mock(side_effect=load))
    monkeypatch.setattr(win32com.client, 'VARIANT', lambda kind, value: N(value=value))
    actual, metadata = transfer._open(sw, tmp_path/'donor.step', step=True,
        import_settings_observed=lambda row: seen.append(deepcopy(row)))
    assert actual is model and metadata['type'] == 1
    assert len(seen) == 2 and seen[-1]['map_configuration_data_after'] is False
    assert sw.LoadFile4.call_count == 1


@pytest.mark.parametrize('failure', ['readback_true', 'readback_integer_zero', 'setter_exception'])
def test_step_mapping_failure_never_imports_and_restores_visibility(tmp_path, monkeypatch, failure):
    import win32com.client
    class ImportData:
        @property
        def MapConfigurationData(self):
            return 0 if failure == 'readback_integer_zero' else True
        @MapConfigurationData.setter
        def MapConfigurationData(self, value):
            assert value is False
            if failure == 'setter_exception': raise RuntimeError('mapping setter failed')
    sw = N(GetDocuments=lambda: [], DocumentVisible=Mock(), GetImportFileData=lambda path: ImportData(),
        LoadFile4=Mock())
    monkeypatch.setattr(win32com.client, 'VARIANT', lambda kind, value: N(value=value))
    seen=[]
    with pytest.raises((ValueError, RuntimeError)):
        transfer._open(sw, tmp_path/'donor.step', step=True, import_settings_observed=seen.append)
    sw.LoadFile4.assert_not_called()
    assert sw.DocumentVisible.call_args_list[-1].args == (True, 1)
    assert seen[0]['stage'] == 'before_configuration_override'


@pytest.mark.parametrize('reject_import', [False, True])
def test_multibody_preferences_applied_before_import_and_restored(graph, monkeypatch, reject_import):
    p=graph
    p.prefs['Toggle', 220]=False
    p.prefs['IntegerValue', 579]=1
    original=transfer._open
    seen=[]
    def open_checked(sw, path, step=False, **kwargs):
        if step:
            assert p.prefs['Toggle', 220] is True
            assert p.prefs['IntegerValue', 579] == 2
            seen.append(str(path))
            if reject_import: raise RuntimeError('native import rejected')
        return original(sw, path, step=step, **kwargs)
    monkeypatch.setattr(transfer, '_open', open_checked)
    result=p.apply()
    assert len(seen)==1
    assert result['body_transfer_verified'] is (not reject_import)
    assert p.prefs['Toggle', 220] is False
    assert p.prefs['IntegerValue', 579] == 1
    assert not result['preference_restore_errors']
    if reject_import: assert p.state['calls']==[]


@pytest.fixture
def repair_graph(graph, monkeypatch):
    p=graph;original=transfer._open;donors=[]
    def rejected_donor(sw,path,step=False,**kwargs):
        model,metadata=original(sw,path,step=step,**kwargs)
        if step:
            model.bodies[0].Check3=N(Count=2,ErrorCode=lambda i: [11,13][i],Entity2=lambda i: None if i==0 else object())
            donors.append(model)
        return model,metadata
    monkeypatch.setattr(transfer,'_open',rejected_donor)
    failed=p.apply()
    assert failed['issue']['code']=='NATIVE_CHECK3_FAULTS'
    prior=json.loads(p.receipt.read_text())
    prior['open_donor'].update(type=1,native_open_returned=True)
    p.receipt.write_text(json.dumps(prior))
    donor=donors[0];calls=[]
    def repair(*args):
        calls.append(args)
        assert p.sw.ActiveDoc is donor
        durable=json.loads((p.tmp_path/'repair.json').read_text())
        assert durable['native_calls'][-1]==dict(name='ImportDiagnosis',attempted=True,returned=False)
        donor.bodies[0].Check3.Count=0
        return 0
    donor.ImportDiagnosis=repair
    values=dict(process_id=71,transfer_receipt_path=str(p.receipt),
        transfer_receipt_sha256=transfer._file_hash(p.receipt),
        repaired_step_path=str(p.tmp_path/'repaired.step'),qualification_only=True)
    def prepare(**changes):return transfer.qualify_import_diagnosis(p.sw,action='prepare',**(values|changes))
    def apply(**changes):
        prepared=prepare()
        assert prepared['status']=='ok',prepared
        return transfer.qualify_import_diagnosis(p.sw,action='apply',expected_state_sha256=prepared['state_sha256'],
            receipt_path=str(p.tmp_path/'repair.json'),**(values|changes))
    return N(p=p,donor=donor,calls=calls,values=values,prepare=prepare,apply=apply)


def test_import_repair_prepare_is_read_only_and_preserves_null_fault_entity(repair_graph):
    q=repair_graph;r=q.prepare()
    assert r['status']=='ok' and not r['mutation_attempted'] and q.calls==[]
    assert r['before']['faults']['fault_count']==2
    assert r['before']['faults']['faults']==[
        dict(index=0,error_code=11,entity_present=False),dict(index=1,error_code=13,entity_present=True)]
    assert not Path(r['repair_marker_path']).exists()


def test_import_repair_exports_only_valid_donor_without_source_save(repair_graph):
    q=repair_graph;r=q.apply()
    assert r['repair_verified'] and not r['geometry_equivalence_verified']
    assert r['source_files_unchanged'] and q.calls==[(True,False,True,0)]
    assert q.p.state['calls']==['export'] and q.p.output.read_bytes()==b'original native'
    assert q.p.sw.ActiveDoc is q.p.anchor
    row=next(x for x in r['native_calls'] if x['name']=='ImportDiagnosis')
    assert row['return_value']==0 and row['returned'] is True
    assert q.prepare()['status']=='error' and len(q.calls)==1


@pytest.mark.parametrize('result',[-1,True,'0',None])
def test_import_repair_invalid_native_return_never_exports_or_repeats(repair_graph,result):
    q=repair_graph;q.donor.ImportDiagnosis=Mock(return_value=result)
    r=q.apply()
    assert not r['repair_verified'] and r['status']=='uncertain'
    assert q.p.state['calls']==[] and not Path(q.values['repaired_step_path']).exists()
    q.donor.ImportDiagnosis.assert_called_once_with(True,False,True,0)
    assert q.prepare()['status']=='error'


def test_import_repair_remaining_fault_stops_before_export(repair_graph):
    q=repair_graph;q.donor.ImportDiagnosis=Mock(return_value=0)
    r=q.apply()
    assert r['issue']['code']=='NATIVE_CHECK3_FAULTS' and not r['repair_verified']
    assert r['faults_after']['fault_count']==2 and q.p.state['calls']==[]


def test_import_repair_rpc_failure_keeps_one_shot_intent(repair_graph):
    q=repair_graph;q.donor.ImportDiagnosis=Mock(side_effect=RuntimeError('transport lost'))
    r=q.apply();row=next(x for x in r['native_calls'] if x['name']=='ImportDiagnosis')
    assert row==dict(name='ImportDiagnosis',attempted=True,returned=False)
    assert Path(r['repair_marker_path']).exists() and q.prepare()['status']=='error'
    q.donor.ImportDiagnosis.assert_called_once()


@pytest.mark.parametrize('changed',['pid','copy_dirty','copy_hash','prior_hash','fault_count','extra_document'])
def test_import_repair_identity_drift_is_read_only_rejection(repair_graph,changed):
    q=repair_graph;p=q.p
    if changed=='pid':p.sw.pid=72
    elif changed=='copy_dirty':next(m for m in p.sw.docs if m.path==str(p.output)).dirty=True
    elif changed=='copy_hash':p.output.write_bytes(b'changed')
    elif changed=='prior_hash':p.receipt.write_text('{}')
    elif changed=='fault_count':q.donor.bodies[0].Check3.Count=1
    elif changed=='extra_document':p.sw.docs.append(p.Model(p.tmp_path/'other.sldprt'))
    r=q.prepare()
    assert r['status']=='error' and not r['mutation_attempted'] and q.calls==[]


def test_fault_accessors_use_indexed_propertyget_not_method():
    import pythoncom
    ole=N(InvokeTypes=Mock(return_value=17));fault=N(_oleobj_=ole)
    assert transfer._fault_indexed_property(fault,'ErrorCode',1)==17
    ole.InvokeTypes.assert_called_once_with(3,0,pythoncom.DISPATCH_PROPERTYGET,
        (pythoncom.VT_I4,0),((pythoncom.VT_I4,1),),1)
    ole.InvokeTypes.reset_mock();transfer._fault_indexed_property(fault,'Entity2',0)
    assert ole.InvokeTypes.call_args.args[0:3]==(4,0,pythoncom.DISPATCH_PROPERTYGET)


@pytest.mark.parametrize('policy,expected',[('knit_surfaces',1),('direct_brep',0)])
@pytest.mark.parametrize('reject_import',[False,True])
def test_step_topology_policy_is_applied_hash_bound_and_restored(graph,monkeypatch,policy,expected,reject_import):
    p=graph;original=transfer._open;seen=[]
    def checked(sw,path,step=False,**kwargs):
        if step:
            assert p.prefs['IntegerValue',207]==expected
            assert p.prefs['IntegerValue',12]==3
            durable=json.loads(p.receipt.read_text())
            assert durable['step_topology_preimport_readback']==dict(policy=policy,swImportUseBrep=expected,swCreateBodyFromSurfacesOption=3)
            seen.append(path)
            if reject_import:raise RuntimeError('controlled importer failure')
        return original(sw,path,step=step,**kwargs)
    monkeypatch.setattr(transfer,'_open',checked)
    r=p.apply(step_topology_policy=policy)
    assert len(seen)==1 and r['body_transfer_verified'] is (not reject_import)
    assert p.prefs['IntegerValue',207]==1
    assert next(x for x in r['before']['import_preferences_requested'] if x['kind']=='IntegerValue' and x['number']==207)['value']==expected


def test_step_topology_policy_change_invalidates_prepare_digest(graph):
    p=graph;prepared=p.run(step_topology_policy='knit_surfaces')
    result=p.run(action='apply',step_topology_policy='direct_brep',
        expected_state_sha256=prepared['state_sha256'],receipt_path=str(p.receipt))
    assert result['status']=='error' and not result['mutation_attempted'] and not p.output.exists()


@pytest.mark.parametrize('bad',[None,True,0,'BREP',[]])
def test_unknown_step_topology_policy_cannot_reach_native(graph,bad):
    p=graph;r=p.run(step_topology_policy=bad)
    assert r['status']=='error' and not r['mutation_attempted'] and p.state['calls']==[]


def test_source_open_topology_setting_drift_blocks_step_import(graph,monkeypatch):
    p=graph;original=transfer._open;imports=[]
    def drift(sw,path,step=False,**kwargs):
        if step:imports.append(path)
        result=original(sw,path,step=step,**kwargs)
        if not step:p.prefs['IntegerValue',207]=1
        return result
    monkeypatch.setattr(transfer,'_open',drift)
    r=p.apply(step_topology_policy='direct_brep')
    assert r['status']=='uncertain' and imports==[] and p.state['calls']==[]
    assert p.prefs['IntegerValue',207]==1


@pytest.fixture
def marked_graph(graph,monkeypatch):
    p=graph;old_init=p.Model.__init__;old_select=p.Body.Select2;old_clear=p.Model.ClearSelection2;old_combine=p.Model.combine
    controls=dict(bad_count=False,bad_identity=False,reject_select=False,null_combine=False,native_calls=[])
    def init(model,*args,**kwargs):
        old_init(model,*args,**kwargs);model.marked=[]
        def selected(mark):return [body for body,m in model.marked if mark==-1 or m==mark]
        model.SelectionManager=N(CreateSelectData=lambda:N(Mark=None),
            GetSelectedObjectCount2=lambda mark: len(selected(mark))+(1 if controls['bad_count'] else 0),
            GetSelectedObject6=lambda index,mark:object() if controls['bad_identity'] else selected(mark)[index-1])
    def select(body,append,data):
        if data.Mark==0:return old_select(body,append,data)
        if controls['reject_select']:return False
        if not append:body.model.marked=[]
        body.model.marked.append((body,data.Mark));return True
    def clear(model,all):
        old_clear(model,all);model.marked=[]
    def combine(model,kind,main,tools):
        controls['native_calls'].append((kind,main.value,tools.value))
        assert main.value is None and tools.value==()
        if controls['null_combine']:return None
        mains=[body for body,mark in model.marked if mark==1]
        selected_tools=[body for body,mark in model.marked if mark==2]
        return old_combine(model,kind,mains[0] if kind==15902 else main,N(value=tuple(selected_tools)))
    monkeypatch.setattr(p.Model,'__init__',init);monkeypatch.setattr(p.Body,'Select2',select)
    monkeypatch.setattr(p.Model,'ClearSelection2',clear);monkeypatch.setattr(p.Model,'combine',combine)
    return N(p=p,controls=controls)


@pytest.mark.parametrize('mode',['subtract_delta','add_delta'])
def test_marked_combine_uses_empty_arguments_after_exact_identity_readback(marked_graph,mode):
    q=marked_graph;r=q.p.apply(mode=mode,acknowledge_delta_only=True,combine_input_mode='marked_selection')
    assert r['body_transfer_verified'] and r['combine_selection']['all_input_identities_verified']
    assert r['combine_selection']['main_count']==int(mode=='subtract_delta')
    assert q.controls['native_calls']==[(15902 if mode=='subtract_delta' else 15903,None,())]


@pytest.mark.parametrize('failure',['bad_count','bad_identity','reject_select'])
def test_bad_marked_selection_never_calls_boolean(marked_graph,failure):
    q=marked_graph;q.controls[failure]=True
    r=q.p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='marked_selection')
    assert r['status']=='uncertain' and not r['body_transfer_verified']
    assert q.controls['native_calls']==[] and 'save' not in q.p.state['calls']


def test_null_marked_boolean_is_one_call_without_direct_fallback(marked_graph):
    q=marked_graph;q.controls['null_combine']=True
    r=q.p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='marked_selection')
    assert r['status']=='uncertain' and len(q.controls['native_calls'])==1
    assert not any(name in q.p.state['calls'] for name in ['save','export'])


def test_marked_combine_selects_fresh_main_not_preinsertion_wrapper(marked_graph):
    q=marked_graph;p=q.p;old_refs=[]
    def replace_main_wrapper(model):
        old=model.bodies[0];old.identity=id(old);old.Select2=Mock(side_effect=AssertionError('stale wrapper selected'))
        fresh=p.Body(old.volume,model);fresh.identity=old.identity;model.bodies[0]=fresh;old_refs.append(old)
        return N(Name='donor insertion')
    p.state['on_insert']=replace_main_wrapper
    p.sw.IsSame=lambda a,b:int(getattr(a,'identity',id(a))==getattr(b,'identity',id(b)))
    r=p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='marked_selection')
    assert r['body_transfer_verified'] and r['combine_selection']['fresh_main_selected_verified']
    old_refs[0].Select2.assert_not_called()


def test_changing_combine_input_mode_invalidates_prepared_state(graph):
    p=graph;prep=p.run(mode='subtract_delta',acknowledge_delta_only=True)
    r=p.run(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='marked_selection',action='apply',
        expected_state_sha256=prep['state_sha256'],receipt_path=str(p.receipt))
    assert r['status']=='error' and not r['mutation_attempted']


@pytest.mark.parametrize('bad',[None,True,0,'auto',[]])
def test_unsupported_combine_mode_is_rejected_before_native(graph,bad):
    p=graph;r=p.run(combine_input_mode=bad)
    assert r['status']=='error' and not r['mutation_attempted']


@pytest.fixture
def temporary_graph(graph,monkeypatch):
    from scripts import sw_body_operation_diagnostic as diagnostic
    p=graph;seen=[];behavior={'error':0,'count':1,'fault':0,'raise_at':None}
    monkeypatch.setattr(p.Body,'IsTemporaryBody',lambda self:self.model is None,raising=False)
    def operation(target,tool,kind):
        assert target.model is None and tool.model is None
        assert all(tool is not old for pair in seen for old in pair[:2])
        seen.append((target,tool,kind))
        if behavior['raise_at']==len(seen):raise RuntimeError('transport failed')
        volume=target.volume+tool.volume if kind==15903 else target.volume-tool.volume
        results=[p.Body(volume) for _ in range(behavior['count'])]
        for body in results:body.Check3.Count=behavior['fault']
        return results,behavior['error']
    monkeypatch.setattr(diagnostic,'_operations',operation)
    return N(p=p,seen=seen,behavior=behavior)

@pytest.mark.parametrize('mode,kind,expected',[('subtract_delta',15902,7.),('add_delta',15903,13.)])
def test_temporary_sequence_inserts_only_final_body_and_reopens(temporary_graph,mode,kind,expected):
    q=temporary_graph;p=q.p;p.state['donor_volumes']=[.25,.5,.75,1.5]
    r=p.apply(mode=mode,acknowledge_delta_only=True,combine_input_mode='temporary_bodies')
    assert r['body_transfer_verified'] and r['reopened_verified'],r
    assert r['source_files_unchanged'] and r['temporary_sequence_verified']
    assert [op[2] for op in q.seen]==[kind]*4
    assert len(r['temporary_operations'])==4 and all(row['verified'] for row in r['temporary_operations'])
    assert p.state['calls']==['insert','delete','save','export']
    assert r['body_reopened']['bodies'][0]['volume_m3']==expected
    assert r['features_after'][:len(r['original_features'])]==r['original_features']
    assert r['temporary_final_volume_verified']

@pytest.mark.parametrize('change',[{'error':1040},{'count':0},{'count':2},{'fault':21},{'raise_at':1}])
def test_temporary_rejection_never_inserts_or_retries(temporary_graph,change):
    q=temporary_graph;q.behavior.update(change);p=q.p
    r=p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='temporary_bodies')
    assert not r['body_transfer_verified'] and r['status']=='uncertain'
    assert not p.state['calls'] and len(q.seen)==1
    assert p.output.read_bytes()==p.source.read_bytes()
    assert len(r['temporary_operations'])==1
    if 'raise_at' not in change:
        assert r['temporary_operations'][0]['returned']
        saved=json.loads(p.receipt.read_text())
        assert saved['temporary_operations'][0]['error_code']==q.behavior['error']


def test_temporary_second_failure_preserves_native_source(temporary_graph):
    q=temporary_graph;p=q.p;p.state['donor_volumes']=[1.,2.];q.behavior['raise_at']=2
    r=p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='temporary_bodies')
    assert r['status']=='uncertain' and not p.state['calls'] and len(q.seen)==2
    assert r['temporary_operations'][0]['verified'] and not r['temporary_operations'][1]['returned']


def test_temporary_mode_changes_prepared_identity(graph):
    p=graph;prepared=p.run(mode='subtract_delta',acknowledge_delta_only=True)
    r=p.run(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='temporary_bodies',action='apply',
        expected_state_sha256=prepared['state_sha256'],receipt_path=str(p.receipt))
    assert not r['mutation_attempted'] and not p.output.exists()


def test_temporary_final_insertion_volume_mismatch_blocks_save(temporary_graph):
    q=temporary_graph;p=q.p
    p.state['on_boolean']=lambda model:setattr(model.bodies[0],'volume',model.bodies[0].volume+0.1)
    r=p.apply(mode='subtract_delta',acknowledge_delta_only=True,combine_input_mode='temporary_bodies',delta_volume_policy='diagnostic')
    assert r['status']=='uncertain' and not r['body_transfer_verified']
    assert p.state['calls']==['insert','delete']
    assert not p.step.exists()


def test_import_repair_activates_before_visibility_readback(repair_graph,monkeypatch):
    q=repair_graph;p=q.p;events=[];activated=set()
    import scripts.sw_assembly as assembly
    def activate(sw,model):
        events.append(('activate',model));sw.ActiveDoc=model;activated.add(id(model));return True
    def get_visible(model):return getattr(model,'_test_visible',False)
    def set_visible(model,value):
        events.append(('visible',model,value))
        # Emulate hidden-loaded donor whose Visible setter works only after activation.
        if model is q.donor and value and id(model) not in activated:return
        model._test_visible=value
    for model in p.sw.docs:model._test_visible=model.Visible
    monkeypatch.setattr(p.Model,'Visible',property(get_visible,set_visible),raising=False)
    monkeypatch.setattr(assembly,'_activate_model_document',activate)
    r=q.apply()
    assert r['repair_verified'] and r['anchor_visibility_restored']
    names=[x['name'] for x in r['native_calls']]
    assert names.index('activate_owned_donor')<names.index('show_only_owned_donor')<names.index('ImportDiagnosis')
    assert names.index('restore_exact_anchor')<names.index('show_only_exact_anchor')
    assert r['before']['activation_policy']=='activate_before_visible_readback'


def test_import_repair_failed_activation_never_calls_diagnosis(repair_graph,monkeypatch):
    q=repair_graph;p=q.p
    import scripts.sw_assembly as assembly
    def activate(sw,model):
        if model is q.donor:return False
        sw.ActiveDoc=model;return True
    monkeypatch.setattr(assembly,'_activate_model_document',activate)
    r=q.apply()
    assert not q.calls and not r['repair_verified'] and r['anchor_visibility_restored']
    assert not any(row['name']=='ImportDiagnosis' for row in r['native_calls'])
    assert q.prepare()['status']=='error'  # Existing one-shot marker is not bypassed.
