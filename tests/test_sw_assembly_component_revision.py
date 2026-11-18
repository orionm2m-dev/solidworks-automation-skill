"""Offline guard/transition regressions; these tests never connect to CAD."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as N

import pytest

MODULE=Path(__file__).parents[1]/'scripts/sw_assembly_component_revision.py'
spec=importlib.util.spec_from_file_location('staged_component_revision',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
IDENTITY=[1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.,1.,0.,0.,0.]


@pytest.fixture
def graph(tmp_path,monkeypatch):
    source=tmp_path/'source.SLDASM';source.write_bytes(b'untouched source')
    target=tmp_path/'copy.SLDASM';target.write_bytes(b'qualified reference copy')
    prior=tmp_path/'prior.json';receipt=tmp_path/'apply.json'
    state=dict(calls=[],on_move=None,on_delete=None,return_move=True,return_delete=True,skip_fix=False,
               wrong_select=False,configs=['Default'],studies=[{'name':'Animation1','duration_seconds':0.}])
    class Component:
        def __init__(self,name,i):
            self.Name2=name;self.ComponentReference=name;self.ReferencedConfiguration='Default';self.i=i
            self.path=tmp_path/(name+'.SLDPRT');self.path.write_bytes(name.encode())
            self.matrix=IDENTITY.copy();self.fixed=True;self.mates=[];self.children=[]
        def GetID(self):return self.i
        def GetPathName(self):return str(self.path)
        def GetModelDoc2(self):return object()
        def IsSuppressed(self):return False
        def IsFixed(self):return self.fixed
        def GetTotalTransform(self,presentation):return N(ArrayData=self.matrix.copy())
        def GetChildren(self):return self.children
        def GetMates(self):return self.mates
        def Select4(self,append,data,popup):
            assert data.Mark==0 and popup is False
            if not append:model.selected=[]
            model.selected.append(components[-1] if state['wrong_select'] else self)
            state['calls'].append(('select',self.Name2));return True
        def SetTransformAndSolve2(self,transform):
            state['calls'].append(('move',self.Name2));model.dirty=True
            if state['return_move']:self.matrix=list(transform.ArrayData)
            if state['on_move']:state['on_move'](self)
            return state['return_move']
    components=[Component(name,i+1) for i,name in enumerate(['screw0','screw3','screw1','screw2','untouched'])]
    class Model:
        def __init__(self):
            self.selected=[];self.dirty=False;self.Visible=True;self.SketchManager=N(ActiveSketch=None)
            self.SelectionManager=N(CreateSelectData=lambda:N(Mark=None),
                GetSelectedObjectCount2=lambda mark:len(self.selected),
                GetSelectedObject6=lambda index,mark:self.selected[index-1])
            self.Extension=N(DeleteSelection2=self.delete)
        def GetType(self):return 2
        def GetPathName(self):return str(target)
        def GetTitle(self):return target.name
        def GetSaveFlag(self):return self.dirty
        def GetEditTargetComponent(self):return object()
        def GetEditTarget(self):return self
        def GetComponents(self,toplevel):return list(components)
        def ClearSelection2(self,all):self.selected=[]
        def UnfixComponent(self):
            state['calls'].append(('unfix',self.selected[0].Name2));self.selected[0].fixed=False;self.dirty=True
        def FixComponent(self):
            state['calls'].append(('fix',self.selected[0].Name2))
            if not state['skip_fix']:self.selected[0].fixed=True
        def delete(self,options):
            assert options==0
            state['calls'].append(('delete',tuple(c.Name2 for c in self.selected)))
            if state['return_delete']:
                for c in self.selected:components.remove(c)
            self.dirty=True
            if state['on_delete']:state['on_delete']()
            return state['return_delete']
    model=Model();sw=N(ActiveDoc=model,GetProcessID=lambda:71,GetDocuments=lambda:[model],
        IsSame=lambda a,b:1 if a is b else 0,
        GetMathUtility=lambda:N(CreateTransform=lambda values:N(ArrayData=values)))
    def snapshot(model,result):
        result.update(document_path=str(target),active_configuration='Default',configuration_names=state['configs'].copy(),
            explode_views=[],explode_step_scope='active_configuration_only',components=m._components(model)[0],
            native_step_sequence=[],studies=deepcopy(state['studies']))
        return result
    monkeypatch.setattr(m,'_snapshot',snapshot);monkeypatch.setattr(m,'_double_array',lambda values:tuple(values))
    def identity(component):
        return dict(name=component.Name2,reference=component.ComponentReference,path=str(component.path),
            sha256=m._file_hash(component.path),configuration='Default',native_id=component.i,matrix=IDENTITY.copy(),fixed=True)
    moves=[identity(c) for c in components[:2]]
    moves[0]['target_matrix']=IDENTITY.copy();moves[0]['target_matrix'][9:12]=[-.0055,.0105,0.]
    moves[1]['target_matrix']=IDENTITY.copy();moves[1]['target_matrix'][9:12]=[.0055,-.0105,0.]
    removals=[identity(c) for c in components[2:4]]
    proof=dict(status='review_required',phase='finished',native_reference_calls_returned=True,source_files_unchanged=True,
        copied_source_sha256=m._file_hash(source),output_path=str(target),output_sha256=m._file_hash(target),
        before=dict(config=dict(source_path=str(source),source_sha256=m._file_hash(source),output_path=str(target)),
                    frozen_files={str(source):dict(path=str(source),sha256=m._file_hash(source))}))
    prior.write_text(json.dumps(proof),encoding='utf8')
    defaults=dict(process_id=71,expected_document_path=str(target),expected_file_sha256=m._file_hash(target),
        source_path=str(source),source_sha256=m._file_hash(source),prior_copy_receipt_path=str(prior),
        prior_copy_receipt_sha256=m._file_hash(prior),moves=moves,removals=removals,action='prepare',qualification_only=True)
    def run(**kwargs):return m.qualify_component_revision(sw,**(defaults|kwargs))
    def apply(**kwargs):
        prepared=run(**kwargs);assert prepared['status']=='ok',prepared
        return run(**(kwargs|dict(action='apply',expected_state_sha256=prepared['state_sha256'],receipt_path=str(receipt))))
    return N(**locals())


def test_prepare_is_read_only(graph):
    g=graph;r=g.run()
    assert r['status']=='ok' and r['phase']=='prepared' and not r['mutation_attempted']
    assert not g.state['calls'] and not g.receipt.exists() and not g.model.dirty


def test_two_moves_two_removals_only_and_unsaved(graph):
    g=graph;disk=g.target.read_bytes();source=g.source.read_bytes();untouched=deepcopy(m._components(g.model)[0][-1])
    r=g.apply()
    assert r['status']=='review_required' and r['component_readback_verified'],r
    assert r['unchanged_other_components_verified'] and r['requires_explicit_save_and_close_reopen']
    assert not r['saved'] and not r['reopened_verified'] and not r['animation_verified'] and g.model.dirty
    assert len(g.components)==3 and {c.Name2 for c in g.components}=={'screw0','screw3','untouched'}
    assert all(c.fixed for c in g.components)
    assert g.target.read_bytes()==disk and g.source.read_bytes()==source
    assert all(Path(row['path']).exists() for row in g.removals)
    assert m._components(g.model)[0][-1]==untouched
    assert json.loads(g.receipt.read_text(encoding='utf8'))['component_readback_verified']


@pytest.mark.parametrize('key,value',[('process_id',72),('expected_file_sha256','0'*64),('source_sha256','0'*64),
                                    ('prior_copy_receipt_sha256','0'*64),('qualification_only',False)])
def test_pins_and_process_fail_before_mutation(graph,key,value):
    r=graph.run(**{key:value})
    assert r['status']=='error' and not r['mutation_attempted'] and not graph.state['calls']


def test_prior_proof_must_qualify_exact_copy(graph):
    g=graph;proof=deepcopy(g.proof);proof['output_path']=str(g.source)
    g.prior.write_text(json.dumps(proof),encoding='utf8')
    r=g.run(prior_copy_receipt_sha256=m._file_hash(g.prior))
    assert r['status']=='error' and not g.state['calls']


def test_stale_prepared_state_blocked(graph):
    g=graph;p=g.run();g.components[-1].ComponentReference='changed reference'
    r=g.run(action='apply',expected_state_sha256=p['state_sha256'],receipt_path=str(g.receipt))
    assert r['status']=='error' and not r['mutation_attempted'] and not g.receipt.exists()


def test_other_dependency_change_blocked(graph):
    g=graph;p=g.run();g.components[-1].path.write_bytes(b'changed dependency')
    r=g.run(action='apply',expected_state_sha256=p['state_sha256'],receipt_path=str(g.receipt))
    assert r['status']=='error' and not r['mutation_attempted']


@pytest.mark.parametrize('field,value',[('name','other'),('reference','other'),('fixed',False),('native_id',999),('configuration','other')])
def test_exact_instance_identity_required(graph,field,value):
    g=graph;moves=deepcopy(g.moves);moves[0][field]=value;r=g.run(moves=moves)
    assert r['status']=='error' and not g.state['calls']


def test_ambiguous_action_rejected(graph):
    g=graph;r=g.run(removals=[{k:v for k,v in g.moves[0].items() if k!='target_matrix'}])
    assert r['status']=='error' and not g.state['calls']


@pytest.mark.parametrize('index,value',[(0,2),(12,.5),(9,float('nan')),(10,2.)])
def test_only_bounded_finite_pure_translation(graph,index,value):
    moves=deepcopy(graph.moves);moves[0]['target_matrix'][index]=value;r=graph.run(moves=moves)
    assert r['status']=='error' and not graph.state['calls']


@pytest.mark.parametrize('restriction',['mates','children','configs','selection','dirty'])
def test_unsupported_document_and_component_states(graph,restriction):
    g=graph
    if restriction in {'mates','children'}:setattr(g.components[0],restriction,[object()])
    elif restriction=='configs':g.state['configs']=['Default','Other']
    elif restriction=='selection':g.model.selected=[g.components[-1]]
    else:g.model.dirty=True
    r=g.run();assert r['status']=='error' and not g.state['calls']


def test_failed_transform_stops_without_fallback_save_or_delete(graph):
    g=graph;g.state['return_move']=False;r=g.apply()
    assert r['status']=='uncertain' and not r['component_readback_verified']
    assert [x[0] for x in g.state['calls']]==['select','unfix','move']
    assert len(g.components)==5 and not g.components[0].fixed
    assert json.loads(g.receipt.read_text(encoding='utf8'))['status']=='uncertain'


def test_fix_readback_required(graph):
    g=graph;g.state['skip_fix']=True;r=g.apply()
    assert r['status']=='uncertain' and not r['component_readback_verified']
    assert not any(c[0]=='delete' for c in g.state['calls'])


def test_unapproved_other_transform_stops(graph):
    g=graph;g.state['on_move']=lambda c:g.components[-1].matrix.__setitem__(9,.001)
    r=g.apply();assert r['status']=='uncertain' and not any(c[0]=='delete' for c in g.state['calls'])


def test_wrong_selection_stops_before_model_edit(graph):
    g=graph;g.state['wrong_select']=True;r=g.apply()
    assert r['status']=='uncertain' and not g.model.dirty
    assert [x[0] for x in g.state['calls']]==['select']


def test_failed_delete_not_retried(graph):
    g=graph;g.state['return_delete']=False;r=g.apply()
    assert r['status']=='uncertain' and len(g.components)==5
    assert len([x for x in g.state['calls'] if x[0]=='delete'])==1


def test_deletion_cascade_detected(graph):
    g=graph;g.state['on_delete']=lambda:g.components.pop();r=g.apply()
    assert r['status']=='uncertain' and not r['component_readback_verified']


def test_motion_metadata_change_detected(graph):
    g=graph;g.state['on_delete']=lambda:g.state['studies'][0].update(duration_seconds=1.)
    r=g.apply();assert r['status']=='uncertain' and not r['component_readback_verified']


def test_receipt_replay_rejected(graph):
    g=graph;g.receipt.write_text('{}',encoding='utf8');p=g.run()
    r=g.run(action='apply',expected_state_sha256=p['state_sha256'],receipt_path=str(g.receipt))
    assert r['status']=='error' and not r['mutation_attempted'] and not g.state['calls']


def test_receipt_failure_stops_before_native_edit(graph,monkeypatch):
    g=graph;original=m._write_receipt
    def writer(path,report,*,create=False):
        if not create:raise OSError('simulated receipt failure')
        return original(path,report,create=create)
    monkeypatch.setattr(m,'_write_receipt',writer)
    r=g.apply();assert r['status']=='uncertain' and not g.state['calls']


def test_source_alias_rejected(graph):
    g=graph;r=g.run(expected_document_path=str(g.source),expected_file_sha256=m._file_hash(g.source))
    assert r['status']=='error' and not g.state['calls']


@pytest.mark.parametrize('side',['actual','expected'])
@pytest.mark.parametrize('invalid',[float('nan'),float('inf'),float('-inf'),True,'0','short'])
def test_matrix_readback_requires_sixteen_finite_numbers(graph,side,invalid):
    rows=m._components(graph.model)[0];actual=deepcopy(rows);expected=deepcopy(rows)
    selected=actual if side=='actual' else expected
    if invalid=='short':selected[0]['matrix']=selected[0]['matrix'][:-1]
    else:selected[0]['matrix'][9]=invalid
    with pytest.raises(ValueError,match='sixteen finite numbers'):
        m._same_rows(actual,expected)


def test_assembly_root_component_is_allowed(graph):
    assert graph.model.GetEditTargetComponent() is not None
    assert graph.run()['status']=='ok'


@pytest.mark.parametrize('missing',[False,True])
def test_foreign_or_missing_edit_target_rejected_before_mutation(graph,missing):
    graph.model.GetEditTarget=lambda:None if missing else object()
    r=graph.run()
    assert r['status']=='error' and not r['mutation_attempted'] and not graph.state['calls']
