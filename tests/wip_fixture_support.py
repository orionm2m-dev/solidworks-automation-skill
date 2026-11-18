"""Synthetic complete circular states; no application or project evidence dependency."""
from copy import deepcopy
from test_current_saved_parameter_fields import fixture as parameter_fixture, actual_change

def state_recipe():
    b, _, _ = parameter_fixture()
    row = deepcopy(b['operation_parameters'][0])
    row.update(operation_native_id=361, feature_native_id=359)
    row['tool']['generic']['native_id'] = 249
    for key, value in [('entry_type',4), ('spiral_radius',3.), ('spiral_pitch',.1),
                       ('first_depth',[False,.3]), ('subsequent_depth',[False,.3])]:
        actual_change(row,key,value)
    b['operation_parameters'] = [row]
    b['operations'] = []
    for i in range(26):
        oid = 361 if i==25 else 100+i
        generated = i<18 or i==25
        b['operations'].append(dict(native_id=oid,mill_operation_type=0,
            linked_feature_ids=[359 if i==25 else 1000+i],suppressed=False,
            toolpath_generated=generated,toolpath_record_counts=[11158 if i==25 else 10+i] if generated else [],
            assigned_tool=deepcopy(row['tool']['generic']),setup_native_id=94))
    b.update(capture_complete=True,extended_capture_complete=True,operation_count=26,operation_counts=[26],
             sketch_state=dict(pid=123,needs_save=False,saved_file_sha256='a'*64,
                               solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[0.,0.,0.,1.])]))
    nc=dict(GetSpndlSpeed=200.,XYFeed=1000.,GetSpeedFeedMethod=0,LinkToTool=True,
            GetIsLockSpindleSpeed=False,GetZFeedrate2=[2.,False],GetLeadinFeedratePercent=30.,
            GetCNCComp=0,GetTlpComp=1,
            leadin_feed=dict(value_native=2.,is_percent=False,physical_units_verified=False))
    b['cutting_context']=dict(nc=nc,local_planes=dict(clearance=5.,rapid=2.))
    b['parameter_batch']['target_nc']={}
    b['parameter_batch']['candidate_consumers']={}
    for family in ('target_nc','candidate_consumers'):
        for oid in (100,361):
            b['parameter_batch'][family][str(oid)] = dict(operation_native_id=oid,read_complete=True,
                feeds_compensation=dict(GetSpndlSpeed=200.,XYFeed=1000.,GetCNCComp=0,GetTlpComp=1))
    r=dict(operation_native_id=361,feature_native_id=359,expected_tool_native_id=249,qualification_only=True,
        rough=[dict(field='first_depth',expected=[False,.3],new=[False,7.4]),
               dict(field='subsequent_depth',expected=[False,.3],new=[False,7.4]),
               dict(field='spiral_pitch',expected=.1,new=.6)],
        nc=[dict(field='LinkToTool',expected=True,new=False),
            dict(field='GetSpndlSpeed',expected=200.,new=2000.),
            dict(field='XYFeed',expected=1000.,new=150.),
            dict(field='leadin_feed',expected=deepcopy(nc['leadin_feed']),
                 new=dict(value_native=75.,is_percent=False,physical_units_verified=False))])
    return b,r

def independently_configured(b,r):
    a=deepcopy(b)
    for change in r['rough']: actual_change(a['operation_parameters'][0],change['field'],change['new'])
    for change in r['nc']: a['cutting_context']['nc'][change['field']]=deepcopy(change['new'])
    for family in ('target_nc','candidate_consumers'):
        a['parameter_batch'][family]['361']['feeds_compensation'].update(GetSpndlSpeed=2000.,XYFeed=150.)
    a['document']['needs_save']=True
    a['sketch_state']['needs_save']=True
    return a
