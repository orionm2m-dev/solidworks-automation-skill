"""Bounded MILL route observation shared by selected read-only operations.

All operation identities and links are observed; only the selected operation gets
full tool/holder geometry. No GOP, GTP, setters, persistence or CL-record reads.
"""
from copy import deepcopy
import math
from scripts.sw_cam_mill_inventory import _items, capture_guarded_mill_inventory, _same_inventory
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool

MAX_SETUPS=8
MAX_FEATURES=64
MAX_OPERATIONS=32
MAX_RECORDS=100000


def integer(value,label,minimum=0,maximum=0xFFFFFFFF):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError('Strict bounded integer required: '+label)
    return value


def read_generic_tool(raw_operation,doc,read,typed):
    operation=typed(raw_operation,'ICWOperation')
    tool=typed(read(operation,'IGetTool'),'ICWTool')
    row=dict(native_id=integer(_object_id(doc,tool,read),'tool identity',1),
        is_mill_tool=read(tool,'IsMillTool'),native_read_complete=False,
        units_verified=False,holder_geometry_verified=False)
    if row['is_mill_tool'] is not True:
        raise ValueError('Assigned tool must explicitly be MILL')
    row['tool_type_raw']=integer(read(tool,'ToolType'),'ToolType')
    for key,name in (('cut_diameter_native','CutDiameter'),('protrusion_native','Protrusion')):
        value=read(tool,name)
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:
            raise ValueError('Finite nonnegative raw tool scalar required')
        row[key]=value
    if row['cut_diameter_native']<=0:
        raise ValueError('Positive raw tool diameter required')
    row['native_read_complete']=True
    return row,tool


def read_route_operations(state,native,read,typed,*,selected=None,diagnostic=None):
    """Read known typed vtable getters; preserve ordered sibling identities."""
    diagnostic={} if diagnostic is None else diagnostic
    diagnostic.update(operation_capture_complete=False,operations=[])
    features=[integer(r['geometry']['native_id'],'feature ID',1) for r in state['features']]
    feature_setups=[integer(r['native_id'],'feature setup ID',1) for r in state['feature_setups']]
    if (not 1<=len(features)<=MAX_FEATURES or not 1<=len(feature_setups)<=MAX_SETUPS
            or len(features)!=len(set(features)) or len(feature_setups)!=len(set(feature_setups))
            or set(features)&set(feature_setups)):
        raise ValueError('Bounded unique disjoint feature/setup identities required')
    known=set(features);protected=known|set(feature_setups)
    counts=state['operation_counts']
    if (type(counts) is not list or len(counts)>MAX_SETUPS
        or any(type(v) is not int or v<0 for v in counts) or sum(counts)>MAX_OPERATIONS):
        raise ValueError('Bounded operation counts required')
    setups=_items(read(native['machine'],'IGetEnumOpSetups'),typed,read,MAX_SETUPS)
    if len(setups)!=len(counts):
        raise ValueError('Operation setup count changed')
    state.update(operation_setups=[],operation_setup_count=len(setups),operations=[],
        operation_count=0,operation_inventory_scope='bounded_raw_id_links_flags_counts_and_generic_tool')
    op_ids=set();setup_ids=set();raw_ops={};tool_ids=set();total_records=0
    for si,raw_setup in enumerate(setups):
        setup=typed(raw_setup,'ICWBaseOpSetup')
        sid=integer(_object_id(native['doc'],setup,read),'operation setup ID',1)
        if sid in protected|setup_ids|op_ids|tool_ids:
            raise ValueError('Duplicate or cross-kind operation setup identity')
        setup_ids.add(sid)
        values=_items(read(setup,'IGetEnumOperations'),typed,read,MAX_OPERATIONS)
        if len(values)!=counts[si]:
            raise ValueError('Operation count changed')
        state['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(values)))
        for oi,raw in enumerate(values):
            operation=typed(raw,'ICWOperation');mill=typed(raw,'ICWMillOperation')
            oid=integer(_object_id(native['doc'],operation,read),'operation ID',1)
            if oid in protected|setup_ids|op_ids|tool_ids:
                raise ValueError('Duplicate or cross-kind operation identity')
            op_ids.add(oid);raw_ops[oid]=raw
            row=dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=oid)
            state['operations'].append(row);diagnostic['operations'].append(row)
            row['mill_operation_type']=integer(read(mill,'OpernType'),'MILL operation type')
            row['base_operation_type']=integer(read(operation,'OpernType'),'base operation type')
            row['suppressed']=read(operation,'Suppressed')
            row['toolpath_generated']=read(operation,'GetIsToolpathGenerated')
            if type(row['suppressed']) is not bool or type(row['toolpath_generated']) is not bool:
                raise ValueError('Strict operation flags required')
            links=[integer(_object_id(native['doc'],item,read),'linked feature ID',1)
                for item in _items(read(operation,'IGetAllFeatures'),typed,read,MAX_FEATURES)]
            if not links or len(set(links))!=len(links) or not set(links)<=known:
                raise ValueError('Nonempty unique links to captured features required')
            row['linked_feature_ids']=links
            records=[]
            for value in _items(read(operation,'IGetEnumToolpaths'),typed,read,32):
                path=typed(value,'ICWToolpath')
                records.append(integer(read(path,'RecordCount'),'record count',0,MAX_RECORDS))
            total_records+=sum(records)
            if total_records>MAX_RECORDS:raise ValueError('Aggregate path-record count bound exceeded')
            row['toolpath_record_counts']=records
            row['assigned_tool'],tool=read_generic_tool(raw,native['doc'],read,typed)
            tid=row['assigned_tool']['native_id']
            if tid in protected|setup_ids|op_ids:
                raise ValueError('Tool identity collides with captured object kind')
            tool_ids.add(tid)
            if selected is not None and oid==selected['operation_native_id']:
                if (links!=[selected['feature_native_id']] or
                    row['mill_operation_type']!=selected['mill_operation_type'] or row['suppressed'] is not False):
                    raise ValueError('Selected operation must be unsuppressed and link only to exact feature/type')
                detail={}
                diagnostic['selected_tool_geometry']=detail
                row['full_tool']=read_full_mill_tool(tool,generic=row['assigned_tool'],read=read,
                    typed=typed,diagnostic=detail)
    state['operation_count']=len(state['operations'])
    if state['operation_count']!=sum(counts):
        raise ValueError('Operation inventory changed')
    if selected is not None and sum(r['native_id']==selected['operation_native_id'] for r in state['operations'])!=1:
        raise ValueError('Exact selected operation not found')
    native['operations']=raw_ops
    diagnostic['operation_capture_complete']=True


def route_protected_state(state):
    """Remove exactly current-operation observations, never feature/stock evidence."""
    result=deepcopy(state)
    for key in ('operation_counts','operation_setups','operation_count','operation_setup_count',
                'operation_inventory_scope','operations'):
        result.pop(key,None)
    # Unsaved operation creation may dirty the document; source SHA remains pinned.
    if type(result['document'].get('needs_save')) is not bool:
        raise ValueError('Strict dirty flag required')
    result['document']['needs_save']=False
    return result


def verify_route_anchor(state,anchor):
    if not _same_inventory(route_protected_state(state),route_protected_state(anchor)):
        raise ValueError('Feature geometry, setup, stock, material, options, source or model differs from pinned inventory')
    return True


def capture_mill_route_state(sw,clsid,typelib_path,expected_path,*,process_id,expected_source_sha256,
        check,diagnostic,stock_reader=None,selected=None):
    """Use the existing file guards and full feature decoder; caller owns event scope."""
    handles={}
    def operations(state,native,read,typed):
        read_route_operations(state,native,read,typed,selected=selected,diagnostic=diagnostic)
        handles.update(native)
    args=dict(operation_reader=operations)
    if stock_reader is not None:args['stock_reader']=stock_reader
    state=capture_guarded_mill_inventory(sw,clsid,typelib_path,expected_path,process_id=process_id,
        expected_source_sha256=expected_source_sha256,check=check,diagnostic=diagnostic,**args)
    return state,handles
