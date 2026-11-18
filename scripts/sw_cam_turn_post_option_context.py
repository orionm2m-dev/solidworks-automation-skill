"""One bounded TURN operation post-option list read; no scalar reread or mutation."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import math
from scripts import sw_cam_turn_entry_context as core
from scripts.sw_cam import _member
from scripts.sw_cam_comtypes import _load_type_library
from scripts.sw_cam_thread import _file_hash
from scripts.sw_cam_generation import _write_receipt

SCOPE='TURN_OPERATION_POST_OPTION_READ_V1'
INDEX_POLICY='sdk_dispatch_collection_zero_based'
COLLECTION='ICWDispatchCollection'
PARAMETER='ICWPostOperationParam'
IIDS={'ICWOperation':'{4EDDCA73-325A-11D6-A9A7-00062999E55F}',
      COLLECTION:'{670DD771-2C33-11D6-A9A1-00062999E55F}',
      PARAMETER:'{DC0FCD90-CDFB-49F7-8A4D-3C237678BE2E}'}
SHARED_READS={'IGetActiveDoc','GetDocType','IGetMachine','MachType','IGetEnumSetups',
              'IGetEnumFeatures','Count','Item','IGetEnumOpSetups','IGetEnumOperations',
              'GetIsToolpathGenerated','IGetEnumToolpaths','RecordCount','OpernType',
              'IGetWorkpiece','GetTurnWorkpieceType','GetCWObjectID','IGetAllFeatures'}
EXTRA_READS={'GetPostOptionParamList','GetTypeInfo','GetTypeAttr','GetDocumentation',
             'QueryInterface','PostParamName','PostParamValue','ParamsCount','PostParamValueList'}
FIELDS=(core.FIELDS-{'post_parameter_index_policy'})|{'collection_index_policy'}
require=core.require


def validate(v):
    require(type(v) is dict and set(v)==FIELDS,'Exact post-option read request required')
    require(v['collection_index_policy']==INDEX_POLICY,'Explicit SDK dispatch-collection index policy required')
    require(type(v['targets']) is list and len(v['targets'])==1,'One selected FACE operation required')
    inherited={k:x for k,x in v.items() if k!='collection_index_policy'}
    inherited['post_parameter_index_policy']='probe_zero_through_count_inclusive'
    # Reuse identity/path/source/receipt/selector checks only; no inherited scalar reads.
    return core.validate(inherited)


def preflight(tlb):
    from ctypes import HRESULT, POINTER, c_int
    from comtypes import BSTR
    from comtypes.automation import IDispatch, VARIANT
    library=_load_type_library(str(tlb))
    classes={name:getattr(library,name) for name in IIDS}
    for name,iid in IIDS.items():require(str(classes[name]._iid_).upper()==iid,'Post-option interface IID mismatch: '+name)
    specs=[('ICWOperation','GetPostOptionParamList',60,(POINTER(POINTER(IDispatch)),),(10,),False),
           (COLLECTION,'_get_Count',1,(POINTER(c_int),),(10,),True),
           (COLLECTION,'Item',0,(c_int,POINTER(POINTER(IDispatch))),(1,10),False),
           (PARAMETER,'_get_PostParamName',1,(POINTER(BSTR),),(10,),True),
           (PARAMETER,'_get_PostParamValue',2,(POINTER(BSTR),),(10,),True),
           (PARAMETER,'_get_PostParamValueList',3,(POINTER(VARIANT),),(10,),True),
           (PARAMETER,'_get_ParamsCount',4,(POINTER(c_int),),(10,),True)]
    for owner,name,dispid,args,flags,prop in specs:
        methods=[m for m in classes[owner]._methods_ if m.name==name]
        require(len(methods)==1,'Unique public post-option getter required')
        m=methods[0]
        require(m.restype is HRESULT and m.idlflags[0]==dispid and m.argtypes==args
                and tuple(x[0] for x in m.paramflags)==flags and ('propget' in m.idlflags)==prop
                and 'propput' not in m.idlflags,'Post-option getter ABI mismatch: '+owner+'.'+name)
    return classes,dict(interfaces=IIDS,getter_count=len(specs),native_calls=0,
        application_connections=0,returned_collection_type_qualified=False)


def text(value,allow_empty=False):
    require(type(value) is str and len(value)<=4096 and (allow_empty or bool(value.strip())),
            'Bounded actual BSTR required')
    return value


def variant_value(raw):
    """Preserve supported converted values without guessing a choice-list type."""
    budget={'nodes':0,'characters':0}
    def decode(value,depth):
        budget['nodes']+=1;require(budget['nodes']<=128 and depth<=2,'VARIANT structure exceeds bound')
        if value is None or type(value) is bool:return value
        if type(value) is str:
            require(len(value)<=4096,'VARIANT string exceeds bound');budget['characters']+=len(value)
            require(budget['characters']<=65536,'VARIANT text exceeds total bound');return value
        if type(value) is int:
            require(-2**63<=value<2**64,'VARIANT integer exceeds supported range');return value
        if type(value) is float:
            require(math.isfinite(value),'Nonfinite VARIANT value');return value
        if type(value) in (tuple,list):
            require(len(value)<=32,'VARIANT sequence exceeds bound')
            return [decode(x,depth+1) for x in value]
        raise ValueError('Unsupported converted VARIANT type: '+type(value).__name__)
    return dict(converted_type=type(raw).__name__,value=decode(raw,0),native_variant_metadata_preserved=False)


def read_options(operation,*,read,typed,metadata,progress):
    row=dict(rows=[],collection_type_verified=False,collection_index_policy=INDEX_POLICY,
             scalar_post_parameters_reread=False,face_or_NC_scalars_reread=False,
             catalog_complete=False,home_point_verified=False,units_verified=False,
             option_value_semantics_verified=False,complete=False)
    progress(row)
    raw=read(operation,'GetPostOptionParamList')
    row['list_returned']=True
    if raw is None or not bool(raw):
        row.update(list_is_null=True,collection_count_native=None,complete=True,
                   reason='NATIVE_POST_OPTION_LIST_NULL_NOT_PROOF_OF_GENERAL_HOME_ABSENCE')
        progress(row);return row
    row['list_is_null']=False
    row['collection_type_info']=metadata(raw);progress(row)
    require(row['collection_type_info']['guid']==IIDS[COLLECTION],
            'Returned list metadata does not identify ICWDispatchCollection')
    collection=typed(raw,COLLECTION);row['collection_type_verified']=True
    count=core.integer(read(collection,'Count'),0,32,'post-option collection count')
    row['collection_count_native']=count;progress(row)
    for index in range(count):
        item=typed(read(collection,'Item',index),PARAMETER)
        entry=dict(index=index);row['rows'].append(entry);progress(row)
        entry['name_raw']=text(read(item,'PostParamName'));progress(row)
        entry['value_raw']=text(read(item,'PostParamValue'),allow_empty=True);progress(row)
        entry['params_count_raw']=core.integer(read(item,'ParamsCount'),0,32,'post-option ParamsCount');progress(row)
        entry['value_list_raw']=variant_value(read(item,'PostParamValueList'));progress(row)
        entry['complete']=True;progress(row)
    require(core.integer(read(collection,'Count'),0,32,'post-option collection recheck')==count,
            'Post-option collection count changed')
    row.update(complete=True,reason='BOUNDED_NATIVE_POST_OPTIONS_OBSERVED_NO_HOME_INFERENCE')
    progress(row);return row


class NativePostOptions(core.NativeRead):
    """Reuse one context, source/lifetime/events and full inventory comparisons."""
    def read(self,obj,name,*args):
        if name in SHARED_READS:
            return super().read(obj,name,*args)
        require(name in EXTRA_READS,'Post-option getter allowlist violation: '+str(name))
        if name=='QueryInterface':
            require(len(args)==1 and any(args[0] is self.classes[n] for n in (COLLECTION,PARAMETER)),
                    'Only exact preflighted post-option public QI allowed')
        self.check();self.report['phase']=name;self.report['native_read_count']+=1
        require(self.report['native_read_count']<=4096,'Native read bound exceeded')
        value=_member(obj,name,*args);self.check();return value

    def typed_option(self,obj,name):
        require(name in (COLLECTION,PARAMETER),'Interface outside post-option scope')
        require(obj is not None and bool(obj),'Non-null public option object required')
        value=self.read(obj,'QueryInterface',self.classes[name])
        require(value is not None and bool(value) and isinstance(value,self.classes[name]),'Exact public option QI failed')
        return value

    def metadata(self,obj):
        info=self.read(obj,'GetTypeInfo',0)
        require(info is not None and bool(info),'Returned list type information required')
        attr=self.read(info,'GetTypeAttr')
        row=dict(guid=str(attr.guid).upper(),typekind=int(attr.typekind),member_count=int(attr.cFuncs))
        docs=self.read(info,'GetDocumentation',-1)
        require(type(docs) in (tuple,list) and len(docs)==4,'Public type documentation tuple required')
        row['name']=text(docs[0]);return row

    def selected(self,target,progress):
        self.boundary()
        result=read_options(self.handles[target['operation_native_id']],read=self.read,
                            typed=self.typed_option,metadata=self.metadata,progress=progress)
        self.boundary();return result


def inspect_turn_post_options(sw,clsid,typelib_path,values,*,runtime_check):
    v=deepcopy(values);source,out=validate(v);classes,abi=preflight(typelib_path)
    pins=[dict(path=str(Path(p).resolve()),sha256=_file_hash(p)) for p in
          (str(source),str(typelib_path),__file__,core.__file__)]
    report=dict(scope=SCOPE,status='started',phase='preflight',request=v,read_only=True,may_continue=False,
                mutation_attempted=False,parameter_setter_attempted=False,GTP_attempted=False,GOP_attempted=False,
                save_attempted=False,model_saved=False,export_attempted=False,readback_verified=False,
                observation_verified=False,catalog_complete=False,home_point_verified=False,
                units_verified=False,coordinate_frame_verified=False,production_qualified=False,
                native_read_count=0,observations=[],pins=pins,getter_abi=abi,
                scalar_post_parameters_reread=False,face_or_NC_scalars_reread=False,
                automatic_retry_permitted=False,bootstrap_scope='GetAddInObject/GetCWApp only before events',
                collection_type_qualification='One public metadata+QI attempt; no alternate interface or index fallback')
    backend=NativePostOptions(sw,clsid,typelib_path,v,report,classes,pins,runtime_check)
    _write_receipt(out,report,create=True)
    result=core.run_read(v,report,backend,lambda:_write_receipt(out,report))
    if result['observation_verified']:
        result['reason']='RAW_OPERATION_POST_OPTIONS_REQUIRE_SEMANTIC_REVIEW';_write_receipt(out,result)
    return result