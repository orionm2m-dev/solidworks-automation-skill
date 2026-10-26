"""Bounded native sketch-only operation for an exact saved qualification part.
No CAM, extrusion, solid edit, automatic save, deletion or UI input. New geometry
is read back in model metres; qualification evidence is maintained by callers.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib,json,math,re
from pathlib import Path
from scripts.sw_cam_feature_sketch import _call_method as call, _point
from scripts.sw_operation_guard import absolute_document_path,check_document_target,solidworks_operation_lock

TOL_M=1e-8
MAX_ENTITIES=32

def _finite(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('finite strict number required')
    return float(v)
def _name(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}',v):raise ValueError('new simple name required')
    return v
def _xyz(v):
    if not isinstance(v,(list,tuple)) or len(v)!=3:raise ValueError('three coordinates required')
    return [_finite(x) for x in v]
def _sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def _digest(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def _input(spec):
    if not isinstance(spec,dict) or set(spec)!={'plane_axis','plane_offset_mm','sketch_name','plane_name','profile'}:raise ValueError('exact sketch specification required')
    c=deepcopy(spec);axis=c['plane_axis']
    if axis not in ('X','Y','Z'):raise ValueError('cardinal plane axis required')
    c['plane_offset_mm']=_finite(c['plane_offset_mm'])
    if abs(c['plane_offset_mm'])>1000:raise ValueError('plane offset bound')
    _name(c['sketch_name']);_name(c['plane_name'])
    if c['sketch_name'].lower()==c['plane_name'].lower():raise ValueError('distinct names required')
    p=c['profile'];idx='XYZ'.index(axis)
    if not isinstance(p,dict):raise ValueError('profile required')
    if p.get('kind')=='circle':
        if set(p)!={'kind','center_model_mm','radius_mm'}:raise ValueError('exact circle fields required')
        points=[_xyz(p['center_model_mm'])];radius=_finite(p['radius_mm'])
        if not .001<=radius<=500:raise ValueError('radius outside bound')
        p['center_model_mm']=points[0];p['radius_mm']=radius
    elif p.get('kind')=='closed_polyline':
        if set(p)!={'kind','points_model_mm'} or not isinstance(p['points_model_mm'],(list,tuple)) or not 3<=len(p['points_model_mm'])<=MAX_ENTITIES:raise ValueError('3..32 distinct vertices required, no repeated endpoint')
        points=[_xyz(x) for x in p['points_model_mm']];p['points_model_mm']=points
        uv=[[v[i] for i in range(3) if i!=idx] for v in points]
        for i,a in enumerate(uv):
            if any(math.dist(a,b)<1e-5 for b in uv[i+1:]):raise ValueError('repeated or degenerate vertices')
        area=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(uv,uv[1:]+uv[:1]))/2
        if abs(area)<1e-6:raise ValueError('degenerate polygon')
        def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i,(a,b) in enumerate(zip(uv,uv[1:]+uv[:1])):
            for j,(d,e) in enumerate(zip(uv,uv[1:]+uv[:1])):
                if j<=i or j in ((i+1)%len(uv),(i-1)%len(uv)):continue
                vals=(orient(a,b,d),orient(a,b,e),orient(d,e,a),orient(d,e,b))
                if vals[0]*vals[1]<=0 and vals[2]*vals[3]<=0:raise ValueError('self intersection or collinear nonadjacent edges')
    else:raise ValueError('only circle or closed_polyline supported')
    for point in points:
        if max(map(abs,point))>1000 or abs(point[idx]-c['plane_offset_mm'])>1e-6:raise ValueError('profile not on requested plane or out of bound')
    return c

def _features(model):
    refs=[];f=call(model,'FirstFeature')
    while f is not None:
        if len(refs)>=512:raise ValueError('bounded feature traversal exceeded')
        refs.append(f);f=call(f,'GetNextFeature')
    rows=[{'name':str(f.Name),'type':str(call(f,'GetTypeName2'))} for f in refs]
    if len({x['name'].lower() for x in rows})!=len(rows):raise ValueError('feature names are not unique')
    return rows,refs

def _identity(sw,pid,path):
    if call(sw,'GetProcessID')!=pid:raise ValueError('SW PID mismatch')
    model=sw.ActiveDoc
    if model is None or call(model,'GetType')!=1:raise ValueError('exact active part required')
    actual=call(model,'GetPathName');title=call(model,'GetTitle')
    check_document_target(actual,title,expected_path=path,required=True)
    return model

def _bodies(model):
    bs=call(model,'GetBodies2',0,False)
    if not isinstance(bs,(list,tuple)) or not 1<=len(bs)<=64:raise ValueError('bounded solid part required')
    rows=[]
    for b in bs:
        box=list(map(_finite,call(b,'GetBodyBox')));mass=list(map(_finite,call(b,'GetMassProperties',1)))
        if len(box)!=6 or len(mass)<4:raise ValueError('invalid body fingerprint')
        rows.append({'box_m':box,'mass_raw':mass})
    return rows

def _plane(sw,feature):
    obj=call(feature,'GetSpecificFeature2');t=obj.Transform
    matrix=list(map(_finite,t.ArrayData))
    if len(matrix)!=16:raise ValueError('invalid plane transform')
    mu=call(sw,'GetMathUtility');origin=_point(mu,[0.,0.,0.],t);normalpoint=_point(mu,[0.,0.,1.],t)
    n=[a-b for a,b in zip(normalpoint,origin)];length=math.sqrt(sum(x*x for x in n))
    if length<1e-10:raise ValueError('degenerate plane')
    n=[v/length for v in n]
    return {'name':str(feature.Name),'origin_m':origin,'normal':n,'plane_to_model':matrix}

def _snapshot(sw,pid,path,spec):
    model=_identity(sw,pid,path);filebefore=_sha(path)
    if call(model,'IsOpenedReadOnly'):raise ValueError('read-only document')
    if len(call(model,'GetConfigurationNames') or [])!=1:raise ValueError('single configuration required')
    if model.SketchManager.ActiveSketch is not None:raise ValueError('existing active sketch')
    rows,refs=_features(model);planes=[];axis='XYZ'.index(spec['plane_axis'])
    for row,feature in zip(rows,refs):
        if row['type']!='RefPlane':continue
        p=_plane(sw,feature);n=p['normal']
        if abs(abs(n[axis])-1)<1e-9 and all(abs(n[i])<1e-9 for i in range(3) if i!=axis):planes.append(p)
    if not planes:raise ValueError('no native cardinal reference plane')
    state={'pid':pid,'path':str(Path(path).resolve()),'saved_file_sha256':filebefore,'needs_save':bool(call(model,'GetSaveFlag')),'features':rows,'planes':planes,'solids':_bodies(model),'spec':spec}
    _identity(sw,pid,path)
    if filebefore!=_sha(path):raise ValueError('saved source changed during snapshot')
    return state,model,refs

def _state_digest(state):
    d=deepcopy(state)
    for b in d['solids']:b['mass_raw']=[float(format(v,'.11g')) for v in b['mass_raw']]
    return _digest(d)

def _same_bodies(before,after):
    if len(before)!=len(after):return False
    for a,b in zip(before,after):
        if a['box_m']!=b['box_m'] or len(a['mass_raw'])!=len(b['mass_raw']):return False
        if any(not math.isclose(x,y,rel_tol=1e-10,abs_tol=0.) for x,y in zip(a['mass_raw'],b['mass_raw'])):return False
    return True

def _select_plane(state):
    axis='XYZ'.index(state['spec']['plane_axis']);offset=state['spec']['plane_offset_mm']/1000
    same=[p for p in state['planes'] if abs(p['origin_m'][axis]-offset)<=TOL_M]
    if len(same)==1:return same[0],False
    if len(same)>1:raise ValueError('ambiguous coincident cardinal planes')
    base=[p for p in state['planes'] if abs(p['origin_m'][axis])<=TOL_M]
    if len(base)!=1:raise ValueError('unique origin plane required for new offset')
    return base[0],True

def _typed_segment(segment,kind):
    import pythoncom,pywintypes
    from win32com.client import Dispatch
    iid='{83A33DC1-27C5-11CE-BFD4-00400513BB57}' if kind==0 else '{83A33DC3-27C5-11CE-BFD4-00400513BB57}'
    return Dispatch(segment._oleobj_.QueryInterface(pywintypes.IID(iid),pythoncom.IID_IDispatch))

def _point_values(p):return [_finite(p.X),_finite(p.Y),_finite(p.Z)]

def _rigid_transform(transform):
    values=list(map(_finite,transform.ArrayData))
    if len(values)!=16 or abs(values[12]-1)>1e-10:raise ValueError('unit-scale native transform required')
    rows=[values[i:i+3] for i in (0,3,6)]
    for i in range(3):
        for j in range(3):
            if abs(sum(a*b for a,b in zip(rows[i],rows[j]))-(1. if i==j else 0.))>1e-10:raise ValueError('orthonormal transform required')
    return values

def _read_sketch(sw,sketch,spec):
    if call(sketch,'Is3D') is not False:raise ValueError('2D sketch required')
    segments=call(sketch,'GetSketchSegments')
    count=1 if spec['profile']['kind']=='circle' else len(spec['profile']['points_model_mm'])
    if not isinstance(segments,(list,tuple)) or len(segments)!=count:raise ValueError('entity count mismatch')
    mu=call(sw,'GetMathUtility');transform=sketch.ModelToSketchTransform;_rigid_transform(transform);inverse=call(transform,'Inverse');_rigid_transform(inverse)
    rows=[]
    for seg in segments:
        k=call(seg,'GetType')
        if seg.ConstructionGeometry is not False or k not in (0,1):raise ValueError('unexpected construction or entity')
        raw=_typed_segment(seg,k)
        if k==1:
            if spec['profile']['kind']!='circle' or call(raw,'IsCircle') is not True:raise ValueError('full circle required')
            center=_point(mu,_point_values(call(raw,'GetCenterPoint2')),inverse);rad=_finite(call(raw,'GetRadius'))
            exp=spec['profile'];wanted=[x/1000 for x in exp['center_model_mm']]
            if math.dist(center,wanted)>TOL_M or abs(rad-exp['radius_mm']/1000)>TOL_M:raise ValueError('circle geometry mismatch')
            rows.append({'type':'circle','center_model_m':center,'radius_m':rad})
        else:
            if spec['profile']['kind']!='closed_polyline':raise ValueError('wrong segment type')
            pts=[_point(mu,_point_values(call(raw,key)),inverse) for key in ('GetStartPoint2','GetEndPoint2')]
            rows.append({'type':'line','points_model_m':pts})
    if spec['profile']['kind']=='closed_polyline':
        points=[[v/1000 for v in p] for p in spec['profile']['points_model_mm']];expected=list(zip(points,points[1:]+points[:1]))
        unmatched=list(rows)
        for pair in expected:
            match=next((i for i,row in enumerate(unmatched) if any(all(math.dist(a,b)<=TOL_M for a,b in zip(pair,order)) for order in (row['points_model_m'],row['points_model_m'][::-1]))),None)
            if match is None:raise ValueError('polyline readback mismatch')
            unmatched.pop(match)
    return {'entities':rows,'model_to_sketch_transform':list(map(_finite,transform.ArrayData)),'readback_tolerance_m':TOL_M}

def _write_receipt(path,report,*,create=False):
    with Path(path).open('x' if create else 'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)

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
        p=spec['profile']
        if p['kind']=='circle':
            c=local(p['center_model_mm']);entity=mutate(manager,'CreateCircleByRadius',c[0],c[1],0.,p['radius_mm']/1000)
            if entity is None:raise ValueError('circle creator returned null')
        else:
            points=[local(x) for x in p['points_model_mm']]
            for a,b in zip(points,points[1:]+points[:1]):
                if mutate(manager,'CreateLine',a[0],a[1],0.,b[0],b[1],0.) is None:raise ValueError('line creator returned null')
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

def create_cam_profile_sketch(sw,*,expected_process_id,expected_document_path,action,spec,
        expected_state_sha256=None,receipt_path=None,qualification_only=True):
    """Inspect/prepare/apply one new 2D profile; apply never saves the part."""
    report={'status':'error','phase':'preflight','mutation_attempted':False,'saved':False,'CAD_solid_edit_attempted':False,'CAM_calls':0,'native_readback_verified':False}
    receipt_created=False
    try:
        if type(expected_process_id) is not int or expected_process_id<=0:raise ValueError('exact positive PID required')
        if not isinstance(expected_document_path,str) or not absolute_document_path(expected_document_path) or Path(expected_document_path).suffix.lower()!='.sldprt' or not Path(expected_document_path).is_file():raise ValueError('exact saved part required')
        if qualification_only is not True or action not in ('inspect','prepare','apply'):raise ValueError('qualification action required')
        spec=_input(spec)
        if action!='apply' and (receipt_path is not None or expected_state_sha256 is not None):raise ValueError('read-only action cannot take mutation fields')
        if action=='apply':
            if not isinstance(expected_state_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_state_sha256):raise ValueError('prepared state hash required')
            if not isinstance(receipt_path,str) or not Path(receipt_path).is_absolute() or Path(receipt_path).suffix.lower()!='.json' or not Path(receipt_path).parent.is_dir():raise ValueError('new absolute JSON receipt required')
        with solidworks_operation_lock(process_id=expected_process_id,timeout_seconds=2):
            before,model,refs=_snapshot(sw,expected_process_id,expected_document_path,spec)
            report.update(before=before,state_sha256=_state_digest(before))
            names={x['name'].lower() for x in before['features']}
            if spec['sketch_name'].lower() in names or spec['plane_name'].lower() in names:raise ValueError('requested new feature name already exists')
            if before['needs_save']:raise ValueError('clean saved qualification copy required')
            _select_plane(before)
            if action in ('inspect','prepare'):
                report.update(status='ok',phase='prepared' if action=='prepare' else 'inspected',prepared=action=='prepare');return report
            if report['state_sha256']!=expected_state_sha256:raise ValueError('prepared state changed')
            _write_receipt(receipt_path,report,create=True);receipt_created=True
            def check():
                _identity(sw,expected_process_id,expected_document_path)
                if _sha(expected_document_path)!=before['saved_file_sha256']:raise ValueError('saved source changed during operation')
            check();report.update(mutation_attempted=True,phase='create_profile');_write_receipt(receipt_path,report)
            created=_create(sw,model,before,refs,check,report)
            after,_,_=_snapshot(sw,expected_process_id,expected_document_path,spec);report['after']=after
            if [x for x in after['features'] if x['name'] not in created]!=before['features']:raise ValueError('old feature list changed')
            actual=[x for x in after['features'] if x['name'] in created]
            expected=[{'name':n,'type':'ProfileFeature' if n==spec['sketch_name'] else 'RefPlane'} for n in created]
            if actual!=expected or not _same_bodies(before['solids'],after['solids']):raise ValueError('unexpected new features or solid geometry change')
            if not after['needs_save']:raise ValueError('expected unsaved sketch change not confirmed')
            check();report.update(status='ok',phase='finished',native_readback_verified=True,created_features=actual,after_state_sha256=_state_digest(after),limits=['No CAM feature/GOP/GTP created. Save and close/reopen must be qualified separately.','Sketch geometry has exact model-coordinate readback; no dimensions/relations or machining method is implied.','Body-box/mass invariants are not a replacement for later saved STEP equivalence verification.'])
    except Exception as exc:
        report.update(status='uncertain' if report['mutation_attempted'] else 'error',failed_phase=report['phase'],issue={'type':type(exc).__name__,'message':str(exc)},native_readback_verified=False)
    finally:
        if receipt_created:
            try:_write_receipt(receipt_path,report)
            except Exception as exc:
                report.update(status='uncertain' if report['mutation_attempted'] else 'error',
                    native_readback_verified=False,receipt_write_error={'type':type(exc).__name__,'message':str(exc)})
    return report
