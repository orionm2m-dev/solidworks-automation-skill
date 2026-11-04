"""当前保存参数批次的固定字段契约、类型化原语与已捕获增量验证。"""
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
import math
from scripts import sw_cam_guide_group_configuration as legacy
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam import _member

NATIVE_QUALIFICATION_COMPLETE=False

@dataclass(frozen=True)
class Field:
    name:str
    getter:str
    setter:str
    mode:str
    value_kind:str
    get_dispid:int
    set_dispid:int
    area:str
    alias:str|None=None

FIELDS=MappingProxyType({x.name:x for x in (
    Field('entry_type','GetEntryExitType','SetEntryExitType','feature','long',58,88,'entry'),
    Field('spiral_radius','GetSpiralRadius','SetSpiralRadius','feature','double',61,90,'entry'),
    Field('spiral_pitch','GetSpiralPitch','SetSpiralPitch','feature','double',62,91,'entry'),
    Field('first_depth','GetStartDepth','SetStartDepth','pair','pair',81,82,'depth','FirstDepthAmt'),
    Field('subsequent_depth','GetSubsequentDepthAmount','SetSubsequentDepthAmount','pair','pair',83,84,'depth','SbsqDepthAmt'),
    Field('side_allowance','SideAllow','SideAllow','property','double',19,19,'boundary'),
    Field('floor_allowance','GetZAllowance','SetZAllowance','scalar','double',51,52,'boundary'),
    Field('side_step','GetStepOver','SetStepover','pair','pair',20,21,'boundary'))})


def require(value,message):
    if not value:raise ValueError(message)


def equal(a,b):
    if type(a) is not type(b):return False
    if type(a) is dict:return set(a)==set(b) and all(equal(a[k],b[k]) for k in a)
    if type(a) is list:return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b


def checked_value(spec,value):
    """仅验证原始类型/有界数值；不赋予单位、枚举物理含义或加工合格性。"""
    if spec.value_kind=='long':require(type(value) is int and 0<=value<=4,'Explicit supported raw entry enum required')
    elif spec.value_kind=='pair':
        require(type(value) is list and len(value)==2 and type(value[0]) is bool,'Exact BOOL/DOUBLE pair required')
        require(type(value[1]) is float and math.isfinite(value[1]) and 0<=value[1]<=100000,'Finite bounded raw double required')
    else:require(type(value) is float and math.isfinite(value) and 0<=value<=100000,'Finite bounded raw double required')
    return deepcopy(value)


def validate_recipe(recipe):
    require(type(recipe) is dict and set(recipe)=={'schema_version','rows'} and type(recipe['schema_version']) is int and recipe['schema_version']==1,'Exact versioned recipe required')
    require(type(recipe['rows']) is list and 1<=len(recipe['rows'])<=8,'Bounded explicit operation rows required')
    seen=set()
    for row in recipe['rows']:
        require(type(row) is dict and set(row)=={'operation_native_id','feature_native_id','operation_type','expected_tool_native_id','existing_tool_native_id','fields'},'Exact row keys required; arbitrary COM members forbidden')
        for name in ('operation_native_id','feature_native_id','expected_tool_native_id'):
            require(type(row[name]) is int and 0<row[name]<2**32,'Strict positive native identity required')
        require(row['operation_native_id'] not in seen,'Duplicate operation row');seen.add(row['operation_native_id'])
        require(type(row['operation_type']) is int and row['operation_type']==0,'Initial allowlist supports rough0 only')
        tool=row['existing_tool_native_id'];require(tool is None or type(tool) is int and 0<tool<2**32,'Optional existing tool native ID must be strict')
        require(type(row['fields']) is list and len(row['fields'])<=8,'At most eight explicit fields per operation')
        require(tool is not None or row['fields'],'At least one explicit requested change required')
        fields=set()
        for change in row['fields']:
            require(type(change) is dict and set(change)=={'field','expected','new'},'Exact expected/new field request required')
            key=change['field'];require(type(key) is str and key in FIELDS and key not in fields,'Unknown or duplicate fixed field');fields.add(key)
            checked_value(FIELDS[key],change['expected']);checked_value(FIELDS[key],change['new'])
    return deepcopy(recipe)


def parameter_row(state,oid):
    rows=[r for r in state['operation_parameters'] if r['operation_native_id']==oid]
    require(len(rows)==1 and rows[0]['read_complete'] is True,'Complete uniquely observed parameter target required')
    return rows[0]


def field_value(row,key):
    spec=FIELDS[key]
    legacy_spec=next(x for x in legacy.ROUGH_FIELDS if x[0]==key)
    require(legacy_spec==(''+spec.name,'ICWRghMillOp',spec.getter,spec.setter,spec.mode),'Existing reviewed field mapping differs')
    return legacy.field_value(row,legacy_spec)


def compile_plan(state,recipe):
    plan=validate_recipe(recipe)
    require(state.get('parameter_capture_complete') is True and type(state['document']['needs_save']) is bool,'Complete current observation and actual host flag required')
    for row in plan['rows']:
        oid=row['operation_native_id'];actual=parameter_row(state,oid);ops=[r for r in state['operations'] if r['native_id']==oid]
        require(len(ops)==1,'Unique route membership required');op=ops[0]
        require(actual['operation_type']==row['operation_type'] and actual['feature_native_id']==row['feature_native_id'] and op['linked_feature_ids']==[row['feature_native_id']] and op['suppressed'] is False and op['toolpath_generated'] is False and op['toolpath_record_counts']==[],'Exact ungenerated selected operation required')
        require(op['assigned_tool']['native_id']==actual['tool']['generic']['native_id']==row['expected_tool_native_id'],'Expected own tool changed')
        for change in row['fields']:require(equal(field_value(actual,change['field']),change['expected']),'Expected field differs: '+change['field'])
    return plan


def _normal_document(state):
    result=deepcopy(state)
    require(type(result['document']['needs_save']) is bool,'Actual Boolean host flag required')
    result['document']['needs_save']=None
    return result


def _replace_observed(row,area,member,value):
    """Build only the exact existing decoder/diagnostic representation of one value."""
    from scripts import sw_cam_rough_entry_parameters as decoder
    kinds=dict(decoder.ENTRY_FIELDS+decoder.DEPTH_FIELDS+decoder.BOUNDARY_FIELDS+decoder.NC_FIELDS)
    require(member in kinds,'Existing fixed decoder required')
    old=row['rough'][area][member];kind=kinds[member]
    require(equal(old,decoder.decode_parameter(old['raw'],kind)),'Complete actual decoded parameter shape required')
    diagnostic=row['rough_diagnostic'];require(diagnostic['read_complete'] is True,'Complete actual rough diagnostic required')
    matches=[r for r in diagnostic['observations'] if r['member']==member]
    require(len(matches)==1,'One exact diagnostic observation required');observed=matches[0]
    require(all(observed.get(k) is True for k in ('attempted','returned','validated')) and equal(observed['value'],old),'Diagnostic value differs from actual parameter')
    def native_shape(raw):
        if type(raw) is list:
            require(observed['returned_type'] in ('tuple','list'),'Actual native pair return shape required')
            return tuple(raw) if observed['returned_type']=='tuple' else list(raw)
        require(type(raw).__name__==observed['returned_type'],'Actual scalar return type differs')
        return raw
    require(equal(observed['raw_observation'],decoder.bounded_raw_observation(native_shape(old['raw']))),'Actual diagnostic raw shape differs')
    updated=decoder.decode_parameter(value,kind)
    row['rough'][area][member]=updated
    observed['value']=deepcopy(updated)
    observed['raw_observation']=decoder.bounded_raw_observation(native_shape(value))


def expected_field_state(before,row,change):
    spec=FIELDS[change['field']];checked_value(spec,change['expected']);checked_value(spec,change['new'])
    expected=deepcopy(before);actual=parameter_row(expected,row['operation_native_id'])
    require(equal(field_value(actual,spec.name),change['expected']),'Expected captured field differs')
    if spec.alias:
        require(equal(actual['rough'][spec.area][spec.alias]['raw'],change['expected'][1]),'Established depth alias differs before change')
    _replace_observed(actual,spec.area,spec.getter,change['new'])
    if spec.alias:_replace_observed(actual,spec.area,spec.alias,change['new'][1])
    return expected


def _derived_tool_usage(state):
    batch=state['parameter_batch'];candidate_id=batch['candidate_tool']['generic']['native_id']
    sources={str(r['tool']['generic']['native_id']):deepcopy(r['tool']) for r in state['operation_parameters']}
    ids=[r['native_id'] for r in state['operations'] if r['assigned_tool']['native_id']==candidate_id]
    return sources,ids


def expected_assignment_state(before,row,candidate):
    expected=deepcopy(before);batch=expected['parameter_batch']
    require(batch.get('read_complete') is True and equal(batch['candidate_tool'],candidate),'Fresh complete exact candidate capture required')
    sources,ids=_derived_tool_usage(expected)
    require(equal(batch['source_tools'],sources) and equal(batch['candidate_consumer_ids'],ids) and set(batch['candidate_consumers'])=={str(i) for i in ids},'Actual source/consumer derivation differs')
    oid=row['operation_native_id'];actual=parameter_row(expected,oid);op=next(x for x in expected['operations'] if x['native_id']==oid)
    require(row['existing_tool_native_id']==candidate['generic']['native_id'] and actual['tool']['generic']['native_id']==op['assigned_tool']['native_id']==row['expected_tool_native_id'],'Exact requested source/candidate tool required')
    actual['tool']=deepcopy(candidate);op['assigned_tool']=deepcopy(candidate['generic'])
    sources,ids=_derived_tool_usage(expected);batch['source_tools']=sources;batch['candidate_consumer_ids']=ids
    consumers={}
    for consumer in ids:
        key=str(consumer)
        if key in batch['candidate_consumers']:consumers[key]=deepcopy(batch['candidate_consumers'][key])
        else:
            require(consumer==oid and key in batch['target_nc'],'Only selected target may become a new candidate consumer')
            nc=batch['target_nc'][key];require(nc.get('read_complete') is True and nc.get('operation_native_id')==oid,'Complete existing own target NC required')
            consumers[key]=dict(deepcopy(nc),assigned_tool_native_id=candidate['generic']['native_id'])
    batch['candidate_consumers']=consumers
    return expected


def projection(state,rows,*,allow_tool):
    """Legacy callable retained only as an exact-state view, never a permissive mask."""
    return _normal_document(state)


def verify_assignment_delta(before,after,row,candidate):
    expected=expected_assignment_state(before,row,candidate)
    require(equal(_normal_document(expected),_normal_document(after)),'SetTool changed unrequested captured fields, NC, levels, catalogue or unselected operations')


def verify_field_delta(before,after,row,change):
    expected=expected_field_state(before,row,change)
    require(equal(_normal_document(expected),_normal_document(after)),'Setter changed unrequested captured state or exact requested readback differs')


def verify_final(before,after,plan,candidates):
    expected=deepcopy(before)
    for row in plan['rows']:
        if row['existing_tool_native_id'] is not None:expected=expected_assignment_state(expected,row,candidates[row['existing_tool_native_id']])
        for change in row['fields']:expected=expected_field_state(expected,row,change)
    require(equal(_normal_document(expected),_normal_document(after)),'Final batch changed protected captured fields or exact requested targets differ')


def preflight(tlb):
    """实际 bridge registry 和生成元数据；必须在任何变更前调用。"""
    from ctypes import HRESULT,POINTER,c_long,c_double
    from ctypes.wintypes import VARIANT_BOOL
    from comtypes.automation import IDispatch
    from scripts.sw_cam_comtypes import _interface_class
    for name in ('ICWRghMillOp','ICWOperation','ICWMillOperation','ICWTool','ICWPartDoc','ICWMachine','ICWToolcrib4','ICWDispatchCollection','ICWNCParam','ICWNCParam2'):_interface_class(name,tlb)
    cls=_interface_class('ICWRghMillOp',tlb)
    require(str(cls._iid_).upper()=='{4EDDCA80-325A-11D6-A9A7-00062999E55F}','Exact rough IID required')
    for spec in FIELDS.values():
        scalar=c_long if spec.value_kind=='long' else c_double
        getter='_get_'+spec.getter if spec.mode=='property' else spec.getter
        setter='_set_'+spec.setter if spec.mode=='property' else spec.setter
        getargs=(POINTER(VARIANT_BOOL),POINTER(c_double)) if spec.mode=='pair' else ((POINTER(IDispatch),POINTER(scalar)) if spec.mode=='feature' else (POINTER(scalar),))
        setargs=(VARIANT_BOOL,c_double) if spec.mode=='pair' else ((POINTER(IDispatch),scalar) if spec.mode=='feature' else (scalar,))
        getdirs=(2,2) if spec.mode=='pair' else ((1,10) if spec.mode=='feature' else (10,))
        for name,dispid,args,dirs,flags in ((getter,spec.get_dispid,getargs,getdirs,{'propget'} if spec.mode=='property' else set()),(setter,spec.set_dispid,setargs,(1,)*len(setargs),{'propput'} if spec.mode=='property' else set())):
            methods=[x for x in cls._methods_ if x.name==name];require(len(methods)==1,'Unique fixed method required');method=methods[0]
            require(method.restype is HRESULT and method.idlflags[0]==dispid and method.argtypes==args and tuple(p[0] for p in method.paramflags)==dirs and set(method.idlflags)&{'propget','propput','propputref'}==flags,'Fixed field ABI changed')
    nc_specs=(('ICWMillOperation','IGetNCParam',7,POINTER(POINTER(IDispatch)),False),
        ('ICWNCParam','GetSpndlSpeed',7,POINTER(c_double),False),
        ('ICWNCParam','GetTlpComp',17,POINTER(c_long),False),
        ('ICWNCParam','GetCNCComp',19,POINTER(c_long),False),
        ('ICWNCParam2','_get_XYFeed',23,POINTER(c_double),True))
    for interface,name,dispid,result_type,is_property in nc_specs:
        owner=_interface_class(interface,tlb);methods=[x for x in owner._methods_ if x.name==name]
        require(len(methods)==1,'One exact own NC getter required');method=methods[0]
        require(method.restype is HRESULT and method.idlflags[0]==dispid and method.argtypes==(result_type,) and tuple(p[0] for p in method.paramflags)==(10,) and set(method.idlflags)&{'propget','propput','propputref'}==({'propget'} if is_property else set()),'Exact operation-owned NC getter ABI required')
    mill=_interface_class('ICWMillOperation',tlb);method=next(x for x in mill._methods_ if x.name=='SetTool')
    require(method.restype is HRESULT and method.idlflags[0]==8 and method.argtypes==(POINTER(IDispatch),) and tuple(p[0] for p in method.paramflags)==(1,),'Exact SetTool ABI required')


def target(guard,doc,row):
    found=guard.read(doc,'GetCWObjectFromID',3,row['operation_native_id']);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact operation lookup required')
    op=guard.typed(found[0],'ICWOperation');mill=guard.typed(found[0],'ICWMillOperation')
    require(_object_id(doc,op,guard.read)==row['operation_native_id'] and guard.read(mill,'OpernType')==0 and guard.read(op,'Suppressed') is False and guard.read(op,'GetIsToolpathGenerated') is False,'Exact ungenerated own rough operation required')
    links=_items(guard.read(op,'IGetAllFeatures'),guard.typed,guard.read,2)
    require([_object_id(doc,x,guard.read) for x in links]==[row['feature_native_id']],'Exact feature link required')
    found=guard.read(doc,'GetCWObjectFromID',1,row['feature_native_id']);require(type(found) in (tuple,list) and len(found)==2 and found[1] is True and _object_id(doc,found[0],guard.read)==row['feature_native_id'],'Exact selected feature lookup required')
    return op,found[0]


def write_field_once(ctx,doc,row,change,*,pending,returned):
    """复用现有模式；名字只来自固定表，返回证据先于 post-event 校验持久化。"""
    key=change['field'];require(key in FIELDS and callable(pending) and callable(returned),'Fixed field and durable callbacks required');spec=FIELDS[key]
    checked_value(spec,change['expected']);checked_value(spec,change['new'])
    with ctx.guard() as guard:
        op,feature=target(guard,doc,row);owner=guard.typed(op,'ICWRghMillOp')
        args=[]
        if spec.mode=='feature':
            from comtypes.automation import IDispatch
            args=[guard.read(feature,'QueryInterface',IDispatch)]
        observed=guard.read(owner,spec.getter,*args);observed=list(observed) if type(observed) is tuple else observed
        require(equal(observed,change['expected']),'Immediate expected field changed')
        def call():
            if spec.mode=='property':value=getattr(owner,'_ICWRghMillOp__com__set_'+spec.setter)(change['new'])
            else:value=_member(owner,spec.setter,*(args+([*change['new']] if spec.mode=='pair' else [change['new']])))
            returned(value)
            require(type(value) is int and value==0,'Strict zero HRESULT required; uncertain outcome preserved, no replay')
            return value
        return guard.dispatch_once(call,persist_pending=pending)
