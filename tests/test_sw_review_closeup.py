"""局部预览的真实调用顺序、坐标变换和文档保护；不连接 CAD。"""
import json
import math
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import Mock

import pytest
from scripts import sw_review as review


class Point:
    def __init__(self, xyz, seen): self.xyz, self.seen = xyz, seen
    def MultiplyTransform(self, transform):
        self.seen.append(tuple(self.xyz))
        x,y,z=self.xyz
        return N(ArrayData=((x-y)/math.sqrt(2),(x+y)/math.sqrt(2),z))


class Model:
    def __init__(self, path):
        self.path=path;self.calls=[];self.dirty=False
        self.ActiveView=N(Orientation3=object())
    def GetPathName(self):return str(self.path)
    def GetType(self):return 1
    def GetSaveFlag(self):return self.dirty
    def ClearSelection2(self, all):self.calls.append(('clear',all))
    def ShowNamedView2(self, name, number):self.calls.append(('view',name,number))
    def ViewZoomTo2(self,*box):self.calls.append(('zoom',box))
    def ViewZoomtofit2(self):self.calls.append(('fit',))
    def GraphicsRedraw2(self):self.calls.append(('redraw',))
    def SaveBMP(self,path,width,height):
        self.calls.append(('bmp',path,width,height));Path(path).write_bytes(b'BMP-PREVIEW');return True
    def Save3(self,*args):raise AssertionError('Never save model')
    def ForceRebuild3(self,*args):raise AssertionError('Never rebuild model')
    def GetBodies2(self,*args):raise AssertionError('No full BRep scan for view review')


@pytest.fixture
def h(tmp_path,monkeypatch):
    path=tmp_path/'model.sldprt';path.write_bytes(b'UNCHANGED-CAD')
    model=Model(path);seen=[]
    utility=N(CreatePoint=lambda xyz:Point(xyz.value,seen))
    sw=N(ActiveDoc=model,GetProcessID=lambda:123,IsSame=lambda a,b:1 if a is b else 0,
         GetMathUtility=lambda:utility)
    monkeypatch.setattr(review,'inspect_bmp_preview',lambda p:dict(path=str(p),exists=True,size_bytes=11,likely_blank=False))
    kwargs=dict(process_id=123,expected_document_path=str(path),views=['isometric'],
        zoom_box_mm=[26,-5,3,31,5,6])
    return N(**locals())


def run(h,**updates):
    return review.run_closeup_review(h.sw,h.model,str(h.tmp_path/'out'),**(h.kwargs|updates))


def test_all_eight_corners_transformed_and_no_fit_after_zoom(h):
    report,path=run(h)
    assert len(h.seen)==8 and len(set(h.seen))==8
    box=next(c[1] for c in h.model.calls if c[0]=='zoom')
    assert box==pytest.approx([.021/math.sqrt(2),.021/math.sqrt(2),.003,
                              .036/math.sqrt(2),.036/math.sqrt(2),.006])
    assert [c[0] for c in h.model.calls]==['clear','view','zoom','redraw','bmp']
    assert report['view_review']['before']==report['view_review']['after']
    assert report['view_review']['model_saved'] is False
    assert report['checks']['saved_file_unchanged'] is True
    assert json.loads(Path(path).read_text())['view_review']['calls'][0]['bitmap_returned'] is True


def test_multiple_selected_views_only_and_orientation_before_each_zoom(h):
    run(h,views=['front','right'])
    assert [c[2] for c in h.model.calls if c[0]=='view']==[1,4]
    assert len(h.seen)==16


def test_explicit_view_without_box_fits_once_and_skips_math(h):
    h.sw.GetMathUtility=Mock(side_effect=AssertionError('not needed'))
    run(h,views=['front'],zoom_box_mm=None)
    assert [c[0] for c in h.model.calls]==['clear','view','fit','redraw','bmp']
    h.sw.GetMathUtility.assert_not_called()


@pytest.mark.parametrize('bad',[[],[0,0,0,1,1], [0,0,0,0,1,1], [0,0,0,1,-1,1],
    [False,0,0,1,1,1],[0,0,0,float('nan'),1,1],[0,0,0,float('inf'),1,1],['0',0,0,1,1,1]])
def test_bad_boxes_fail_before_native_calls(h,bad):
    with pytest.raises(ValueError):run(h,zoom_box_mm=bad)
    assert not h.model.calls and not (h.tmp_path/'out').exists()


@pytest.mark.parametrize('bad',[[],['front','front'],['*Front'],['front',1],'front'])
def test_bad_views_fail_before_native_calls(h,bad):
    with pytest.raises(ValueError):run(h,views=bad)
    assert not h.model.calls


@pytest.mark.parametrize('fault',['pid','foreign','missing','type'])
def test_identity_guard_blocks_before_view_or_output(h,fault):
    if fault=='pid':h.sw.GetProcessID=lambda:999
    if fault=='foreign':h.sw.ActiveDoc=Model(h.path)
    if fault=='missing':h.sw.ActiveDoc=None
    if fault=='type':h.model.GetType=lambda:3
    with pytest.raises(ValueError):run(h)
    assert not h.model.calls and not (h.tmp_path/'out').exists()


def test_existing_output_preserved(h):
    out=h.tmp_path/'out';out.mkdir();(out/'keep').write_bytes(b'proof')
    with pytest.raises(ValueError):run(h)
    assert (out/'keep').read_bytes()==b'proof' and not h.model.calls


def test_bitmap_failure_stops_before_next_view_and_persists_partial(h):
    h.model.SaveBMP=Mock(return_value=False)
    with pytest.raises(RuntimeError):run(h,views=['front','right'])
    assert h.model.SaveBMP.call_count==1
    data=json.loads((h.tmp_path/'out/review_review_report.json').read_text())
    assert data['evaluation']['status']=='error'
    assert data['view_review']['calls'][0]['bitmap_native_result'] is False
    assert len(data['view_review']['calls'])==1


def test_changed_doc_after_orientation_prevents_bitmap(h):
    h.model.ShowNamedView2=lambda *args:setattr(h.sw,'ActiveDoc',None)
    h.model.SaveBMP=Mock()
    with pytest.raises(ValueError):run(h)
    h.model.SaveBMP.assert_not_called()


def test_dirty_flag_change_is_explicit_and_file_unchanged(h):
    original=h.model.SaveBMP
    def save(*args):h.model.dirty=True;return original(*args)
    h.model.SaveBMP=save
    report,_=run(h)
    assert report['view_review']['before']['needs_save'] is False
    assert report['view_review']['after']['needs_save'] is True
    assert report['view_review']['saved_file_unchanged'] is True


def test_saved_bytes_change_fails_readback_without_retry(h):
    original=h.model.SaveBMP
    def save(*args):h.path.write_bytes(b'changed');return original(*args)
    h.model.SaveBMP=save
    with pytest.raises(ValueError,match='bytes changed'):run(h)
    assert sum(c[0]=='bmp' for c in h.model.calls)==1


def test_method_flag_precedes_dynamic_lookup(h):
    class DynamicModel(Model):
        flagged=set()
        def _FlagAsMethod(self,name):self.flagged.add(name)
        def __getattribute__(self,name):
            if name in ('ShowNamedView2','ViewZoomTo2','SaveBMP') and name not in object.__getattribute__(self,'flagged'):
                raise AssertionError('Eager PROPERTYGET is forbidden for documented METHOD')
            return super().__getattribute__(name)
    h.model=DynamicModel(h.path);h.sw.ActiveDoc=h.model
    run(h)
    assert {'ShowNamedView2','ViewZoomTo2','SaveBMP'} <= h.model.flagged
