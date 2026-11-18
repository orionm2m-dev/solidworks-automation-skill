"""固定读取 MILL setup transform 的原始分量；不推断 CL/world 映射。"""
from ctypes import POINTER,byref,c_double,c_short,HRESULT
from ctypes.wintypes import VARIANT_BOOL
import math
from comtypes.automation import IDispatch
from scripts.sw_cam_comtypes import _interface_class
from scripts import sw_cam_virtual_feature_observation as metadata_reader

INTERFACES=('ICWTransform','ICWVector','ICWPosition','ICWUnitVector')
IIDS={'ICWTransform':'{9DA5A2DD-7E9A-4D87-BEB7-848B3BECF9F8}',
    'ICWVector':'{7ECF7B73-C8B6-462B-9123-3C52206B502D}',
    'ICWPosition':'{E7807F27-04D2-48A3-91AF-6DB704DBCC9C}',
    'ICWUnitVector':'{51E2211D-ED7A-4EE4-942F-2850614BA0F3}'}
RAW_SETUP='_ICWMillOperation3__com_GetSetupParameters'
RAW_DATA='_ICWTransform__com_GetData'
RAW_COORDS={name:'_'+name+'__com_GetCoordinates' for name in INTERFACES[1:]}
RAW_READS=(RAW_SETUP,RAW_DATA,*RAW_COORDS.values(),metadata_reader.RAW_INFO_COUNT,
    metadata_reader.RAW_INFO,metadata_reader.RAW_ATTR,metadata_reader.RAW_DOC)
require=metadata_reader.require


def preflight(tlb):
    """仅固定厂商 getter 和复用的标准 type-info ABI；不连接原生对象。"""
    metadata_reader.preflight(tlb)
    dispatch=POINTER(POINTER(IDispatch))
    specs=[('ICWMillOperation3','{20DEC8D6-8B4F-4876-90CB-F2A8D87A9D78}','GetSetupParameters',24,(dispatch,)*3,(2,)*3,RAW_SETUP),
        ('ICWTransform',IIDS['ICWTransform'],'GetData',3,(dispatch,)*4+(POINTER(c_double),POINTER(VARIANT_BOOL)),(2,)*6,RAW_DATA)]
    specs.extend((name,IIDS[name],'GetCoordinates',1,(POINTER(c_double),)*3,(2,)*3,RAW_COORDS[name]) for name in INTERFACES[1:])
    for name,iid,method,disp,args,flags,raw in specs:
        cls=_interface_class(name,tlb);rows=[x for x in cls._methods_ if x.name==method]
        require(str(cls._iid_).upper()==iid and len(rows)==1,'Exact setup interface/member required: '+method)
        m=rows[0]
        require(m.restype is HRESULT and m.argtypes==args and tuple(x[0] for x in m.paramflags)==flags
            and m.idlflags[0]==disp and not any(x in m.idlflags for x in ('propget','propput','propputref'))
            and callable(getattr(cls,raw,None)),'Exact setup raw getter ABI required: '+method)
    return dict(native_calls=0,raw_owned_OUT_buffers=True,coordinate_getters=3,transform_out_vectors=4,CL_world_mapping_declared=False)


def read_setup_transform(operation,*,typed,raw_call,row,boundary):
    """一次固定 setup/GetData/六个坐标 getter；每个指针先检查准确类型。"""
    row.update(parameters_complete=False,setup_transform_complete=False,setup_call={},coordinate_frame_verified=False,
        generic_CL_frame_verified=False,units_verified=False,coordinates_normalized=False)
    call=metadata_reader.call;presence=metadata_reader.presence
    owner=typed(operation,'ICWMillOperation3');setup=[POINTER(IDispatch)() for _ in range(3)]
    names=('transform','origin','axis')
    if not call(owner,RAW_SETUP,tuple(byref(x) for x in setup),row['setup_call'],
            lambda:{name:presence(x) for name,x in zip(names,setup)},raw_call,boundary):
        row['outcome']='setup_getter_diagnostic';return
    def exact(raw,name,diag):
        if not raw:diag['outcome']='null_interface';boundary();return None
        diag['metadata']={}
        if not metadata_reader.metadata(raw,typed=typed,raw_call=raw_call,boundary=boundary,row=diag['metadata']):
            diag['outcome']='metadata_unavailable';return None
        if diag['metadata']['guid']!=IIDS[name]:diag['outcome']='unadmitted_interface_guid';boundary();return None
        diag['interface']=name;diag['interface_query_attempted']=True
        value=typed(raw,name);diag['interface_query_returned']=True;return value
    row['transform_interface']={};transform=exact(setup[0],'ICWTransform',row['transform_interface'])
    if transform is None:row['outcome']='setup_transform_interface_diagnostic';return
    vectors=[POINTER(IDispatch)() for _ in range(4)];scale=c_double(float('nan'));flag=VARIANT_BOOL();c_short.from_buffer(flag).value=12345
    row['data_call']={};vector_names=('x_axis','y_axis','z_axis','translation')
    def outputs():return dict(vectors={name:presence(x) for name,x in zip(vector_names,vectors)},
        scale_raw=scale.value if math.isfinite(scale.value) else None,scale_finite=math.isfinite(scale.value),rotate_short=c_short.from_buffer(flag).value)
    if not call(transform,RAW_DATA,tuple(byref(x) for x in [*vectors,scale,flag]),row['data_call'],outputs,raw_call,boundary):
        row['outcome']='transform_data_diagnostic';return
    require(math.isfinite(scale.value),'Finite raw transform scale required')
    rotate=c_short.from_buffer(flag).value;require(rotate in (0,-1),'Populated VARIANT_BOOL transform flag required')
    row['transform_components']=dict(scale_raw=scale.value,rotate_raw=rotate==-1,vectors={})
    def coordinates(raw,name,diag):
        obj=exact(raw,name,diag)
        if obj is None:return False
        values=[c_double(float('nan')) for _ in range(3)];diag['coordinate_call']={}
        def observed():return dict(raw=[x.value if math.isfinite(x.value) else None for x in values],finite=[math.isfinite(x.value) for x in values])
        if not call(obj,RAW_COORDS[name],tuple(byref(x) for x in values),diag['coordinate_call'],observed,raw_call,boundary):
            diag['outcome']='coordinate_getter_diagnostic';return False
        require(all(math.isfinite(x.value) for x in values),'Three populated finite coordinates required')
        diag.update(coordinates_raw=[x.value for x in values],outcome='typed_raw_coordinates');boundary();return True
    for name,raw in zip(vector_names,vectors):
        diag={};row['transform_components']['vectors'][name]=diag
        if not coordinates(raw,'ICWVector',diag):row['outcome']='transform_vector_diagnostic';return
    row['origin']={};row['axis']={}
    if not coordinates(setup[1],'ICWPosition',row['origin']):row['outcome']='setup_origin_diagnostic';return
    if not coordinates(setup[2],'ICWUnitVector',row['axis']):row['outcome']='setup_axis_diagnostic';return
    row.update(setup_transform_complete=True,outcome='typed_setup_transform_components_observed');boundary()
