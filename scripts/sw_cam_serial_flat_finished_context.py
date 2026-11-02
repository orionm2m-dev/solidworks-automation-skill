"""Provide a completed mixed-pocket state to the shared serial-tool creator.

No native backend is implemented here. Historical holder/catalogue carriers are
joined to a fully read-back current inventory only after both authorities pass.
"""
from copy import deepcopy
from pathlib import Path
from scripts import sw_cam_serial_flat_tool as serial
from scripts import sw_cam_mixed_root_finish as mixed
from scripts import sw_cam_profile_sketch as cad_core
from scripts import sw_cam_long_cut_reconciliation as reconciliation
from scripts.sw_cam_rough_firstcut import require

common, group, prior = serial.common, serial.group, serial.prior
ACTION = 'create_serial_flat_tool_after_mixed_pockets'
PROOF_ONLY = {'sw_cam_long_cut_cutter_geometry.py',
              'sw_cam_guide_group_definitions.py', 'sw_cam_ud14_qualification.py'}


def same(left, right, message):
    require(group.exact(left, right), message)


def project_context(creation, current):
    """Pure projection; arguments must already pass their complete loaders."""
    source = creation['checkpoint']['context']
    out = deepcopy(source)
    state = out['state']
    snapshot = current['guide_parameters']['expected_parameters']
    binding = snapshot['binding']
    serial.deep.cl.contract(binding)
    require(len(binding['operations']) == 17 and len(snapshot['parameters']) == 8,
            'Complete current seventeen/eight snapshot required')
    same(state['operations'][:13], binding['operations'][:13], 'Protected thirteen operations changed')
    same(state['operation_setups'], binding['operation_setups'], 'Operation setups changed')
    same(source['ownership'], current['ownership'], 'Historical and current owner differ')
    catalogue = deepcopy(creation['final_observation']['tools'])
    same(catalogue, source['long_cut_tool_checkpoint']['catalogue'], 'Historical catalogue proof differs')
    ids = [row['native_id'] for row in catalogue]
    require(len(ids) == len(set(ids)) == 20, 'Complete twenty-tool catalogue required')
    same(ids, current['tool_catalogue_ids'], 'Current saved catalogue differs')
    old_rows = state['features']
    old_by_id = {row['geometry']['native_id']: row for row in old_rows}
    require(len(old_by_id) == len(old_rows), 'Duplicate historical feature')
    inventory = current['root_pocket_native_inventory']
    observed_ids = [row['header']['native_id'] for row in inventory]
    require(len(observed_ids) == len(set(observed_ids)), 'Duplicate actual current feature')
    full = current['root_pocket_full_features']
    require(len(full) == 2, 'Exactly two full native added features required')
    new_ids = [row['header']['native_id'] for row in full]
    require(len(set(new_ids)) == 2 and not set(new_ids).intersection(old_by_id),
            'Two independent new actual features required')
    require(set(observed_ids) == set(old_by_id).union(new_ids), 'Exact additive native feature inventory required')
    old_order = [row['header']['native_id'] for row in inventory if row['header']['native_id'] in old_by_id]
    same(old_order, list(old_by_id), 'Historical feature order changed')
    setup_ids = [row['native_id'] for row in state['feature_setups']]
    require(len(set(setup_ids)) == len(setup_ids), 'Unique actual setup identities required')
    counts = {ident: 0 for ident in setup_ids}
    projected = []
    for row in inventory:
        header, owner = row['header'], row['owner_setup_native_id']
        ident = header['native_id']
        require(owner in counts, 'Unverified feature setup')
        if ident in old_by_id:
            prior_row = old_by_id[ident]
            same(header, prior_row['geometry'], 'Historical native feature geometry changed')
            require(owner == prior_row['setup_native_id'], 'Historical feature owner changed')
        else:
            found = next(value for value in full if value['header']['native_id'] == ident)
            same(header, found['header'], 'New full/header observations differ')
            require(owner == found['owner_setup_native_id'], 'New full/header owner differs')
        projected.append(dict(setup_index=setup_ids.index(owner), feature_index=counts[owner],
                              setup_native_id=owner, geometry=deepcopy(header)))
        counts[owner] += 1
    cad = current['root_pocket_cad']
    require(cad['needs_save'] is False, 'Current CAD state must be saved')
    require(cad_core._same_bodies(state['sw_reference']['solids'], cad['solids']),
            'Historical solid-body geometry changed')
    state['features'] = projected
    for setup in state['feature_setups']:
        setup['feature_count'] = counts[setup['native_id']]
    state['sw_reference'] = dict(feature_tree=deepcopy(cad['features']), solids=deepcopy(cad['solids']))
    state.update(operations=deepcopy(binding['operations']), operation_count=17,
                 operation_setups=deepcopy(binding['operation_setups']),
                 operation_counts=[row['operation_count'] for row in binding['operation_setups']],
                 operation_setup_count=len(binding['operation_setups']),
                 document=deepcopy(current['guide_parameters']['document']),
                 saved_file_sha256=current['source_sha256'])
    require(state['document']['needs_save'] is False, 'Current document must be saved')
    out.update(source_sha256=current['source_sha256'], ownership=deepcopy(current['ownership']),
               deep_loaded=deepcopy(current), serial_flat_catalogue=catalogue,
               native_feature_inventory_verified=True,
               parent_pin=deepcopy(current['root_pocket_checkpoint_pin']),
               authority_kind='saved_two_native_mixed_pockets',
               current_feature_inventory_provenance=deepcopy(current['root_pocket_checkpoint_pin']))
    out['deep_loaded'].pop('tool_creation_context', None)
    out['deep_loaded'].pop('first_sketch_failure', None)  # Immutable source receipt remains a proof pin.
    out['deep_loaded'].pop('first_native_pocket_failure', None)
    out['deep_loaded'].pop('first_native_pocket_diagnostic', None)
    out['current_context_sha256'] = prior._digest(group.current_projection(out))
    return out


def partition_pins(live, proof):
    retired = [pin for pin in live if Path(pin['path']).name in PROOF_ONLY]
    require({Path(pin['path']).name for pin in retired} == PROOF_ONLY and len(retired) == 3,
            'Exact reviewed historical phase roles required')
    active = common._merge([pin for pin in live if Path(pin['path']).name not in PROOF_ONLY],
        [common._pin(serial.__file__), common._pin(serial.geometry.__file__)])
    require(len(active) == 63, 'Expected sixty-three native files before source guard')
    return active, common._merge(proof, retired), dict(live_count=len(active),
        retired_as_phase_proof=deepcopy(retired), shared_guard_limit=64, source_included_by_guard=True)


def prepare_provider(params, authority_pin):
    """Resolve historical carrier and current saved authority without COM."""
    require(type(authority_pin) is dict and set(authority_pin) == {'path', 'sha256'},
            'Exact historical authority pin required')
    creation, initial, verified_pin, authority = reconciliation.verified_terminal(
        authority_pin['path'], authority_pin['sha256'], check_current=False)
    same(verified_pin, authority_pin, 'Historical authority pin differs')
    current = mixed.load_completed(params['context_receipt_path'], params['context_receipt_sha256'], check_current=True)
    require(current['ownership']['process_id'] == params['process_id'], 'Current owned process differs')
    require(current['source_sha256'] == params['expected_source_sha256'], 'Current source hash differs')
    require(common._key(current['guide_parameters']['document']['path']) == common._key(params['expected_document_path']),
            'Current document path differs')
    require(current['guide_parameters']['configuration']['sw_configuration_name']==params['expected_configuration'], 'Current configuration differs')
    loaded = project_context(creation, current)
    proof = common._merge(creation['offline_proof_pins'], current['checkpoint_pins'], current['pins'],
        [verified_pin, current['root_pocket_checkpoint_pin'], common._pin(__file__), common._pin(mixed.__file__),
         common._pin(reconciliation.__file__), creation['marker_pin'], creation['loaded_context_pin']])
    loaded['pins'], loaded['offline_export_proof_pins'], loaded['native_pin_partition'] = partition_pins(creation['live_pins'], proof)
    common._check(loaded['pins']); common._check(loaded['offline_export_proof_pins'])
    common._check(loaded['bootstrap_export_pins'])
    registration = deepcopy(current['root_pocket_registration'])
    same(registration, source_registration(creation), 'Historical/current registration differs')
    actual = common.discover_export_registration(loaded, registration['clsid'])
    same(actual, registration, 'Installed native registration differs')
    typelib = str(Path(actual['addin_path']).parent / 'camworks.tlb')
    require(common._pin(typelib) in loaded['pins'], 'Verified installed type library required')
    serial.existing.factory.audit_interfaces(typelib, loaded['generated_pin'])
    return dict(loaded=loaded, registration=actual, typelib=typelib,
                interface_audit=dict(scope='MIXED_POCKET_SERIAL_TOOL_CONTEXT_V1', native_calls=0,
                    current_authority_pin=deepcopy(current['root_pocket_checkpoint_pin']),
                    historical_authority_pin=verified_pin, native_feature_inventory_verified=True,
                    full_native_added_feature_count=2, catalogue_native_read_repeated_before_creation=True),
                provider_pin=common._pin(__file__))


def source_registration(creation):
    return creation['checkpoint']['context']['long_cut_tool_checkpoint']['registration']


def dispatch_request(request, *, validate_only=False):
    require(type(request) is dict and set(request) == {'action', 'params', 'authority'}
            and request['action'] == ACTION, 'Only sealed mixed-context serial-tool request allowed')
    authority = request['authority']
    require(type(authority) is dict and set(authority) == {'creation_receipt_path', 'creation_receipt_sha256', 'provider_sha256'},
            'Exact provider authority fields required')
    require(authority['provider_sha256'] == prior._file_hash(__file__), 'Exact provider implementation required')
    pin = dict(path=authority['creation_receipt_path'], sha256=authority['creation_receipt_sha256'])
    return serial.dispatch_request(dict(action='create_serial_flat_tool', params=deepcopy(request['params'])),
        validate_only=validate_only, context_provider=lambda params: prepare_provider(params, pin))
