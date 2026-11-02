"""Pure projection of a verified serial-tool authority into local-operation inputs.

The caller must first run the completed serial-tool loader. No partial feature
receipt, guessed curve, unverified source or arbitrary caller snapshot is authority.
Native default catalogues must be freshly read before compiling the selected plan.
"""
from copy import deepcopy
from scripts import sw_cam_local_operation_group as engine
from scripts import sw_cam_deep_long_tool_replace as dimensions
from scripts.sw_cam_rough_firstcut import require

group=engine.group


def tool_dimensions(context,baseline):
    candidate=context['serial_flat_tool'];body=candidate['full_tool'];tid=context['serial_flat_tool_native_id']
    require(body['geometry_read_complete']is True and body['profile_complete']is True and body['tool_native_id']==tid,'Complete actual serial tool profile required')
    template=deepcopy(baseline['parameters'][0]['tool']);generic=template['generic']
    generic.update(native_id=tid,is_mill_tool=True,native_read_complete=True,tool_type_raw=body['tool_type_raw'],
        cut_diameter_native=body['cut_diameter_native'],protrusion_native=body['tool_protrusion_native'])
    require(set(template['mill'])==set(dimensions.MILL_MAP)and set(template['holder'])==set(dimensions.HOLDER_MAP),'Exact reused dimension-reader field set required')
    observe=dimensions.writer.reader.pocket.rough.bounded_raw_observation
    template['mill']={k:observe(body['mill_tool'][v])for k,v in dimensions.MILL_MAP.items()}
    template['holder']={k:observe(body['holder'][v])for k,v in dimensions.HOLDER_MAP.items()}
    return template


def select_default(catalogues,kind,choice):
    rows=[r for r in catalogues if type(r['operation_type'])is int and r['operation_type']==kind]
    require(len(rows)==1,'Exactly one actual operation-kind catalogue required');entries=rows[0]['entries']
    require(type(choice)is dict,'Sealed default selection required')
    if choice=={'selection':'unique_native_default'}:
        require(len(entries)==1,'Native default is ambiguous; stop before any insertion')
        selected=entries[0]
    else:
        require(set(choice)=={'name','default_operation_id'},'Exact name/ID or unique-default policy required')
        hits=[r for r in entries if group.exact(r['name'],choice['name'])and group.exact(r['default_operation_id'],choice['default_operation_id'])]
        require(len(hits)==1,'Sealed name/ID is absent or ambiguous in actual catalogue');selected=hits[0]
    require(type(selected['name'])is str and selected['name']and type(selected['default_operation_id'])is int and selected['default_operation_id']>0,'Strict actual catalogue choice required')
    return dict(default_operation_name=selected['name'],default_operation_id=selected['default_operation_id'])


def project_context(context,recipe,catalogue_observations,choices,*,verify_feature,feed_policy):
    require(context.get('authority_kind')=='saved_serial_flat_tool_unassigned','Completed serial-tool authority required')
    loaded=deepcopy(context['deep_loaded']);baseline=loaded['guide_parameters']['expected_parameters']
    require(context['source_sha256']==context['state']['saved_file_sha256'],'Current saved source authority differs')
    require(group.exact(context['state']['document'],loaded['guide_parameters']['document'])and context['state']['document']['needs_save']is False,'Exact saved clean document required')
    require(type(context['serial_flat_catalogue'])is list and len(context['serial_flat_catalogue'])==21,'Actual saved21-tool catalogue required')
    catalogueids=engine.ids(context['serial_flat_catalogue'],'native_id');require(context['serial_flat_tool_native_id']in catalogueids,'Created serial tool missing from catalogue')
    features=loaded['root_pocket_full_features'];specs=loaded['root_pocket_specs'];inventory=loaded['root_pocket_native_inventory']
    require(len(features)==len(specs)==2,'Exactly two completed full native pockets required')
    require(catalogue_observations is None or len(catalogue_observations)==2,'Exactly two fresh catalogue observations required')
    require([r['key']for r in recipe['rows']]==list(engine.KEYS)and set(choices)==set(engine.KEYS),'Exact selected four-row recipe/default policy required')
    # Headers are actual readback objects, never fabricated from planned segments.
    owners={str(r['header']['native_id']):r['owner_setup_native_id']for r in inventory}
    require(len(owners)==len(inventory),'Native feature inventory contains duplicate IDs')
    checks=[];pairs=[]
    for index,(feature,spec)in enumerate(zip(features,specs)):
        observed=catalogue_observations[index]if catalogue_observations is not None else None
        fid=feature['header']['native_id'];checks.append(verify_feature(feature,spec,native_id=fid))
        if observed is not None:require(group.exact(observed['header'],feature['header'])and observed['feature_native_id']==fid,'Fresh catalogue belongs to a different pocket')
        hits=[r for r in inventory if r['header']['native_id']==fid]
        require(len(hits)==1 and group.exact(hits[0]['header'],feature['header'])and hits[0]['owner_setup_native_id']==feature['owner_setup_native_id'],'Actual full pocket/inventory linkage differs')
        baseline['binding']['features'][str(fid)]=deepcopy(feature['header']);pairs.append((fid,feature,observed))
    require(len({f for f,_,_ in pairs})==2,'Distinct actual pockets required')
    tool=tool_dimensions(context,baseline)
    loaded.update(configuration_tool=deepcopy(tool['generic']),local_tool_dimensions=tool,serial_flat_catalogue=deepcopy(context['serial_flat_catalogue']),
        local_feature_checks=checks,local_feature_owners={k:owners[k]for k in baseline['binding']['features']},source_sha256=context['source_sha256'])
    loaded['guide_parameters']['baseline']=deepcopy(baseline['binding'])
    loaded['unpartitioned_live_pins']=deepcopy(context['pins']);loaded['outer_proof_pins']=deepcopy(context['offline_export_proof_pins'])
    loaded['local_tool_authority_pin']=deepcopy(context['parent_pin']);loaded['dispatch_ready']=False
    if catalogue_observations is None:return loaded
    rows=[];ops={r['native_id']:r for r in baseline['binding']['operations']}
    for i,proposal in enumerate(recipe['rows']):
        fid,feature,observed=pairs[i//2];kind=i%2
        require(proposal['operation_type']==kind,'Declared rough/finish order required')
        # Reuse an actual operation-level/setup shape; only the feature depth is
        # replaced with the newly observed native pocket depth, then read back.
        templates=[p for p in baseline['parameters']if ops[p['operation_native_id']]['mill_operation_type']==kind]
        require(templates,'Saved parameter template of the same native kind required')
        selected=templates[-1];levels=deepcopy(selected['levels'])
        require(levels['levels']['override_machining_depth']is False and levels['levels']['toolpath_parameters']['first_cut_Z_type_raw']==1,'Template must use native feature top/depth')
        levels['levels']['machining_depth_native']=feature['header']['depth_native']
        row=dict(key=proposal['key'],feature_native_id=fid,operation_type=kind,
            feature_owner_setup_native_id=feature['owner_setup_native_id'],operation_setup_native_id=baseline['binding']['operations'][-1]['setup_native_id'],
            fields=deepcopy(proposal['fields']),expected_levels=levels,level_template_operation_native_id=selected['operation_native_id'])
        row.update(select_default(observed['defaults_catalogue'],kind,choices[proposal['key']]))
        if kind==0:
            point=proposal['startpoint_anchor_world_xy_mm'];require(type(point)is list and len(point)==2,'Qualified explicit XY anchor required')
            row['entry_point_native']=deepcopy(point)+[0.]
        rows.append(row)
    plan=dict(rows=rows,tool=deepcopy(tool['generic']),feed_policy=deepcopy(feed_policy),physical_cutting_conditions_qualified=False)
    engine.validate_plan(plan,baseline)
    loaded.update(local_plan=plan,configuration_tool=deepcopy(tool['generic']),local_tool_dimensions=tool,
        serial_flat_catalogue=deepcopy(context['serial_flat_catalogue']),local_feature_checks=checks,
        local_feature_owners={k:owners[k]for k in baseline['binding']['features']},source_sha256=context['source_sha256'])
    loaded['guide_parameters']['baseline']=deepcopy(baseline['binding'])
    # Keep the outer factory and historical closure. Native/proof partition is a
    # separate explicit audited step; never silently discard pins to fit a limit.
    loaded['unpartitioned_live_pins']=deepcopy(context['pins'])
    loaded['outer_proof_pins']=deepcopy(context['offline_export_proof_pins'])
    loaded['local_tool_authority_pin']=deepcopy(context['parent_pin'])
    loaded['dispatch_ready']=False
    return loaded
