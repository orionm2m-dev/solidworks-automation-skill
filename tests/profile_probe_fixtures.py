from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_mill_profile_headers as m

@pytest.fixture
def feature():
    owner=N(id=69)
    base=N(id=79,GetOwner=lambda:owner,Suppressed=False)
    mill=N(VolumeType=2,Shape=2,IGetIslandCount=lambda:5)
    profile=N(GetSketchCount=lambda:5,
        GetSketchNameList=lambda:tuple('Sketch'+str(i) for i in range(5)),
        GetEndCondition1=lambda:(2.,1,'Top',False),
        GetEndCondition2=lambda:(-1.,2,'Bottom',True))
    doc=N(GetCWObjectFromID=lambda kind,oid:(base,True),GetCWObjectID=lambda obj:(obj.id,True))
    selected=dict(feature_native_id=79,owner_setup_native_id=69,
                  volume_type=2,shape=2,island_count=5,include_contours=False)
    calls=[]
    def read(obj,name,*args):
        calls.append((obj,name,args))
        value=getattr(obj,name)
        return value(*args) if callable(value) else value
    def typed(raw,name):
        calls.append((raw,'QI '+name,()))
        if name=='ICWMillFeature':return mill
        if name=='ICWProfileFeature':return profile
        return raw
    diagnostic={}
    progress=Mock()
    def run():return m.read_profile_feature_headers(doc,selected=selected,read=read,
        typed=typed,diagnostic=diagnostic,progress=progress)
    return N(**locals())

