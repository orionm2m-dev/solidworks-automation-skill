"""Versioned full definition capture with an explicit 128-pin guard budget.

Geometry, owner, source, event, body and sketch checks retain the frozen
legacy capture sequence. This adapter does not mutate its parent module.
The caller must pin this module and the unchanged parent dependencies.
"""
from copy import deepcopy
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard
from scripts.sw_cam_pocket_definition_context import (
    SCOPE, OP_KEYS, require, identity, verify_files, inventory, creator,
    _object_id, _feature_header, _snapshot, _read_sketch, _same_bodies,
)

def capture(sw,clsid,tlb,context,check,diagnostic):
    """Generic full inventory plus exact basic feature/analytic sketch readback."""
    diagnostic={} if diagnostic is None else diagnostic
    observed=identity(sw,context);v=context['request'];r=context['creator'];check()
    def owned():require(identity(sw,context)==observed,'Definition context changed during capture')
    with ScopedCamDispatchGuard(sw,tlb,process_id=v['process_id'],expected_document=observed['document'],source_sha256=context['expected_source_sha256'],evidence_pins=context['pins'],verify_evidence=lambda:verify_files(context),verify_owned_process=owned,check_events=check,evidence_pin_limit=128) as guard:
        addin=guard.read(sw,'GetAddInObject',clsid);app=guard.typed(guard.read(addin,'GetCWApp'),'ICWApp4')
        state=inventory.capture_import_inventory(app,tlb,guard,diagnostic,lambda d:None)
        require(state['cam_configuration_name']==v['expected_cam_configuration'] and state['associated_sw_configuration']==v['expected_sw_configuration'],'Exact CAM/CAD configuration binding required')
        baseline=deepcopy(context['expected_inventory']);baseline.pop('sw_reference');baseline.pop('all_solid_body_count')
        for key in OP_KEYS:baseline.pop(key)
        current={k:deepcopy(value)for k,value in state.items()if k not in OP_KEYS}
        require(current==baseline,'Feature/setup/configuration definition differs from creator')
        doc=guard.typed(guard.read(app,'IGetActiveDoc'),'ICWDoc3');machine=guard.typed(guard.read(guard.typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
        setups=inventory._items(guard.read(machine,'IGetEnumSetups'),guard.typed,guard.read,1)
        require(len(setups)==1 and _object_id(doc,setups[0],guard.read)==v['owner_setup_native_id'],'Exact feature owner required')
        features=inventory._items(guard.read(guard.typed(setups[0],'ICWBaseSetup'),'IGetEnumFeatures'),guard.typed,guard.read,1)
        require(len(features)==1,'Exactly one native feature required')
        header,feature=_feature_header(guard,doc,features[0]);require(header==r['feature_header'],'Feature header differs from definition receipt')
        actual,model,_=guard._observe(lambda:_snapshot(sw,v['process_id'],v['expected_document_path'],context['spec']))
        expected=deepcopy(context['current_sketch_baseline']);expected['needs_save']=observed['document']['needs_save'];a,b=deepcopy(actual),deepcopy(expected);sa,sb=a.pop('solids'),b.pop('solids')
        require(a==b and _same_bodies(sa,sb),'CAD/sketch snapshot differs from immutable creator baseline')
        diagnostic['actual_sketch_snapshot']=actual
        sketch_feature=guard.read(model,'FeatureByName',context['spec']['sketch_name'])
        require(guard.read(sketch_feature,'GetTypeName2')=='ProfileFeature','Exact analytic sketch required')
        sketch=guard.read(sketch_feature,'GetSpecificFeature2');profile=guard._observe(lambda:_read_sketch(sw,sketch,context['spec']))
        require(profile==(context['creator']['circle_readback'] if creator.saved_caps(v) else context['sketch']['sketch_readback']),'Native sketch circle differs')
        guard._boundary()
    state.update(document=observed['document'],saved_file_sha256=context['expected_source_sha256'],selected_feature=header,operation_setup_count=len(state['operation_setups']),operation_counts=[x['operation_count']for x in state['operation_setups']],definition_authority=dict(scope=SCOPE,recovery_receipt_sha256=context['evidence']['sha256'],save_receipt_sha256=context['save_pin']['sha256'],raw_creator_status=context['creator']['status'],saved_definition_binding_verified=True,persistence_verified=False,analytic_sketch_and_body_invariants_verified=True,island_geometry_verified=False,physical_depth_verified=False))
    if creator.saved_caps(v) or context.get('origin_kind')=='creator':
        state['definition_authority']['origin_kind']=context['origin_kind']
    diagnostic.update(capture_complete=True,stage='complete',state=deepcopy(state))
    return state,dict(app=app,doc=doc,machine=machine,selected_feature=feature)
