"""Fixed nominal representation projection for an observed partial MILL configuration."""
from copy import deepcopy
import math
from scripts import sw_cam_saved_floor_wall_configure as writer
recipe_core=writer.recipe_core;finish=recipe_core.finish;require=writer.require;exact=writer.exact
NUMERIC_FIELDS=frozenset({'machining_depth','first_depth','max_depth'})


def prefix_actions(recipe):
    actions=writer.action_names(recipe);wall=recipe['rows'][1]
    require([(r['role'],r['operation_kind'])for r in recipe['rows']]==[('floor',0),('wall',1)],'Exact two-role recipe required')
    last='field:'+str(wall['operation_native_id'])+':machining_depth';require(actions.count(last)==1,'One wall depth write required')
    return actions[:actions.index(last)+1]


def remaining_changes(recipe):
    row=deepcopy(recipe['rows'][1]);done=set(prefix_actions(recipe));row['changes']=[c for c in row['changes']if 'field:'+str(row['operation_native_id'])+':'+c['field']not in done]
    require([c['field']for c in row['changes']]==['side_allowance','final_side','final_depth','spring_passes','first_depth','max_depth','side_step','override_previous','previous_allowance','gouge_check'],'Only the established ten remaining wall fields supported')
    return row


def expected_targets(before_targets,recipe,phase):
    require(phase in('prefix','final'),'Explicit projection phase required');require(len(before_targets)==len(recipe['rows'])==2,'Two targets required')
    done=set(prefix_actions(recipe))if phase=='prefix'else set(writer.action_names(recipe)[:-1]);out=[]
    for before,row in zip(before_targets,recipe['rows']):
        selected=deepcopy(row);selected['changes']=[c for c in row['changes']if 'field:'+str(row['operation_native_id'])+':'+c['field']in done]
        out.append(recipe_core.expected_observation(before,selected))
    return out


def fixed_double(actual,nominal):
    require(type(actual)is float and type(nominal)is float and math.isfinite(actual)and math.isfinite(nominal),'Strict finite native doubles required')
    if nominal==0.0:
        require(actual.hex()==nominal.hex(),'Zero must remain exact');return
    require(actual in(nominal,math.nextafter(nominal,-math.inf),math.nextafter(nominal,math.inf)),'Native double is not the fixed nominal or an immediate neighbor')


def project_targets(raw,expected,recipe,phase):
    require(phase in('prefix','final')and len(raw)==len(expected)==2,'Explicit two-target representation projection required')
    out=deepcopy(raw);evidence=[];wall=recipe['rows'][1];oid=wall['operation_native_id']
    require(out[1]['operation_native_id']==expected[1]['operation_native_id']==oid,'Exact selected wall required')
    allowed={'machining_depth'}if phase=='prefix'else NUMERIC_FIELDS
    for change in wall['changes']:
        key=change['field']
        if key not in allowed:continue
        spec=finish.FIELDS[key];require(spec.kind in('double','absolute_pair'),'Only registered native Double depth fields supported')
        nominal=change['new'][0]if spec.kind=='absolute_pair'else change['new'];require(type(nominal)is float and nominal==7.1,'Only the established wall-depth nominal 7.1 is qualified for representation projection')
        paths=[spec.path,*spec.echoes]
        for path in paths:
            rawvalue=finish.value_at(out[1],path);want=finish.value_at(expected[1],path)
            pair=path==spec.path and spec.kind=='absolute_pair'
            if pair:
                finish.checked(spec,rawvalue);require(type(want)is list and len(want)==2 and want[1]is False,'Exact nominal absolute pair required');actual=rawvalue[0];anchor=want[0]
            else:actual=rawvalue;anchor=want
            require(type(anchor)is float and anchor==nominal,'Projection anchor must be original recipe nominal');fixed_double(actual,anchor)
            if actual.hex()!=anchor.hex():
                evidence.append(dict(operation_native_id=oid,field=key,path=list(path),raw=actual,raw_hex=actual.hex(),nominal=anchor,nominal_hex=anchor.hex(),direction='positive'if actual>anchor else'negative',distance_representable_steps=1,manufacturing_tolerance_applied=False))
            finish.put(out[1],path,[anchor,False]if pair else anchor)
    require(exact(out,expected),'Unrequested target, floor, NC or nonregistered parameter drift')
    return out,evidence


def verify_checkpoint(original,current,recipe,candidate,before_targets,after_targets,before_draft,after_draft,phase):
    require(exact(before_draft,after_draft),'Protected draft observation changed')
    expected=expected_targets(before_targets,recipe,phase);normalized,representations=project_targets(after_targets,expected,recipe,phase)
    wanted=writer.expected_configuration_state(original,recipe,candidate,normalized);actual=deepcopy(current)
    for state in(wanted,actual):
        for key in('document','sketch_state'):
            require(type(state[key]['needs_save'])is bool,'Strict document/sketch dirty flags required');state[key]['needs_save']=False
    require(writer.circular.circular_state_equal(wanted,actual),'Protected full route, paths, geometry, tool or unrequested NC changed')
    return dict(phase=phase,selected_operation_ids=[r['operation_native_id']for r in recipe['rows']],protected_operation_count=len(original['operations'])-2,protected_generated_operation_count=sum(r['toolpath_generated']for r in original['operations']),protected_native_records=sum(sum(r['toolpath_record_counts'])for r in original['operations']),retained_draft_unchanged=True,shared_candidate_unchanged=True,full_captured_configuration_verified=True,native_double_representations=representations,representation_anchor='ORIGINAL_SEALED_RECIPE_7_1',manufacturing_tolerance_applied=False,production_qualified=False)
