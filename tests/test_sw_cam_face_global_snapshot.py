"""合成状态下的 CAM 边界与失败回归；不连接应用。"""
from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from scripts import sw_cam_raw_mill_face_feature as m
from scripts import sw_cam_dispatch_guard as guards
from scripts import sw_cam_mill_qualification as legacy
from scripts import sw_cam_turn_feature_attribute as oldcollections
from test_sw_cam_face_headers import environment,Node


def graph(monkeypatch,tmp_path,count=20):
    reader=m._snapshot_bounded
    e=environment(monkeypatch,tmp_path,count)
    monkeypatch.setattr(m,'_snapshot_bounded',reader)
    app,addin,part=Node('app'),Node('addin'),Node('part')
    catalogue=[Node('catalogue',row=r) for r in e.ref['mill_catalogue']]
    original=e.read
    faults={};fired=[]
    def read(obj,name,*args):
        if name=='ExtendHolesToStock' and faults.get('exit') and not fired:
            fired.append(True);faults['exit']()
        if obj.kind=='sw' and name=='GetAddInObject':return addin
        if obj.kind=='addin' and name=='GetCWApp':return app
        if obj.kind=='app':
            if name=='IGetActiveDoc':return e.doc
            if name=='GetNumMachineOfType':assert args==(1,);return len(catalogue)
            if name=='GetMachines':assert args==(1,);return Node('collection',items=catalogue)
        if obj.kind=='part' and name=='IGetMachine':return e.machine
        if obj.kind in ('machine','catalogue'):
            row=e.ref['current_machine'] if obj.kind=='machine' else obj.values['row']
            if name=='MachType':return row['machine_type']
            if name in ('Name','MachId','Description'):return row[{'Name':'name','MachId':'machine_id','Description':'description'}[name]]
            if name=='IGetEnumSetups':return Node('collection',items=e.setups)
        if obj.kind=='setup':
            row=obj.values['row']
            if name in ('SetupName','Axis','GetReferencePosition','OriginType'):
                return deepcopy(row[{'SetupName':'name','Axis':'axis_native','GetReferencePosition':'origin_native','OriginType':'origin_type_raw'}[name]])
        if obj.kind=='workpiece' and name=='Material':return e.ref['material_raw']
        if obj.kind=='doc' and name=='ExtendHolesToStock':return e.ref['extend_holes_to_stock']
        return original(obj,name,*args)
    def typed(obj,name,tlb):
        if obj is e.doc and name=='ICWPartDoc':return part
        if obj.kind=='operation' and name=='ICWMillOperation':return Node('milloperation',obj.oid,**obj.values)
        return obj
    for module in (m,m.cone,guards,legacy):monkeypatch.setattr(module,'_member',read)
    for module in (m,m.cone,legacy,oldcollections):monkeypatch.setattr(module,'_typed',typed)
    import scripts.sw_cam_generation as generation
    monkeypatch.setattr(generation,'_typed',typed)
    # Guard's imported helper, not generation's name, is the actual strong QI.
    monkeypatch.setattr(guards,'_typed',typed)
    monkeypatch.setattr(legacy,'document_snapshot',lambda sw:deepcopy(e.ctx.identity()))
    return SimpleNamespace(e=e,app=app,part=part,addin=addin,read=read,typed=typed,faults=faults)

@pytest.mark.parametrize('count',[20,21])
def test_exact_original_snapshot_schema_and_values(monkeypatch,tmp_path,count):
    v=graph(monkeypatch,tmp_path,count);e=v.e
    expected,_=legacy._snapshot(e.ctx.sw,'offline','offline',e.ctx.args['expected_document_path'],check=e.ctx.events,required_machine_type=1)
    d={};actual,native=m._snapshot_bounded(e.ctx,'offline',d)
    assert actual==expected and d['observed_state']==expected and d['capture_complete']
    batch=d['read_batch'];assert batch['read_scope_complete'] and batch['complete_boundary_checks']==2
    assert batch['retained_binding_checks']==2 and batch['getter_calls']>len(e.state['features']) and batch['query_interface_calls']>10
    assert batch['metadata_checks']==6*batch['unique_file_count'] and not batch['dispatch_available']
    assert native['doc'] is e.doc and native['machine'] is e.machine and native['setups']==e.setups

@pytest.mark.parametrize('count',[20,21])
def test_whole_header_actual_global_snapshot_and_header_helpers(monkeypatch,tmp_path,count):
    v=graph(monkeypatch,tmp_path,count);e=v.e;d={}
    state,native=m._capture_headers(e.ctx,'offline',e.ref,count,d)
    assert state==e.state and len(state['features'])==count and len(state['operations'])==6
    assert d['global_snapshot_before']['capture_complete'] and d['global_snapshot_after']['capture_complete']
    assert d['global_snapshot_before']['read_batch']['getter_calls']>len(e.state['features'])
    assert d['header_read_batch']['getter_calls']>400 and d['capture_complete']
    guards_list=[d['header_strong_before'],d['header_strong_after']]
    for label in ('global_snapshot_before','global_snapshot_after'):
        guards_list.extend([d[label]['root_acquisition_guard'],d[label]['read_batch']])
    units=sum(g['metadata_checks']//g['unique_file_count'] for g in guards_list)
    assert units<100

@pytest.mark.parametrize('fault',['source','evidence','owned','identity','events','history'])
def test_changed_boundary_rejected_with_raw_observations(monkeypatch,tmp_path,fault):
    v=graph(monkeypatch,tmp_path);e=v.e
    if fault=='source':callback=lambda:e.source.write_bytes(b'changed source')
    elif fault=='evidence':callback=lambda:e.evidence.write_bytes(b'changed evidence')
    elif fault=='owned':callback=lambda:e.fault.update(owned=True)
    elif fault=='identity':callback=lambda:e.fault.update(identity=True)
    elif fault=='events':callback=lambda:e.fault.update(event=True)
    else:
        original=e.ctx.files;history={'changed':False}
        def files():
            original()
            if history['changed']:raise ValueError('History changed')
        e.ctx.files=files;callback=lambda:history.update(changed=True)
    v.faults['exit']=callback;d={}
    with pytest.raises(ValueError):m._snapshot_bounded(e.ctx,'offline',d)
    assert not d['capture_complete'] and d['observed_state']['feature_setups']
    assert 'read_batch' in d

@pytest.mark.parametrize('bad',['setter','global','interface','foreign','boolindex','foreign_id','dispatch'])
def test_closed_allowlist_and_retained_owners(monkeypatch,tmp_path,bad):
    v=graph(monkeypatch,tmp_path);e=v.e
    b=m.ScopedMillSnapshotReadBatch(e.ctx.sw,'offline',native_context=dict(app=v.app,doc=e.doc,machine=e.machine),
        process_id=17,expected_document=e.ctx.identity(),source_sha256=e.ctx.args['expected_source_sha256'],
        evidence_pins=e.ctx.loaded['pins'],verify_evidence=e.ctx.files,verify_owned_process=e.ctx.owned,check_events=e.ctx.events)
    with pytest.raises(ValueError):
        with b:
            if bad=='setter':b.read(e.doc,'Save')
            elif bad=='global':b.read(e.ctx.sw,'ActiveDoc')
            elif bad=='interface':b.typed(e.doc,'ICWStrategy')
            elif bad=='foreign':b.read(Node('doc'),'GetDocType')
            elif bad=='boolindex':b.read(e.doc,'Item',True)
            elif bad=='foreign_id':b.read(e.doc,'GetCWObjectID',Node('setup',999))
            else:b.dispatch_once(lambda:None,persist_pending=lambda:None)
    assert not b.summary()['read_scope_complete']
    with pytest.raises(ValueError):b.require_complete()
