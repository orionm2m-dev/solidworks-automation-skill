"""Pinned compact scope for one shared tapered-cutter configuration."""
from copy import deepcopy
from scripts.sw_cam_mill_saved_plan_tools import load_saved_plan_tools_evidence
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_stock_export_evidence import _require
from scripts.sw_cam_mill_inventory import _same_inventory
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_shared_cutter_geometry import KEYS,close,validate_target

SCOPE='MILL_SAVED_SHARED_CUTTER_CONFIG_V1'


class CutterEvidence:
    def __init__(self,base,report,pin,nominal,npin,target):
        self.base=base;self.tools=deepcopy(report);self.nominal=deepcopy(nominal)
        self.tool_pin=deepcopy(pin);self.nominal_pin=deepcopy(npin)
        self.pins=deepcopy(base.pins)+[self.tool_pin,self.nominal_pin]
        self.selected=deepcopy(base.selected);self.target=dict(target)
        self.full=deepcopy(report['before_tool_details']['items'][0]['full_tool'])
    def check_files(self):
        self.base.check_files()
        for pin in (self.tool_pin,self.nominal_pin):
            _,current=read_pin(pin['path'],pin['sha256'])
            _require(current==pin,'Pinned tool or nominal recipe receipt changed')
    def check_runtime_identity(self):
        if hasattr(self.base,'check_runtime_identity'):
            self.base.check_runtime_identity()
    def read_stock(self,*args):return self.base.read_stock(*args)
    def verify_before(self,state,details):
        self.base.verify(state)
        _require(details==self.tools['before_tool_details'],'Full shared tool/holder baseline changed')
    def verify_after_context(self,state):
        normalized=deepcopy(state)
        _require(type(normalized['document']['needs_save']) is bool,'Strict dirty state required')
        normalized['document']['needs_save']=self.base.state['document']['needs_save']
        seen=[]
        for row in normalized['operations']:
            if row['assigned_tool']['native_id']==self.base.tool_id:
                seen.append(row['native_id'])
                _require(close(row['assigned_tool']['cut_diameter_native'],self.target['CutDiameter'])
                    and close(row['assigned_tool']['protrusion_native'],self.target['Protrusion']),
                    'Shared generic tool delta differs')
                old=next(x for x in self.base.state['operations'] if x['native_id']==row['native_id'])
                row['assigned_tool']['cut_diameter_native']=old['assigned_tool']['cut_diameter_native']
                row['assigned_tool']['protrusion_native']=old['assigned_tool']['protrusion_native']
        _require(seen==self.base.operation_ids,'Shared tool use changed')
        self.base.verify(normalized)
    def summary(self):
        return dict(scope=SCOPE,saved_plan=self.base.summary(),tool_inspection=self.tool_pin,
            nominal_geometry=self.nominal_pin,target_geometry=self.target,
            native_units_qualified=False,physical_holder_qualified=False,production_qualified=False)


def load_cutter_evidence(*,saved_plan_receipt_path,saved_plan_receipt_sha256,
        tools_receipt_path,tools_receipt_sha256,nominal_geometry_receipt_path,
        nominal_geometry_receipt_sha256,target_geometry,**binding):
    target=validate_target(target_geometry)
    rebind={k:binding.pop(k,None) for k in ('session_rebind_receipt_path','session_rebind_receipt_sha256')}
    if any(v is not None for v in rebind.values()):
        _require(all(type(v) is str and v for v in rebind.values()),'Complete explicit session rebind pair required')
    else:rebind={}
    base=load_saved_plan_tools_evidence(saved_plan_receipt_path,saved_plan_receipt_sha256,**binding,**rebind)
    historical_pid=getattr(base,'historical_process_id',binding['process_id'])
    historical_summary=getattr(base,'historical_summary',base.summary)()
    data,pin=read_pin(tools_receipt_path,tools_receipt_sha256)
    _require(data.get('scope')=='MILL_SAVED_PLAN_TOOLS_V1' and data.get('status')=='review_required'
        and data.get('phase')=='finished','Completed assigned-tool inspection required')
    for key in ('read_only','readback_verified','tools_readback_verified',
                'tool_geometry_read_complete','tool_profile_complete'):
        _require(data.get(key) is True,'Incomplete assigned-tool evidence: '+key)
    for key in ('mutation_attempted','AFR_attempted','GOP_attempted','GTP_attempted','model_saved',
                'save_attempted','tool_assignment_attempted','stock_edit_attempted',
                'material_edit_attempted','TechDB_write_attempted','post_cleanup_CAM_getters',
                'production_qualified'):
        _require(data.get(key) is False,'Unexpected tool inspection field: '+key)
    _require(not any(k in data for k in ('issue','failed_phase','receipt_write_error')),
             'Tool inspection contains failure')
    _require(type(data.get('process_id')) is int and data['process_id']==historical_pid
        and data.get('saved_file_sha256')==binding['expected_source_sha256'],'Tool inspection identity differs')
    clean_events(data)
    _require(data.get('anchor')==historical_summary,'Tool inspection saved-plan provenance differs')
    base.verify(data['before']);base.verify(data['after'])
    _require(_same_inventory(data['before'],data['after'])
        and data.get('state_sha256')==_digest(data['before']),'Tool context digest differs')
    details=data['before_tool_details']
    _require(details==data['after_tool_details'] and data.get('tool_details_sha256')==_digest(details),
             'Tool details are not stable and digest-bound')
    _require(details.get('metadata_read_complete') is True and details.get('profile_complete') is True
        and details.get('generic_operation_context_unchanged') is True
        and details.get('canonical_state_changed') is False,'Complete unmodified tool details required')
    items=details['items']
    _require([x['operation_native_id'] for x in items]==base.operation_ids,'Exact shared operation order required')
    full=items[0]['full_tool']
    _require(all(x.get('tool_metadata_complete') is True and x.get('status')=='observed'
        and x['full_tool']==full for x in items),'All shared users require equal complete tools')
    _require(full['tool_native_id']==base.tool_id and full['geometry_read_complete'] is True
        and full['profile_complete'] is True and full['tool_type_raw']==1
        and full['mill_tool']['type_raw']==1 and full['mill_tool']['subtype_raw']==3
        and full['mill_tool']['end_radius_native']==0.0,
        'Retained nominal flat-end BOTH classification/R0 required')
    nominal,npin=read_pin(nominal_geometry_receipt_path,nominal_geometry_receipt_sha256)
    _require(nominal.get('status')=='PRIMARY_DOCUMENTED_COHERENT_CUTTER_MAPPING_CANDIDATE_NOT_NATIVE_APPLIED',
             'Reviewed coherent nominal geometry mapping required')
    model=nominal['complete_nominal_cutter_candidate']
    _require(all(close(target[k],model[k]) for k in KEYS if k!='Protrusion'),
             'Target differs from pinned complete nominal geometry')
    _require(close(model['EndRadius'],0) and model['MillToolType']==1 and model['MillToolSubType']==3,
             'Nominal protected classification differs')
    _require(nominal['limits']['production_qualified'] is False,'Nominal review cannot claim production qualification')
    result=CutterEvidence(base,data,pin,nominal,npin,target);result.check_files();return result
