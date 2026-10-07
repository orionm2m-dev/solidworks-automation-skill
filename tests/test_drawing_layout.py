import pytest
from scripts.sw_drawing_layout import DrawingLayout


def valid():
    return {'output_path':'C:/output/review.SLDDRW','views':[{'id':'front','center_mm':[80,100]}]}


def test_reject_unknown_keys():
    data=valid(); data['code']='anything'
    with pytest.raises(ValueError): DrawingLayout.model_validate(data)


def test_reject_missing_parent():
    data=valid(); data['views'][0]['parent']='absent'
    with pytest.raises(ValueError): DrawingLayout.model_validate(data)


def test_reject_unknown_dimension_view():
    data=valid(); data['dimensions']=[{'view':'missing','kind':'horizontal','points_mm':[[0,0,0],[1,0,0]],'offset_mm':[0,2],'expected_mm':1}]
    with pytest.raises(ValueError): DrawingLayout.model_validate(data)


@pytest.mark.parametrize('path',['relative.SLDDRW','C:/output/model.SLDPRT'])
def test_output_must_be_absolute_drawing(path):
    data=valid(); data['output_path']=path
    with pytest.raises(ValueError): DrawingLayout.model_validate(data)


@pytest.mark.parametrize('scale',[0,-1,float('nan'),float('inf')])
def test_reject_invalid_scale(scale):
    data=valid(); data['views'][0]['scale']=scale
    with pytest.raises(ValueError): DrawingLayout.model_validate(data)


def test_valid_section_and_dimension():
    data=valid();data['views'].append({'id':'sec','parent':'front','section_line_mm':[[0,0,0],[0,10,0]],'center_mm':[150,100]})
    data['dimensions']=[{'view':'sec','kind':'vertical','points_mm':[[0,0,0],[0,10,0]],'offset_mm':[10,0],'expected_mm':10}]
    assert DrawingLayout.model_validate(data).views[1].parent=='front'


def test_dimension_prompt_cancellation_is_process_and_control_scoped():
    from scripts.sw_drawing_layout import cancel_dimension_prompt
    class GUI:
        def __init__(self): self.posted=[]
        def EnumWindows(self,fn,data):
            for h in (1,2,3,4):fn(h,data)
        def IsWindowVisible(self,h):return True
        def GetClassName(self,h):return '#32770'
        def GetWindowText(self,h):return {1:'Modify',2:'Save As',3:'Modify',4:'Modify'}[h]
        def EnumChildWindows(self,h,fn,data):
            for i in ({1111,2222,5555,44168} if h!=4 else {1,2}):fn(i,data)
        def GetDlgCtrlID(self,h):return h
        def PostMessage(self,*args):self.posted.append(args)
    class Processes:
        def GetWindowThreadProcessId(self,h):return (1,99 if h==3 else 55)
    gui=GUI()
    result=cancel_dimension_prompt(55,gui=gui,processes=Processes())
    assert result['dismissed']==[1]
    assert gui.posted==[(1,0x10,0,0)]


def test_no_matching_prompt_does_not_send_messages():
    from scripts.sw_drawing_layout import cancel_dimension_prompt
    class GUI:
        def EnumWindows(self,fn,data):pass
    class Processes:pass
    assert cancel_dimension_prompt(55,gui=GUI(),processes=Processes())['status']=='no_matching_prompt'


def test_projected_point_uses_rotation_scale_then_translation():
    from scripts.sw_drawing_layout import transform_point
    m=[-1,0,0, 0,1,0, 0,0,-1, .1,.2,.3, 5,0,0,0]
    assert transform_point([.01,.02,.03],m)==pytest.approx([.05,.3,.15])


def test_projected_point_rejects_truncated_matrix():
    from scripts.sw_drawing_layout import transform_point
    with pytest.raises(ValueError): transform_point([0,0,0],[1,0,0])
