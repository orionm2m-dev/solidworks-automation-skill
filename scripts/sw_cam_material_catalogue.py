"""Read-only native CAM workpiece catalogue; no SQL inference or assignments."""
from __future__ import annotations
from scripts.sw_cam import _member, _error, document_snapshot
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _file_hash
from scripts.sw_operation_guard import absolute_document_path, check_document_target


def _parse_catalogue(raw):
    if not isinstance(raw, (tuple, list)) or len(raw) != 5:
        raise ValueError('Expected four native arrays and material count')
    *arrays, count = raw
    if type(count) is not int or not 0 <= count <= 4096:
        raise ValueError('Material count exceeds bound')
    values=[]
    for column, array in enumerate(arrays):
        if count == 0 and array is None: array=[]
        if not isinstance(array, (tuple, list)) or len(array) != count:
            raise ValueError('Native material arrays/count mismatch')
        for value in array:
            if column in (0,2):
                if type(value) is not int or value < 0: raise ValueError('Invalid native material/group ID')
            elif not isinstance(value,str) or not value.strip() or len(value)>1024 or '\x00' in value:
                raise ValueError('Invalid native material/group name')
        values.append(list(array))
    if len(set(values[0])) != count: raise ValueError('Duplicate native material IDs')
    return [dict(material_id=values[0][i],material_name=values[1][i],group_id=values[2][i],group_name=values[3][i]) for i in range(count)]


def inspect_material_catalogue(sw, clsid, typelib_path, *, expected_document_path):
    """GetWorkpieceMaterials dispid65, explicit raw shapes; no material equivalence claim."""
    from scripts.sw_cam_events import CamMessageSession
    if not isinstance(expected_document_path,str) or not absolute_document_path(expected_document_path):
        raise ValueError('Exact saved document path required')
    report=dict(status='started',read_only=True,mutation_attempted=False,post_cleanup_CAM_getters=False,
                material_mapping_qualified=False,native_getter_units_qualified=False,may_continue=False)
    session=None
    try:
        before=document_snapshot(sw)
        if before is None or before.get('type')!=1 or before.get('needs_save'):
            raise ValueError('Clean saved part required')
        check_document_target(before['path'],before['title'],expected_path=expected_document_path,required=True)
        file_before=_file_hash(expected_document_path)
        addin=_member(sw,'GetAddInObject',clsid)
        if addin is None: raise ValueError('CAM add-in must already be loaded')
        app=_typed(_member(addin,'GetCWApp'),'ICWApp4',typelib_path)
        session=CamMessageSession(app,typelib_path)
        def check():
            state=session.summary()
            if (not state.get('subscribed') or not state.get('active') or state.get('event_count') or state.get('overflow')
                    or state.get('callback_errors') or state.get('callback_error_count') or state.get('subscription_error') or state.get('disconnect_errors')):
                raise ValueError('Native message/event transport: stop')
        def read(name):
            check();result=_member(app,name);check();return result
        with session:
            rows=_parse_catalogue(read('GetWorkpieceMaterials'))
            use_doc=read('GetUseDocumentUnit')
            if type(use_doc) is not bool:raise ValueError('Expected strict native document-unit flag')
            if rows!=_parse_catalogue(read('GetWorkpieceMaterials')):raise ValueError('Catalogue changed during read')
            report.update(materials=rows,material_count=len(rows),use_document_unit_raw=use_doc)
            check()
        state=session.summary()
        if (not state.get('disconnected') or state.get('active') or state.get('event_count') or state.get('overflow')
                or state.get('callback_errors') or state.get('callback_error_count') or state.get('subscription_error') or state.get('disconnect_errors')):
            raise ValueError('Event cleanup unconfirmed')
        if document_snapshot(sw)!=before or _file_hash(expected_document_path)!=file_before:
            raise ValueError('Document or saved file changed')
        report.update(status='ok',document=before,saved_file_sha256=file_before,
                      source_interface='ICWApp4.GetWorkpieceMaterials',native_names_verified=True,
                      limitation='Catalogue names are observed; alloy equivalence and Workpiece.Material setter mapping require separate qualification')
    except Exception as exc:report.update(status='error',issue=_error(exc))
    finally:
        if session is not None:report['messages']=session.summary()
    return report
