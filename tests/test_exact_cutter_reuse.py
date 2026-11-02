from copy import deepcopy
from pathlib import Path
import os,sys
import pytest
ROOT=Path(os.environ.get('SOLIDWORKS_SKILL_ROOT',Path(__file__).resolve().parents[1]));sys.path.insert(0,str(ROOT))
import scripts
if not(ROOT/'scripts/sw_cam_exact_cutter_reuse.py').is_file():scripts.__path__.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scripts import sw_cam_exact_cutter_reuse as m

TARGET={'CutDiameter':2.,'EffCutlength':6.,'ShoulderLength':6.,'ShankLength':8.,'NoOfFlutes':4,
    'ShoulderDia':2.,'ShankDia':4.,'MillToolShankType':1,'OverallLen':40.,'Protrusion':20.}
IDENTITY={'ToolVendor':'OSG','ToolIdentifier':'3130520'}

def fixture():
    profile={'status':'observed','declared_chain_count':1,'chains':[{'read_complete':True,'declared_curve_count':1,'curves':[{'read_complete':True}]}]}
    def row(oid,identity,loc):
        vals=dict(TARGET,EffCutlength=loc)
        full={'geometry_read_complete':True,'profile_complete':True,'profiles':{k:deepcopy(profile)for k in ('tool','shank','holder')},
            'tool_native_id':oid,'tool_type_raw':1,'cut_diameter_native':2.,'tool_protrusion_native':20.,
            'mill_tool':{'type_raw':1,'subtype_raw':3,'end_radius_native':0.}}
        from scripts.sw_cam_shared_cutter_geometry import FIELDS
        for name,section,key in FIELDS:
            (full[section]if section else full)[key]=vals[name]
        return {'native_id':oid,'identity':{'ToolVendor':'OSG','ToolIdentifier':identity},'full_tool':full}
    return ([{'native_id':i,'tool_type_raw':1,'CutDiameter':2.}for i in (145,273)],
        [row(145,'404-078711',7.),row(273,'3133020',3.)])

def call(cat,rows,**kw):return m.require_new_exact_cutter(cat,rows,IDENTITY,TARGET,**kw)

def test_same_diameter_different_complete_geometry_allowed():
    cat,rows=fixture();assert call(cat,rows)['distinct_existing_ids']==[145,273]

@pytest.mark.parametrize('kind',['exact_identity','identity_alias','equivalent_body','same_body_other_holder','missing_read','reversed','wrong_id','missing_profile'])
def test_duplicates_and_incomplete_read_stop(kind):
    cat,rows=fixture();kw={}
    if kind=='exact_identity':rows[1]['identity']=deepcopy(IDENTITY)
    elif kind=='identity_alias':kw['accepted_identity_aliases']=[deepcopy(rows[1]['identity'])]
    elif kind in ('equivalent_body','same_body_other_holder'):
        rows[1]['full_tool']['mill_tool']['effective_cutting_length_native']=6.
        if kind=='same_body_other_holder':rows[1]['full_tool']['tool_protrusion_native']=26.
    elif kind=='missing_read':rows.pop()
    elif kind=='reversed':rows.reverse()
    elif kind=='wrong_id':rows[1]['full_tool']['tool_native_id']=999
    elif kind=='missing_profile':rows[1]['full_tool']['profiles']['shank']['chains']=[]
    with pytest.raises(ValueError):call(cat,rows,**kw)


def test_missing_vendor_with_distinct_complete_body_is_explicit_unknown():
    cat,rows=fixture();rows[0]['identity']['ToolVendor']=''
    result=call(cat,rows)
    assert result['identity_unknown_ids']==[145]and result['physical_identity_verified']is False

@pytest.mark.parametrize('same_identifier',[False,True])
def test_missing_vendor_never_allows_same_body_or_known_identifier(same_identifier):
    cat,rows=fixture();rows[1]['identity']['ToolVendor']=''
    if same_identifier:rows[1]['identity']['ToolIdentifier']='3130520'
    else:rows[1]['full_tool']['mill_tool']['effective_cutting_length_native']=6.
    with pytest.raises(ValueError):call(cat,rows)
