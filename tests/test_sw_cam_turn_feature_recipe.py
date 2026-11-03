"""Read-only recipe metadata checks with real bounded helpers and synthetic native objects."""
from types import SimpleNamespace as N
from unittest.mock import Mock
import pytest
from scripts import sw_cam_turn_feature_recipe as cam
from scripts import sw_cam_turn_feature_attribute as attribute


class Collection:
    def __init__(self, rows): self.rows = rows
    @property
    def Count(self): return len(self.rows)
    def Item(self, index): return self.rows[index]


@pytest.fixture
def probe(tmp_path, monkeypatch):
    path=tmp_path/'part.sldprt';path.write_bytes(b'saved synthetic part')
    state=dict(dirty=False, catalog={'Rough-Finish':0,'Finish':7}, attribute_id=0,
               attribute_name='Rough-Finish', spindle=1, diameters=(10.,20.), stock_attribute=1, pid=731, records=66,
               techdb='C:/catalog/recipe.mdb')
    forbidden=[]
    def deny(*args): forbidden.append(args);raise AssertionError('No native mutation/profile/NC allowed')
    class Feature:
        def __init__(self, native_id, kind):
            self.native_id=native_id
            self.GetTurnFeatureType=Mock(return_value=kind)
            self.IGetAllAttributes=Mock(side_effect=lambda:tuple(state['catalog']))
            self.GetTdbIdForAttribute=Mock(side_effect=lambda name:state['catalog'][name])
            self.GetAttributeName=Mock(side_effect=lambda:state['attribute_name'])
            self.GetSpindleType=Mock(side_effect=lambda:state['spindle'])
            self.GetMinMaxDiameter=Mock(side_effect=lambda:state['diameters'])
            self.IGetProfile=self.IGetEnumSegments=self.InsertOperation=self.SetAttribute=deny
        @property
        def Attribute(self): return state['attribute_id']
        @Attribute.setter
        def Attribute(self, value): deny(value)
    old,target=Feature(74,1),Feature(76,2)
    features=[old,target]
    class Toolpath:
        @property
        def RecordCount(self): return state['records']
    def operation(native_id,kind,linked):
        return N(native_id=native_id,OpernType=kind,GetIsToolpathGenerated=Mock(return_value=True),
                 IGetEnumToolpaths=Mock(return_value=Collection([Toolpath()])),
                 IGetAllFeatures=Mock(return_value=Collection(linked)),IGetTurnNCParam=deny,SetTool=deny)
    ops=[operation(127,7,[old]),operation(132,9,[target])]
    feature_setup=N(IGetEnumFeatures=Mock(return_value=Collection(features)))
    operation_setup=N(IGetEnumOperations=Mock(return_value=Collection(ops)))
    stock=N(GetTurnWorkpieceType=Mock(return_value=3),GetAttribute=Mock(side_effect=lambda:state['stock_attribute']))
    machine=N(MachType=3,IGetEnumSetups=Mock(return_value=Collection([feature_setup])),
              IGetEnumOpSetups=Mock(return_value=Collection([operation_setup])),IGetWorkpiece=Mock(return_value=stock))
    doc=N(GetDocType=Mock(return_value=1),IGetMachine=Mock(return_value=machine),
          GetCWObjectID=Mock(side_effect=lambda obj:(obj.native_id,True)))
    app=N(IGetActiveDoc=Mock(return_value=doc),IGetTechDBPath=Mock(side_effect=lambda:state['techdb']),
          SetTechDBPath=deny,ActiveDocGOP=deny,ActiveDocGTP=deny,SaveActiveDocument=deny)
    addin=N(GetCWApp=Mock(return_value=app))
    model=N(GetPathName=Mock(return_value=str(path)),GetTitle=Mock(return_value=path.name),
            GetType=Mock(return_value=1),GetSaveFlag=Mock(side_effect=lambda:state['dirty']),
            Save=deny,Save3=deny,GetBodies2=deny)
    sw=N(ActiveDoc=model,GetAddInObject=Mock(return_value=addin),GetProcessID=Mock(side_effect=lambda:state['pid']))
    monkeypatch.setattr(cam,'_typed',lambda obj,*_:obj)
    monkeypatch.setattr(attribute,'_typed',lambda obj,*_:obj)
    params=dict(process_id=731,expected_document_path=str(path),expected_source_sha256=cam._file_hash(path),
                feature_setup_index=0,expected_feature_native_id=76,expected_turn_feature_type=2,
                attribute_name='Rough-Finish',max_features=64,max_operations=64)
    def call(**changes):return cam.inspect_turn_feature_recipe(sw,'registered-clsid','registered.tlb',**(params|changes))
    return N(**locals())


def test_metadata_only_multisegment_compatible_id_zero(probe):
    result=probe.call()
    assert result['status']=='ok' and result['readback_verified']
    assert result['current_attribute']=={'native_id':0,'name':'Rough-Finish'}
    assert result['feature_spindle_type_raw']==1 and result['stock_attribute_raw']==1
    assert result['feature_diameters_native']=={'minimum':10.,'maximum':20.}
    assert not result['before']['diameter_units_qualified']
    assert result['before']['inventory']['stock']['type']==3
    assert not result['before']['database_condition_mapping_qualified']
    assert result['linked_operations']==[dict(setup_index=0,operation_index=1,native_id=132,
        turn_operation_type=9,linked_feature_ids=[76])]
    assert result['before']==result['after']
    assert not result['profiles_read'] and not result['NC_parameters_read'] and not result['full_model_geometry_verified']
    assert result['document_verification_scope']=='path_title_type_dirty_flag_snapshot'
    assert not result['mutation_attempted'] and not result['model_saved'] and not result['generation_attempted']
    assert probe.app.IGetTechDBPath.call_count==2 and probe.stock.GetAttribute.call_count==2
    assert probe.target.GetSpindleType.call_count==2 and not probe.forbidden


def test_optional_exact_name_and_no_normalization(probe):
    assert probe.call(attribute_name=None)['status']=='ok'
    assert probe.call(attribute_name=' Rough-Finish ')['status']=='error'
    assert not probe.forbidden


@pytest.mark.parametrize('change',['feature_id','feature_setup','feature_type','operation_duplicate','feature_duplicate','link_duplicate','link_unknown','dirty','process','file_pin','machine'])
def test_wrong_or_ambiguous_target_stops_readback(probe,change):
    args={}
    if change=='feature_id':args['expected_feature_native_id']=999
    elif change=='feature_setup':args['feature_setup_index']=1
    elif change=='feature_type':args['expected_turn_feature_type']=1
    elif change=='operation_duplicate':probe.ops[1].native_id=probe.ops[0].native_id
    elif change=='feature_duplicate':probe.old.native_id=probe.target.native_id
    elif change=='link_duplicate':probe.ops[1].IGetAllFeatures.return_value.rows.append(probe.target)
    elif change=='link_unknown':probe.ops[1].IGetAllFeatures.return_value.rows.append(N(native_id=999))
    elif change=='dirty':probe.state['dirty']=True
    elif change=='process':probe.state['pid']=123
    elif change=='file_pin':args['expected_source_sha256']='0'*64
    else:probe.machine.MachType=2
    result=probe.call(**args)
    assert result['status']=='error' and not result['readback_verified'] and not probe.forbidden
    if change in ('dirty','process','file_pin'):probe.sw.GetAddInObject.assert_not_called()


@pytest.mark.parametrize('change',['catalog','current_name','stock','spindle','diameters','techdb','file','dirty','inventory'])
def test_state_change_rejected(probe,change):
    calls=[]
    def path_read():
        calls.append(1)
        if len(calls)==1:
            if change=='catalog':probe.state['catalog']['Extra']=8
            elif change=='current_name':probe.state['attribute_name']='Finish';probe.state['attribute_id']=7
            elif change=='stock':probe.state['stock_attribute']=2
            elif change=='spindle':probe.state['spindle']=2
            elif change=='diameters':probe.state['diameters']=(11.,20.)
            elif change=='techdb':probe.state['techdb']='C:/other/catalog.mdb'
            elif change=='file':probe.path.write_bytes(b'changed')
            elif change=='dirty':probe.state['dirty']=True
            else:probe.state['records']=67
            return 'C:/catalog/recipe.mdb'
        return probe.state['techdb']
    probe.app.IGetTechDBPath.side_effect=path_read
    result=probe.call()
    assert result['status']=='error' and not result['readback_verified'] and not probe.forbidden


@pytest.mark.parametrize('change',['unknown_requested','empty_catalog','duplicate_name','negative_id','bool_id','current_name_absent','bool_stock','bool_spindle'])
def test_catalog_and_scalar_ambiguity(probe,change):
    args={}
    if change=='unknown_requested':args['attribute_name']='Unknown'
    elif change=='empty_catalog':probe.state['catalog']={}
    elif change=='duplicate_name':probe.target.IGetAllAttributes.side_effect=None;probe.target.IGetAllAttributes.return_value=('Rough-Finish','Rough-Finish')
    elif change=='negative_id':probe.state['catalog']['Finish']=-1
    elif change=='bool_id':probe.state['catalog']['Finish']=True
    elif change=='current_name_absent':probe.state['attribute_name']='Missing'
    elif change=='bool_stock':probe.state['stock_attribute']=True
    else:probe.state['spindle']=True
    result=probe.call(**args)
    assert result['status']=='error' and not result['readback_verified'] and not probe.forbidden


@pytest.mark.parametrize('key',['max_features','max_operations'])
def test_total_bounds_use_existing_inventory_reader(probe,key):
    result=probe.call(**{key:1})
    assert result['status']=='error' and not probe.forbidden


@pytest.mark.parametrize('key,value',[('process_id',True),('feature_setup_index',True),('max_features',65),
    ('max_operations',65),('expected_feature_native_id',0),('expected_source_sha256','bad'),('attribute_name',False)])
def test_strict_preflight_without_cam(probe,key,value):
    assert probe.call(**{key:value})['status']=='error'
    probe.sw.GetAddInObject.assert_not_called()
    assert not probe.forbidden


def test_default_attribute_id_and_catalog_lookup_are_distinct_raw_observations(probe):
    probe.state.update(attribute_id=0,attribute_name='Drill',catalog={'Drill':21,'Rough-Finish':50})
    result=probe.call(attribute_name='Rough-Finish')
    assert result['status']=='ok' and result['readback_verified']
    assert result['current_attribute']=={'native_id':0,'name':'Drill'}
    assert result['current_attribute_lookup_id_raw']==21 and result['current_name_in_catalog']
    assert result['current_id_matches_lookup'] is False
    assert result['current_attribute_id_mapping_qualified'] is False and not result['apply_eligible']
    assert result['catalog']['requested_id']==50 and not probe.forbidden


def test_catalog_id_aliases_are_metadata_not_an_apply_contract(probe):
    probe.state['catalog']['Finish']=0
    result=probe.call()
    assert result['status']=='ok' and result['readback_verified']
    assert result['catalog']['native_ids_unique'] is False
    assert result['catalog']['id_aliases']==[{'native_id':0,'names':['Rough-Finish','Finish']}]
    assert result['catalog']['apply_eligible'] is False and result['apply_eligible'] is False
    assert not result['catalog']['database_row_id_mapping_qualified'] and not probe.forbidden


@pytest.mark.parametrize('values',[(True,20.),(float('nan'),20.),(10.,),(10.,20.,30.)])
def test_diameter_shape_and_finite_native_values(probe,values):
    probe.state['diameters']=values
    result=probe.call()
    assert result['status']=='error' and not result['readback_verified'] and not probe.forbidden
