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
    def open_model(sw_arg,path,step=False,observed=None):
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
    sw=N(GetDocuments=lambda:[],DocumentVisible=Mock(),GetImportFileData=lambda path:object(),
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
    def open_assembly(sw,path,step=False,observed=None):
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
