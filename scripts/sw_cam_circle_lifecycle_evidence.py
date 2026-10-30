"""Pinned creator evidence for circular MILL lifecycle; no mutation or geometry inference."""
from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path
from scripts.sw_cam import _member
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_mill_units_qualification import (
    _sha, _nonnull, _circle_sketch, _sketch_input, _read_sketch, _features, _bodies, _same_bodies, call)
from scripts.sw_cam_mill_circle_geometry import prove_mill_circle_geometry
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def read_circle_creation_evidence(path, sha256, expected_path, feature_id):
    _sha(sha256)
    if (type(path) is not str or not absolute_document_path(path) or Path(path).suffix.casefold() != '.json'
            or not Path(path).is_file() or Path(path).is_symlink() or Path(path).stat().st_size > 16*1024*1024):
        raise ValueError('Pinned absolute bounded existing creation JSON required')
    if _file_hash(path) != sha256:raise ValueError('Circular creation receipt SHA changed')
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha256:raise ValueError('Read creation bytes differ from pinned SHA')
    # Duplicate keys would make the evidence ambiguous.
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate JSON evidence key')
            out[key]=value
        return out
    value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON evidence')))
    if _file_hash(path) != sha256:raise ValueError('Creation receipt changed while reading')
    if (type(value) is not dict or value.get('action')!='apply' or value.get('status')!='review_required'
            or value.get('feature_kind')!='circular_pocket'
            or any(value.get(k) is not True for k in ('mutation_attempted','native_call_returned','readback_verified',
                'creation_delta_verified','native_feature_readback_complete','contour_readback_verified'))
            or value.get('physical_depth_verified') is not False):
        raise ValueError('Successful scoped circular creator readback required; not physical qualification')
    after=value['after'];row=value['observed_feature']
    if (type(row.get('native_id')) is not int or row['native_id']!=feature_id or
            type(row.get('volume_type')) is not int or row['volume_type']!=2 or row.get('suppressed') is not False
            or _digest(after['features']) != _digest([row]) or after.get('feature_kind')!='circular_pocket'):
        raise ValueError('Creation receipt exact feature identity/representation mismatch')
    doc=after['document']
    check_document_target(doc['path'],doc['title'],expected_path=expected_path,required=True)
    spec=_sketch_input(after['sketch_spec'])
    if spec['profile']['kind']!='circle':raise ValueError('Receipt must pin saved circle sketch')
    actual_circle=_circle_sketch(after['sketch'],spec)
    if _digest(actual_circle)!=_digest(after['sketch_circle_m']):raise ValueError('Receipt sketch circle mismatch')
    proof=prove_mill_circle_geometry(actual_circle,row['top_curves_native'],row['bottom_curves_native'],
                                    after['requested_depth_native'],row['axis_native'])
    if row['depth_native']!=after['requested_depth_native'] or not proof['contour_verified']:
        raise ValueError('Receipt scalar depth or contour evidence inconsistent')
    if _digest(proof)!=_digest(value['dimensional_evidence']):
        raise ValueError('Pinned circle proof differs from current geometry contract')
    if type(after.get('solids')) is not list or not after['solids'] or type(after.get('SW_feature_tree')) is not list:
        raise ValueError('Pinned original solid/tree evidence required')
    return dict(path=path,sha256=sha256,after=deepcopy(after),selected_feature=deepcopy(row))


def raw_part_identity(sw):
    model=_nonnull(sw.ActiveDoc,'ActiveDoc')
    doc=dict(path=call(model,'GetPathName'),title=call(model,'GetTitle'),
             type=call(model,'GetType'),needs_save=call(model,'GetSaveFlag'))
    if type(doc['type']) is not int or doc['type']!=1 or type(doc['needs_save']) is not bool:
        raise ValueError('Strict raw active part type/save flag required')
    return doc


def canonical_circle_solids(observed,pinned,diagnostic=None):
    """Anchor tolerated mass noise to immutable creator evidence; preserve raw observations."""
    for rows in (observed,pinned):
        if type(rows) is not list or not 1<=len(rows)<=64:
            raise ValueError('Bounded solid reference list required')
        for row in rows:
            if type(row) is not dict or set(row)!={'box_m','mass_raw'}:
                raise ValueError('Exact solid fingerprint fields required')
            if type(row['box_m']) is not list or len(row['box_m'])!=6:
                raise ValueError('Exact six-value body box required')
            if type(row['mass_raw']) is not list or not 4<=len(row['mass_raw'])<=64:
                raise ValueError('Bounded native mass fingerprint required')
            if any(type(v) not in (int,float) or not math.isfinite(v)
                   for values in (row['box_m'],row['mass_raw']) for v in values):
                raise ValueError('Finite numeric solid fingerprint required')
    if diagnostic is not None:
        diagnostic['circle_solid_observation']=dict(
            observed=deepcopy(observed),canonical_source='immutable_circle_creator',
            mass_relative_tolerance=1e-10,mass_absolute_tolerance=0.,
            exact_body_boxes=True,comparison_verified=False)
    if not _same_bodies(observed,pinned):
        raise ValueError('Solid evidence changed beyond existing mass tolerance')
    if diagnostic is not None:
        diagnostic['circle_solid_observation']['comparison_verified']=True
    return deepcopy(pinned)


def verify_circle_reference(sw,state,evidence,check,native_app,diagnostic=None):
    if _file_hash(evidence['path'])!=evidence['sha256']:
        raise ValueError('Immutable creation receipt changed')
    if _digest(state['selected_feature'])!=_digest(evidence['selected_feature']):
        raise ValueError('Current circular feature differs from pinned creator readback')
    pinned=evidence['after'];spec=pinned['sketch_spec']
    context_keys=('current_machine','mill_catalogue','feature_setups','material_raw',
                  'extend_holes_to_stock','unit_record_raw','unit_record_status')
    for key in context_keys:
        if key not in pinned or key not in state or _digest(pinned[key])!=_digest(state[key]):
            raise ValueError('Creator-to-lifecycle context changed: '+key)
    check();model=_nonnull(sw.ActiveDoc,'ActiveDoc');check()
    if call(model,'IsOpenedReadOnly') is not False:raise ValueError('Writable qualification copy required')
    check();configs=call(model,'GetConfigurationNames');check()
    if not isinstance(configs,(list,tuple)) or len(configs)!=1 or call(model,'GetActiveSketch2') is not None:
        raise ValueError('One configuration outside sketch edit required')
    check();feature=call(model,'FeatureByName',spec['sketch_name']);check()
    if feature is None or call(feature,'GetTypeName2')!='ProfileFeature' or call(feature,'IsSuppressed') is not False:
        raise ValueError('Exact unsuppressed saved circle sketch required')
    check();sketch=_read_sketch(sw,call(feature,'GetSpecificFeature2'),spec);check()
    if _digest(sketch)!=_digest(pinned['sketch']):raise ValueError('Saved circle sketch changed since creation')
    tree,_=_features(model);check();bodies=_bodies(model);check()
    if _digest(tree)!=_digest(pinned['SW_feature_tree']):
        raise ValueError('SW feature tree changed since circle creation')
    canonical_bodies=canonical_circle_solids(bodies,pinned['solids'],diagnostic)
    check();units=call(model,'GetUnits');check()
    if not isinstance(units,(list,tuple)) or len(units)!=5 or any(type(x) is not int for x in units):
        raise ValueError('Exact five SW unit integers required')
    check();use=_member(_nonnull(native_app,'CAM app'),'GetUseDocumentUnit');check()
    if type(use) is not bool or list(units)!=pinned['SW_document_units_raw'] or use is not pinned['CAM_use_document_units_raw']:
        raise ValueError('Document/native unit flags changed since circle creation')
    state['circle_creation_evidence']=dict(path=evidence['path'],sha256=evidence['sha256'])
    state['circle_reference']=dict(sketch=sketch,SW_feature_tree=tree,solids=canonical_bodies,
        SW_document_units_raw=list(units),CAM_use_document_units_raw=use)
