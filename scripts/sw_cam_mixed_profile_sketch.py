"""Mixed LINE/ARC extension of the shared guarded sketch creation scaffold.

Only profile validation, segment creation and readback differ. The caller must
provide the owned document, once journal and protected CAM-route checks.
"""
from copy import deepcopy
import math
from scripts import sw_cam_profile_sketch as core
from scripts import sw_cam_mixed_profile as mixed

TOL_M=core.TOL_M
call=core.call
_point=core._point
_features=core._features
_plane=core._plane
_select_plane=core._select_plane
_rigid_transform=core._rigid_transform


def _input(spec):
    if type(spec) is not dict or set(spec)!={'plane_axis','plane_offset_mm','sketch_name','plane_name','profile'}:
        raise ValueError('exact mixed sketch specification required')
    profile=mixed.validate_profile(spec['profile'],plane_axis=spec['plane_axis'],plane_offset_mm=core._finite(spec['plane_offset_mm']),tolerance_mm=TOL_M*1000)
    proxy=deepcopy(spec)
    proxy['profile']={'kind':'circle','center_model_mm':profile['segments'][0]['start_model_mm'],'radius_mm':1.}
    checked=core._input(proxy)
    checked['profile']=profile
    return checked


def _read_sketch(sw,sketch,spec,*,diagnostic=None):
    return mixed.read_native(sw,sketch,spec,call=call,point=_point,point_values=core._point_values,typed_segment=core._typed_segment,rigid_transform=_rigid_transform,tolerance_m=TOL_M)


def _create(sw,model,state,refs,check,report):
    spec=state['spec'];record,newplane=_select_plane(state)
    reference=next(f for f in refs if str(f.Name)==record['name'])
    created_names=[];axis='XYZ'.index(spec['plane_axis'])
    def mutate(obj,name,*args):
        check();v=call(obj,name,*args);check();return v
    mutate(model,'ClearSelection2',True)
    if mutate(reference,'Select2',False,0) is not True:raise ValueError('reference plane selection failed')
    if newplane:
        distance=(spec['plane_offset_mm']/1000-record['origin_m'][axis])/record['normal'][axis]
        report['plane_create_attempted']=True
        raw=mutate(model.FeatureManager,'InsertRefPlane',8|(256 if distance<0 else 0),abs(distance),0,0.,0,0.)
        if raw is None:raise ValueError('InsertRefPlane returned null; no retry')
        rows,afterrefs=_features(model);old={x['name'] for x in state['features']}
        added=[f for f in afterrefs if str(f.Name) not in old]
        if len(added)!=1 or call(added[0],'GetTypeName2')!='RefPlane':raise ValueError('exactly one offset plane required')
        reference=added[0];check();reference.Name=spec['plane_name'];check()
        if str(reference.Name)!=spec['plane_name']:raise ValueError('plane rename failed')
        record=_plane(sw,reference)
        if abs(record['origin_m'][axis]-spec['plane_offset_mm']/1000)>TOL_M or abs(abs(record['normal'][axis])-1)>1e-9:raise ValueError('offset plane direction or location mismatch; no retry')
        created_names.append(spec['plane_name']);report['created_plane']=record
        mutate(model,'ClearSelection2',True)
        if mutate(reference,'Select2',False,0) is not True:raise ValueError('offset plane selection failed')
    manager=model.SketchManager;entered=False;sketch=None;original_add=None;add_touched=False
    try:
        report['sketch_create_attempted']=True;entered=True
        mutate(manager,'InsertSketch',True);sketch=manager.ActiveSketch
        if sketch is None or call(sketch,'Is3D') is not False or call(sketch,'GetSketchSegments') not in (None,[],()):raise ValueError('new empty 2D sketch not active')
        mu=call(sw,'GetMathUtility');t=sketch.ModelToSketchTransform;_rigid_transform(t)
        def local(point):
            world=[v/1000 for v in point];p=_point(mu,world,t)
            if math.dist(_point(mu,p,call(t,'Inverse')),world)>TOL_M:raise ValueError('transform roundtrip failed')
            if abs(p[2])>TOL_M:raise ValueError('transformed point not on sketch plane')
            return p
        before_names={x['name'] for x in state['features']}|set(created_names)
        _,nowrefs=_features(model)
        added=[f for f in nowrefs if str(f.Name) not in before_names]
        if len(added)!=1 or call(added[0],'GetTypeName2')!='ProfileFeature' or call(sw,'IsSame',call(added[0],'GetSpecificFeature2'),sketch)!=1:raise ValueError('new sketch identity not proven')
        feature=added[0];original_add=manager.AddToDB
        if type(original_add) is not bool:raise ValueError('unknown AddToDB state')
        check();add_touched=True;manager.AddToDB=True;check()
        mixed.create_segments(manager,spec['profile'],local=local,mutate=mutate)
        check();feature.Name=spec['sketch_name'];check()
        if str(feature.Name)!=spec['sketch_name']:raise ValueError('sketch rename failed')
        report['sketch_readback']=_read_sketch(sw,sketch,spec);check()
    finally:
        # Cleanup only our exact active sketch. No save, deletion, rollback or replay.
        errors=[]
        try:
            check()
            if add_touched:manager.AddToDB=original_add
            if entered:
                active=manager.ActiveSketch
                if active is not None:
                    if sketch is None or call(sw,'IsSame',active,sketch)!=1:raise ValueError('cannot close unconfirmed sketch')
                    call(manager,'InsertSketch',True)
                report['sketch_edit_exited']=manager.ActiveSketch is None
                if not report['sketch_edit_exited']:raise ValueError('sketch edit not exited')
            check()
        except Exception as exc:errors.append(str(exc));report['cleanup_errors']=errors;raise
    report['sketch_readback']=_read_sketch(sw,sketch,spec)
    return created_names+[spec['sketch_name']]
