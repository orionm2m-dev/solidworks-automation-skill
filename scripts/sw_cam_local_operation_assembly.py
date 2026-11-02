"""Compose the checked local group in one retained native session.

The caller owns request/source/pin/lock validation and supplies the completed
serial-tool context plus the reviewed full-feature verifier. No arbitrary module
name is read from user JSON, and no fresh native process is started here.
"""
from functools import partial
from scripts import sw_cam_local_operation_group as engine
from scripts import sw_cam_local_operation_native as native
from scripts import sw_cam_local_operation_context as context
from scripts import sw_cam_local_operation_recipe as recipe_hooks
from scripts import sw_cam_local_operation_nc as nc
from scripts import sw_cam_local_operation_cl as cl
from scripts.sw_cam_rough_firstcut import require


def hooks():
    return engine.Hooks(recipe_hooks.verify_assignment,
        partial(recipe_hooks.configure_selected,configure_nc=nc.configure_nc),
        recipe_hooks.verify_configured,cl.verify_saved)


def compile_in_session(backend,loaded,*,verified_context,recipe,choices,feed_policy,verify_feature):
    ids=[v['header']['native_id']for v in loaded['root_pocket_full_features']]
    observed=backend.observe_default_catalogues(ids)
    compiled=context.project_context(verified_context,recipe,observed,choices,
        verify_feature=verify_feature,feed_policy=feed_policy)
    require(engine.group.exact(compiled['guide_parameters']['expected_parameters'],backend.baseline),'Fresh catalogue cannot alter saved authority')
    loaded['local_plan']=compiled['local_plan']
    return loaded['local_plan']


def make_backend(loaded,args,sw,clsid,typelib,report,persist):
    return native.NativeBackend(loaded,args,sw,clsid,typelib,report,persist,
        before_generate=nc.before_generate,exporter=cl.export_saved)


class Journal(native.writer.Journal):
    def _marker_state(self):
        value=super()._marker_state();value['scope']=engine.SCOPE;return value
