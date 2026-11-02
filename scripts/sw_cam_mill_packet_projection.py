"""Pure semantic projection of the bounded fixed MILL host packet.

No COM objects, filesystem access, native calls or dynamic member invocation.
Declared CLR outputs are materialized for the existing Python semantic readers.
CLR shapes for two object returns are retained separately from native VARIANT
provenance, which remains unverified. The caller still owns host/source checks.
"""
from copy import deepcopy
import math, json
from scripts import sw_cam_guide_group_parameters as reader
from scripts import sw_cam_guide_group_configuration as config

SCHEMA=2
SCOPE='MILL_FIXED_PARAMETER_PACKET_V2'
ENGINE='mill-fixed-parameters-reader-2'
CAM_CLASS='{CCAC6208-0E19-6455-2022-2026CEB541FA}'


def require(value,message):
    if not value:raise ValueError(message)


def scalar(value,kind):
    if kind=='System.Double':
        require(type(value)in(int,float) and math.isfinite(value),'Finite typed double required')
        return float(value)
    if kind=='System.Int32':
        require(type(value)is int and -(2**31)<=value<2**31,'Strict Int32 required');return value
    if kind=='System.Boolean':require(type(value)is bool,'Strict Boolean required');return value
    if kind=='System.String':require(type(value)is str and len(value)<=4096,'Bounded string required');return value
    raise ValueError('Unsupported fixed CLR scalar type')


def clr_variant(value,shape,depth=0):
    require(depth<=4 and type(shape)is dict and 'kind'in shape,'Bounded CLR object shape required')
    kind=shape['kind']
    if kind=='array':
        require(set(shape)=={'kind','items'}and type(value)is list and type(shape['items'])is list and len(value)==len(shape['items'])<=16,'Exact CLR array shape required')
        return tuple(clr_variant(v,s,depth+1)for v,s in zip(value,shape['items']))
    require(set(shape)=={'kind'},'Exact scalar shape required')
    if kind=='null':require(value is None,'Null CLR object required');return None
    require(kind in {'double','int','bool','str'},'Supported CLR shape required')
    return scalar(value,{'double':'System.Double','int':'System.Int32','bool':'System.Boolean','str':'System.String'}[kind])


def materialize(value,spec,shape=None):
    group,arg,result,outs=spec
    if result=='System.Object':return clr_variant(value,shape)
    require(shape is None,'Unexpected object-shape permission')
    if result=='System.Void':
        require(type(value)is list and len(value)==len(outs)>0,'Exact typed out-parameter array required')
        result=tuple(scalar(v,t)for v,t in zip(value,outs))
        return result[0]if len(result)==1 else result
    require(not outs,'Unsupported return-plus-out signature')
    return scalar(value,result)

_FIXED = {
    'operation|ICWMillOperation|GetMachiningDepth': ('all', 'feature', 'System.Double', ()),
    'operation|ICWMillOperation3|GetOverrideMachiningDepth': ('all', 'feature', 'System.Boolean', ()),
    'toolpath|ICWToolpathParam|GetToolpathParameters': ('all', 'none', 'System.Void', ('System.Boolean', 'System.Boolean', 'System.Boolean', 'System.Int32', 'System.Boolean', 'System.Double', 'System.Double')),
    'origin|ICWPosition|GetCoordinates': ('all', 'none', 'System.Void', ('System.Double', 'System.Double', 'System.Double')),
    'axis|ICWUnitVector|GetCoordinates': ('all', 'none', 'System.Void', ('System.Double', 'System.Double', 'System.Double')),
    'operation|ICWRghMillOp|GetEntryExitType': ('rough', 'feature', 'System.Int32', ()),
    'operation|ICWRghMillOp|GetEntryHoleAttr': ('rough', 'feature', 'System.String', ()),
    'operation|ICWRghMillOp|GetRampAngle': ('rough', 'feature', 'System.Double', ()),
    'operation|ICWRghMillOp|GetSpiralRadius': ('rough', 'feature', 'System.Double', ()),
    'operation|ICWRghMillOp|GetSpiralPitch': ('rough', 'feature', 'System.Double', ()),
    'operation|ICWRghMillOp|GetHoleCentreEntry': ('rough', 'feature', 'System.Boolean', ()),
    'operation|ICWRghMillOp|GetEntryLengthAngle': ('rough', 'feature', 'System.Boolean', ()),
    'operation|ICWRghMillOp|GetEntryLength': ('rough', 'feature', 'System.Double', ()),
    'operation|ICWRghMillOp|GetEntryAngle': ('rough', 'feature', 'System.Double', ()),
    'operation|ICWRghMillOp|GetAutoCorrectEntryLengthAngle': ('rough', 'feature', 'System.Boolean', ()),
    'operation|ICWRghMillOp|GetEntryStartPtX': ('rough', 'feature', 'System.Object', ()),
    'operation|ICWRghMillOp|GetEntryStartPtY': ('rough', 'feature', 'System.Object', ()),
    'operation|ICWRghMillOp|DepthMethod': ('rough', 'none', 'System.Int32', ()),
    'operation|ICWRghMillOp|DepthAllow': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|FirstDepthAmt': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|SbsqDepthAmt': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|FinCutAmt': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|GetStartDepth': ('rough', 'none', 'System.Void', ('System.Boolean', 'System.Double')),
    'operation|ICWRghMillOp|GetSubsequentDepthAmount': ('rough', 'none', 'System.Void', ('System.Boolean', 'System.Double')),
    'operation|ICWRghMillOp|PocketMethod': ('rough', 'none', 'System.Int32', ()),
    'operation|ICWRghMillOp|SideAllow': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|GetStepOver': ('rough', 'none', 'System.Void', ('System.Boolean', 'System.Double')),
    'operation|ICWRghMillOp|GetZAllowance': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|GetContainType': ('rough', 'none', 'System.Int32', ()),
    'operation|ICWRghMillOp|GetContainAllowance': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|GetXYClearance': ('rough', 'none', 'System.Double', ()),
    'operation|ICWRghMillOp|GetToolDiameterPercent': ('rough', 'feature', 'System.Void', ('System.Double',)),
    'operation|ICWFinishMillOp|SideAllow': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|SideCutAmt': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|FinalSideCutAmt': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|SpringPass': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|DepthMethod': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|Ramp': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|DepthAllow': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|FirstDepthCut': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|MaxDepthCut': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|FinalDepthCut': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|DepthAngle': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp|CleanUpPassOpt': ('finish', 'none', 'System.Boolean', ()),
    'operation|ICWFinishMillOp|CutMethod': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|BottomFinOpt': ('finish', 'none', 'System.Boolean', ()),
    'operation|ICWFinishMillOp|PerimeterPassType': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|BottomFinMethod': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp|OverridePrevAllow': ('finish', 'none', 'System.Boolean', ()),
    'operation|ICWFinishMillOp2|GetPreviousAllowance': ('finish', 'feature', 'System.Double', ()),
    'operation|ICWFinishMillOp3|GetZAllowance': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp3|GetContainType': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp3|GetContainAllowance': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp3|GetTypeOfFirstCutZ': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp3|GetIsChamferMachining': ('finish', 'none', 'System.Void', ('System.Boolean',)),
    'operation|ICWFinishMillOp3|GetChamferLength': ('finish', 'none', 'System.Double', ()),
    'operation|ICWFinishMillOp3|GetFirstDepthCut': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'operation|ICWFinishMillOp3|GetMaxDepthCut': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'operation|ICWFinishMillOp3|GetSideCutAmt': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'operation|ICWFinishMillOp3|LeadInOutApplyToAll': ('finish', 'none', 'System.Boolean', ()),
    'lead_out|ICWLeadInOut|GetIsSameLeadinout': ('finish', 'none', 'System.Void', ('System.Boolean',)),
    'lead_in|ICWLeadInOut|ArcAngle': ('finish', 'none', 'System.Double', ()),
    'lead_in|ICWLeadInOut|GetArcRadius2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'lead_in|ICWLeadInOut|GetLeadAmt2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'lead_in|ICWLeadInOut|GetLeadOverlap2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'lead_out|ICWLeadInOut|ArcAngle': ('finish', 'none', 'System.Double', ()),
    'lead_out|ICWLeadInOut|GetArcRadius2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'lead_out|ICWLeadInOut|GetLeadAmt2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'lead_out|ICWLeadInOut|GetLeadOverlap2': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean', 'System.Double')),
    'operation|ICWFinishMillOp3|GougeCheck': ('finish', 'none', 'System.Boolean', ()),
    'operation|ICWFinishMillOp3|GetIsSingleCutDepth': ('finish', 'none', 'System.Void', ('System.Boolean',)),
    'operation|ICWFinishMillOp|DepthProcessOpt': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp3|ContourMillRestMachMethod': ('finish', 'none', 'System.Int32', ()),
    'operation|ICWFinishMillOp3|GetToolRadiusLeadInLeadOut': ('finish', 'none', 'System.Boolean', ()),
    'lead_in|ICWLeadInOut|LeadType': ('finish', 'none', 'System.Int32', ()),
    'lead_in|ICWLeadInOut|LeadAngle': ('finish', 'none', 'System.Double', ()),
    'lead_in|ICWLeadInOut|SidePassType': ('finish', 'none', 'System.Int32', ()),
    'lead_in|ICWLeadInOut|CutDepthType': ('finish', 'none', 'System.Int32', ()),
    'lead_in|ICWLeadInOut|StartAngle': ('finish', 'none', 'System.Double', ()),
    'lead_in|ICWLeadInOut|GetIsSameLeadinout': ('finish', 'none', 'System.Void', ('System.Boolean',)),
    'lead_in|ICWLeadInOut|GetFeedRate': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'lead_out|ICWLeadInOut|LeadType': ('finish', 'none', 'System.Int32', ()),
    'lead_out|ICWLeadInOut|LeadAngle': ('finish', 'none', 'System.Double', ()),
    'lead_out|ICWLeadInOut|SidePassType': ('finish', 'none', 'System.Int32', ()),
    'lead_out|ICWLeadInOut|CutDepthType': ('finish', 'none', 'System.Int32', ()),
    'lead_out|ICWLeadInOut|StartAngle': ('finish', 'none', 'System.Double', ()),
    'lead_out|ICWLeadInOut|GetFeedRate': ('finish', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'nc|ICWNCParam3|FeedPlaneType': ('all', 'none', 'System.Int32', ()),
    'nc|ICWNCParam3|FeedPlaneDistance': ('all', 'none', 'System.Double', ()),
    'nc|ICWNCParam4|GetUseCurrentMachiningDepthForFeedPlane': ('all', 'none', 'System.Boolean', ()),
    'nc|ICWNCParam|GetClrPlaneUseSetupStatus': ('all', 'none', 'System.Boolean', ()),
    'nc|ICWNCParam|GetRpdPlaneUseSetupStatus': ('all', 'none', 'System.Boolean', ()),
    'nc|ICWNCParam|GetSpndlSpeed': ('all', 'none', 'System.Double', ()),
    'nc|ICWNCParam|GetTlpComp': ('all', 'none', 'System.Int32', ()),
    'nc|ICWNCParam|GetCNCComp': ('all', 'none', 'System.Int32', ()),
    'nc|ICWNCParam|GetRetractType': ('all', 'none', 'System.Int32', ()),
    'nc|ICWNCParam2|XYFeed': ('all', 'none', 'System.Double', ()),
    'nc|ICWNCParam4|GetZFeedrate2': ('all', 'none', 'System.Void', ('System.Double', 'System.Boolean')),
    'setup|ICWOpSetup3|ClearancePlaneType': ('all', 'none', 'System.Int32', ()),
    'setup|ICWOpSetup3|ClearancePlaneDistance': ('all', 'none', 'System.Double', ()),
    'setup|ICWOpSetup3|RapidPlaneType': ('all', 'none', 'System.Int32', ()),
    'setup|ICWOpSetup3|RapidPlaneDistance': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|MillToolType': ('all', 'none', 'System.Int32', ()),
    'tool|ICWMillTool|MillToolSubType': ('all', 'none', 'System.Int32', ()),
    'tool|ICWMillTool|EffCutlength': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|ShankDia': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|OverallLen': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|EndRadius': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|NoOfFlutes': ('all', 'none', 'System.Int32', ()),
    'tool|ICWMillTool|ShoulderLength': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|MillToolShankType': ('all', 'none', 'System.Int32', ()),
    'tool|ICWMillTool|ShoulderDia': ('all', 'none', 'System.Double', ()),
    'tool|ICWMillTool|ShankLength': ('all', 'none', 'System.Double', ()),
    'holder|ICWMillToolHolder|GetHolderShape': ('all', 'none', 'System.String', ()),
    'holder|ICWMillToolHolder|GetHolderId': ('all', 'none', 'System.Int32', ()),
    'holder|ICWMillToolHolder|GetHolderNumber': ('all', 'none', 'System.String', ()),
    'holder|ICWMillToolHolder|GetName': ('all', 'none', 'System.String', ()),
    'holder|ICWMillToolHolder|GetHolderTopDia': ('all', 'none', 'System.Double', ()),
    'holder|ICWMillToolHolder|GetHolderBottomDia': ('all', 'none', 'System.Double', ()),
    'holder|ICWMillToolHolder|GetHolderOverallLength': ('all', 'none', 'System.Double', ()),
    'holder|ICWMillToolHolder|GetHolderBottomLength': ('all', 'none', 'System.Double', ()),
    'holder|ICWMillToolHolder|GetProtrusion': ('all', 'none', 'System.Double', ()),
}


def _generic(raw):
    fields={'native_id','is_mill_tool','native_read_complete','units_verified','holder_geometry_verified','tool_type_raw','cut_diameter_native','protrusion_native'}
    require(type(raw)is dict and set(raw)==fields,'Exact generic tool fields required')
    out=deepcopy(raw)
    for k in ('native_id','tool_type_raw'):out[k]=scalar(out[k],'System.Int32')
    for k in ('is_mill_tool','native_read_complete','units_verified','holder_geometry_verified'):out[k]=scalar(out[k],'System.Boolean')
    for k in ('cut_diameter_native','protrusion_native'):out[k]=scalar(out[k],'System.Double')
    require(out['native_id']>0 and out['tool_type_raw']>=0 and out['is_mill_tool']and out['native_read_complete']and not out['units_verified']and not out['holder_geometry_verified']and out['cut_diameter_native']>0 and out['protrusion_native']>=0,'Complete unqualified MILL tool identity required')
    return out


def _vector(raw):
    require(type(raw)is list and len(raw)==3,'Three coordinates required')
    return [scalar(x,'System.Double')for x in raw]



def read_packet_json(text):
    require(type(text)is str and 0<len(text.encode('utf-8'))<=1048576,'Bounded packet JSON required')
    def pairs(rows):
        result={}
        for k,v in rows:
            require(k not in result,'Duplicate JSON packet key');result[k]=v
        return result
    def reject(value):raise ValueError('Nonfinite JSON packet number')
    value=json.loads(text,object_pairs_hook=pairs,parse_constant=reject,parse_float=lambda v:scalar(float(v),'System.Double'))
    stack=[(value,0)];nodes=0
    while stack:
        item,depth=stack.pop();nodes+=1;require(depth<=32 and nodes<=50000,'Bounded JSON packet tree required')
        if type(item)is dict:stack.extend((v,depth+1)for v in item.values())
        elif type(item)is list:stack.extend((v,depth+1)for v in item)
    return value


def _integer(value,minimum=0):
    value=scalar(value,'System.Int32');require(value>=minimum,'Integer below bound');return value


def _ids(values,maximum,minimum=0):
    require(type(values)is list and minimum<=len(values)<=maximum,'Bounded identity list required')
    result=[_integer(v,1)for v in values];require(len(result)==len(set(result)),'Duplicate identity');return result


def _starts(raw):
    if raw is None:return
    require(type(raw)is dict and set(raw)=={'metadata','rows'}and type(raw['rows'])is list and len(raw['rows'])<=64,'Bounded startpoint packet required')
    meta=raw['metadata'];require(type(meta)is dict and set(meta)=={'guid','typekind','member_count','name'},'Exact startpoint metadata required')
    require(meta['guid']==reader.guide.start.COLLECTION_IID and type(meta['name'])is str and len(meta['name'])<=4096,'Known collection metadata required')
    _integer(meta['typekind']);require(_integer(meta['member_count'])<=128,'Bounded metadata member count')
    for row in raw['rows']:
        require(type(row)is dict and set(row)=={'type','position'},'Exact startpoint row required')
        _integer(row['type'])
        if row['position']is not None:_vector(row['position'])

def project_binding(raw):
    require(type(raw)is dict and set(raw)=={'features','operation_setups','operations'},'Exact binding required')
    out=deepcopy(raw)
    require(type(out['features'])is dict and 1<=len(out['features'])<=8,'Bounded feature binding required')
    require(type(out['operations'])is list and 1<=len(out['operations'])<=64,'Bounded operation binding required')
    require(type(out['operation_setups'])is list and 1<=len(out['operation_setups'])<=3,'Bounded setup binding required')
    for key,row in out['features'].items():
        require(type(row)is dict and set(row)=={'native_id','volume_type','subtype_raw','shape_raw','suppressed','name','axis_native','depth_native','bounds_native','start_native'},'Exact feature header required')
        require(type(key)is str and str(_integer(row['native_id'],1))==key,'Feature key/identity mismatch')
        for field in ('volume_type','subtype_raw','shape_raw'):_integer(row[field])
        scalar(row['suppressed'],'System.Boolean');scalar(row['name'],'System.String')
        for field in ('axis_native','bounds_native','start_native'):row[field]=_vector(row[field])
        row['depth_native']=scalar(row['depth_native'],'System.Double')
    setup_ids=[]
    for index,row in enumerate(out['operation_setups']):
        require(type(row)is dict and set(row)=={'index','native_id','operation_count'},'Exact setup row required')
        require(_integer(row['index'])==index,'Setup index changed');setup_ids.append(_integer(row['native_id'],1));_integer(row['operation_count'])
    require(len(set(setup_ids))==len(setup_ids),'Duplicate setup identity')
    counts=[0]*len(setup_ids);seen=set()
    for row in out['operations']:
        require(type(row)is dict and set(row)=={'setup_index','setup_native_id','operation_index','native_id','mill_operation_type','base_operation_type','suppressed','toolpath_generated','linked_feature_ids','toolpath_record_counts','assigned_tool'},'Exact operation binding row required')
        si=_integer(row['setup_index']);require(si<len(setup_ids)and _integer(row['setup_native_id'],1)==setup_ids[si],'Operation setup differs')
        require(_integer(row['operation_index'])==counts[si],'Operation index changed');counts[si]+=1
        oid=_integer(row['native_id'],1);require(oid not in seen,'Duplicate operation identity');seen.add(oid)
        for key in ('mill_operation_type','base_operation_type'):_integer(row[key])
        for key in ('suppressed','toolpath_generated'):scalar(row[key],'System.Boolean')
        _ids(row['linked_feature_ids'],4)
        require(type(row['toolpath_record_counts'])is list and len(row['toolpath_record_counts'])<=4,'Bounded path counts required')
        for value in row['toolpath_record_counts']:_integer(value)
        row['assigned_tool']=_generic(row['assigned_tool'])
    require(counts==[x['operation_count']for x in out['operation_setups']],'Setup operation counts differ')
    return out


class _Handle:
    __slots__=('owner','role','interface','index')
    def __init__(self,owner,role,interface='',index=None):self.owner,self.role,self.interface,self.index=owner,role,interface,index


class PacketReplay:
    """Finite retained graph over one packet row; every getter is a fixed key."""
    def __init__(self,row):
        self.row=row;self.calls=0;self.used=set();self.generic=_generic(row['generic_tool']);self.operation=self.handle('operation');self.feature=self.handle('feature');self.setup=self.handle('setup');self.doc=self.handle('doc')
        require(type(row['operation_type'])is int and row['operation_type']in(0,1),'Exact rough/finish kind required')
        require(type(row['planes'])is dict and set(row['planes'])=={'GetClrPlanePrms','GetRpdPlnPrms'},'Exact two planes required')
        _starts(row['startpoints'])
        if row['operation_type']==1:require(row['startpoints']is None,'Finish packet must not contain rough starts')
        group='rough'if row['operation_type']==0 else'finish'
        expected={key for key,spec in _FIXED.items()if spec[0]in('all',group)}
        require(type(row['values'])is dict and set(row['values'])==expected,'Fixed packet getter key set differs')
        variants={key for key in expected if _FIXED[key][2]=='System.Object'}
        require(type(row['value_shapes'])is dict and set(row['value_shapes'])==variants,'Exact two object-return shapes required for rough, none for finish')
        self.values={key:materialize(row['values'][key],_FIXED[key],row['value_shapes'].get(key))for key in expected}
    def handle(self,role,interface='',index=None):return _Handle(self,role,interface,index)
    def _check(self,obj):require(type(obj)is _Handle and obj.owner is self,'Foreign replay object rejected')
    def typed(self,obj,name):
        self._check(obj)
        allowed={key.split('|')[1]for key in _FIXED if key.split('|')[0]==obj.role}
        allowed|={'operation':{'ICWOperation','ICWMillOperation','ICWMillOperation3'},'tool':{'ICWTool'},'feature':{'IDispatch'},'starts':{'ICWDispatchCollection'},'start':{'ICWStartPoint'},'position':{'ICWPosition'}}.get(obj.role,set())
        require(name in allowed,'Interface outside fixed retained role')
        return self.handle(obj.role,name,obj.index)
    def feature_dispatch(self,obj):self._check(obj);require(obj.role=='feature','Feature handle required');return obj
    def metadata(self,obj):
        self._check(obj);require(obj.role=='starts','Only start collection metadata permitted');return deepcopy(self.row['startpoints']['metadata'])
    def plane(self,obj,name,diagnostic):
        self._check(obj);require(obj.role=='nc'and name in('GetClrPlanePrms','GetRpdPlnPrms'),'Fixed plane getter required')
        v=deepcopy(self.row['planes'][name]);require(set(v)=={'distance_native','basis_raw','hresult','unit_binding_verified','enum_binding_verified','conversion_performed'},'Exact pointer-plane output required')
        v['distance_native']=scalar(v['distance_native'],'System.Double');v['basis_raw']=scalar(v['basis_raw'],'System.Int32')
        require(type(v['hresult'])is int and v['hresult']==0 and all(v[k]is False for k in ('unit_binding_verified','enum_binding_verified','conversion_performed')),'Successful unqualified raw plane output required')
        return v
    def read(self,obj,name,*args):
        self._check(obj);self.calls+=1;require(self.calls<=512,'Replay read budget exceeded')
        role=obj.role
        if role=='doc'and name=='GetCWObjectID':
            require(len(args)==1,'Identity argument required');self._check(args[0]);other=args[0]
            require(other.role in('feature','tool'),'Fixed identity role required');return (self.row['feature_native_id']if other.role=='feature'else self.row['tool_native_id'],True)
        links={('operation','IGetNCParam'):'nc',('operation','GetToolpathParam'):'toolpath',('operation','IGetLeadin'):'lead_in',('operation','IGetLeadout'):'lead_out',('operation','IGetTool'):'tool',('tool','IGetMillToolHolder'):'holder'}
        if (role,name)in links:
            require(args==((self.feature,)if name in('IGetLeadin','IGetLeadout')else()),'Exact retained getter arguments required');return self.handle(links[(role,name)])
        if role=='operation'and name=='GetSetupParameters':
            require(not args,'No setup arguments');return self.handle('transform'),self.handle('origin'),self.handle('axis')
        if role=='tool'and name in('IsMillTool','ToolType','CutDiameter','Protrusion'):
            require(not args,'No generic tool arguments');return self.generic[{'IsMillTool':'is_mill_tool','ToolType':'tool_type_raw','CutDiameter':'cut_diameter_native','Protrusion':'protrusion_native'}[name]]
        if role=='operation'and name=='GetStartPointList':
            require(args==(self.feature,),'Exact start feature required');return None if self.row['startpoints']is None else self.handle('starts')
        if role=='starts'and name=='Count':require(not args,'No count arguments');return len(self.row['startpoints']['rows'])
        if role=='starts'and name=='Item':
            require(len(args)==1 and type(args[0])is int and 0<=args[0]<len(self.row['startpoints']['rows']),'Start index outside packet');return self.handle('start',index=args[0])
        if role=='start':
            require(not args and name in('StartPointType','Position'),'Fixed start getter required');row=self.row['startpoints']['rows'][obj.index]
            return scalar(row['type'],'System.Int32')if name=='StartPointType'else(None if row['position']is None else self.handle('position',index=obj.index))
        if role=='position'and name=='GetCoordinates':require(not args,'No position arguments');return tuple(_vector(self.row['startpoints']['rows'][obj.index]['position']))
        key='|'.join((role,obj.interface,name));require(key in self.values,'Getter outside fixed packet')
        expected=(self.feature,)if _FIXED[key][1]=='feature'else()
        require(args==expected,'Getter arguments outside retained packet graph');self.used.add(key);return deepcopy(self.values[key])


def project_row(row):
    batch=PacketReplay(row);op,feature,setup=batch.operation,batch.feature,batch.setup
    out=dict(operation_native_id=row['operation_native_id'],feature_native_id=row['feature_native_id'],read_complete=False)
    pocket=reader.pocket
    out['levels']=pocket.read_levels(op,feature,read=batch.read,typed=batch.typed,feature_dispatch=batch.feature_dispatch)
    if row['operation_type']==0:
        out['rough']=pocket.rough.read_rough_entry_parameters(op,feature,read=batch.read,typed=batch.typed,diagnostic={})
        out['startpoints']=reader.guide.start.read_startpoints(op,feature,read=batch.read,typed=batch.typed,metadata=batch.metadata,diagnostic={})
    else:
        out['finish']=pocket.read_finish_parameters(op,feature,read=batch.read,typed=batch.typed)
        out['finish_fields']=reader.fields.read_cached_fields(batch,op,feature,{})
        out['protected_finish']=reader.protected.read_protected(op,feature,read=batch.read,typed=batch.typed,record=lambda *a:None)
        out['leads']=pocket.leads.read_lead_details(op,feature,read=batch.read,typed=batch.typed,lead_typed=lambda raw:batch.typed(raw,'ICWLeadInOut'))
    out['nc']=pocket.read_nc_settings(op,setup,read=batch.read,typed=batch.typed,pointer_read=batch.plane,diagnostic={},persist=lambda:None)
    generic,tool=reader.read_generic_tool(op,batch.doc,batch.read,batch.typed)
    require(reader.group.exact(generic,batch.generic),'Replay generic tool differs')
    out['tool']=reader.read_tool_dimensions(tool,generic,batch);out['read_complete']=True
    require(batch.used==set(batch.values),'Unconsumed fixed packet getter')
    return config.parameter_projection(out),dict(replayed_getters=batch.calls,fixed_getters_used=len(batch.used),typed_outputs_materialized=True,original_variant_tag_verified=False,native_calls=0)


def project_packet(packet,request):
    """Project a checked host packet; native host/provenance remains caller-owned."""
    require(type(packet)is dict and type(request)is dict,'Packet and sealed request objects required')
    for k,v in {'schema_version':SCHEMA,'scope':SCOPE,'engine_version':ENGINE,'status':'observed','read_only':True,'mutation_attempted':False,'readback_verified':True,'binding_complete':True,'parameter_groups_complete':True,'full_snapshot_complete':False,'original_variant_tag_verified':False,'stage':'finished'}.items():
        require(k in packet and reader.group.exact(packet[k],v),'Host packet terminal contract differs: '+k)
    require(not any(k in packet for k in ('error_type','message','hresult')),'Error packet cannot be projected')
    request_keys={'schema_version','profile','expected_process_id','expected_document_path','cam_addin_clsid','expected_sw_configuration','expected_cam_configuration','expected_operation_ids','feature_ids','feature_setup_id','parameter_targets'}
    require(set(request)==request_keys and type(request['schema_version'])is int and request['schema_version']==2 and request['profile']=='mill_snapshot','Exact snapshot request profile required')
    require(type(packet.get('validated_request'))is dict and reader.group.exact(packet['validated_request'],request),'Host validated request echo differs')
    require(type(request['cam_addin_clsid'])is str and request['cam_addin_clsid'].upper()==CAM_CLASS,'Fixed vendor CAM class required')
    _ids(request['expected_operation_ids'],64,1);_ids(request['feature_ids'],8,1);_integer(request['feature_setup_id'],1);_integer(request['expected_process_id'],1)
    require(type(packet['process_id'])is int and packet['process_id']==request['expected_process_id'],'Host PID differs')
    require(reader.group.exact(packet['document_before'],packet['document_after']),'Host document boundary differs')
    doc=packet['document_before'];require(doc['path'].replace('/','\\').lower()==request['expected_document_path'].replace('/','\\').lower()and doc['configuration']==request['expected_sw_configuration']and type(doc['type'])is int and doc['type']==1 and type(doc['needs_save'])is bool,'Host document identity differs')
    configuration=packet['configuration_before'];require(configuration=={'name':request['expected_cam_configuration'],'object_name':request['expected_cam_configuration'],'sw_name':request['expected_sw_configuration']},'Host configuration differs')
    binding=project_binding(packet['binding']);targets=request['parameter_targets'];rows=packet['parameters']
    require(type(targets)is list and type(rows)is list and 1<=len(rows)==len(targets)<=16,'Bounded complete parameter groups required')
    require([x['native_id']for x in binding['operations']]==request['expected_operation_ids'],'Host route differs')
    require(set(binding['features'])=={str(i)for i in request['feature_ids']},'Host feature set differs')
    operations={x['native_id']:x for x in binding['operations']};seen=set();result=[];diagnostics=[];tools={}
    keys={'operation_native_id','feature_native_id','operation_type','tool_native_id','setup_native_id'}
    for row,target in zip(rows,targets):
        require(type(target)is dict and set(target)==keys and all(type(target[k])is int for k in keys),'Exact target fields required')
        require(type(row)is dict and set(row)==keys|{'generic_tool','values','value_shapes','startpoints','planes'},'Exact parameter packet row required')
        require(all(type(row[k])is int and row[k]==target[k]for k in keys),'Packet target mapping differs')
        require(row['operation_type']in(0,1)and all(row[k]>0 for k in keys-{'operation_type'}),'Positive target identities and rough/finish kind required')
        require(row['feature_native_id']in request['feature_ids']and str(row['feature_native_id'])in binding['features'],'Target feature is outside checked feature inventory')
        oid=row['operation_native_id'];require(oid in operations and oid not in seen,'Unique current target required');seen.add(oid)
        op=operations[oid];require(op['linked_feature_ids']==[row['feature_native_id']]and op['mill_operation_type']==row['operation_type']and op['setup_native_id']==row['setup_native_id'],'Parameter binding differs')
        generic=_generic(row['generic_tool']);require(reader.group.exact(generic,op['assigned_tool'])and generic['native_id']==row['tool_native_id'],'Packet tool differs from binding')
        projected,diagnostic=project_row(row);tid=row['tool_native_id']
        if tid in tools:require(reader.group.exact(tools[tid],projected['tool']),'Shared tool dimensions drift')
        tools[tid]=deepcopy(projected['tool']);result.append(projected);diagnostics.append(diagnostic)
    require([request['expected_operation_ids'].index(t['operation_native_id'])for t in targets]==sorted(request['expected_operation_ids'].index(t['operation_native_id'])for t in targets),'Parameter target order differs from route')
    return dict(snapshot={'binding':binding,'parameters':result},diagnostic=dict(scope='MILL_PACKET_SEMANTIC_MATERIALIZATION_V1',semantic_projection_complete=True,
        typed_outputs_materialized=True,embedded_reader_counters_describe_replay=True,python_shape_materialized_not_directly_observed=True,python_sequence_representation='tuple materialized from declared out signatures or retained CLR array shape',
        original_variant_tag_verified=False,validated_request_echo_matches=True,request_echo_means_parser_acceptance_only=True,native_calls=0,parameter_groups=diagnostics,production_qualified=False,host_native_compatibility_qualified=False))
