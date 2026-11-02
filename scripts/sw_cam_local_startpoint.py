"""Parameterize the existing six-action USERDEFINED rough-entry lifecycle.

Coordinates are declared raw planar coordinates. Their physical applicability and
actual generated helix envelope remain separate checks; no motion is generated here.
"""
from copy import deepcopy
from math import isfinite
from scripts import sw_cam_pocket_rough_apply as prior
from scripts.sw_cam import _member
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_comtypes import _is_comtypes_pointer

group=prior.group


def verify_startpoint(value,point):
    require(value.get('read_complete')is True and value.get('collection_interface_verified')is True and value.get('list_is_null')is False,'Complete nonnull startpoint collection required')
    require(value['count']==1 and len(value['rows'])==1 and value['entry_type']==4,'One helical USERDEFINED point required')
    row=value['rows'][0]
    require(type(row['type_raw'])is int and row['type_raw']==1 and row['position_is_null']is False and group.exact(row['position_native'],point),'Exact native raw point required')
    return deepcopy(value)


class EntryAdapter:
    # These functions contain no operation IDs or point constants.
    typed=prior.NativeBackend.typed
    create_point=prior.NativeBackend.create_point
    point_state=prior.NativeBackend.point_state
    created_type=prior.NativeBackend.created_type
    create_position=prior.NativeBackend.create_position
    position_state=prior.NativeBackend.position_state
    set_point_position=prior.NativeBackend.set_point_position
    attach_point=prior.NativeBackend.attach_point

    def __init__(self,backend,target,point):
        require(target['operation_type']==0,'Only selected rough entry accepts this adapter')
        require(type(point)is list and len(point)==3 and all(type(x)in(int,float)and isfinite(x)for x in point),'Finite raw native XYZ required')
        self.backend,self.selected,self.point_coordinates=backend,deepcopy(target),deepcopy(point)
        self.ctx,self.typelib_path,self.loaded=backend.ctx,backend.typelib_path,backend.loaded
        self.point=self.position=self.entry_collection=None

    def target(self,g):return self.backend.target(g,self.selected)

    def set_point_coordinates(self,pending):
        with self.ctx.guard()as g:
            self.target(g);owner=self.typed(g,self.position,'ICWPosition')
            return g.dispatch_once(lambda:_member(owner,'SetCoordinates',*self.point_coordinates),persist_pending=pending)

    def collection_state(self):
        with self.ctx.guard()as g:
            self.target(g);coll=self.typed(g,self.entry_collection,'ICWDispatchCollection')
            require(g.read(coll,'Count')==1,'Held point collection count differs')
            point=self.typed(g,g.read(coll,'Item',0),'ICWStartPoint');kind=g.read(point,'StartPointType')
            position=self.typed(g,g.read(point,'Position'),'ICWPosition');xyz=prior.pocket.vector(g.read(position,'GetCoordinates'),3)
            require(type(kind)is int and kind==1 and group.exact(xyz,self.point_coordinates),'Held USERDEFINED point changed')
            return dict(count=1,type_raw=kind,position_native=xyz)


def apply_entry(backend,journal,target,point,*,adapter_class=EntryAdapter):
    """Six explicit claims, no routing change, no GTP and no retry."""
    selected=backend.capture_snapshot('entry_before_'+str(target['operation_native_id']),own=target)
    require(len(selected['parameters'])==1,'One entry target snapshot required')
    before=selected['parameters'][0]['startpoints']
    require(before['read_complete']is True and before['count']==0 and before['rows']==[] and before['list_is_null']is False,'Only a genuinely empty existing list may be initialized')
    adapter=adapter_class(backend,target,point);prefix=str(target['operation_native_id'])+':entry:'
    def execute(name,call,observe):
        label=prefix+name
        # GroupJournal.execute validates HRESULT0 itself and returns its action
        # record, not the native scalar. Preserve that existing public contract.
        journal.execute(label,call)
        backend.refresh_dirty();actual=observe();journal.verified(label,actual);return actual
    def created():
        require(_is_comtypes_pointer(adapter.point)and bool(adapter.point),'Nonnull native startpoint factory result required')
        return dict(type_raw=adapter.created_type(),returned_nonnull=True)
    execute('CreateStartPointInstance',adapter.create_point,created)
    def position():
        require(_is_comtypes_pointer(adapter.position)and bool(adapter.position),'Nonnull native position factory result required')
        return dict(coordinates=adapter.position_state(),returned_nonnull=True)
    execute('CreatePosition',adapter.create_position,position)
    def coords():
        actual=adapter.position_state();require(group.exact(actual,point),'Position coordinate readback differs');return actual
    execute('SetPointCoordinates',adapter.set_point_coordinates,coords)
    def associated():
        actual=adapter.point_state();require(group.exact(actual,point),'Associated startpoint differs');return actual
    execute('SetPointPosition',adapter.set_point_position,associated)
    execute('AddStartPoint',lambda pending:adapter.attach_point('Add',pending),adapter.collection_state)
    execute('SetStartPointList',lambda pending:adapter.attach_point('SetStartPointList',pending),adapter.collection_state)
    after=backend.capture_snapshot('entry_after_'+str(target['operation_native_id']),own=target)
    require(len(after['parameters'])==1,'One associated entry readback required')
    actual=verify_startpoint(after['parameters'][0]['startpoints'],point)
    require(group.exact(selected['binding'],after['binding']),'Entry initialization changed route or tool')
    journal.report.setdefault('entry_readbacks',{})[str(target['operation_native_id'])]=actual;journal.persist()
    return after['parameters'][0]
