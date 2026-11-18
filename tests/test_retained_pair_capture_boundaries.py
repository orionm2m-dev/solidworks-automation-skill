"""Strong capture integration and late failures; fixed synthetic data only."""
from copy import deepcopy
from pathlib import Path
import ast
import pytest
from test_current_pocket_pair_retained import env,m,RT


def reference(e):
    g=e['graph'];batch=object.__new__(m.reader.ReadGuard)
    batch._invalid=False;batch.calls=0;batch.report={};batch._observe=lambda f:f();batch._boundary=lambda:None
    out={};m.generation.read_pair(deepcopy(g.state),g.native,g.rows,batch,out,lambda:None,{})
    state=deepcopy(g.state);state['document']=deepcopy(e['document'])
    return dict(inventory=state,parameters=out['parameters'])

@pytest.fixture
def full(env,monkeypatch):
    s=reference(env);g=env['graph'];control={'captures':0,'fault':None};diag={}
    paths=(m.__file__,m.generation.__file__,m.definition_capture.__file__,m.retained.__file__,env['source'],env['evidence'])
    context=dict(request={'process_id':123},expected_source_sha256=env['kwargs']['source_sha256'],pins=[env['pin'](Path(p))for p in paths])
    def capture(*args):
        control['captures']+=1;value=deepcopy(s['inventory']);native=g.native;fault=control['fault']
        if control['captures']==1 and fault=='missing_machine':native={k:v for k,v in native.items()if k!='machine'}
        if control['captures']==2:
            if fault=='body':raise ValueError('CAD/sketch snapshot differs from immutable creator baseline')
            if fault=='inventory':value['operations'][1]['setup_native_id']+=1
            if fault=='dirty':value['document']['needs_save']=True
            if fault=='runtime':env['state']['owned']=False
            if fault=='event':env['state']['events']=False
            if fault=='source':env['source'].write_bytes(b'changed saved source')
            if fault=='evidence':env['evidence'].write_bytes(b'changed evidence')
        return value,native
    monkeypatch.setattr(m.definition_capture,'capture',capture)
    monkeypatch.setattr(m.reader.definition,'identity',lambda *a:dict(document=deepcopy(env['state']['doc'])))
    def run():
        return m.capture_pair(env['sw'],'fixed','none.tlb',context,expected_snapshot=s,generation_observations={},check_events=env['events'],runtime_check=env['owned'],abi={'generated_pin':env['pin'](env['evidence'])},diagnostic=diag,persist=lambda:None)
    return env,s,context,control,diag,run

@pytest.mark.parametrize('fault',['body','inventory','dirty','runtime','event','source','evidence','missing_machine'])
def test_no_usable_result_after_context_drift(full,fault):
    e,s,c,control,diag,run=full;control['fault']=fault
    with pytest.raises((ValueError,AssertionError,KeyError)):run()
    assert diag['read_complete']is False
    assert 'before_definition'in diag['timing_seconds']
    if fault!='missing_machine':assert set(diag['timing_seconds'])=={'before_definition','parameters','after_definition'}
    assert not any(diag[k]for k in ('mutation_attempted','Save_attempted','GOP_attempted','GTP_attempted','automatic_retry'))


def test_parameter_difference_is_not_silently_adopted(full):
    e,s,c,ctl,diag,run=full;s['parameters'][0]['rough']['entry']['GetSpiralRadius']['raw']=999.
    with pytest.raises(ValueError,match='payload differs'):run()
    assert diag['read_complete']is False


def test_missing_dependency_pin_rejects_before_capture(full):
    e,s,c,ctl,diag,run=full;c['pins']=[p for p in c['pins']if Path(p['path'])!=Path(m.retained.__file__)]
    with pytest.raises(ValueError,match='dependency pin'):run()
    assert ctl['captures']==0 and not diag


def test_definition_capture_really_returns_retained_machine():
    tree=ast.parse(Path(m.definition_capture.__file__).read_text(encoding='utf-8'))
    method=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='capture')
    returned=next(n.value for n in method.body if isinstance(n,ast.Return))
    assert isinstance(returned,ast.Tuple)
    native=returned.elts[1]
    assert isinstance(native,ast.Call)and isinstance(native.func,ast.Name)and native.func.id=='dict'
    assert {x.arg for x in native.keywords}=={'app','doc','machine','selected_feature'}
    assert next(x.value for x in native.keywords if x.arg=='machine').id=='machine'


def test_fixed_payload_and_native_getters_are_imported_not_cloned():
    assert m.RetainedPairReadBatch.typed is m.reader.ReadGuard.typed
    assert m.RetainedPairReadBatch.plane is m.reader.ReadGuard.plane
    tree=ast.parse(Path(m.__file__).read_text(encoding='utf-8'))
    calls=[n for n in ast.walk(tree)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)]
    assert sum(isinstance(n.func.value,ast.Name)and n.func.value.id=='generation'and n.func.attr=='read_pair'for n in calls)==1
    assert sum(isinstance(n.func.value,ast.Name)and n.func.value.id=='definition_capture'and n.func.attr=='capture'for n in calls)==2


@pytest.mark.parametrize('member,args',[('Item',(True,)),('GetCWObjectFromID',(3,True))])
def test_boolean_native_index_rejected_before_invocation(env,member,args):
    b=env['make']();g=env['graph']
    with pytest.raises(ValueError,match='Argument outside'):
        with b:b.read(g.doc,member,*args)
    assert not g.trace
    with pytest.raises(ValueError):b.require_complete()
