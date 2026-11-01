from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import json
from scripts import sw_cam_turn_named_bore_definitions as m

def event_ok():return dict(subscribed=True,active=False,disconnected=True,event_count=0,overflow=0,callback_errors=[],callback_error_count=0,subscription_error=None,disconnect_errors=[])


def state():
    types=[7,8,1,2,14,9,3,4,13];counts=[[40],[19],[97],[43],[],[],[],[],[]]
    operations=[dict(setup_index=0,operation_index=i,native_id=100+i,turn_operation_type=t,linked_feature_ids=[76 if i==5 else 20+i],suppressed=False) for i,t in enumerate(types)]
    inventory=dict(machine_type=3,feature_setup_count=1,feature_counts_by_setup=[5],feature_count=5,operation_setup_count=1,operation_count=9,operations=[dict(setup_index=0,operation_index=i,turn_operation_type=t,toolpath_generated=bool(counts[i]),toolpath_record_counts=counts[i]) for i,t in enumerate(types)],stock=dict(type=3))
    return dict(document=dict(path='part.SLDPRT',title='part',type=1,needs_save=False),saved_file_sha256='a'*64,inventory=inventory,operations=operations,feature_ids=[dict(setup_index=0,native_ids=[20,21,22,76,24])],feature_header=dict(turn_feature_type_raw=2,name='Bore',attribute_id_raw=0,attribute_name='Drill'))


def insert_state(s,kind,new_id,anchor_id):
    t=deepcopy(s);ai=next(i for i,x in enumerate(t['operations']) if x['native_id']==anchor_id);oi=t['operations'][ai]['operation_index']+1
    for x in t['operations'][ai+1:]:x['operation_index']+=1
    t['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,native_id=new_id,turn_operation_type=kind,linked_feature_ids=[76],suppressed=False))
    for x in t['inventory']['operations'][ai+1:]:x['operation_index']+=1
    t['inventory']['operations'].insert(ai+1,dict(setup_index=0,operation_index=oi,turn_operation_type=kind,toolpath_generated=False,toolpath_record_counts=[]));t['inventory']['operation_count']+=1;t['document']['needs_save']=True;return t



def resolved(rough=5,finish=6):
    return m.roles.resolve_roles(SimpleNamespace(CW_TURN_OP_ROUGH_BORE=rough,CW_TURN_OP_FINISH_BORE=finish,CW_TURN_OP_ROUGH_TURN=1,CW_TURN_OP_FINISH_TURN=2),list(m.roles.ROLE_SYMBOLS))


def request(tmp_path):
    return dict(process_id=7,expected_document_path=str(tmp_path/'part.SLDPRT'),expected_source_sha256='a'*64,feature_native_id=76,anchor_operation_native_id=105,definitions=[dict(role='rough_bore',default_name='Default',default_operation_id=3),dict(role='finish_bore',default_name='Default',default_operation_id=4)],receipt_path=str(tmp_path/'result.json'))


def catalogue(s,p,rs):
    before=dict(operation_native_id=105,feature_native_id=76,operation_type=9,suppressed=False,generated=False,feature_header=deepcopy(s['feature_header']))
    obs=[];cats={}
    for spec,d in zip(rs,p['definitions']):
        role=spec['role'];obs.extend([dict(key=role+'_names',value=['Default'],returned_type='tuple'),dict(key=role+'_id_Default',value=d['default_operation_id'],returned_type='int')])
        cats[role]=dict(spec,operation_type=1,converted_python_type='tuple',entries=[dict(name='Default',default_operation_id=d['default_operation_id'])],unique_default_available=True,selected_default_operation_id=None,selection_performed=False)
    r=dict(scope=m.roles.SCOPE,status='observed',phase='finished',readback_verified=True,read_only=True,source_path=p['expected_document_path'],source_sha256='a'*64,before=before,after=deepcopy(before),inventory_before=deepcopy(s['inventory']),inventory_after=deepcopy(s['inventory']),request=dict(process_id=7,setup_index=0,operation_index=5,roles=list(m.roles.ROLE_SYMBOLS)),messages=event_ok(),abi=dict(roles=rs),observations=obs,catalogues=cats)
    r.update({k:False for k in ('mutation_attempted','GTP_attempted','model_saved','operation_inserted','assignment_attempted')});return r


def reference(oid):return dict(operation_native_id=oid,tool_native_id=oid+1000,tool_type_raw=15,turn_tool_type_raw=1,insert_type_raw=1,holder_type_raw=2,holder_id_raw=2)


def fake_run(tmp_path,*,fail=None,kinds=(5,6)):
    p=request(tmp_path);s=state();s['document']['path']=p['expected_document_path'];rs=resolved(*kinds);c=catalogue(s,p,rs);trace=[]
    r=dict(scope=m.SCOPE,status='prepared',phase='prepared',request=p,process_id=7,source_path=p['expected_document_path'],source_sha256='a'*64,actions={},native_dispatch_pending=False,mutation_attempted=False,readback_verified=False,**{k:False for k in m.FORBIDDEN})
    plan=dict(catalogue=c,roles=rs,marker=tmp_path/'marker.json')
    def persist():Path(p['receipt_path']).write_text(json.dumps(r))
    class Backend:
        current=deepcopy(s);insert_count=0;tool_calls=0
        def start(self):trace.append('start')
        def capture(self,label):
            trace.append(label)
            if fail==label:raise RuntimeError('capture failed')
            value=deepcopy(self.current)
            if fail=='drift_after_first' and label=='InsertOperation_rough_bore_readback':value['inventory']['operations'][0]['toolpath_record_counts']=[999]
            return value
        def catalogue_check(self):trace.append('catalogue')
        def insert(self,spec,anchor,pending):
            pending();label='insert'+str(spec['operation_type']);trace.append(label)
            assert plan['marker'].exists() and json.loads(Path(p['receipt_path']).read_text())['native_dispatch_pending'] is True
            if fail==label:raise RuntimeError('native outcome unknown')
            self.insert_count+=1;oid=200+self.insert_count;self.current=insert_state(self.current,spec['operation_type'],oid,anchor)
            if fail=='wrong_turn_type' and self.insert_count==1:
                self.current['operations'][6]['turn_operation_type']=1;self.current['inventory']['operations'][6]['turn_operation_type']=1
            return oid
        def assigned(self,oid):
            trace.append('tool'+str(oid));self.tool_calls+=1
            if fail=='tool'+str(oid):raise RuntimeError('IGetTool unavailable')
            value=reference(oid)
            if fail=='final_first_tool_drift' and self.tool_calls==3:value['tool_native_id']+=1
            if fail=='final_second_tool_drift' and self.tool_calls==4:value['tool_native_id']+=1
            if fail=='wrong_holder' and oid==201:value['holder_type_raw']=1
            if fail=='zero_tool' and oid==201:value['tool_native_id']=0
            return value
        def finish(self):trace.append('finish');r['messages']=event_ok()
        def close(self):trace.append('close');r['messages']=event_ok()
        def save(self):raise AssertionError('Save forbidden')
    return lambda:m.run_backend(Backend(),p,plan,r,persist),r,trace,plan


