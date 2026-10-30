"""不依赖 CAD 文件或历史收据的合成 CAM 测试状态。"""
from copy import deepcopy

def state(feature_count=19, appended=False):
    counts=[feature_count-6,5,1]; setups=[];features=[]
    ids=[75,76,77,78,79,80,81,82,83,84,85,86,244]
    for si,(sid,count) in enumerate(zip((69,71,73),counts)):
        setups.append(dict(native_id=sid,name='Fixture setup '+str(si),feature_count=count,axis_native=[0.,0.,-1.],origin_native=[0.,0.,0.],origin_type_raw=6))
        for fi in range(count):
            oid=(ids[fi] if fi<len(ids) else (264 if fi==13 else 265)) if si==0 else 300+si*20+fi
            g=dict(native_id=oid,name='Fixture feature '+str(oid),volume_type=2 if oid==79 else 6,subtype_raw=0,shape_raw=2 if oid==79 else 0,suppressed=False,axis_native=[0.,0.,-1.],depth_native=1.,bounds_native=[2.,2.,1.],start_native=[0.,0.,0.])
            features.append(dict(setup_index=si,setup_native_id=sid,feature_index=fi,geometry=g))
    operations=[]
    for i,oid in enumerate((143,144,195,196,247,248)):
        generated=i>=4;tool_id=(263 if i==4 else 249 if i==5 else 145+i)
        tool=dict(native_id=tool_id,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,tool_type_raw=1,cut_diameter_native=8. if generated else 2.,protrusion_native=25. if generated else 20.)
        operations.append(dict(setup_index=0,setup_native_id=93,operation_index=i,native_id=oid,mill_operation_type=1 if i==5 else 0,base_operation_type=0,suppressed=False,toolpath_generated=generated,linked_feature_ids=[244 if generated else 79],toolpath_record_counts=[191 if i==4 else 74] if generated else [],assigned_tool=tool))
    if appended:
        operations.append(dict(setup_index=0,setup_native_id=93,operation_index=6,native_id=267,mill_operation_type=20,base_operation_type=0,suppressed=False,toolpath_generated=False,linked_feature_ids=[265],toolpath_record_counts=[],assigned_tool=dict(native_id=252,is_mill_tool=True,native_read_complete=True,units_verified=False,holder_geometry_verified=False,tool_type_raw=1,cut_diameter_native=12.,protrusion_native=50.)))
    ec=lambda:dict(depth_native=1.,type_raw=2,name='',is_reversed=False,units_verified=False,name_observed_representation='python_str')
    profile=dict(native_id=79,owner_setup_native_id=69,volume_type=2,suppressed=False,shape=2,island_count=0,sketch_count=1,sketch_names=dict(value=['Fixture sketch'],observed_representation='python_tuple',native_vartype=None,native_vartype_status='not_exposed_by_marshaller',observed_name_count=1,matches_sketch_count=True,count_relation_verified=False),sketch_names_return_python_type='tuple',end_conditions={n:ec() for n in ('GetEndCondition1','GetEndCondition2')},representation='ICWProfileFeature metadata',read_complete=True,profile_headers_read_complete=True,profile_geometry_complete=False,contour_status='not_requested',indexed_methods_called=False,units_verified=False,native_behavior_qualified=False)
    machine=dict(name='Fixture mill',machine_id='Fixture metric mill',machine_type=1,description='Offline fixture')
    opts={name:[dict(enum_value=i,enabled=False) for i in range(count)] for name,count in [('GetEMFFeatTypeOptions',6),('GetEMFPartPeriTypeOptions',2),('GetEMFTypeOptions',4)]};opts.update(EMFHoleMaxDiameter=.01,EMFHoleMinimumIncludedAngle=1.)
    n=len(operations)
    return dict(all_solid_body_count=1,visible_solid_body_count=1,current_machine=machine,mill_catalogue=[deepcopy(machine)],document=dict(path='fixture.SLDPRT',title='fixture.SLDPRT',type=1,needs_save=False),extend_holes_to_stock=False,feature_setups=setups,features=features,material_raw='Fixture material',operation_count=n,operation_counts=[n,0,0],operation_inventory_scope='bounded_raw_id_links_flags_counts_and_generic_tool',operation_setup_count=3,operation_setups=[dict(index=i,native_id=sid,operation_count=n if i==0 else 0) for i,sid in enumerate((93,94,95))],operations=operations,recognition_method=dict(name='MFGVIEW',status='observed_via_ICWDoc3_FeatureCreationStyle',value=1),recognition_options=opts,saved_file_sha256='a'*64,selected_profile_headers=profile,stock=dict(bounds_native=[-1.,-1.,-1.,1.,1.,1.],coordinate_system='',length_units_raw=0,offset_read_status='unavailable_native_false',offsets_native=None,stl_path='fixture.stl',stl_sha256='b'*64,type_raw=4,uniform_flags=None),sw_reference=dict(feature_tree=[dict(name='Fixture solid',type='Imported')],solids=[dict(box_m=[0.,0.,0.,1.,1.,1.],mass_raw=[float(i+1)/100 for i in range(12)])]),unit_record_raw=None,unit_record_status='unavailable_native_getter_disabled_after_RPC_failure')

def current():
    s=state(21,True)
    return dict(state=s,payload={'fixture':'rough'},finish_payload={'fixture':'finish'},ownership={'fixture':'owned'},ids=dict(target_feature_native_id=244,target_operation_native_id=247,target_operation_setup_native_id=93,expected_candidate_tool_native_id=263,finish_operation_native_id=248,finish_tool_native_id=249),observation_pin={'path':'fixture.json','sha256':'a'*64},holder_recipe={},cone_observation={'fixture':'cone'},face_observation={'fixture':'face'},cone_sketch_spec={},face_sketch_spec={},cone_feature_native_id=264,face_feature_native_id=265,source_sha256='a'*64,qualification=None,read_mode='bounded',base_saved_pin={'path':'base.json','sha256':'b'*64})

def mass_pair():
    a=state();a['document']['needs_save']=True;b=deepcopy(a)
    for i in range(8):b['sw_reference']['solids'][0]['mass_raw'][i]*=1.+1e-13
    return a,b
