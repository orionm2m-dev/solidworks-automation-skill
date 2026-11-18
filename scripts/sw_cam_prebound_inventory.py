"""Staged prebound inventory extraction; not integrated or natively qualified.

The caller acquires doc and machine together from the same verified native CAM
context under the strong process/document/source/event guard. This function
accepts retained native roots, never a fake application or substitute getter.
All inventory observations after bootstrap preserve the parent implementation.
"""
from scripts import sw_cam_process_import as parent
require=parent.require
integer=parent.integer
_vector=parent._vector
_object_id=parent._object_id
_items=parent._items
read_generic_tool=parent.read_generic_tool

def capture_bound_inventory(doc, machine, guard, diagnostic, progress):
    """Generic bounded identities/links/flags/counts after import; no contour or CL record reads."""
    state = dict(capture_complete=False, feature_setups=[], features=[], operation_setups=[], operations=[])
    diagnostic.update(capture_complete=False, native_read_count=0, state=state)

    def read(obj, name, *args):
        diagnostic['native_read_count'] += 1
        require(diagnostic['native_read_count'] <= 4096, 'Imported inventory read limit')
        diagnostic['last_native_method'] = name
        value = guard.read(obj, name, *args)
        return value

    def typed(raw, name):
        require(raw is not None, 'Missing public ' + name)
        return guard.typed(raw, name)
    require(integer(read(doc, 'GetDocType'), 'CAM document type') == 1, 'Imported CAM part required')
    state['cam_configuration_name'] = read(doc, 'GetActiveConfigurationName')
    conf = typed(read(doc, 'GetActiveConfiguration'), 'ICWConfiguration')
    state['associated_sw_configuration'] = read(conf, 'SWConfigurationName')
    state['configuration_name'] = read(conf, 'ConfigurationName')
    require(type(state['cam_configuration_name']) is str and state['cam_configuration_name'] == state['configuration_name'], 'CAM configuration object mismatch')
    state['machine_type'] = integer(read(machine, 'MachType'), 'machine type')
    require(state['machine_type'] == 1, 'Imported archive must produce MILL')
    native_ids = set()
    feature_ids = set()
    tool_ids = set()

    def identity(raw):
        value = integer(_object_id(doc, raw, read), 'native ID', 1)
        require(value not in native_ids, 'Duplicate or cross-kind native identity')
        native_ids.add(value)
        return value
    for (si, raw) in enumerate(_items(read(machine, 'IGetEnumSetups'), typed, read, 8)):
        setup = typed(raw, 'ICWBaseSetup')
        sid = identity(setup)
        mill = typed(raw, 'ICWSetup')
        members = _items(read(setup, 'IGetEnumFeatures'), typed, read, 64 - len(state['features']))
        row = dict(index=si, native_id=sid, axis_native=_vector(read(setup, 'Axis')), origin_native=_vector(read(mill, 'GetReferencePosition')), feature_ids=[])
        state['feature_setups'].append(row)
        for (fi, item) in enumerate(members):
            feat = typed(item, 'ICWFeature')
            fid = identity(feat)
            feature_ids.add(fid)
            row['feature_ids'].append(fid)
            header = typed(item, 'ICWMillFeature')
            suppressed = read(feat, 'Suppressed')
            name = read(feat, 'FeatureName')
            require(type(suppressed) is bool and type(name) is str and (len(name) <= 1024), 'Bounded raw feature header required')
            state['features'].append(dict(setup_index=si, feature_index=fi, setup_native_id=sid, native_id=fid, volume_type=integer(read(header, 'VolumeType'), 'feature type'), subtype_raw=integer(read(header, 'SubType'), 'feature subtype'), name=name, suppressed=suppressed))
        progress(diagnostic)
    total_records = 0
    for (si, raw) in enumerate(_items(read(machine, 'IGetEnumOpSetups'), typed, read, 8)):
        setup = typed(raw, 'ICWBaseOpSetup')
        sid = identity(setup)
        members = _items(read(setup, 'IGetEnumOperations'), typed, read, 32 - len(state['operations']))
        state['operation_setups'].append(dict(index=si, native_id=sid, operation_count=len(members)))
        for (oi, item) in enumerate(members):
            op = typed(item, 'ICWOperation')
            mill = typed(item, 'ICWMillOperation')
            oid = identity(op)
            row = dict(setup_index=si, operation_index=oi, setup_native_id=sid, native_id=oid, mill_operation_type=integer(read(mill, 'OpernType'), 'MILL type'), base_operation_type=integer(read(op, 'OpernType'), 'base type'), suppressed=read(op, 'Suppressed'), toolpath_generated=read(op, 'GetIsToolpathGenerated'))
            state['operations'].append(row)
            require(type(row['suppressed']) is bool and type(row['toolpath_generated']) is bool, 'Strict imported flags required')
            links = [integer(_object_id(doc, x, read), 'linked feature ID', 1) for x in _items(read(op, 'IGetAllFeatures'), typed, read, 64)]
            require(len(links) == len(set(links)), 'Duplicate feature links')
            row['linked_feature_ids'] = links
            row['all_linked_features_observed'] = bool(links) and set(links) <= feature_ids
            counts = []
            for path in _items(read(op, 'IGetEnumToolpaths'), typed, read, 32):
                counts.append(integer(read(typed(path, 'ICWToolpath'), 'RecordCount'), 'record count', 0, 100000))
            total_records += sum(counts)
            require(total_records <= 100000, 'Imported aggregate record limit')
            row['toolpath_record_counts'] = counts
            (row['assigned_tool'], _) = read_generic_tool(item, doc, read, typed)
            tid = row['assigned_tool']['native_id']
            require(tid not in native_ids, 'Tool collides with definition identity')
            tool_ids.add(tid)
            require(len(tool_ids) <= 32, 'Imported tool bound')
            progress(diagnostic)
    require(not native_ids & tool_ids, 'Cross-kind native identity collision')
    state.update(feature_count=len(state['features']), operation_count=len(state['operations']), generated_operation_count=sum((x['toolpath_generated'] for x in state['operations'])), total_record_count=total_records, unique_tool_count=len(tool_ids), capture_complete=True, inventory_scope='bounded_generic_ids_setup_vectors_links_flags_path_counts_generic_tools', feature_association_verified=False, units_verified=False)
    diagnostic['capture_complete'] = True
    progress(diagnostic)
    return state
