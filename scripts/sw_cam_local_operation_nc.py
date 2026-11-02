"""Integrate the bounded raw microtool NC helper into the grouped journal."""
from copy import deepcopy
from scripts import sw_cam_root_microtool_nc as micro
from scripts.sw_cam_rough_firstcut import require

group=micro.group


def scope(backend):
    return dict(source_sha256=backend.args['expected_source_sha256'],process_id=backend.args['process_id'],
        protected_operation_ids=[r['native_id']for r in backend.baseline['binding']['operations']],
        targets=deepcopy(backend.learned),tool=deepcopy(backend.loaded['configuration_tool']))


def configure_nc(backend,journal,target,loaded):
    oid=target['operation_native_id'];actual=backend.read_nc(target)
    require(type(actual['GetTlpComp'])is int and actual['GetTlpComp']==1 and type(actual['GetCNCComp'])is int and actual['GetCNCComp']in(0,1),'Known CAM1/CNC0-or1 state required')
    if actual['GetCNCComp']==1:
        label='CNC0:'+str(oid);expected=dict(actual,GetCNCComp=0)
        journal.execute(label,lambda pending:backend.set_nc(target,actual,pending));backend.refresh_dirty()
        observed=backend.read_nc(target);require(group.exact(observed,expected),'CNC0 changed another NC field');journal.verified(label,observed)
    bounded=scope(backend);value=micro.read_fields(backend,target,bounded)
    for field,setter in (('GetSpndlSpeed',micro.set_spindle_once),('XYFeed',micro.set_xy_feed_once)):
        label=str(oid)+':NC:'+field
        if group.exact(value[field],micro.TARGET_VALUES[field]):
            journal.entry(label);journal.verified(label,dict(already_satisfied=True,value=value[field]));continue
        before=deepcopy(value)
        journal.execute(label,lambda pending,setter=setter,expected=before:setter(backend,target,bounded,expected,pending))
        backend.refresh_dirty();value=micro.read_fields(backend,target,bounded)
        evidence=micro.verify_readback(before,value,field);journal.verified(label,dict(readback=deepcopy(value),verification=evidence))
    verification=micro.verify_final(value)
    journal.report.setdefault('nc_readbacks',{})[str(oid)]=dict(values=deepcopy(value),verification=verification);journal.persist()


def before_generate(backend,target):
    actual=micro.read_fields(backend,target,scope(backend));micro.verify_final(actual)
    saved=backend.report['nc_readbacks'][str(target['operation_native_id'])]['values']
    require(group.exact(actual,saved),'NC changed after explicit readback and before GTP')
