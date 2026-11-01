"""Configure one fresh Finish from a pinned recipe, generate it once, save once.

An observed empty result is preserved as settings only. Existing operations,
feature geometry and cutter definitions remain protected. No global generation.
"""
from copy import deepcopy
from pathlib import Path
import json,math,re
import xml.etree.ElementTree as ET
from scripts import sw_cam_fresh_finish_insert as parent
from scripts import sw_cam_pocket_finish_apply as finish
from scripts import sw_cam_wall_apply_all as lead_scope
from scripts.sw_cam_finish_defaults_progress import CompactDefaultsMixin
from scripts.sw_cam import _member,_error
from scripts.sw_cam_thread import _file_hash,_object_id
from scripts.sw_cam_turn_tool import _digest
from scripts.sw_cam_generation import _write_receipt
from scripts.sw_cam_mill_selected_plan_evidence import read_pin,clean_events
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_rough_firstcut import require
common,group,insert=parent.common,parent.group,parent.insert
SCOPE='SAVED_FRESH_FINISH_RECIPE_V2'
# key, owner, getter, setter, mode; values are provided by the pinned recipe.
FIELDS=(
 ('side_allowance','ICWFinishMillOp','SideAllow','SideAllow','property'),
 ('final_side','ICWFinishMillOp','FinalSideCutAmt','FinalSideCutAmt','property'),
 ('spring_passes','ICWFinishMillOp','SpringPass','SpringPass','property'),
 ('first_depth','ICWFinishMillOp3','GetFirstDepthCut','SetFirstDepthCut','depth_pair'),
 ('max_depth','ICWFinishMillOp3','GetMaxDepthCut','SetMaxDepthCut','depth_pair'),
 ('final_depth','ICWFinishMillOp','FinalDepthCut','FinalDepthCut','property'),
 ('side_step','ICWFinishMillOp3','GetSideCutAmt','SetSideCutAmt','depth_pair'),
 ('previous_allowance','ICWFinishMillOp2','GetPreviousAllowance','SetPreviousAllowance','feature'),
 ('override_previous','ICWFinishMillOp','OverridePrevAllow','OverridePrevAllow','property'),
 ('perimeter','ICWFinishMillOp','PerimeterPassType','PerimeterPassType','property'),
 ('apply_all','ICWFinishMillOp3','LeadInOutApplyToAll','LeadInOutApplyToAll','property'),
 ('out_independent','lead_out','GetIsSameLeadinout','SetIsSameLeadinout','scalar'),
)+tuple((side+'_'+key,side,getter,setter,mode) for side in ('lead_in','lead_out')
 for key,getter,setter,mode in (
 ('angle','ArcAngle','ArcAngle','property'),('radius','GetArcRadius2','SetArcRadius2','pair'),
 ('straight','GetLeadAmt2','SetLeadAmt2','pair'),('overlap','GetLeadOverlap2','SetLeadOverlap2','pair')))
SCOPE_FIELDS=(('gouge_check','ICWFinishMillOp3','GougeCheck','GougeCheck','property'),('lead_in_type','lead_in','LeadType','LeadType','property'),('lead_out_type','lead_out','LeadType','LeadType','property'))
DEFAULT_FIELDS={'side_allowance':'SideAllow','final_side':'FinalSideCutAmt','spring_passes':'SpringPass',
 'first_depth':'FirstDepthCut','max_depth':'MaxDepthCut','final_depth':'FinalDepthCut','side_step':'SideCutAmt',
 'previous_allowance':'GetPreviousAllowance','override_previous':'OverridePrevAllow','perimeter':'PerimeterPassType'}
PARAMS={'process_id','expected_document_path','expected_source_sha256','addin_clsid','checkpoint_receipt_path',
 'checkpoint_receipt_sha256','source_operation_native_id','operation_native_id','feature_native_id','tool_native_id',
 'recipe_path','recipe_sha256','protected_receipt_path','protected_receipt_sha256','module_sha256','receipt_path'}
FORBIDDEN=('tool_creation_attempted','tool_edit_attempted','feature_edit_attempted','operation_creation_attempted',
 'operation_delete_attempted','move_attempted','global_generation_attempted','GOP_attempted','automatic_replay',
 'automatic_rollback','bottom_finish_setter_attempted','geometry_acceptance_complete','production_qualified')
ACTIONS={'SetTool','GenerateToolpath','SaveActiveDocument'}|{'field:'+s[0] for s in FIELDS}|{'scope:'+s[0] for s in SCOPE_FIELDS}


def validate_request(request):
    require(type(request) is dict and set(request)=={'action','params'} and request['action']=='configure_generate_fresh_finish','Exact fresh Finish action required')
    p=deepcopy(request['params']);require(type(p) is dict and set(p)==PARAMS,'Exact request fields required')
    for name in ('process_id','source_operation_native_id','operation_native_id','feature_native_id','tool_native_id'):
        require(type(p[name]) is int and 0<p[name]<2**31,'Strict positive identity required')
    for name,value in p.items():
        if name.endswith('_path'):require(type(value) is str and Path(value).is_absolute(),'Absolute path required')
        if name.endswith('_sha256'):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'Exact SHA256 required')
    require(p['module_sha256']==_file_hash(__file__),'Writer changed')
    require(type(p['addin_clsid']) is str and re.fullmatch(r'\{[0-9A-Fa-f-]{36}\}',p['addin_clsid']),'Exact CAM registration required');return p


def validate_recipe(recipe,p):
    require(set(recipe)=={'scope','binding','field_values','scope_values','bottom_finish','gouge_check','save_empty_result','maximum_gtp_calls','production_feeds_qualified'}
        and recipe['scope']=='FRESH_FINISH_WALL_RECIPE_V2','Exact bounded recipe required')
    require(recipe['binding']=={k:p[k] for k in ('source_operation_native_id','operation_native_id','feature_native_id','tool_native_id')},'Recipe binding differs')
    require(recipe['bottom_finish'] is False and recipe['gouge_check'] is True and recipe['save_empty_result'] is True
        and type(recipe['maximum_gtp_calls']) is int and recipe['maximum_gtp_calls']==1 and recipe['production_feeds_qualified'] is False,'Exact wall-only experiment required')
    require(group.exact(recipe['scope_values'],{'gouge_check':True,'lead_in_type':1,'lead_out_type':1}),'Explicit gouge check and arc leads required')
    values=recipe['field_values'];require(set(values)=={s[0] for s in FIELDS},'Complete bounded field recipe required')
    for spec in FIELDS:
        key,_,_,_,mode=spec;value=values[key]
        if mode in ('pair','depth_pair'):
            require(type(value) is list and len(value)==(3 if mode=='pair' else 2) and type(value[1]) is bool and value[1] is False,'Absolute length tuple required')
            scalar=[value[0]]+([value[2]] if mode=='pair' else [])
        elif key in ('spring_passes','perimeter'):
            require(type(value) is int and value>=0,'Strict count/enum required');scalar=[]
        elif key in ('override_previous','apply_all','out_independent'):
            require(type(value) is bool,'Strict Boolean recipe field required');scalar=[]
        else:scalar=[value]
        require(all(type(v) is float and math.isfinite(v) and 0<=v<=1000 for v in scalar),'Bounded positive native scalar required')
    require(values['side_allowance']==values['final_side']==values['final_depth']==0.
        and values['spring_passes']==0 and values['override_previous'] is True and values['apply_all'] is True
        and values['out_independent'] is False and values['perimeter']==2,'Reviewed wall finishing choices required')


def binding(loaded,p):
    authority=loaded['fresh_finish_definition'];rows=loaded['state']['operations']
    require(authority['native_id']==p['operation_native_id'] and authority['source_operation_native_id']==p['source_operation_native_id']
        and authority['feature_native_id']==p['feature_native_id'],'Saved fresh definition binding differs')
    target=next(r for r in rows if r['native_id']==p['operation_native_id']);source=next(r for r in rows if r['native_id']==p['source_operation_native_id'])
    require(target['native_id']!=source['native_id'] and rows[-1]['native_id']==target['native_id'],'Unique last fresh Finish required')
    for row in (source,target):
        require(row['mill_operation_type']==1 and row['linked_feature_ids']==[p['feature_native_id']] and row['suppressed'] is False
            and row['toolpath_generated'] is False and row['toolpath_record_counts']==[],'Ungenerated same-feature Finish pair required')
    require(source['assigned_tool']['native_id']==p['tool_native_id']==loaded['neck_tool_candidate']['native_id'],'Reuse the saved qualified source tool')
    require(loaded['state']['document']['needs_save'] is False and len(rows)==loaded['state']['operation_count']<32,'Bounded saved inventory required')
    return source,target


def wanted_tool(loaded,p):return deepcopy(binding(loaded,p)[0]['assigned_tool'])


def executed_regressions(loaded):
    """Supplement older compatibility evidence: skipped tests are not execution."""
    pin=loaded.get('runtime_compatibility_pin')
    if pin is None:return
    data,_=read_pin(pin['path'],pin['sha256']);common._check([data['regression_pin']])
    root=ET.fromstring(Path(data['regression_pin']['path']).read_bytes());suites=[root] if root.tag=='testsuite' else root.findall('testsuite')
    require(suites and all(int(x.attrib.get('errors',0))==int(x.attrib.get('failures',0))==0 for x in suites)
        and sum(int(x.attrib.get('tests',0))-int(x.attrib.get('skipped',0)) for x in suites)>0,'At least one executed passing compatibility test required')


def protected_evidence(loaded,p):
    data,pin=read_pin(p['protected_receipt_path'],p['protected_receipt_sha256'])
    require(data['scope']=='SAVED_FRESH_FINISH_PROTECTED_READ_V1' and data['status']=='observed' and data['readback_verified'] is True
        and data['read_only'] is True and all(data[k] is False for k in ('mutation_attempted','GTP_attempted','save_attempted')),'Completed read-only protected observation required')
    require(data['process_id']==p['process_id'] and data['operation_native_id']==p['operation_native_id'] and data['feature_native_id']==p['feature_native_id']
        and common._key(data['source_path'])==common._key(p['expected_document_path']) and data['source_sha256']==p['expected_source_sha256']
        and data['checkpoint_pin']['sha256']==loaded['parent_pin']['sha256'],'Protected observation binding differs')
    require(group.exact(data['before'],data['after']) and data['batch']['read_scope_complete'] is True and data['batch']['invalid'] is False
        and data['cleanup']['session_active'] is False and data['cleanup']['messages']['disconnected'] is True,'Completed stable protected observation required')
    clean_events(data);common._check(data['runtime_pins'])
    source,target=binding(loaded,p)
    expected=dict(native_id=p['operation_native_id'],suppressed=False,generated=False,feature_ids=[p['feature_native_id']],tool_id=target['assigned_tool']['native_id'],record_counts=[],mill_type=1)
    require(group.exact(data['before'],expected),'Protected observation selected route differs')
    value=data['protected']
    require(set(value)=={'gouge_check','single_depth','depth_process','rest_method','add_tool_radius','lead_types','compensation'}
        and value['gouge_check'] is False and value['single_depth'] is False and type(value['depth_process']) is int
        and type(value['rest_method']) is int and value['rest_method']==0 and type(value['add_tool_radius']) is bool
        and value['lead_types']==[4,4] and type(value['compensation']) is list and len(value['compensation'])==2
        and all(type(x) is int for x in value['compensation']),'Observed fresh arc-conversion baseline required')
    return deepcopy(value),pin


def expected_protected(initial):
    result=deepcopy(initial);result.update(gouge_check=True,lead_types=[1,1]);return result


def load_inputs(p):
    loaded=parent.load_completed(p['checkpoint_receipt_path'],p['checkpoint_receipt_sha256'],
        **{k:p[k] for k in ('process_id','expected_document_path','expected_source_sha256')})
    binding(loaded,p);executed_regressions(loaded)
    recipe,rpin=read_pin(p['recipe_path'],p['recipe_sha256']);validate_recipe(recipe,p)
    observed,protected_pin=protected_evidence(loaded,p)
    from scripts import sw_cam_finish_defaults_progress as compact
    from scripts import sw_cam_fresh_finish_field_batch as field_batch
    retired=[x for x in loaded['pins'] if Path(x['path']).name in ('sw_cam_finish_runtime_compatibility.py','sw_cam_chamfer_catalogue_preflight.py')
        or common._key(x['path'])==common._key(loaded.get('runtime_compatibility_pin',{}).get('path','/not-a-pin'))]
    live=common._merge([x for x in loaded['pins'] if x not in retired],[common._pin(__file__),common._pin(compact.__file__),common._pin(field_batch.__file__)])
    require(len(live)<=64,'Bounded native closure required')
    loaded.update(pins=live,offline_export_proof_pins=common._merge(loaded['offline_export_proof_pins'],retired,[rpin,protected_pin]),recipe=recipe,recipe_pin=rpin,protected_baseline=observed,protected_receipt_pin=protected_pin)
    common._check(live);common._check(loaded['offline_export_proof_pins']);return loaded


def expected_defaults(initial,values):
    result=deepcopy(initial)
    for key,member in DEFAULT_FIELDS.items():result['finish'][member]=values[key][0] if key in ('first_depth','max_depth','side_step') else values[key]
    return result


def verify_observation(loaded,p,baseline,observed,*,configured,generated):
    a,b=deepcopy(baseline['route']),deepcopy(observed['route'])
    before=next(x for x in a['operations'] if x['native_id']==p['operation_native_id']);target=next(x for x in b['operations'] if x['native_id']==p['operation_native_id'])
    require(target['assigned_tool']==(wanted_tool(loaded,p) if configured else before['assigned_tool'])
        and target['toolpath_generated'] is generated,'Target assignment/generated flag differs')
    counts=target['toolpath_record_counts'];require((generated and type(counts) is list and len(counts)==1 and type(counts[0]) is int and 0<counts[0]<=100000)
        or (not generated and counts==[]),'Bounded actual target stream required')
    for key in ('assigned_tool','toolpath_generated','toolpath_record_counts'):target[key]=deepcopy(before[key])
    require(group.exact(a,b),'Prior route/settings or operation changed')
    for key in ('tools','feature','source_defaults','source_restrictions'):
        require(group.exact(baseline[key],observed[key]),'Protected observation changed: '+key)
    expected=expected_defaults(baseline['target_defaults'],loaded['recipe']['field_values']) if configured else baseline['target_defaults']
    require(group.exact(expected,observed['target_defaults']),'Unexpected target defaults/levels changed')
    require(group.exact(observed['fields'],loaded['recipe']['field_values'] if configured else baseline['fields']),'Target direct readback differs')
    protected=expected_protected(baseline['protected']) if configured else baseline['protected']
    require(group.exact(protected,observed['protected']),'Unexpected protected field change')
    require(observed['target_defaults']['finish']['BottomFinOpt'] is False and (not configured or observed['protected']['gouge_check'] is True and observed['protected']['lead_types']==[1,1]),'Wall-only gouge/arc guard required')
    return deepcopy(counts)


def verify_before(loaded,p,value):
    require(group.exact(value['route'],insert.base.expected_route(loaded)) and group.exact(value['tools'],loaded['neck_tool_checkpoint']['catalogue']),'Saved route/tool catalogue changed')
    expected=next(x for x in loaded['state']['features'] if x['geometry']['native_id']==p['feature_native_id'])
    require(group.exact(value['feature'],expected) and group.exact(value['target_defaults'],loaded['fresh_finish_definition']['defaults']),'Saved feature/new defaults changed')
    source_pin=loaded['parent_pin'];prior,_=read_pin(source_pin['path'],source_pin['sha256'])
    require(group.exact(value['source_defaults'],prior['final_observation']['source_defaults'])
        and group.exact(value['source_restrictions'],prior['final_observation']['source_restrictions']),'Saved source recipe changed')
    require(group.exact(value['protected'],loaded['protected_baseline']),'Fresh protected state differs from pinned diagnostic')
    verify_observation(loaded,p,value,value,configured=False,generated=False)


def status_contract(status,p,*,generated=None):
    require(status['operation_native_id']==p['operation_native_id'] and status['feature_native_id']==p['feature_native_id'],'Outcome target differs')
    require(type(status['generated']) is bool and status['generated_for_feature'] is status['generated'],'Actual operation/feature flags disagree')
    counts=status['record_counts'];require(type(counts) is list and len(counts)<=1 and all(type(x) is int and 0<x<=100000 for x in counts)
        and bool(counts) is status['generated'],'Actual flags/stream counts disagree')
    if generated is not None:require(status['generated'] is generated,'Unexpected selected generation state')
    return counts


def audit(typelib,generated):
    from ctypes import POINTER,c_int,c_double
    from ctypes.wintypes import VARIANT_BOOL
    rows=lead_scope.audit(typelib,generated)['members']
    cls=finish.interface_class('ICWFinishMillOp',typelib,generated)
    for member,ident,scalar in (('SideAllow',1,c_double),('FinalSideCutAmt',3,c_double),
        ('SpringPass',4,c_int),('FinalDepthCut',13,c_double),('PerimeterPassType',23,c_int)):
        for name,args,flags in (('_get_'+member,(POINTER(scalar),),(10,)),('_set_'+member,(scalar,),(1,))):
            found=[x for x in cls._methods_ if x.name==name];require(len(found)==1,'Exact property declaration required')
            finish.prior.require_abi(found[0],ident,args,flags);rows.append(dict(interface='ICWFinishMillOp',name=name,dispid=ident))
        require(hasattr(POINTER(cls),'_ICWFinishMillOp__com__set_'+member),'Raw HRESULT setter required')
    for interface,member,ident,scalar in (('ICWFinishMillOp3','GougeCheck',130,VARIANT_BOOL),('ICWLeadInOut','LeadType',1,c_int)):
        cls=finish.interface_class(interface,typelib,generated)
        for name,args,flags in (('_get_'+member,(POINTER(scalar),),(10,)),('_set_'+member,(scalar,),(1,))):
            found=[x for x in cls._methods_ if x.name==name];require(len(found)==1,'Exact scope property required')
            finish.prior.require_abi(found[0],ident,args,flags);rows.append(dict(interface=interface,name=name,dispid=ident))
        require(hasattr(POINTER(cls),'_'+interface+'__com__set_'+member),'Raw scope HRESULT setter required')
    return dict(all_resolved=True,native_calls=0,members=rows)


class NativeBackend(CompactDefaultsMixin,parent.NativeBackend):
    def selected_feature(self):
        with self.ctx.guard() as g:
            fid=self.args['feature_native_id'];found=g.read(self.native['doc'],'GetCWObjectFromID',1,fid)
            require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact feature lookup required')
            feature=g.typed(found[0],'ICWMillFeature');require(_object_id(self.native['doc'],feature,g.read)==fid,'Feature identity differs')
            saved=next(x for x in self.loaded['state']['features'] if x['geometry']['native_id']==fid)
            row,_=insert.read_header(feature,self.native['doc'],g.read,g.typed,saved['setup_native_id'])
            require(group.exact(row,saved['geometry']),'Feature header changed');return feature,deepcopy(saved)
    def target(self,g):
        oid,fid=self.args['operation_native_id'],self.args['feature_native_id']
        found=g.read(self.native['doc'],'GetCWObjectFromID',3,oid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact target operation required')
        raw=found[0];op=g.typed(raw,'ICWOperation');mill=g.typed(raw,'ICWMillOperation')
        require(_object_id(self.native['doc'],op,g.read)==oid and g.read(op,'Suppressed') is False and g.read(mill,'OpernType')==1,'Target identity/type differs')
        links=[_object_id(self.native['doc'],v,g.read) for v in _items(g.read(op,'IGetAllFeatures'),g.typed,g.read,2)]
        require(links==[fid],'Target feature differs')
        feature=g.read(self.native['doc'],'GetCWObjectFromID',1,fid)
        require(type(feature) in (tuple,list) and len(feature)==2 and feature[1] is True,'Exact target feature required')
        self.native['operations'][oid]=raw;return raw,feature[0]
    def typed(self,g,obj,name):
        cls=finish.interface_class(name,self.typelib_path,self.loaded['generated_pin']);value=g.read(obj,'QueryInterface',cls)
        require(value is not None and bool(value) and isinstance(value,cls),'Exact typed interface required');return value
    def owner(self,g,spec):
        raw,feature=self.target(g);name=spec[1]
        if name in ('lead_in','lead_out'):
            owner=self.typed(g,raw,'ICWFinishMillOp');raw=g.read(owner,'IGetLeadin' if name=='lead_in' else 'IGetLeadout',feature)
            require(raw is not None and bool(raw),'Nonnull feature lead required');name='ICWLeadInOut'
        return self.typed(g,raw,name),feature,name
    def field(self,spec):
        with self.ctx.guard() as g:
            owner,feature,_=self.owner(g,spec);value=g.read(owner,spec[2],*([feature] if spec[4]=='feature' else []))
        return list(value) if type(value) is tuple else value
    def set_field(self,spec,value,pending):
        require(spec in FIELDS+SCOPE_FIELDS,'Setter outside reviewed recipe')
        with self.ctx.guard() as g:
            owner,feature,name=self.owner(g,spec);mode=spec[4]
            if mode=='property':
                method=getattr(owner,'_'+name+'__com__set_'+spec[3]);call=lambda:method(value)
            else:
                args=[feature,value] if mode=='feature' else list(value) if mode in ('pair','depth_pair') else [value]
                call=lambda:_member(owner,spec[3],*args)
            return g.dispatch_once(call,persist_pending=pending)
    def protected(self):
        with self.ctx.guard() as g:
            raw,feature=self.target(g);op=self.typed(g,raw,'ICWFinishMillOp');v3=self.typed(g,raw,'ICWFinishMillOp3')
            value=dict(gouge_check=g.read(v3,'GougeCheck'),single_depth=g.read(v3,'GetIsSingleCutDepth'),
                depth_process=g.read(op,'DepthProcessOpt'),rest_method=g.read(v3,'ContourMillRestMachMethod'),
                add_tool_radius=g.read(v3,'GetToolRadiusLeadInLeadOut'))
            value['lead_types']=[g.read(self.typed(g,g.read(op,member,feature),'ICWLeadInOut'),'LeadType') for member in ('IGetLeadin','IGetLeadout')]
            mill=g.typed(raw,'ICWMillOperation');nc=self.typed(g,g.read(mill,'IGetNCParam'),'ICWNCParam')
            value['compensation']=[g.read(nc,name) for name in ('GetTlpComp','GetCNCComp')]
        self.report.setdefault('protected_observations',[]).append(deepcopy(value));self.persist()
        require(type(value['gouge_check']) is bool and type(value['single_depth']) is bool and type(value['depth_process']) is int
            and type(value['rest_method']) is int and all(type(x) is int for x in value['lead_types']+value['compensation'])
            and type(value['add_tool_radius']) is bool,'Exact protected scalar types required')
        return value
    def snapshot(self,label):
        value=insert.NativeBackend.snapshot(self,label)
        source=self.args['source_operation_native_id'];target=self.args['operation_native_id'];fid=self.args['feature_native_id']
        value['source_defaults']=self.operation_defaults(source,label+'_source',fid)
        value['source_restrictions']=self.source_restrictions()
        value['target_defaults']=self.operation_defaults(target,label+'_target',fid)
        from scripts.sw_cam_fresh_finish_field_batch import read_fields
        value['fields']=read_fields(self,label);value['protected']=self.protected();return value
    def current_tool(self):
        with self.ctx.guard() as g:
            raw,_=self.target(g);value,_=read_generic_tool(raw,self.native['doc'],g.read,g.typed);return value
    def assign(self,pending):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,_=self.target(g);tid=self.args['tool_native_id']
            rows=_items(g.read(self.crib,'GetAllTools'),g.typed,g.read,insert.base.MAX_TOOLS)
            ids=[_object_id(self.native['doc'],x,g.read) for x in rows]
            require(ids==[x['native_id'] for x in self.loaded['neck_tool_checkpoint']['catalogue']] and ids.count(tid)==1,'Saved tool catalogue changed')
            tool=g.typed(rows[ids.index(tid)],'ICWTool');wanted=wanted_tool(self.loaded,self.args)
            require(g.read(tool,'ToolType')==wanted['tool_type_raw'] and g.read(tool,'CutDiameter')==wanted['cut_diameter_native']
                and group.exact(g.read(tool,'Protrusion'),wanted['protrusion_native']),'Qualified source tool changed')
            dispatch=g.read(tool,'QueryInterface',IDispatch);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)
    def outcome(self):
        from comtypes.automation import IDispatch
        with self.ctx.guard() as g:
            raw,feature=self.target(g);op=g.typed(raw,'ICWOperation');dispatch=g.read(feature,'QueryInterface',IDispatch)
            generated=g.read(op,'GetIsToolpathGenerated');byfeature=g.read(op,'GetIsToolpathGeneratedForFeature',dispatch)
            counts=[g.read(g.typed(v,'ICWToolpath'),'RecordCount') for v in _items(g.read(op,'IGetEnumToolpaths'),g.typed,g.read,1)]
        value=dict(operation_native_id=self.args['operation_native_id'],feature_native_id=self.args['feature_native_id'],
            generated=generated,generated_for_feature=byfeature,record_counts=counts)
        status_contract(value,self.args);return value
    def generate(self,pending):
        require(self.protected()['gouge_check'] is True and group.exact(self.current_tool(),wanted_tool(self.loaded,self.args)),'Exact assigned guarded target required')
        status_contract(self.outcome(),self.args,generated=False)
        with self.ctx.guard() as g:
            raw,_=self.target(g);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'GenerateToolpath'),persist_pending=pending)


class Journal(insert.base.Journal):
    def pending(self,label):
        require(label in ACTIONS,'Action outside selected recipe');return super().pending(label)
    def marker_state(self):
        r=self.report
        return dict(scope=SCOPE,receipt_path=str(self.receipt),source_path=r['source_path'],initial_source_sha256=r['initial_source_sha256'],
            target=r['request']['operation_native_id'],recipe_pin=r['recipe_pin'],phase=r['phase'],actions=deepcopy(r['actions']),
            status=r['status'],readback_verified=r['readback_verified'],saved_source_sha256=r.get('saved_source_sha256'),automatic_replay=False)


def marker_path(p):
    return common.local_evidence_root()/('fresh_finish_recipe_'+_digest(dict(scope=SCOPE,source=common._key(p['expected_document_path']),
        source_sha256=p['expected_source_sha256'],operation=p['operation_native_id'],protected_receipt_sha256=p['protected_receipt_sha256']))+'.json')


def returned(backend,journal,label,value):
    journal.returned(label,value);require(type(value) is int and value==0,'Strict native HRESULT zero required');backend.refresh_dirty()


def run_backend(backend,journal,loaded,p):
    r=journal.report
    try:
        backend.start();r['before']=backend.snapshot('before');verify_before(loaded,p,r['before']);journal.persist()
        status_contract(backend.outcome(),p,generated=False)
        value=backend.assign(lambda:journal.pending('SetTool'));returned(backend,journal,'SetTool',value)
        actual=backend.current_tool();require(group.exact(actual,wanted_tool(loaded,p)),'Tool assignment readback differs')
        r['actions']['SetTool'].update(readback_verified=True,observed=actual);journal.persist()
        for spec in SCOPE_FIELDS:
            label='scope:'+spec[0];value=loaded['recipe']['scope_values'][spec[0]]
            r.setdefault('scope_before',{})[spec[0]]=backend.field(spec);journal.persist()
            result=backend.set_field(spec,value,lambda label=label:journal.pending(label));returned(backend,journal,label,result)
            actual=backend.field(spec);r['actions'][label]['observed']=actual;journal.persist()
            require(group.exact(actual,value),'Scope field readback differs');r['actions'][label]['readback_verified']=True;journal.persist()
        for spec in FIELDS:
            label='field:'+spec[0];value=loaded['recipe']['field_values'][spec[0]]
            r.setdefault('field_before',{})[spec[0]]=backend.field(spec);journal.persist()
            result=backend.set_field(spec,value,lambda label=label:journal.pending(label));returned(backend,journal,label,result)
            actual=backend.field(spec);r['actions'][label]['observed']=actual;journal.persist()
            require(group.exact(actual,value),'Direct field readback differs');r['actions'][label]['readback_verified']=True;journal.persist()
        r['configured']=backend.snapshot('configured');verify_observation(loaded,p,r['before'],r['configured'],configured=True,generated=False)
        r['configuration_readback_verified']=True;journal.persist()
        result=backend.generate(lambda:journal.pending('GenerateToolpath'));returned(backend,journal,'GenerateToolpath',result)
        r['generation_status']=backend.outcome();status_contract(r['generation_status'],p)
        generated=r['generation_status']['generated'];r['generated']=backend.snapshot('generated')
        counts=verify_observation(loaded,p,r['before'],r['generated'],configured=True,generated=generated)
        require(counts==r['generation_status']['record_counts'],'Observed generation stream differs')
        r['generated_record_counts']=counts;r['actions']['GenerateToolpath'].update(readback_verified=True,observed=deepcopy(r['generation_status']))
        r['generation_verified']=generated;journal.persist();expected=deepcopy(r['generated']);r['save_stage']={}
        def guard():
            backend.boundary();require(group.exact(backend.outcome(),r['generation_status']),'Selected outcome changed before Save')
        def capture(label):
            if label=='before':guard();return deepcopy(expected)
            r['final']=backend.snapshot('saved');verify_observation(loaded,p,r['before'],r['final'],configured=True,generated=generated)
            r['final_state']=deepcopy(backend.current_state);journal.persist();return deepcopy(r['final'])
        def verify(value):require(group.exact(value,expected),'Save changed configured machining state')
        def save():value=backend.save();journal.returned('SaveActiveDocument',value);return value
        def saved_hash():
            value=backend.saved_hash(r['save_stage']);require(value!=r['initial_source_sha256'],'Saved bytes must change')
            r['saved_source_sha256']=value;journal.persist();return value
        insert.run_one_existing_save(r['save_stage'],capture=capture,verify=verify,guard=guard,
            claim=lambda:journal.pending('SaveActiveDocument'),persist=journal.persist,save=save,saved_hash=saved_hash)
        r['actions']['SaveActiveDocument']['readback_verified']=True;backend.finish()
        r.update(status='saved_generated_review_required' if generated else 'saved_configuration_no_toolpath',phase='finished',readback_verified=True,model_saved=True)
    except Exception as exc:r.update(status='uncertain' if r['mutation_attempted'] else 'error',failed_phase=r['phase'],phase='finished',readback_verified=False,issue=_error(exc))
    finally:
        try:backend.close()
        except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        session=getattr(backend,'session',None)
        if session is not None:
            r['messages']=session.summary();r['cleanup_session_active']=getattr(backend,'session_active',None)
            try:backend.events(False)
            except Exception as exc:r.update(status='uncertain',readback_verified=False,cleanup_issue=_error(exc))
        journal.persist()
    return r


def validate_terminal(r):
    generated=r['generation_verified'];require(type(generated) is bool,'Strict generated result required')
    require(r['scope']==SCOPE and r['status']==('saved_generated_review_required' if generated else 'saved_configuration_no_toolpath')
        and r['phase']=='finished' and all(r[k] is True for k in ('configuration_readback_verified','readback_verified','model_saved','phase_proofs_verified')),'Completed saved selected result required')
    require(not any(k in r for k in ('issue','failed_phase','cleanup_issue','phase_proof_error')) and set(r['actions'])==ACTIONS
        and all(r[k] is False for k in FORBIDDEN),'Unexpected/uncertain machining actions')
    loaded,p=r['loaded_context_before'],r['request'];validate_recipe(loaded['recipe'],p);binding(loaded,p)
    verify_before(loaded,p,r['before']);verify_observation(loaded,p,r['before'],r['configured'],configured=True,generated=False)
    for label in ('generated','final'):
        require(verify_observation(loaded,p,r['before'],r[label],configured=True,generated=generated)==r['generated_record_counts'],'Saved counts differ')
    status_contract(r['generation_status'],p,generated=generated)
    require(r['generation_status']['record_counts']==r['generated_record_counts'] and group.exact(r['generated'],r['final']),'Save machining observation differs')
    for action in r['actions'].values():parent.parent.wall.history.verified_action(action)
    require(group.exact(r['actions']['SetTool']['observed'],wanted_tool(loaded,p)),'Recorded assignment differs')
    for spec in SCOPE_FIELDS:require(group.exact(r['actions']['scope:'+spec[0]]['observed'],loaded['recipe']['scope_values'][spec[0]]),'Recorded scope choice differs')
    for spec in FIELDS:require(group.exact(r['actions']['field:'+spec[0]]['observed'],loaded['recipe']['field_values'][spec[0]]),'Recorded recipe differs')
    t=r['source_transition'];require(type(t['strict_save_return']) is int and t['strict_save_return']==0
        and t['source_before_sha256']==r['initial_source_sha256'] and t['source_after_sha256']==r['saved_source_sha256']
        and r['initial_source_sha256']!=r['saved_source_sha256'],'Strict source transition required')
    require(r['save_stage']['save_readback_verified'] is True and r['save_stage']['saved_file_sha256']==r['saved_source_sha256'],'Save proof incomplete')
    state=r['final_state'];require(state['document']['needs_save'] is False and state['saved_file_sha256']==r['saved_source_sha256'],'Clean saved source required')
    for name in ('operations','operation_counts','operation_setups'):require(group.exact(state[name],r['final']['route'][name]),'Final inventory/route differs')
    require(state['operation_count']==len(state['operations']) and group.exact(state['features'],loaded['state']['features']),'Feature/count changed')
    clean_events(r);context=deepcopy(loaded);context.update(state=deepcopy(state),source_sha256=r['saved_source_sha256'],
        authority_kind='saved_fresh_finish_generated_review_pending' if generated else 'saved_fresh_finish_configuration_no_toolpath')
    context['fresh_finish_result']=dict(native_id=p['operation_native_id'],feature_native_id=p['feature_native_id'],tool_native_id=p['tool_native_id'],
        generated=generated,record_counts=deepcopy(r['generated_record_counts']),defaults=deepcopy(r['final']['target_defaults']),
        fields=deepcopy(r['final']['fields']),protected=deepcopy(r['final']['protected']),geometry_acceptance_complete=False)
    context['current_context_sha256']=_digest(group.current_projection(context));return context


def load_completed(path,digest,*,process_id,expected_document_path,expected_source_sha256):
    r,pin=read_pin(path,digest)
    require(r['module_pin']==common._pin(__file__) and r['process_id']==process_id and common._key(r['source_path'])==common._key(expected_document_path)
        and r['saved_source_sha256']==expected_source_sha256==_file_hash(expected_document_path),'Saved selected source/writer/owner changed')
    for name in ('live_pins','offline_proof_pins','bootstrap_export_pins'):common._check(r[name])
    context=validate_terminal(r);require(r['checkpoint_digest']==_digest(group.current_projection(context)),'Completed context digest differs')
    marker=marker_path(r['request']);mark,mpin=read_pin(str(marker),r['marker_pin']['sha256'])
    require(group.exact(mark,Journal(r,path,marker).marker_state()),'Saved once-marker differs')
    live=common._merge([x for x in r['live_pins'] if common._key(x['path'])!=common._key(r['parent_pin']['path'])],[pin])
    require(len(live)<=64,'Bounded completed closure required')
    context.update(pins=live,offline_export_proof_pins=common._merge(r['offline_proof_pins'],[r['parent_pin'],mpin]),parent_pin=pin,group_marker_pin=mpin)
    return context


def dispatch_request(request,*,validate_only=False):
    p=validate_request(request);loaded=load_inputs(p)
    receipt=common._local_receipt(p['receipt_path']);marker=marker_path(p)
    paths=[receipt,marker]
    protected={common._key(x['path']) for name in ('pins','offline_export_proof_pins','bootstrap_export_pins') for x in loaded[name]}
    protected.add(common._key(p['expected_document_path']))
    require(len({common._key(x) for x in paths})==len(paths) and not protected.intersection(common._key(x) for x in paths)
        and all(x.is_absolute() and x.parent.is_dir() and not x.exists() and not x.is_symlink() for x in paths),'Fresh distinct output paths required')
    reg=common.discover_export_registration(loaded,p['addin_clsid']);typelib=str(Path(reg['addin_path']).parent/'camworks.tlb')
    audited=audit(typelib,loaded['generated_pin'])
    if validate_only:return dict(status='validated_offline',native_called=False,live_pin_count=len(loaded['pins']),setter_count=len(FIELDS)+len(SCOPE_FIELDS),max_selected_gtp_calls=1,save_empty_result=True,setter_audit=audited)
    from scripts.sw_operation_guard import solidworks_operation_lock
    from scripts.sw_connect import connect_solidworks
    with solidworks_operation_lock(timeout_seconds=1,process_id=p['process_id']):
        sw,_=connect_solidworks(process_id=p['process_id'],launch_new_instance=False,wait_seconds=1)
        r=dict(scope=SCOPE,status='prepared',phase='prepared',process_id=p['process_id'],source_path=p['expected_document_path'],initial_source_sha256=p['expected_source_sha256'],
            request=p,module_pin=common._pin(__file__),parent_pin=loaded['parent_pin'],recipe_pin=loaded['recipe_pin'],loaded_context_before=loaded,
            live_pins=loaded['pins'],offline_proof_pins=loaded['offline_export_proof_pins'],bootstrap_export_pins=loaded['bootstrap_export_pins'],setter_audit=audited,
            actions={},mutation_attempted=False,configuration_readback_verified=False,generation_verified=False,readback_verified=False,model_saved=False,**{k:False for k in FORBIDDEN})
        j=Journal(r,receipt,marker);_write_receipt(receipt,r,create=True)
        b=NativeBackend(loaded,p,sw,reg['clsid'],typelib,r,j.persist);run_backend(b,j,loaded,p)
        try:
            for name in ('pins','offline_export_proof_pins','bootstrap_export_pins'):common._check(loaded[name])
            clean_events(r);r['phase_proofs_verified']=True
            if r['readback_verified']:
                context=validate_terminal(r);r['checkpoint_digest']=_digest(group.current_projection(context));j.persist()
                r['marker_pin']=common._pin(marker);j.persist();require(r['marker_pin']['sha256']==_file_hash(marker),'Stable terminal marker required')
        except Exception as exc:r.update(status='uncertain',readback_verified=False,phase_proof_error=_error(exc))
        j.persist();return r


def main(argv=None):
    import argparse
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--request',required=True);a.add_argument('--validate-only',action='store_true');args=a.parse_args(argv)
    r=dispatch_request(json.loads(Path(args.request).read_text(encoding='utf-8-sig')),validate_only=args.validate_only)
    print(json.dumps({k:r.get(k) for k in ('status','readback_verified','saved_source_sha256','generated_record_counts','issue','native_called')}))
    return 0 if r.get('readback_verified') is True or r.get('status')=='validated_offline' else 1


if __name__=='__main__':raise SystemExit(main())
