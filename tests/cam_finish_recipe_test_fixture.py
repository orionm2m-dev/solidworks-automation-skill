"""纯合成输入；只替换外部清单和 COM 传输，保留写入及校验流程。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import sw_cam_finish_recipe as recipe
from scripts import sw_cam_events
from scripts.sw_cam_shared_cutter_geometry import FIELDS

TARGET = dict(CutDiameter=6., EffCutlength=12., ShankDia=6., OverallLen=50.,
              NoOfFlutes=4, MillToolShankType=0, ShoulderLength=12.,
              ShoulderDia=6., ShankLength=12., Protrusion=20.)
OLD = dict(CutDiameter=10., EffCutlength=18., ShankDia=10., OverallLen=70.,
           NoOfFlutes=2, MillToolShankType=0, ShoulderLength=18.,
           ShoulderDia=10., ShankLength=18., Protrusion=30.)
HOLDER_ALIASES = dict(GetHolderShape='shape', GetHolderId='holder_id_raw',
    GetHolderNumber='number', GetName='name', GetHolderTopDia='top_diameter_native',
    GetHolderBottomDia='bottom_diameter_native', GetHolderOverallLength='overall_length_native',
    GetHolderBottomLength='bottom_length_native', GetProtrusion='holder_protrusion_native')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data), encoding='utf-8')
    return dict(path=str(path), sha256=sha(path))


def line_profile(segments):
    curves = [dict(index=i, read_complete=True, curve_type=0,
        start_native=[a[0], 0., a[1]], end_native=[b[0], 0., b[1]])
        for i, (a, b) in enumerate(segments)]
    return dict(status='observed', declared_chain_count=1, chains=[dict(index=0,
        read_complete=True, declared_curve_count=len(curves), curves=curves)])


class RecipeCase:
    def __init__(self, tmp_path, monkeypatch, *, holder_current=False, dirty_after=False):
        self.root = tmp_path
        self.source = tmp_path/'SyntheticPart.SLDPRT'
        self.source.write_bytes(b'synthetic saved document, not a CAD model')
        self.source_sha = sha(self.source)
        self.holder_path = tmp_path/'synthetic_holder.mh'
        self.holder_path.write_text('# CWToolGen Version: <1.0>\nline 0 0 5 0\nline 5 0 5 30\n')
        self.holder_recipe_path = tmp_path/'holder_recipe.json'
        write_json(self.holder_recipe_path, dict(source_sha256=sha(self.holder_path),
            coordinate_order=['radius', 'axial_z'], record_count=2, records=[
                dict(kind='line', start_rz=[0., 0.], end_rz=[5., 0.]),
                dict(kind='line', start_rz=[5., 0.], end_rz=[5., 30.])]))
        self.provenance = tmp_path/'provenance.json'
        write_json(self.provenance, dict(synthetic=True, physical_identity_qualified=False))
        self.manifest_path = tmp_path/'manifest.json'
        self.manifest_pin = write_json(self.manifest_path, dict(synthetic=True))
        self.data = deepcopy(OLD)
        self.holder_name = str(self.holder_path) if holder_current else 'initial_holder.mh'
        self.dirty_after = dirty_after
        self.calls = []
        self.capture_count = self.bootstrap_count = self.files_count = 0
        self.mode = None
        self.after_mutation = None
        self.before_mutation = None
        self.event_count = 0
        self.fail_write_once = False
        self.active_receipt = tmp_path/'configuration.json'
        self.operation = SimpleNamespace(native_id=248)
        case = self

        class Tool:
            native_id = 249
            def __setattr__(self, key, value):
                case.assert_pending('scalar', key)
                case.calls.append(('scalar', key, value))
                if case.mode == 'no_effect' and key == 'ShoulderLength':
                    return
                case.data[key] = value
                if case.mode == 'setter_throw' and key == 'ShoulderLength':
                    raise RuntimeError('transport failed after possible application')
                if case.mode == 'coupled_bad' and key == 'EffCutlength':
                    case.data['ShoulderLength'] = 13.
                if case.mode == 'coupled_target' and key == 'EffCutlength':
                    case.data['ShoulderLength'] = TARGET['ShoulderLength']
                if case.mode == 'source_drift':
                    case.source.write_bytes(b'changed externally')
                if case.mode == 'holder_pin_drift':
                    case.holder_path.write_text('changed externally')
                if case.mode == 'event':
                    case.event_count = 1

        self.tool = Tool()
        self.holder = object()
        self.doc = object()
        self.identity = dict(path=str(self.source), title=self.source.name, type=1, needs_save=False)
        generic = self.generic_tool()
        operations = [dict(native_id=i, setup_native_id=93, linked_feature_ids=[79],
            mill_operation_type=0, suppressed=False, toolpath_generated=False,
            toolpath_record_counts=[], assigned_tool=dict(generic, native_id=500+i))
            for i in (143, 144, 195, 196, 247)]
        operations.append(dict(native_id=248, setup_native_id=93, linked_feature_ids=[79],
            mill_operation_type=1, suppressed=False, toolpath_generated=False,
            toolpath_record_counts=[], assigned_tool=generic))
        self.state = dict(document=deepcopy(self.identity), saved_file_sha256=self.source_sha,
            features=[dict(native_id=i) for i in range(19)],
            feature_setups=[dict(native_id=i) for i in range(3)],
            operation_setups=[dict(native_id=i) for i in range(3)], operation_count=6, operations=operations)
        self.rough_payload = dict(candidate={'synthetic': 1}, levels={'clearance': 5.}, entry={'mode': 0})
        finish = self.finish_payload()
        self.loaded = dict(state=deepcopy(self.state), payload=deepcopy(self.rough_payload),
            finish={k:deepcopy(finish[k]) for k in ('details', 'levels', 'leads', 'unit_record')},
            pins=[self.manifest_pin], pin=self.manifest_pin)
        self.loaded['finish']['tool_summary'] = deepcopy(generic)

        class Guard:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def typed(self, obj, name): return obj
            def read(self, obj, name, *args):
                if obj is case.operation and name == 'IGetTool': return case.tool
                if obj is case.tool:
                    if name == 'IsMillTool': return True
                    if name == 'IGetMillToolHolder': return case.holder
                    return case.data[name]
                if obj is case.holder and name == 'GetName': return case.holder_name
                raise AssertionError((obj, name, args))

        class Context:
            def __init__(self, loaded, args, sw, typelib_path, unused, events):
                self.args = args
                self.app = None
                self.allow_dirty_transition = False
            def files(self):
                case.files_count += 1
                if sha(case.source) != case.source_sha: raise ValueError('saved source drift')
            def identity(self):
                if case.mode == 'identity_drift' and case.calls:
                    raise ValueError('active document drift')
                value = deepcopy(case.identity)
                value['needs_save'] = case.dirty_after if case.calls else False
                return value
            def guard(self): return Guard()

        class Session:
            def __init__(self, app, typelib_path): self.active = False
            def __enter__(self): self.active = True; return self
            def __exit__(self, *exc): self.active = False; return False
            def summary(self):
                return dict(subscribed=True, active=self.active, disconnected=not self.active,
                    event_count=case.event_count, overflow=False, callback_errors=[],
                    callback_error_count=0, subscription_error=None, disconnect_errors=[])

        def load_manifest(*args, **kwargs): return deepcopy(case.loaded)
        def bootstrap(*args):
            case.bootstrap_count += 1
            return object()
        def capture(ctx, state, *, holder_recipe, diagnostic):
            case.capture_count += 1
            result = case.capture()
            change = case.before_mutation if case.capture_count == 1 else case.after_mutation
            if change: change(result)
            diagnostic.update(capture_complete=True, raw_synthetic=recipe.public_checkpoint(result))
            return result
        def invoke(obj, name, *args):
            assert obj is case.holder and name == 'SetFilePathForUserDefinedHolder'
            case.assert_pending('holder')
            case.calls.append(('holder', name, args[0]))
            case.holder_name = args[0]
            if case.mode == 'holder_throw': raise RuntimeError('holder response lost')
            if case.mode == 'holder_no_effect': case.holder_name = 'initial_holder.mh'
            return {'holder_none': None, 'holder_bool': False, 'holder_nonzero': 1}.get(case.mode, 0)
        real_write = recipe._write_receipt
        def receipt_write(path, report, **kwargs):
            if (case.fail_write_once and report.get('native_dispatch_pending')
                    and Path(path) == case.active_receipt):
                case.fail_write_once = False
                raise OSError('durable receipt unavailable')
            return real_write(path, report, **kwargs)

        monkeypatch.setattr(recipe, 'load_saved_route_manifest', load_manifest)
        monkeypatch.setattr(recipe, 'RouteCheckpointContext', Context)
        monkeypatch.setattr(recipe, 'capture_finish_recipe', capture)
        monkeypatch.setattr(recipe, '_bootstrap', bootstrap)
        monkeypatch.setattr(recipe, '_object_id', lambda doc, obj, read: obj.native_id)
        monkeypatch.setattr(recipe, '_member', invoke)
        monkeypatch.setattr(recipe, '_write_receipt', receipt_write)
        monkeypatch.setattr(sw_cam_events, 'CamMessageSession', Session)

    def assert_pending(self, kind, key=None):
        report = json.loads(self.active_receipt.read_text(encoding='utf-8'))
        marker = json.loads(Path(report['marker_path']).read_text(encoding='utf-8'))
        assert report['native_dispatch_pending'] is marker['native_dispatch_pending'] is True
        assert report['mutation_attempted'] is marker['mutation_attempted'] is True
        if kind == 'scalar':
            entry = report['field_attempts'][-1]
            assert entry['property'] == key and entry['setter_attempted'] is True
            assert entry['native_call_returned'] is False
        else:
            assert report['holder_reference']['setter_attempted'] is True

    def generic_tool(self):
        return dict(native_id=249, tool_type_raw=1, is_mill_tool=True, native_read_complete=True,
                    cut_diameter_native=self.data['CutDiameter'], protrusion_native=self.data['Protrusion'])

    def full_tool(self):
        p, length, cutting = self.data['Protrusion'], self.data['OverallLen'], self.data['EffCutlength']
        radius = self.data['CutDiameter']/2
        full = dict(tool_native_id=249, tool_type_raw=1, geometry_read_complete=True, profile_complete=True,
            mill_tool=dict(type_raw=1, subtype_raw=3, end_radius_native=0.), holder=dict(shape=4,
            holder_id_raw=501, number='SYNTHETIC', name=self.holder_name, top_diameter_native=10.,
            bottom_diameter_native=10., overall_length_native=30., bottom_length_native=5.,
            holder_protrusion_native=p), profile_budget=dict(curves=6, chains=3, islands=0))
        for prop, section, key in FIELDS:
            (full[section] if section else full)[key] = self.data[prop]
        full['profiles'] = dict(tool=line_profile([((0., 0.), (radius, 0.)), ((radius, 0.), (radius, length))]),
            shank=line_profile([((radius, cutting), (radius, length))]),
            holder=line_profile([((0., p), (5., p)), ((5., p), (5., p+30.))]))
        return full

    def finish_payload(self):
        full = self.full_tool()
        aliases = {prop:key for prop, section, key in FIELDS if section}
        aliases.update(MillToolType='type_raw', MillToolSubType='subtype_raw', EndRadius='end_radius_native')
        return dict(details=dict(tool={prop:{'raw':full['mill_tool'][key]} for prop,key in aliases.items()},
            holder={prop:{'raw':full['holder'][key]} for prop,key in HOLDER_ALIASES.items()},
            finish={'Step': {'raw':.4}}), full_tool=full, levels={'clearance':5.},
            leads={'length':1.}, unit_record={'unit':'mm'})

    def capture(self):
        state = deepcopy(self.state)
        state['operations'][-1]['assigned_tool'] = self.generic_tool()
        state['document']['needs_save'] = self.dirty_after if self.calls else False
        return dict(state=state, native=dict(doc=self.doc, operations={248:self.operation}),
            rough_payload=deepcopy(self.rough_payload), finish_payload=self.finish_payload())

    def args(self):
        return dict(process_id=4242, expected_document_path=str(self.source),
            expected_source_sha256=self.source_sha, target_feature_native_id=79,
            target_operation_native_id=247, target_operation_setup_native_id=93,
            expected_candidate_tool_native_id=263, finish_operation_native_id=248,
            finish_tool_native_id=249, qualification_only=True, acknowledge_disposable_copy=True,
            receipt_path=str(self.active_receipt), message_policy='vendor_default', software_only_experiment=True)

    def run(self):
        return recipe.configure_finish_recipe(object(), 'synthetic-clsid', 'synthetic.tlb',
            manifest_path=str(self.manifest_path), manifest_sha256=sha(self.manifest_path),
            runtime_pins=[], generated_typelib_path='synthetic-generated.py',
            holder_file_path=str(self.holder_path), holder_file_sha256=sha(self.holder_path),
            holder_recipe_path=str(self.holder_recipe_path), holder_recipe_sha256=sha(self.holder_recipe_path),
            target_geometry=deepcopy(TARGET), recipe_provenance_path=str(self.provenance),
            recipe_provenance_sha256=sha(self.provenance), **self.args())

    def load(self):
        return recipe.load_completed_finish_recipe(str(self.active_receipt), sha(self.active_receipt), **self.args())
