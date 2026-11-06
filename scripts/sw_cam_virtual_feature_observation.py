"""固定虚拟孔集合观察；不读取成员几何，不自动发现其它接口。"""
from ctypes import POINTER,byref,c_int,c_long,c_ulong,HRESULT
from comtypes import IUnknown,BSTR,COMError
from comtypes.automation import IDispatch
from comtypes.typeinfo import ITypeInfo,TYPEATTR
from scripts.sw_cam import _member,_error
from scripts.sw_cam_comtypes import _interface_class

COLLECTION_IID='{670DD771-2C33-11D6-A9A1-00062999E55F}'
RAW_VIRTUAL='_ICWOperation__com_IGetAllVirtualHoleFeatures'
RAW_COUNT='_ICWDispatchCollection__com__get_Count'
RAW_ITEM='_ICWDispatchCollection__com_Item'
RAW_INFO_COUNT='_IDispatch__com_GetTypeInfoCount'
RAW_INFO='_IDispatch__com_GetTypeInfo'
RAW_ATTR='_ITypeInfo__com_GetTypeAttr'
RAW_DOC='_ITypeInfo__com_GetDocumentation'
RAW_RELEASE='_ITypeInfo__com_ReleaseTypeAttr'
RAW_READS=(RAW_VIRTUAL,RAW_COUNT,RAW_ITEM,RAW_INFO_COUNT,RAW_INFO,RAW_ATTR,RAW_DOC)


def require(condition,message):
    if not condition:raise ValueError(message)


def preflight(tlb):
    """验证厂商与标准 COM 的确切 ABI；不接触应用程序。"""
    specs=[(_interface_class('ICWOperation',tlb),'{4EDDCA73-325A-11D6-A9A7-00062999E55F}','IGetAllVirtualHoleFeatures',30,(POINTER(POINTER(IDispatch)),),(10,),RAW_VIRTUAL,False),
        (_interface_class('ICWDispatchCollection',tlb),COLLECTION_IID,'_get_Count',1,(POINTER(c_int),),(10,),RAW_COUNT,True),
        (_interface_class('ICWDispatchCollection',tlb),COLLECTION_IID,'Item',0,(c_int,POINTER(POINTER(IDispatch))),(1,10),RAW_ITEM,False),
        (IDispatch,'{00020400-0000-0000-C000-000000000046}','GetTypeInfoCount',None,(POINTER(c_ulong),),(2,),RAW_INFO_COUNT,False),
        (IDispatch,'{00020400-0000-0000-C000-000000000046}','GetTypeInfo',None,(c_ulong,c_ulong,POINTER(POINTER(IUnknown))),(1,1,2),RAW_INFO,False),
        (ITypeInfo,'{00020401-0000-0000-C000-000000000046}','GetTypeAttr',None,(POINTER(POINTER(TYPEATTR)),),(2,),RAW_ATTR,False),
        (ITypeInfo,'{00020401-0000-0000-C000-000000000046}','GetDocumentation',None,(c_long,POINTER(BSTR),POINTER(BSTR),POINTER(c_ulong),POINTER(BSTR)),(1,2,2,2,2),RAW_DOC,False),
        (ITypeInfo,'{00020401-0000-0000-C000-000000000046}','ReleaseTypeAttr',None,(POINTER(TYPEATTR),),(1,),RAW_RELEASE,False)]
    for cls,iid,name,disp,args,flags,raw,prop in specs:
        methods=[m for m in cls._methods_ if m.name==name]
        require(str(cls._iid_).upper()==iid and len(methods)==1,'Exact metadata interface/member required: '+name)
        m=methods[0]
        require(m.restype is (None if raw==RAW_RELEASE else HRESULT) and m.argtypes==args and tuple(x[0] for x in m.paramflags)==flags
            and (disp is None and not m.idlflags or disp is not None and m.idlflags[0]==disp)
            and ('propget' in m.idlflags)==prop and not any(x in m.idlflags for x in ('propput','propputref')) and callable(getattr(cls,raw,None)),
            'Exact raw metadata getter ABI required: '+name)
    return dict(native_calls=0,raw_owned_OUT_buffers=True,maximum_members=8,exact_collection_guid=COLLECTION_IID,member_geometry_read=False)


def presence(value):
    return dict(present=bool(value),address_recorded=False)


def call(obj,name,args,row,observe,raw_call,boundary):
    """COM 失败或 S_FALSE 只留下该固定调用的观察；其它状态停止。"""
    try:status=raw_call(obj,name,args,row,observe)
    except COMError:
        boundary();row['outcome']='COM_failure';return False
    require(type(status) is int,'Exact integer HRESULT required')
    if status==1:row['outcome']='status1_diagnostic';boundary();return False
    require(status==0,'Unsupported raw getter HRESULT')
    return True


def metadata(dispatch,*,typed,raw_call,boundary,row):
    """标准 IDispatch 元数据；TYPEATTR 在所有退出路径即时释放。"""
    row.update(complete=False,count_call={});count=c_ulong(0xFFFFFFFF)
    if not call(dispatch,RAW_INFO_COUNT,(byref(count),),row['count_call'],lambda:dict(type_info_count=count.value),raw_call,boundary):return False
    require(count.value in (0,1),'TypeInfoCount must be exactly zero or one')
    if count.value==0:row['outcome']='type_info_unavailable';boundary();return False
    unknown=POINTER(IUnknown)();row['info_call']={}
    if not call(dispatch,RAW_INFO,(0,0,byref(unknown)),row['info_call'],lambda:dict(type_info=presence(unknown)),raw_call,boundary):return False
    if not unknown:row['outcome']='null_type_info';boundary();return False
    row['interface_call']=dict(interface='ITypeInfo',attempted=True,returned=False)
    try:info=typed(unknown,'ITypeInfo')
    except Exception as exc:row['interface_call']['issue']=_error(exc);raise
    row['interface_call']['returned']=True
    attr=POINTER(TYPEATTR)();row['attribute_call']={}
    def attr_out():
        return dict(present=bool(attr),guid=str(attr.contents.guid).upper() if attr else None,typekind_raw=int(attr.contents.typekind) if attr else None)
    try:
        okay=call(info,RAW_ATTR,(byref(attr),),row['attribute_call'],attr_out,raw_call,boundary)
        if not okay:return False
        if not attr:row['outcome']='null_type_attributes';return False
        values=attr_out();row.update(guid=values['guid'],typekind_raw=values['typekind_raw'])
    finally:
        if attr:
            # 清理已拥有的内存不受事后事件门禁阻挡；此处不再获取 CAM 数据。
            release=row['attribute_release']=dict(attempted=True,returned=False)
            try:_member(info,RAW_RELEASE,attr);release['returned']=True
            except Exception as exc:release['issue']=_error(exc);raise
    boundary()
    name=BSTR();doc=BSTR();helpfile=BSTR();helpcontext=c_ulong();row['documentation_call']={}
    def documentation_out():
        value=name.value
        return dict(type_name=(value or '')[:256],name_present=value is not None,name_truncated=value is not None and len(value)>256)
    if not call(info,RAW_DOC,(-1,byref(name),byref(doc),byref(helpcontext),byref(helpfile)),row['documentation_call'],documentation_out,raw_call,boundary):return False
    row.update(**documentation_out(),complete=True,outcome='declared_type_metadata');boundary();return True


def read_virtual_features(operation,*,typed,raw_call,row,boundary):
    """只在已观察到确切集合 GUID 后读取有界 Count/Item。"""
    row.update(parameters_complete=False,virtual_collection_complete=False,virtual_call={},members=[])
    pointer=POINTER(IDispatch)()
    if not call(operation,RAW_VIRTUAL,(byref(pointer),),row['virtual_call'],lambda:dict(collection=presence(pointer)),raw_call,boundary):
        row['outcome']='virtual_getter_diagnostic';return
    if not pointer:row['outcome']='null_virtual_collection';boundary();return
    row['collection_metadata']={}
    if not metadata(pointer,typed=typed,raw_call=raw_call,boundary=boundary,row=row['collection_metadata']):row['outcome']='virtual_collection_metadata_unavailable';return
    if row['collection_metadata']['guid']!=COLLECTION_IID:row['outcome']='unadmitted_collection_guid';boundary();return
    row['collection_interface_call']=dict(interface='ICWDispatchCollection',attempted=True,returned=False)
    try:collection=typed(pointer,'ICWDispatchCollection')
    except Exception as exc:row['collection_interface_call']['issue']=_error(exc);raise
    row['collection_interface_call']['returned']=True
    count=c_int(-1);row['count_call']={}
    if not call(collection,RAW_COUNT,(byref(count),),row['count_call'],lambda:dict(count=count.value),raw_call,boundary):row['outcome']='collection_count_diagnostic';return
    require(0<=count.value<=8,'Virtual collection Count must be bounded zero through eight');row['count']=count.value
    for index in range(count.value):
        boundary();member=POINTER(IDispatch)();item=dict(index=index,item_call={},metadata={});row['members'].append(item)
        if not call(collection,RAW_ITEM,(index,byref(member)),item['item_call'],lambda:dict(member=presence(member)),raw_call,boundary):row['outcome']='collection_item_diagnostic';return
        if not member:item['outcome']='null_member';row['outcome']='null_virtual_member';boundary();return
        if not metadata(member,typed=typed,raw_call=raw_call,boundary=boundary,row=item['metadata']):row['outcome']='member_metadata_unavailable';return
        item['outcome']='member_type_observed'
    row.update(virtual_collection_complete=True,outcome='observed_empty_virtual_collection' if count.value==0 else 'bounded_virtual_member_metadata');boundary()
