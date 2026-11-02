"""Typed native adapter for a dynamically bound local rough/finish operation group.

Leaf getters/setters, insertion and save/session ownership remain the previously
qualified implementations. Only inventory bounds and selected identities differ.
No request dispatcher is exposed until actual saved feature/tool authority exists.
"""
from copy import deepcopy
from scripts import sw_cam_local_operation_group as engine
from scripts import sw_cam_deep_guide_group as writer
from scripts import sw_cam_guide_group_configuration as config
from scripts import sw_cam_guide_group_generation as generation
from scripts import sw_cam_guide_group_reader as default_reader
from scripts.sw_cam_mill_selected_plan_context import read_header
from scripts.sw_cam_mill_inventory import _items
from scripts.sw_cam_mill_route_context import read_generic_tool
from scripts.sw_cam_thread import _object_id
from scripts.sw_cam import _member
from scripts.sw_cam_rough_firstcut import require

group=writer.group


def read_current_binding(doc, baseline, owners, *, read, typed):
    require(read(doc,'GetDocType')==1,'Current CAM part required')
    machine=typed(read(typed(doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
    require(read(machine,'MachType')==1,'Current MILL machine required')
    out=dict(features={},operation_setups=[],operations=[]);handles={}
    for si,raw_setup in enumerate(_items(read(machine,'IGetEnumOpSetups'),typed,read,3)):
        setup=typed(raw_setup,'ICWBaseOpSetup');sid=_object_id(doc,setup,read)
        operations=_items(read(setup,'IGetEnumOperations'),typed,read,21)
        out['operation_setups'].append(dict(index=si,native_id=sid,operation_count=len(operations)))
        for oi,raw in enumerate(operations):
            op=typed(raw,'ICWOperation');oid=_object_id(doc,op,read)
            require(oid not in handles,'Duplicate operation native ID');handles[oid]=raw
            mill=typed(raw,'ICWMillOperation');tool,_=read_generic_tool(raw,doc,read,typed)
            out['operations'].append(dict(setup_index=si,setup_native_id=sid,operation_index=oi,native_id=oid,
                mill_operation_type=read(mill,'OpernType'),base_operation_type=read(op,'OpernType'),
                suppressed=read(op,'Suppressed'),toolpath_generated=read(op,'GetIsToolpathGenerated'),
                linked_feature_ids=[_object_id(doc,v,read) for v in _items(read(op,'IGetAllFeatures'),typed,read,4)],
                toolpath_record_counts=[read(typed(v,'ICWToolpath'),'RecordCount') for v in _items(read(op,'IGetEnumToolpaths'),typed,read,4)],assigned_tool=tool))
    require(17<=len(out['operations'])<=21,'Only saved seventeen plus at most four definitions allowed')
    for key in baseline['features']:
        fid=int(key)
        found=read(doc,'GetCWObjectFromID',1,fid)
        require(type(found) in (tuple,list) and len(found)==2 and found[1] is True,'Exact guide lookup required')
        header,_=read_header(found[0],doc,read,typed,owners[str(fid)]);require(header['native_id']==fid,'Guide ID changed')
        out['features'][str(fid)]=header
    return out,handles


def read_parameter_groups(doc, handles, targets, batch, report, persist, *, allowed):
    """Observe a nonempty subset of the four newly learned targets, no mutations."""
    require(type(targets)is list and 1<=len(targets)<=12,'Bounded selected1..12 groups required')
    require(type(report)is dict and 'parameters'not in report,'Fresh parameter report required')
    selected_ids=[]
    allowed_byid={r['operation_native_id']:r for r in allowed}
    require(len(allowed_byid)==len(allowed),'Unique authoritative target IDs required')
    for row in targets:
        oid=row['operation_native_id']
        require(type(oid)is int and oid in allowed_byid and oid in handles and oid not in selected_ids,'Exact retained target required')
        expected=allowed_byid[oid]
        require(all(group.exact(row[k],expected[k])for k in ('operation_native_id','feature_native_id','operation_type','operation_setup_native_id')),'Target identity differs')
        assigned=row.get('assigned_tool')
        require(type(assigned)is dict and type(assigned.get('native_id'))is int and assigned['native_id']>0,'Actual assigned tool required')
        selected_ids.append(oid)
    reader=writer.reader
    pocket,guide,fields,protected=reader.pocket,reader.guide,reader.fields,reader.protected
    read_generic_tool=reader.read_generic_tool
    read_tool_dimensions=reader.read_tool_dimensions
    machine = batch.typed(batch.read(batch.typed(doc, 'ICWPartDoc'), 'IGetMachine'), 'ICWMachine')
    setups = _items(batch.read(machine, 'IGetEnumOpSetups'), batch.typed, batch.read, 3)
    selected = [s for s in setups if _object_id(doc, s, batch.read) == targets[0]['operation_setup_native_id']]
    require(len(selected) == 1 and len({r['operation_setup_native_id']for r in targets})==1, 'Exact shared operation setup required')
    setup, tool_cache = selected[0], {}
    for row in targets:
        oid, fid = row['operation_native_id'], row['feature_native_id']
        report['phase'] = 'parameters_' + str(oid)
        out = dict(operation_native_id=oid, feature_native_id=fid, read_complete=False)
        report.setdefault('parameters', []).append(out); persist()
        found = batch.read(doc, 'GetCWObjectFromID', 1, fid)
        require(type(found) in (tuple, list) and len(found) == 2 and found[1] is True,
            'Exact retained guide feature lookup required')
        feature, operation = batch.feature_dispatch(found[0]), handles[oid]
        require(_object_id(doc, feature, batch.read) == fid, 'Resolved guide identity differs')
        out['levels'] = pocket.read_levels(operation, feature, read=batch.read,
            typed=batch.typed, feature_dispatch=batch.feature_dispatch)
        if row['operation_type'] == 0:
            out['rough'] = pocket.rough.read_rough_entry_parameters(operation, feature,
                read=batch.read, typed=batch.typed, diagnostic=out.setdefault('rough_diagnostic', {}))
            out['startpoints'] = guide.start.read_startpoints(operation, feature, read=batch.read,
                typed=batch.typed, metadata=batch.metadata, diagnostic=out.setdefault('startpoint_diagnostic', {}))
        else:
            out['finish'] = pocket.read_finish_parameters(operation, feature, read=batch.read, typed=batch.typed)
            out['finish_fields'] = fields.read_cached_fields(batch, operation, feature,
                out.setdefault('finish_field_diagnostic', {}))
            out['protected_finish'] = protected.read_protected(operation, feature, read=batch.read,
                typed=batch.typed, record=lambda key, value: out.setdefault('protected_raw', {}).update(
                    {key: pocket.rough.bounded_raw_observation(value)}))
            out['leads'] = pocket.leads.read_lead_details(operation, feature, read=batch.read,
                typed=batch.typed, lead_typed=lambda raw: batch.typed(raw, 'ICWLeadInOut'))
        out['nc'] = pocket.read_nc_settings(operation, setup, read=batch.read, typed=batch.typed,
            pointer_read=batch.plane, diagnostic=out.setdefault('nc_diagnostic', {}), persist=persist)
        generic, tool = read_generic_tool(operation, doc, batch.read, batch.typed)
        require(group.exact(generic, row['assigned_tool']), 'Assigned tool changed')
        tid = generic['native_id']; reused = tid in tool_cache
        if not reused: tool_cache[tid] = read_tool_dimensions(tool, generic, batch)
        require(group.exact(tool_cache[tid]['generic'], generic), 'Shared tool identity differs')
        out.update(tool=deepcopy(tool_cache[tid]), tool_dimensions_reused=reused, read_complete=True)
        persist()
    require(len(report['parameters']) == len(targets) and all(r['read_complete'] for r in report['parameters']),
        'Every selected actual parameter group must be complete')
    report['unique_tool_dimension_reads'] = len(tool_cache)

class NativeBackend(writer.NativeBackend):
    # These methods bind every interface before dispatch_once claims the action.
    field=config.NativeBackend.field
    set_field=config.NativeBackend.set_field
    outcome=generation.NativeBackend.outcome

    def __init__(self,*args,before_generate,exporter):
        super().__init__(*args)
        require(callable(before_generate)and callable(exporter),'Trusted checked NC and export adapters required')
        self.before_generate=before_generate
        self.exporter=exporter
        self.learned=[]
        self.baseline=self.loaded['guide_parameters']['expected_parameters']
        self.owners=self.loaded['local_feature_owners']
        require(set(self.owners)==set(self.baseline['binding']['features']),'Every actual feature owner must be pinned')
        self.protected_targets=[]
        ops={r['native_id']:r for r in self.baseline['binding']['operations']}
        for p in self.baseline['parameters']:
            o=ops[p['operation_native_id']]
            require(o['linked_feature_ids']==[p['feature_native_id']],'Protected parameter feature binding differs')
            self.protected_targets.append(dict(operation_native_id=o['native_id'],feature_native_id=p['feature_native_id'],
                operation_type=o['mill_operation_type'],operation_setup_native_id=o['setup_native_id'],assigned_tool=deepcopy(o['assigned_tool'])))
        require(len(self.protected_targets)==8,'Full saved8 parameter targets required')

    def target(self,g,row):
        allowed=self.protected_targets+self.learned
        require(any(all(group.exact(row[k],v[k])for k in ('operation_native_id','feature_native_id','operation_type'))for v in allowed),'Target outside authoritative operations')
        return config.NativeBackend.target(self,g,row)

    def capture_snapshot(self,label,*,full=False,own=None):
        self.boundary()
        with self.ctx.guard()as g:
            self.doc=g.typed(g.read(self.ctx.app,'IGetActiveDoc'),'ICWDoc3');self.save_app=g.typed(self.ctx.app,'ICWApp')
        out=dict(label=label,parameters=[]);self.report.setdefault('captures',[]).append(out);self.persist()
        if full:self.verify_catalogue(label+'_before')
        batch=self.batch(self.doc,lambda:None,dict(member='',returned=False,read_index=0))
        try:
            with batch:
                before,handles=read_current_binding(self.doc,self.baseline['binding'],self.owners,read=batch.read,typed=batch.typed)
                allowed=deepcopy(self.protected_targets+self.learned)
                selected=deepcopy(allowed if full else [] if own is None else [own])
                current={r['native_id']:r for r in before['operations']}
                for target in selected:target['assigned_tool']=deepcopy(current[target['operation_native_id']]['assigned_tool'])
                if selected:
                    selected_report={}
                    read_parameter_groups(self.doc,handles,selected,batch,selected_report,lambda:None,allowed=allowed)
                    out['parameters']=[config.parameter_projection(v)for v in selected_report['parameters']]
                after,_=read_current_binding(self.doc,self.baseline['binding'],self.owners,read=batch.read,typed=batch.typed)
                require(group.exact(before,after),'Route changed during bounded parameter snapshot');out['binding']=after
            batch.require_complete()
        finally:out['read_batch']=batch.summary();self.persist()
        if full:self.verify_catalogue(label+'_after')
        return dict(binding=deepcopy(out['binding']),parameters=deepcopy(out['parameters']))

    def observe_default_catalogues(self,feature_ids):
        require(type(feature_ids)is list and len(feature_ids)==len(set(feature_ids))==2,'Two selected actual features required')
        out=[]
        for fid in feature_ids:
            self.boundary()
            with self.ctx.guard()as g:
                found=g.read(self.doc,'GetCWObjectFromID',1,fid)
                require(type(found)in(tuple,list)and len(found)==2 and found[1]is True,'Actual selected feature required')
                before,raw=read_header(found[0],self.doc,g.read,g.typed,self.owners[str(fid)])
                require(group.exact(before,self.baseline['binding']['features'][str(fid)]),'Selected profile header changed')
                catalogue=default_reader.read_catalogues(raw,read=g.read,typed=g.typed)
                after,_=read_header(raw,self.doc,g.read,g.typed,self.owners[str(fid)])
                require(group.exact(before,after),'Feature changed during default catalogue observation')
            out.append(dict(feature_native_id=fid,header=after,defaults_catalogue=catalogue))
        self.report['actual_default_catalogues']=deepcopy(out);self.persist()
        return out

    def verify_catalogue(self,label):
        with self.ctx.guard()as g:
            machine=g.typed(g.read(g.typed(self.doc,'ICWPartDoc'),'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4')
            actual=[_object_id(self.doc,v,g.read)for v in _items(g.read(crib,'GetAllTools'),g.typed,g.read,64)]
        require(actual==[r['native_id']for r in self.loaded['serial_flat_catalogue']],'Saved tool catalogue changed')
        self.report.setdefault('catalogue_readbacks',[]).append(dict(label=label,native_ids=actual));self.persist()
        return actual

    def insert(self,row,anchor,pending,returned):
        header=self.baseline['binding']['features'][str(row['feature_native_id'])]
        raw=writer.definitions.insert_selected_once(self.ctx,self.doc,row,anchor,header,pending)
        returned(raw);self.refresh_dirty()
        with self.ctx.guard()as g:oid=_object_id(self.doc,raw,g.read)
        forbidden={r['native_id']for r in self.baseline['binding']['operations']}|{r['operation_native_id']for r in self.learned}
        require(type(oid)is int and 0<oid<2**31 and oid not in forbidden,'Actual returned new operation ID invalid')
        return oid

    def assign(self,target,pending):
        from comtypes.automation import IDispatch
        wanted=self.loaded['configuration_tool'];tid=wanted['native_id']
        with self.ctx.guard()as g:
            raw,_=self.target(g,target);part=g.typed(self.doc,'ICWPartDoc');machine=g.typed(g.read(part,'IGetMachine'),'ICWMachine')
            crib=g.typed(g.read(machine,'IGetToolcrib'),'ICWToolcrib4');tools=_items(g.read(crib,'GetAllTools'),g.typed,g.read,64)
            actual=[_object_id(self.doc,v,g.read)for v in tools]
            expected=[r['native_id']for r in self.loaded['serial_flat_catalogue']]
            require(actual==expected and len(actual)==len(set(actual))and actual.count(tid)==1,'Saved serial tool catalogue changed')
            tool=g.typed(tools[actual.index(tid)],'ICWTool')
            require(g.read(tool,'ToolType')==wanted['tool_type_raw']and g.read(tool,'CutDiameter')==wanted['cut_diameter_native']
                and group.exact(g.read(tool,'Protrusion'),wanted['protrusion_native']),'Actual qualified tool dimensions changed')
            dispatch=g.read(tool,'QueryInterface',IDispatch);mill=g.typed(raw,'ICWMillOperation')
            return g.dispatch_once(lambda:_member(mill,'SetTool',dispatch),persist_pending=pending)

    def generate(self,target,pending):
        self.before_generate(self,target)
        return generation.NativeBackend.generate(self,target,pending)

    def export(self,label,binding):
        return self.exporter(self,label,binding)
