"""Bounded finish/profile getter batch; strong mutation guards remain unchanged."""
from copy import deepcopy
from ctypes import c_int
from math import isfinite
from scripts.sw_cam import _member
from scripts.sw_cam_generation import _typed
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam_rough_firstcut import require
from scripts.sw_cam_route_read_batch import ScopedCamRouteReadBatch, ROUTE_READ_MEMBERS, ROUTE_READ_INTERFACES
from scripts.sw_cam_read_batch_guard import READ_MEMBERS, READ_INTERFACES
from scripts.sw_cam_route_checkpoint import capture_route_checkpoint
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_mill_tool_geometry import read_full_mill_tool
from scripts.sw_cam_mill_levels import read_mill_level_values
from scripts.sw_cam_document_unit_scope import read_document_cam_unit_scope
from scripts.sw_cam_finish_observation import (read_finish_details, FINISH_BASE_FIELDS,
    FINISH_V3_FIELDS, MILL_TOOL_FIELDS, HOLDER_FIELDS)
from scripts.sw_cam_finish_lead_observation import read_lead_details, query_lead_interface, LEAD_FIELDS
from scripts.sw_cam_finish_recipe import selected_finish
from scripts.sw_cam_shared_holder_geometry import check_holder_pins
from scripts.sw_cam_mill_inventory_geometry import MAX_CURVES_PER_CHAIN, MAX_SPLINE_FACETS

SCOPE="BOUNDED_FINISH_RECIPE_READ_BATCH_V1"
FINISH_MEMBERS=(ROUTE_READ_MEMBERS | READ_MEMBERS | frozenset(FINISH_BASE_FIELDS+FINISH_V3_FIELDS+MILL_TOOL_FIELDS+HOLDER_FIELDS)
    | frozenset(LEAD_FIELDS) | frozenset({"GetPreviousAllowance","IGetLeadin","IGetLeadout","GetHolderType","GetHolderSpec"})) - {"QueryInterface"}
FINISH_INTERFACES=ROUTE_READ_INTERFACES | READ_INTERFACES | {"ICWFinishMillOp","ICWFinishMillOp2","ICWFinishMillOp3","ICWMillTool"}
INDEX_LIMITS={"GetCurveAtIndex":MAX_CURVES_PER_CHAIN,"GetFacetAtIndex":MAX_SPLINE_FACETS}


class ScopedFinishReadBatch(ScopedCamRouteReadBatch):
    """Read-only retained graph, strict getter names and bounded native index pointers."""
    def _arguments(self,name,args):
        if name in INDEX_LIMITS:
            require(len(args)==1,"One native index pointer required")
            target=getattr(args[0],"_obj",None)
            require(type(target) is c_int and 0<=target.value<INDEX_LIMITS[name],"Bounded byref(c_int) index required")
            # ctypes.byref(c_int) is accepted; pointers, integers and arbitrary proxy objects are not.
            from ctypes import byref
            require(type(args[0]) is type(byref(c_int())) and args[0]._obj is target,"Exact byref(c_int) wrapper required")
            return
        for value in args:
            if type(value) in (bool,int,bytes):continue
            if type(value) is float and isfinite(value):continue
            if type(value) is str and len(value)<=4096:continue
            require(id(value) in self._known_objects,"Argument is outside the retained document graph")
    def read(self,obj,name,*args):
        try:
            require(type(name) is str and name in FINISH_MEMBERS,"Getter is outside finish/profile read scope")
            self._arguments(name,args)
            return self._observe_read(obj,"getter",lambda:_member(obj,name,*args))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def typed(self,obj,name):
        try:
            require(type(name) is str and name in FINISH_INTERFACES,"Interface is outside finish/profile read scope")
            return self._observe_read(obj,"qi",lambda:_typed(obj,name,self.typelib_path))
        except BaseException:
            self._invalid=True;self._completed=False;raise
    def lead_interface(self,obj):
        return self._observe_read(obj,"qi",lambda:query_lead_interface(obj,self.typelib_path))
    def summary(self):
        result=super().summary()
        result.update(scope=SCOPE,original_route_qualification_extended=False,
            finish_native_match_verified=False,atomic_snapshot=False)
        return result


def capture_finish_recipe_batch(ctx, reference_state, *, holder_recipe, diagnostic):
    """Same current getter payload; only observation scheduling changes.

    The caller must compare the entire payload with the completed strong recipe
    before authorizing Save/GTP/CL. This function does not qualify those actions.
    """
    result=capture_route_checkpoint(ctx,reference_state,diagnostic.setdefault("route",{}))
    state,native,levels,_,entry,candidate=result
    selected=selected_finish(state,ctx.args)
    def units():
        with ctx.guard() as guard:
            return read_document_cam_unit_scope(guard.read(ctx.sw,"ActiveDoc"),ctx.app,
                sw_read=lambda obj,name:guard.read(obj,name),cam_read=guard.read)
    before_units=units()
    batch=ScopedFinishReadBatch(ctx.sw,ctx.typelib_path,native_context=native,reference_state=state,
        process_id=ctx.args["process_id"],expected_document=ctx.identity(),source_sha256=ctx.args["expected_source_sha256"],
        evidence_pins=ctx.loaded["pins"],verify_evidence=ctx.files,verify_owned_process=ctx.owned,
        check_events=ctx.events,max_native_calls=900)
    try:
        with batch:
            raw=native["operations"][ctx.args["finish_operation_native_id"]]
            require(_object_id(native["doc"],raw,batch.read)==ctx.args["finish_operation_native_id"],"Finish operation changed")
            generic,tool=read_generic_tool(raw,native["doc"],batch.read,batch.typed)
            require(generic==selected["assigned_tool"],"Assigned finish tool changed")
            found=batch.read(native["doc"],"GetCWObjectFromID",1,ctx.args["target_feature_native_id"])
            require(type(found) in (list,tuple) and len(found)==2 and found[1] is True,"Exact feature lookup required")
            feature=batch.typed(found[0],"ICWFeature")
            require(_object_id(native["doc"],feature,batch.read)==ctx.args["target_feature_native_id"],"Feature ID changed")
            def native_read(label,invoke,decoder=None,interface=False,validator=None):
                value=batch.feature_dispatch(feature) if label=="QueryInterface.IDispatch.feature" else invoke()
                if interface:require(value is not None and bool(value),"Non-null level interface required")
                if validator:validator(value)
                return decoder(value) if decoder else value
            def getter(obj,interface_name,name,*params,**kw):
                return native_read(interface_name+"."+name,lambda:batch.read(obj,name,*params),**kw)
            finish_levels={}
            read_mill_level_values(feature,raw,native_read=native_read,typed=batch.typed,getter=getter,report=finish_levels)
            details=read_finish_details(raw,found[0],tool,read=batch.read,typed=batch.typed,
                diagnostic=diagnostic.setdefault("finish_details",{}))
            leads=read_lead_details(raw,found[0],read=batch.read,typed=batch.typed,lead_typed=batch.lead_interface)
            full=read_full_mill_tool(tool,generic=generic,read=batch.read,typed=batch.typed,
                diagnostic=diagnostic.setdefault("full_tool",{}))
        batch.require_complete()
        after_units=units()
        require(before_units==after_units,"Global document/CAM units changed during finish batch")
        check_holder_pins(holder_recipe)
        ctx.files();require(state["document"]==ctx.identity(),"Document changed during finish batch")
        diagnostic.update(capture_complete=True,finish_read_mode="bounded_finish_batch",
            finish_units_stable=True,original_route_qualification_extended=False,
            finish_current_checkpoint_match_verified=False)
        return dict(state=state,native=native,rough_payload=dict(candidate=candidate,levels=levels,entry=entry),
            finish_payload=dict(details=details,levels=finish_levels,leads=leads,full_tool=full,unit_record=after_units))
    finally:
        diagnostic["finish_read_batch"]=deepcopy(batch.summary())
