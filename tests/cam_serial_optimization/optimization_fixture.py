from copy import deepcopy

def fixture():
    tool=dict(native_id=88,cut_diameter_native=.8,protrusion_native=19.,tool_type_raw=1)
    def operation(i,idx,kind=0,fid=1001):return dict(native_id=i,setup_index=0,setup_native_id=93,operation_index=idx,mill_operation_type=kind,base_operation_type=1,suppressed=False,toolpath_generated=idx>=3,toolpath_record_counts=[100+idx]if idx>=3 else[],linked_feature_ids=[fid],assigned_tool=deepcopy(tool))
    binding=dict(features={str(i):dict(native_id=i)for i in range(997,1003)},operation_setups=[dict(index=0,native_id=93,operation_count=17)],operations=[operation(i,i-1)for i in range(1,18)])
    baseline=dict(binding=deepcopy(binding),parameters=[dict(operation_native_id=i,feature_native_id=1001,read_complete=True,sentinel=i)for i in range(1,9)])
    snap=deepcopy(baseline);snap['binding']['operation_setups'][0]['operation_count']=21;targets=[];planrows=[]
    for j,oid in enumerate(range(101,105)):
        kind=j%2;fid=1001+j//2
        t=dict(key='local'+str(j),operation_native_id=oid,feature_native_id=fid,operation_type=kind,operation_setup_native_id=93,assigned_tool=deepcopy(tool));targets.append(t)
        snap['binding']['operations'].append(operation(oid,17+j,kind,fid))
        row=dict(operation_native_id=oid,feature_native_id=fid,read_complete=True,tool=dict(generic=deepcopy(tool),mill=dict(EffCutlength=dict(raw=4.))),levels=dict(levels=dict(machining_depth_native=3.4000000000000004,axis=-1)),nc=dict(feeds_compensation=dict(GetTlpComp=1,GetCNCComp=0,GetSpndlSpeed=7100.,GetRetractType=0,XYFeed=35.)))
        if kind==0:
            row['rough']=dict(depth=dict(FirstDepthAmt=dict(raw=.3),SbsqDepthAmt=dict(raw=.3),FinCutAmt=dict(raw=.25),GetStartDepth=dict(raw=[False,.3],is_percent=False,value_native=.3),GetSubsequentDepthAmount=dict(raw=[False,.3],is_percent=False,value_native=.3)),entry=dict(GetEntryExitType=dict(raw=4),GetSpiralRadius=dict(raw=.1),GetSpiralPitch=dict(raw=.02)),boundary=dict(SideAllow=dict(raw=.008)))
            row['startpoints']=dict(entry_type=4,count=1,points=[dict(x=1.,y=2.)])
        else:
            row['finish_fields']=dict(first_depth=[.3,False],max_depth=[.3,False],final_depth=0.)
            row['finish']=dict(FirstDepthCut=dict(raw=.3),MaxDepthCut=dict(raw=.3),FinalDepthCut=dict(raw=0.),SideAllow=dict(raw=0.))
        snap['parameters'].append(row)
        p=dict(operation_native_id=oid,feature_native_id=fid,operation_type=kind,tool_native_id=88,depth_mm=3.4)
        if kind==0:p['spiral_pitch_mm']=.5
        planrows.append(p)
    plan=dict(scope='EXISTING_FOUR_DEPTH_AND_AIR_PITCH_V1',rows=planrows,maximum_GTP=4,maximum_Save=1,physical_cutting_conditions_qualified=False,production_qualified=False)
    return baseline,snap,targets,plan
