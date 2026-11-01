"""Explicit two-file runtime compatibility for a saved Finish-definition parent.

Historical bytes remain immutable archives. Only the listed interface additions
and the unchanged default shared-reader branch are accepted; no CAD calls.
"""
import ast
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
from scripts import sw_cam_wall_apply_all_save as parent
from scripts.sw_cam_mill_selected_plan_evidence import read_pin
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_rough_firstcut import require
common,group=parent.common,parent.group
SCOPE='SAVED_FINISH_RUNTIME_COMPATIBILITY_V1'
NAMES={'sw_cam_comtypes.py':'live_pins','sw_cam_operation_profile.py':'offline_proof_pins'}
ADDED_INTERFACES={'ICWDrillTool':'{7532C747-3BC4-11D6-A9AF-00062999E55F}',
                  'ICWTurnDrillOp':'{44ADE2D0-3FA3-44C6-9B3D-8952D60FC0BB}'}


def _dump(value):return ast.dump(value,include_attributes=False)
def _function(tree,name):
    values=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name]
    require(len(values)==1,'Unique declared function required: '+name);return values[0]
def _tree(path):
    p=Path(path);require(p.is_file() and p.stat().st_size<=1024*1024,'Bounded source file required')
    return ast.parse(p.read_text(encoding='utf-8-sig'))


def verify_source_change(name,archive,current):
    """Prove the narrow BASE caller scope, without executing archived code."""
    old,new=_tree(archive),_tree(current)
    if name=='sw_cam_comtypes.py':
        def registry(t):
            values=[n.value for n in t.body if isinstance(n,ast.Assign)
                and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='_INTERFACES']
            require(len(values)==1 and isinstance(values[0],ast.Dict),'Exact interface registry required');return values[0]
        a,b=registry(old),registry(new);before=ast.literal_eval(a);after=ast.literal_eval(b)
        require(set(after)==set(before)|set(ADDED_INTERFACES) and not set(before).intersection(ADDED_INTERFACES)
            and all(after[k]==v for k,v in before.items()) and all(after[k]==v for k,v in ADDED_INTERFACES.items()),
            'Only the two declared interface additions are compatible')
        keep=[i for i,key in enumerate(b.keys) if ast.literal_eval(key) not in ADDED_INTERFACES]
        b.keys=[b.keys[i] for i in keep];b.values=[b.values[i] for i in keep]
        require(_dump(old)==_dump(new),'Bridge code outside the registry changed')
        return dict(kind='two_interface_registry_additions_only',old_helpers_unchanged=True)
    require(name=='sw_cam_operation_profile.py','Unsupported compatibility module')
    a,b=_function(old,'_read_tool'),_function(new,'_read_tool')
    require(len(b.args.kwonlyargs)==1 and b.args.kwonlyargs[0].arg=='include_drill'
        and len(b.args.kw_defaults)==1 and isinstance(b.args.kw_defaults[0],ast.Constant)
        and b.args.kw_defaults[0].value is False,'New reader option must default to False')
    expected=ast.parse("result['turn_tool_type_raw'] == 2 and include_drill",mode='eval').body
    extra=[n for n in b.body if isinstance(n,ast.If) and _dump(n.test)==_dump(expected)]
    require(len(extra)==1 and not extra[0].orelse,'Exactly one opt-in drill branch required')
    b.body.remove(extra[0]);b.args.kwonlyargs=[];b.args.kw_defaults=[]
    require(_dump(a)==_dump(b),'Shared reader default behavior changed')
    permitted={'_read_tool','_read_drill_operation','inspect_operation_profile'}
    old.body=[n for n in old.body if not isinstance(n,ast.FunctionDef) or n.name not in permitted]
    new.body=[n for n in new.body if not isinstance(n,ast.FunctionDef) or n.name not in permitted]
    require(_dump(old)==_dump(new),'Shared profile imports/helpers or module initialization changed')
    return dict(kind='shared_reader_default_branch_unchanged',include_drill_default=False,
        full_profile_entrypoint_equivalence_claimed=False,archived_code_executed=False)


def verify_regression(pin):
    common._check([pin]);root=ET.fromstring(Path(pin['path']).read_bytes())
    suites=[root] if root.tag=='testsuite' else list(root.findall('testsuite'))
    require(suites and all(int(s.attrib.get('errors',0))==0 and int(s.attrib.get('failures',0))==0
        for s in suites),'Passing regression evidence required')
    total=sum(int(s.attrib.get('tests',0)) for s in suites)
    require(total>0,'Nonempty regression evidence required');return total


def validate_evidence(e,r,parent_pin):
    require(e.get('scope')==SCOPE and e.get('status')=='compatible_for_finish_definition'
        and e.get('native_called') is False and e.get('historical_code_executed') is False,'Exact offline compatibility scope required')
    require(e['parent_receipt_pin']==parent_pin and e['source_pin']==dict(path=r['source_path'],sha256=r['saved_source_sha256'])
        and e['verifier_pin']==common._pin(__file__),'Compatibility parent/source/verifier differs')
    common._check([e['source_pin']]);verify_regression(e['regression_pin'])
    rows=e['replacements'];require(type(rows) is list and len(rows)==len(NAMES),'Exactly two replacements required')
    result={}
    for row in rows:
        require(type(row) is dict and set(row)=={'name','role','historical_pin','archive_pin','current_pin'},'Exact replacement record required')
        name=row['name'];require(name in NAMES and name not in result and row['role']==NAMES[name],'Duplicate/unsupported replacement')
        old,archive,current=row['historical_pin'],row['archive_pin'],row['current_pin']
        require(Path(old['path']).name==name and common._key(old['path'])==common._key(current['path'])
            and common._key(archive['path'])!=common._key(current['path']) and old['sha256']==archive['sha256']
            and old['sha256']!=current['sha256'],'Historical archive/current identities differ')
        require([x for x in r[row['role']] if common._key(x['path'])==common._key(old['path'])]==[old],
            'Historical pin must occur exactly once in its declared parent role')
        from scripts import sw_cam_comtypes,sw_cam_operation_profile
        module=sw_cam_comtypes if name=='sw_cam_comtypes.py' else sw_cam_operation_profile
        require(current==common._pin(module.__file__),'Compatibility current implementation differs from imported module')
        common._check([archive,current]);verify_source_change(name,archive['path'],current['path']);result[name]=deepcopy(row)
    return result


def checked_lists(r,replacements):
    """Check all unchanged pins normally; resolve only the exact two histories."""
    out={};seen=set()
    for role in ('live_pins','offline_proof_pins','bootstrap_export_pins'):
        rows=[]
        for pin in r[role]:
            name=Path(pin['path']).name
            if name in replacements:
                rec=replacements[name]
                require(role==rec['role'] and pin==rec['historical_pin'] and name not in seen,'Unexpected duplicate/version/role replacement')
                seen.add(name);rows.append(deepcopy(rec['current_pin'] if role=='live_pins' else rec['archive_pin']))
            else:rows.append(deepcopy(pin))
        common._check(rows);out[role]=rows
    require(seen==set(NAMES),'Missing explicit replacement');return out


def load_saved_configuration(path,digest,*,compatibility_path,compatibility_sha256,
                             process_id,expected_document_path,expected_source_sha256):
    """Same saved-parent checks, with explicit immutable historical/current pins."""
    r,pin=read_pin(path,digest);e,epin=read_pin(compatibility_path,compatibility_sha256)
    require(r['module_pin']==common._pin(parent.__file__) and r['process_id']==process_id
        and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),
        'Saved configuration source, owner or writer changed')
    replacements=validate_evidence(e,r,pin);lists=checked_lists(r,replacements)
    previous,previouspin=read_pin(r['parent_pin']['path'],r['parent_pin']['sha256'])
    earlier=parent.validate_empty(previous)
    require(group.exact(group.current_projection(earlier),group.current_projection(r['loaded_context_before'])),
        'Save parent differs from terminal empty candidate')
    context=parent.validate_saved(r)
    require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Completed context digest differs')
    marker=parent.marker_path(r['source_path'],r['initial_source_sha256'],r['parent_pin']['sha256'])
    mark,markpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,parent.Journal(r,path,marker).marker_state()),'Saved once-marker differs')
    live=common._merge([x for x in lists['live_pins'] if common._key(x['path'])!=common._key(previous['checkpoint_pin']['path'])],
        [pin,epin,common._pin(__file__)])
    require(len(live)<=64,'Bounded compatible saved closure required')
    archives=[row['archive_pin'] for row in replacements.values()]
    offline=common._merge(lists['offline_proof_pins'],archives,
        [row['current_pin'] for row in replacements.values()],[markpin,e['regression_pin']])
    context.update(pins=live,offline_export_proof_pins=offline,parent_pin=pin,group_marker_pin=markpin,
        runtime_compatibility_pin=epin,runtime_compatibility_scope=SCOPE,
        bootstrap_export_pins=lists['bootstrap_export_pins'])
    return context


def prepare_evidence(parent_path,parent_sha256,*,archives,regression_pin,output_path):
    """Create a new bound compatibility receipt; never edit the saved parent."""
    require(type(archives) is dict and set(archives)==set(NAMES),'Exactly two historical archives required')
    r,pin=read_pin(parent_path,parent_sha256)
    from scripts import sw_cam_comtypes,sw_cam_operation_profile
    current_modules={'sw_cam_comtypes.py':sw_cam_comtypes,'sw_cam_operation_profile.py':sw_cam_operation_profile}
    rows=[]
    for name,role in NAMES.items():
        old=[x for x in r[role] if Path(x['path']).name==name]
        require(len(old)==1,'Exactly one historical dependency required')
        rows.append(dict(name=name,role=role,historical_pin=deepcopy(old[0]),
            archive_pin=common._pin(archives[name]),current_pin=common._pin(current_modules[name].__file__)))
    evidence=dict(scope=SCOPE,status='compatible_for_finish_definition',native_called=False,historical_code_executed=False,
        parent_receipt_pin=pin,source_pin=dict(path=r['source_path'],sha256=r['saved_source_sha256']),
        verifier_pin=common._pin(__file__),regression_pin=deepcopy(regression_pin),replacements=rows)
    checked_lists(r,validate_evidence(evidence,r,pin))
    target=Path(output_path)
    protected={common._key(x['path']) for role in ('live_pins','offline_proof_pins','bootstrap_export_pins') for x in r[role]}
    protected.update(common._key(x['path']) for x in [pin,evidence['source_pin'],evidence['verifier_pin'],regression_pin])
    protected.update(common._key(row[k]['path']) for row in rows for k in ('archive_pin','current_pin'))
    require(target.is_absolute() and target.parent.is_dir() and not target.exists() and not target.is_symlink()
        and common._key(target) not in protected,'Fresh distinct compatibility receipt required')
    parent._write_receipt(target,evidence,create=True)
    return common._pin(target)
