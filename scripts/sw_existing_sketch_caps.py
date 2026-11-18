"""Four saved signed sketches -> merged blind bosses, RAM only, no CAM/redraw.
Native qualification and a separate STEP Boolean audit are still required.
"""
from copy import deepcopy
from pathlib import Path
import math
import os
import re
from scripts import sw_cam_profile_sketch as core
from scripts import sw_cam_explicit_island_sketch as signed
from scripts import sw_part
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_executable_launch import _process_identity

SCOPE = 'EXISTING_SIGNED_SKETCH_MERGED_CAP_BATCH_V1'
require = signed.require
call = core.call


def key(path):
    return os.path.normcase(str(Path(path).resolve()))


def parameters(value):
    fields = {'process_id', 'expected_process_creation_time', 'expected_document_path',
              'expected_source_sha256', 'protected_document_path', 'protected_source_sha256',
              'expected_configuration', 'profile_specs', 'feature_names', 'depth_mm',
              'desired_direction_world', 'receipt_path'}
    require(type(value) is dict and set(value) == fields, 'Exact cap-batch fields required')
    p = deepcopy(value)
    require(type(p['process_id']) is int and 0 < p['process_id'] < 2**31, 'Strict PID required')
    require(core._finite(p['expected_process_creation_time']) > 0, 'Positive process lifetime required')
    for name in ('expected_document_path', 'protected_document_path', 'receipt_path'):
        require(type(p[name]) is str and Path(p[name]).is_absolute(), 'Absolute path required: ' + name)
    for name in ('expected_source_sha256', 'protected_source_sha256'):
        require(type(p[name]) is str and re.fullmatch('[0-9a-f]{64}', p[name]), 'Exact SHA required: ' + name)
    require(p['expected_source_sha256'] == p['protected_source_sha256'], 'Pristine byte-copy hashes required')
    require(key(p['expected_document_path']) != key(p['protected_document_path']), 'Separate qualification copy required')
    require(Path(p['expected_document_path']).suffix.lower() == '.sldprt' and
            Path(p['protected_document_path']).suffix.lower() == '.sldprt', 'Saved part files required')
    require(Path(p['receipt_path']).suffix.lower() == '.json', 'JSON receipt required')
    require(type(p['expected_configuration']) is str and 0 < len(p['expected_configuration']) <= 1024,
            'Explicit configuration required')
    require(0 < core._finite(p['depth_mm']) <= 5, 'Bounded cap depth (0,5] mm required')
    direction = p['desired_direction_world']
    require(type(direction) is list and len(direction) == 3 and
            all(type(x) in (int, float) and math.isfinite(x) for x in direction) and
            direction[:2] == [0, 0] and direction[2] in (-1, 1), 'Exact world +Z or -Z required')
    require(type(p['profile_specs']) is list and len(p['profile_specs']) == 4, 'Exactly four signed sketches required')
    p['profile_specs'] = [signed.sketch._input(spec) for spec in p['profile_specs']]
    for spec in p['profile_specs']:
        rows = spec['profile']['segments']
        require(spec['plane_axis'] == 'Z' and len(rows) == 4 and
                sum(x['kind'] == 'arc' for x in rows) == 2, 'Two-arc/two-line XY profile required')
    require(len({s['plane_offset_mm'] for s in p['profile_specs']}) == 1, 'Common saved sketch elevation required')
    require(type(p['feature_names']) is list and len(p['feature_names']) == 4, 'Four new feature names required')
    for name in p['feature_names']:
        core._name(name)
    names = [s['sketch_name'] for s in p['profile_specs']] + p['feature_names']
    require(len({x.casefold() for x in names}) == 8, 'Distinct source/output names required')
    require(key(p['receipt_path']) not in {key(p['expected_document_path']), key(p['protected_document_path'])},
            'Receipt cannot replace a part')
    return p


def marker_path(p):
    target = Path(p['expected_document_path'])
    return target.with_name('.' + target.name + '.existing-sketch-caps.once.json')


def file_guards(p):
    for path, digest in ((p['expected_document_path'], p['expected_source_sha256']),
                         (p['protected_document_path'], p['protected_source_sha256'])):
        require(core._sha(path) == digest, 'Saved source/copy hash changed')
    require(not os.path.samefile(p['expected_document_path'], p['protected_document_path']),
            'Source and target are the same file identity')


def direction_from_normal(normal, desired):
    n = core._xyz(normal)
    require(abs(math.sqrt(sum(x*x for x in n)) - 1) <= 1e-10 and
            abs(n[0]) <= 1e-10 and abs(n[1]) <= 1e-10 and abs(abs(n[2]) - 1) <= 1e-10,
            'Only unit axial sketch normals supported')
    dot = sum(a*b for a, b in zip(n, desired))
    require(abs(abs(dot) - 1) <= 1e-10, 'Desired world direction must align with actual sketch normal')
    # Official FeatureExtrusion3: Dir=True reverses default sketch-normal direction.
    return dot < 0


def sketch_direction(sw, raw, observed, spec, desired):
    transform = raw.ModelToSketchTransform
    values = core._rigid_transform(transform)
    require(values == observed['model_to_sketch_transform'], 'Sketch transform changed during readback')
    inverse = call(transform, 'Inverse')
    inverse_values = core._rigid_transform(inverse)
    a = values
    determinant = a[0]*(a[4]*a[8]-a[5]*a[7])-a[1]*(a[3]*a[8]-a[5]*a[6])+a[2]*(a[3]*a[7]-a[4]*a[6])
    require(abs(determinant-1) <= 1e-10, 'Proper rotation required; reflected sketch frame rejected')
    mu = call(sw, 'GetMathUtility')
    origin = core._point(mu, [0., 0., 0.], inverse)
    tip = core._point(mu, [0., 0., 1.], inverse)
    normal = [a-b for a, b in zip(tip, origin)]
    require(abs(origin[2] - spec['plane_offset_mm']/1000) <= core.TOL_M, 'Actual sketch elevation differs')
    return dict(normal_world=normal, origin_world_m=origin,
                sketch_to_model_transform=inverse_values,
                reverse_direction=direction_from_normal(normal, desired))


class NativeBackend:
    def __init__(self, sw, p):
        self.sw, self.p, self.model = sw, p, None

    def boundary(self, dirty):
        p = self.p
        owner = _process_identity(p['process_id'])
        require(owner['process_id'] == p['process_id'] and owner['alive'] is True and
                abs(owner['create_time'] - p['expected_process_creation_time']) <= 1e-6,
                'Owned process lifetime changed')
        self.model = core._identity(self.sw, p['process_id'], p['expected_document_path'])
        docs = call(self.sw, 'GetDocuments')
        require(type(docs) in (list, tuple) and len(docs) == 1 and
                key(call(docs[0], 'GetPathName')) == key(p['expected_document_path']),
                'Only the qualification copy may be loaded')
        require(call(self.model, 'IsOpenedReadOnly') is False, 'Writable target required')
        require(call(self.model, 'GetSaveFlag') is dirty, 'Unexpected dirty state')
        require(list(call(self.model, 'GetConfigurationNames')) == [p['expected_configuration']] and
                self.model.ConfigurationManager.ActiveConfiguration.Name == p['expected_configuration'],
                'Exact single configuration required')
        require(self.model.SketchManager.ActiveSketch is None, 'Active sketch edit is forbidden')
        return owner

    def capture(self):
        rows, _ = core._features(self.model)
        solids = core._bodies(self.model)
        require(len(solids) == 1 and solids[0]['mass_raw'][3] > 0, 'One positive-volume solid required')
        body = call(self.model, 'GetBodies2', 0, False)[0]
        health = call(body, 'Check2')
        require(type(health) is int and health == 0, 'Solid body check failed')
        return dict(features=rows, solids=solids, volume_m3=solids[0]['mass_raw'][3],
                    body_check=health, needs_save=call(self.model, 'GetSaveFlag'))

    def read_sketch(self, spec):
        feature = call(self.model, 'FeatureByName', spec['sketch_name'])
        require(feature is not None and str(feature.Name) == spec['sketch_name'] and
                call(feature, 'GetTypeName2') == 'ProfileFeature', 'Exact saved sketch feature required')
        raw = call(feature, 'GetSpecificFeature2')
        observed = signed.sketch._read_sketch(self.sw, raw, spec)
        proof = signed.verify_readback(spec, observed)
        orientation = sketch_direction(self.sw, raw, observed, spec, self.p['desired_direction_world'])
        ref = sw_part.SketchSelectionRef(name=spec['sketch_name'], sketch=raw, feature=feature,
                                         source='existing_signed_sketch_cap')
        return dict(spec=deepcopy(spec), sketch_readback=observed, proof=proof, **orientation), ref

    def existing_features(self, rows):
        for row in rows:
            feature = call(self.model, 'FeatureByName', row['name'])
            require(feature is not None and str(feature.Name) == row['name'] and
                    call(feature, 'GetTypeName2') == row['type'], 'Existing CAD feature lost or changed type')

    def create(self, reference, depth_mm, reverse):
        return sw_part.extrude_boss(self.model, reference, depth_mm/1000,
                                   direction=reverse, merge=True, start_offset=0.0)

    def read_feature(self, feature, name, observed, persist):
        read_feature_fields(feature, observed, persist)
        observed['type'] = observed.get('type_name2')
        persist()
        return observed

    def rename_feature(self, feature, name):
        feature.Name = name
        return str(feature.Name)

    def cleanup(self):
        if self.model is not None:
            owner = _process_identity(self.p['process_id'])
            require(owner['alive'] is True and abs(owner['create_time'] - self.p['expected_process_creation_time']) <= 1e-6,
                    'Owned lifetime changed before selection cleanup')
            core._identity(self.sw, self.p['process_id'], self.p['expected_document_path'])
            call(self.model, 'ClearSelection2', True)
            require(call(self.model.SelectionManager, 'GetSelectedObjectCount2', -1) == 0,
                    'Selection cleanup not verified')


def verify_feature(observed, p, index, reverse):
    require(canonical_boss_type(observed) == 'Boss', 'Actual extrusion type is not a supported boss')
    require(observed['name'] == p['feature_names'][index] and
            abs(core._finite(observed['depth_m']) - p['depth_mm']/1000) <= 1e-10,
            'Actual boss name/type/depth differs')
    for name, expected in (('reverse_direction', reverse), ('merge', True), ('both_directions', False),
                           ('is_boss', True), ('is_thin', False), ('draft', False)):
        require(observed[name] is expected, 'Actual extrusion flag differs: ' + name)
    require(type(observed['end_condition']) is int and observed['end_condition'] == 0 and
            type(observed['from_type']) is int and observed['from_type'] == 0, 'Blind extrusion from sketch required')
    require(p['profile_specs'][index]['sketch_name'] in observed['parents'], 'Returned boss does not reference intended sketch')


def same_capture(left, right):
    return (left['features'] == right['features'] and
            left['needs_save'] is right['needs_save'] and left['body_check'] == right['body_check'] and
            core._same_bodies(left['solids'], right['solids']) and
            math.isclose(left['volume_m3'], right['volume_m3'], rel_tol=1e-10, abs_tol=0.0))


def verify_delta(before, after, p, completed, verified_features=None):
    consumed = {s['sketch_name'] for s in p['profile_specs'][:completed]}
    added = p['feature_names'][:completed]
    added_set = set(added)
    # SolidWorks may absorb used sketches below their boss in the top-level tree.
    require([r for r in after['features'] if r['name'] not in added_set | consumed] ==
            [r for r in before['features'] if r['name'] not in consumed], 'Unexpected CAD feature-tree change')
    expected = [dict(name=n, type='Boss') for n in added]
    if verified_features is not None:
        require(len(verified_features) == completed, 'Every added feature must have independent definition readback')
        for i, item in enumerate(verified_features):
            require(item['name'] == added[i] and canonical_boss_type(item) == 'Boss',
                    'Observed boss prefix binding differs')
        expected = [dict(name=x['name'], type=x['type_name2']) for x in verified_features]
    require([r for r in after['features'] if r['name'] in added] == expected,
            'Exactly the requested raw boss prefix required')


def run(sw, value, *, runtime_check, backend=None):
    p = parameters(value)
    output, marker = Path(p['receipt_path']), marker_path(p)
    require(output.parent.is_dir() and not output.exists() and not marker.exists(), 'Fresh receipt/target without prior attempt required')
    file_guards(p)
    r = dict(scope=SCOPE, status='prepared', phase='preflight', request=deepcopy(p),
             marker_path=str(marker), actions=[], mutation_attempted=False, native_dispatch_pending=False,
             readback_verified=False, completed_count=0, source_unchanged=False, selection_cleanup_verified=False,
             model_saved=False, Save_attempted=False, CAM_calls=0, automatic_retry=False,
             original_volume_preserved_verified=False, added_volume_containment_verified=False,
             STEP_geometry_verified=False, production_qualified=False)
    _write_receipt(output, r, create=True)
    b = backend or NativeBackend(sw, p)
    def persist():
        _write_receipt(output, r)
    def boundary(dirty):
        runtime_check(); file_guards(p)
        owner = b.boundary(dirty)
        r['owner_last'] = owner
    try:
        boundary(False)
        before = b.capture(); r['before'] = before
        existing = {x['name'].casefold() for x in before['features']}
        require(all(n.casefold() not in existing for n in p['feature_names']), 'Output feature already exists')
        all_profiles = [b.read_sketch(s)[0] for s in p['profile_specs']]
        r['preflight_profiles'] = all_profiles
        boundary(False); persist()
        _write_receipt(marker, dict(scope=SCOPE, request_sha256=core._digest(p),
                                   target=p['expected_document_path'], receipt_path=p['receipt_path'],
                                   status='claimed_no_replay'), create=True)
        previous = before
        previous = execute_cap_suffix(b, p, r, before, all_profiles, 0, previous, [], boundary, persist)
        r['after'] = previous
        r['profiles_after'] = [b.read_sketch(s)[0] for s in p['profile_specs']]
        require(r['profiles_after'] == all_profiles, 'Source sketches changed during cap batch')
        boundary(True)
        r.update(status='caps_observed_ram_only', readback_verified=True, source_unchanged=True)
    except Exception as error:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error', readback_verified=False,
                 issue=dict(type=type(error).__name__, message=str(error)))
    finally:
        try:
            b.cleanup(); r['selection_cleanup_verified'] = True
            runtime_check(); file_guards(p)
        except Exception as error:
            r.update(status='uncertain' if r['mutation_attempted'] else 'error', readback_verified=False,
                     cleanup_issue=dict(type=type(error).__name__, message=str(error)))
        r['phase'] = 'finished' if not r['native_dispatch_pending'] else 'native_result_unknown'
        persist()
    return r


INSPECT_SCOPE = 'EXISTING_CAP_FIRST_RETURNED_FEATURE_INSPECTION_V1'


def inspection_parameters(value):
    fields = {'process_id', 'expected_process_creation_time', 'expected_document_path',
              'partial_receipt_path', 'partial_receipt_sha256', 'original_marker_sha256', 'receipt_path'}
    require(type(value) is dict and set(value) == fields, 'Exact inspection fields required')
    q = deepcopy(value)
    require(type(q['process_id']) is int and 0 < q['process_id'] < 2**31, 'Strict PID required')
    require(core._finite(q['expected_process_creation_time']) > 0, 'Positive lifetime required')
    for name in ('partial_receipt_path', 'expected_document_path', 'receipt_path'):
        require(type(q[name]) is str and Path(q[name]).is_absolute(), 'Absolute inspection path required')
    for name in ('partial_receipt_sha256', 'original_marker_sha256'):
        require(type(q[name]) is str and re.fullmatch('[0-9a-f]{64}', q[name]), 'Exact inspection SHA required')
    require(Path(q['receipt_path']).suffix.lower() == '.json', 'JSON inspection receipt required')
    return q


def inspection_authority(q):
    import json
    require(core._sha(q['partial_receipt_path']) == q['partial_receipt_sha256'], 'Partial receipt hash changed')
    raw = json.loads(Path(q['partial_receipt_path']).read_text(encoding='utf-8-sig'))
    p = parameters(raw['request'])
    require(p['process_id'] == q['process_id'] and
            p['expected_process_creation_time'] == q['expected_process_creation_time'] and
            key(p['expected_document_path']) == key(q['expected_document_path']) and
            key(p['receipt_path']) == key(q['partial_receipt_path']), 'Partial receipt identity differs')
    require(raw['scope'] == SCOPE and raw['status'] == 'uncertain' and raw['phase'] == 'finished' and
            raw['mutation_attempted'] is True and raw['native_dispatch_pending'] is False and
            raw['completed_count'] == 0 and raw['readback_verified'] is False and
            raw['selection_cleanup_verified'] is True and len(raw['actions']) == 1,
            'Only terminal first returned cap may be inspected')
    a = raw['actions'][0]
    require(type(a['index']) is int and a['index'] == 0 and a['attempted'] is True and
            a['returned'] is True and a['returned_object'] is True and a['pending'] is False and
            a['sketch_name'] == p['profile_specs'][0]['sketch_name'] and
            a['feature_name'] == p['feature_names'][0], 'First returned action binding differs')
    marker = marker_path(p)
    require(key(raw['marker_path']) == key(marker) and core._sha(marker) == q['original_marker_sha256'],
            'Original once marker changed')
    expected = dict(scope=SCOPE, request_sha256=core._digest(p), target=p['expected_document_path'],
                    receipt_path=p['receipt_path'], status='claimed_no_replay')
    require(json.loads(marker.read_text(encoding='utf-8-sig')) == expected, 'Original once binding differs')
    require(key(q['receipt_path']) not in {key(q['partial_receipt_path']), key(marker),
            key(p['expected_document_path']), key(p['protected_document_path'])}, 'Inspection cannot replace evidence')
    file_guards(p)
    return p, raw


class InspectionBackend(NativeBackend):
    def inspect_feature(self, before, baseline, output, persist):
        original = {x['name'] for x in baseline['features']}
        candidates = [x for x in before['features'] if x['name'] not in original]
        output['new_top_level_candidates'] = deepcopy(candidates); persist()
        feature = call(self.model, 'FeatureByName', self.p['feature_names'][0])
        output['expected_name_found'] = feature is not None; persist()
        if feature is None:
            require(len(candidates) == 1, 'A unique new feature is required for bounded lookup')
            feature = call(self.model, 'FeatureByName', candidates[0]['name'])
        require(feature is not None, 'Returned feature is no longer available')
        read_feature_fields(feature, output, persist)


def run_inspection(sw, value, *, runtime_check, backend=None):
    q = inspection_parameters(value)
    p, original = inspection_authority(q)
    output = Path(q['receipt_path'])
    require(output.parent.is_dir() and not output.exists(), 'Fresh inspection receipt required')
    r = dict(scope=INSPECT_SCOPE, status='prepared', request=q, source_request=deepcopy(p),
             observed={}, mutation_attempted=False, readback_verified=False,
             Save_attempted=False, rebuild_attempted=False, selection_changed=False, CAM_calls=0,
             batch_continuation_authorized=False, STEP_geometry_verified=False)
    _write_receipt(output, r, create=True)
    b = backend or InspectionBackend(sw, p)
    def persist(): _write_receipt(output, r)
    def boundary():
        runtime_check(); inspection_authority(q)
        r['owner_last'] = b.boundary(True)
    try:
        boundary(); r['before'] = b.capture(); persist()
        b.inspect_feature(r['before'], original['before'], r['observed'], persist)
    except Exception as error:
        r['issue'] = dict(type=type(error).__name__, message=str(error))
    finally:
        if 'before' in r:
            try:
                boundary(); r['after'] = b.capture(); persist()
                require(same_capture(r['before'], r['after']), 'CAD state changed during read-only inspection')
                boundary()
                r['state_unchanged'] = True
            except Exception as error:
                r['final_guard_issue'] = dict(type=type(error).__name__, message=str(error))
        r['readback_verified'] = (r.get('state_unchanged') is True and r['observed'].get('read_complete') is True
                                  and 'issue' not in r and 'final_guard_issue' not in r)
        r['status'] = 'observed_read_only' if r['readback_verified'] else 'error'
        persist()
    return r


def canonical_boss_type(observed):
    require(observed.get('read_complete') is True and not observed.get('getter_errors'),
            'Complete error-free native definition readback required')
    pair = (observed.get('type_name2'), observed.get('type_name'))
    require(pair in (('Boss', 'Boss'), ('ICE', 'Boss')), 'Unsupported raw/underlying feature type pair')
    return 'Boss'


def read_feature_fields(feature, output, persist):
    errors = output.setdefault('getter_errors', {})
    def read(name, getter):
        try:
            value = getter()
            require(value is None or type(value) in (str, bool, int, float, list), 'Unsupported raw getter value')
            if type(value) is float: require(math.isfinite(value), 'Nonfinite raw getter value')
            output[name] = value
        except Exception as error:
            errors[name] = dict(type=type(error).__name__, message=str(error))
        persist()
    read('name', lambda: str(feature.Name))
    read('type_name2', lambda: call(feature, 'GetTypeName2'))
    read('type_name', lambda: call(feature, 'GetTypeName'))
    try:
        definition = call(feature, 'GetDefinition')
        output['definition_available'] = definition is not None; persist()
        require(definition is not None, 'Extrusion definition unavailable')
    except Exception as error:
        errors['definition'] = dict(type=type(error).__name__, message=str(error)); persist()
        definition = None
    if definition is not None:
        for name, getter in (
            ('depth_m', lambda: call(definition, 'GetDepth', True)),
            ('end_condition', lambda: call(definition, 'GetEndCondition', True)),
            ('reverse_direction', lambda: definition.ReverseDirection),
            ('merge', lambda: definition.Merge),
            ('both_directions', lambda: definition.BothDirections),
            ('from_type', lambda: definition.FromType),
            ('is_boss', lambda: call(definition, 'IsBossFeature')),
            ('is_thin', lambda: call(definition, 'IsThinFeature')),
            ('draft', lambda: call(definition, 'GetDraftWhileExtruding', True))):
            read(name, getter)
    def parents():
        rows = call(feature, 'GetParents')
        require(type(rows) in (list, tuple) and 0 <= len(rows) <= 32, 'Bounded parents required')
        return [str(x.Name) for x in rows]
    read('parents', parents)
    output['read_complete'] = not errors; persist()


def execute_cap_suffix(b, p, r, before, all_profiles, start, previous, verified, boundary, persist):
    for i in range(start, 4):
        spec = p['profile_specs'][i]
        boundary(i > 0)
        current = b.capture()
        require(same_capture(current, previous), 'CAD state drift before next cap')
        b.existing_features(before['features'])
        fresh, ref = b.read_sketch(spec)
        require(fresh == all_profiles[i], 'Saved profile changed before extrusion')
        reverse = fresh['reverse_direction']
        row = dict(index=i, sketch_name=spec['sketch_name'], feature_name=p['feature_names'][i],
                   depth_mm=p['depth_mm'], normal_world=fresh['normal_world'], reverse_direction=reverse,
                   attempted=True, pending=True, returned=False, returned_object=False, readback_verified=False)
        r['actions'].append(row)
        r.update(phase='extrude:' + spec['sketch_name'], mutation_attempted=True, native_dispatch_pending=True)
        persist()
        feature = b.create(ref, p['depth_mm'], reverse)
        row.update(returned=True, pending=False, returned_object=feature is not None)
        r['native_dispatch_pending'] = False; persist()
        require(feature is not None, 'Boss extrusion returned null; no retry')
        boundary(True)
        row['feature'] = {}; persist()
        b.read_feature(feature, p['feature_names'][i], row['feature'], persist)
        row['name_before_rename'] = row['feature'].get('name'); persist()
        row['feature']['name'] = b.rename_feature(feature, p['feature_names'][i]); persist()
        verify_feature(row['feature'], p, i, reverse)
        after = b.capture(); row['after'] = after; persist()
        require(after['volume_m3'] > previous['volume_m3'] and
                not math.isclose(after['volume_m3'], previous['volume_m3'], rel_tol=1e-10, abs_tol=0.0),
                'Each merged cap must add positive volume beyond readback noise')
        b.existing_features(before['features'])
        verified.append(row['feature'])
        verify_delta(before, after, p, i+1, verified)
        boundary(True)
        row['readback_verified'] = True; r['completed_count'] = i+1
        previous = after; persist()
    return previous


CONTINUE_SCOPE = 'EXISTING_CAP_REMAINING_THREE_CONTINUATION_V1'


def continuation_parameters(value):
    extras = {'inspection_receipt_path', 'inspection_receipt_sha256'}
    require(type(value) is dict and extras.issubset(value), 'Inspection authority fields required')
    inspection_parameters({k: v for k, v in value.items() if k not in extras})
    require(type(value['inspection_receipt_path']) is str and Path(value['inspection_receipt_path']).is_absolute(),
            'Absolute inspection receipt path required')
    require(type(value['inspection_receipt_sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['inspection_receipt_sha256']),
            'Exact inspection receipt SHA required')
    return deepcopy(value)


def continuation_authority(q):
    import json
    iq = {k: v for k, v in q.items() if k not in ('inspection_receipt_path', 'inspection_receipt_sha256')}
    p, original = inspection_authority(iq)
    require(core._sha(q['inspection_receipt_path']) == q['inspection_receipt_sha256'], 'Inspection receipt hash changed')
    inspected = json.loads(Path(q['inspection_receipt_path']).read_text(encoding='utf-8-sig'))
    expected = dict(iq, receipt_path=q['inspection_receipt_path'])
    actual = inspected['request']
    require(set(actual) == set(expected) and all(key(actual[k]) == key(v) if k.endswith('_path') else actual[k] == v
            for k, v in expected.items()), 'Inspection request binding differs')
    require(inspected['scope'] == INSPECT_SCOPE and inspected['status'] == 'observed_read_only' and
            inspected['readback_verified'] is True and inspected['state_unchanged'] is True and
            inspected['mutation_attempted'] is False and inspected['selection_changed'] is False and
            inspected['Save_attempted'] is False and inspected['rebuild_attempted'] is False and
            inspected['CAM_calls'] == 0 and inspected['source_request'] == p,
            'Successful unchanged read-only inspection required')
    require(same_capture(inspected['before'], inspected['after']) and inspected['after']['needs_save'] is True,
            'Inspection state capture differs')
    require(key(q['receipt_path']) != key(q['inspection_receipt_path']), 'Continuation must not overwrite inspection')
    observed = inspected['observed']
    require(observed['expected_name_found'] is True, 'Exact first cap name required for continuation')
    require(len(original['preflight_profiles']) == 4 and
            [x['spec'] for x in original['preflight_profiles']] == p['profile_specs'], 'Original four profile bindings differ')
    reverse = original['preflight_profiles'][0]['reverse_direction']
    verify_feature(observed, p, 0, reverse)
    verify_delta(original['before'], inspected['after'], p, 1, [observed])
    require(inspected['after']['volume_m3'] > original['before']['volume_m3'] and
            not math.isclose(inspected['after']['volume_m3'], original['before']['volume_m3'], rel_tol=1e-10, abs_tol=0),
            'Inspected first cap must add positive volume')
    return p, original, inspected


def continuation_marker_path(p):
    target = Path(p['expected_document_path'])
    return target.with_name('.' + target.name + '.existing-sketch-caps-remaining3.once.json')


def run_continuation(sw, value, *, runtime_check, backend=None):
    q = continuation_parameters(value)
    p, original, inspected = continuation_authority(q)
    output, marker = Path(q['receipt_path']), continuation_marker_path(p)
    require(output.parent.is_dir() and not output.exists() and not marker.exists(),
            'Fresh continuation receipt and unused remaining-three marker required')
    require(key(output) != key(marker), 'Continuation receipt cannot replace its once marker')
    r = dict(scope=CONTINUE_SCOPE, status='prepared', phase='adopt_first', request=q, source_request=deepcopy(p),
             marker_path=str(marker), actions=[], mutation_attempted=False, native_dispatch_pending=False,
             readback_verified=False, completed_count=0, adopted_count=0, source_unchanged=False,
             selection_cleanup_verified=False, model_saved=False, Save_attempted=False, CAM_calls=0,
             automatic_retry=False, original_volume_preserved_verified=False,
             added_volume_containment_verified=False, STEP_geometry_verified=False, production_qualified=False)
    _write_receipt(output, r, create=True)
    b = backend or InspectionBackend(sw, p)
    def persist(): _write_receipt(output, r)
    def boundary(dirty=True):
        runtime_check(); continuation_authority(q)
        r['owner_last'] = b.boundary(dirty)
    try:
        boundary(); current = b.capture(); r['before'] = current; persist()
        require(same_capture(current, inspected['after']), 'Current CAD differs from inspected first-cap state')
        b.existing_features(original['before']['features'])
        r['adopted_feature'] = {}; persist()
        b.inspect_feature(current, original['before'], r['adopted_feature'], persist)
        require(r['adopted_feature'] == inspected['observed'], 'First feature changed since inspection')
        all_profiles = [b.read_sketch(s)[0] for s in p['profile_specs']]
        r['preflight_profiles'] = all_profiles; persist()
        require(all_profiles == original['preflight_profiles'], 'Original signed sketch profiles or frames changed')
        verify_feature(r['adopted_feature'], p, 0, all_profiles[0]['reverse_direction'])
        verify_delta(original['before'], current, p, 1, [r['adopted_feature']])
        boundary(); require(same_capture(b.capture(), current), 'CAD changed during first-cap adoption')
        r.update(adopted_count=1, completed_count=1); persist()
        _write_receipt(marker, dict(scope=CONTINUE_SCOPE, request_sha256=core._digest(q),
                                   target=p['expected_document_path'], receipt_path=q['receipt_path'],
                                   status='claimed_no_replay'), create=True)
        after = execute_cap_suffix(b, p, r, original['before'], all_profiles, 1, current,
                                   [r['adopted_feature']], boundary, persist)
        r['after'] = after
        r['profiles_after'] = [b.read_sketch(s)[0] for s in p['profile_specs']]
        require(r['profiles_after'] == all_profiles, 'Source sketches changed during continuation')
        boundary()
        r.update(status='caps_observed_ram_only', readback_verified=True, source_unchanged=True)
    except Exception as error:
        r.update(status='uncertain' if r['mutation_attempted'] else 'error', readback_verified=False,
                 issue=dict(type=type(error).__name__, message=str(error)))
    finally:
        if r['mutation_attempted']:
            try:
                b.cleanup(); r['selection_cleanup_verified'] = True
                runtime_check(); continuation_authority(q)
            except Exception as error:
                r.update(status='uncertain', readback_verified=False,
                         cleanup_issue=dict(type=type(error).__name__, message=str(error)))
        r['phase'] = 'finished' if not r['native_dispatch_pending'] else 'native_result_unknown'
        persist()
    return r
