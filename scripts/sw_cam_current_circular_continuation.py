"""已保存圆形口袋的配置/GTP上下文适配；原生动作复用现有有界实现。"""
from copy import deepcopy
from scripts import sw_cam_current_circular_authority as authority
from scripts import sw_cam_current_saved_generation_delta as delta
from scripts.sw_cam_current_circular_context import NativeCircularContext
from scripts.sw_cam_current_generation_native import NativeGenerationContext

require=authority.require


def _restore_request(loaded,source):
    request=deepcopy(loaded['binding']);request['expected_source_sha256']=source
    request.pop('prepare_receipt_path',None);request.pop('prepare_receipt_sha256',None)
    return request


class CircularBatchContext(NativeCircularContext):
    """保护原始 reference；新 target 仅来自真实已保存创建证据。"""
    def __init__(self,sw,clsid,tlb,v,data,report,persist,runtime_check):
        loaded=data['circular'];pins=list(data['pins'].values())+list(data['protected_pins'].values())
        if 'prepare_pin' in data:pins.append(data['prepare_pin'])
        super().__init__(sw,clsid,tlb,_restore_request(loaded,v['expected_source_sha256']),loaded['original'],report,persist,runtime_check,restore=loaded['restore'],continuation_pins=pins)


class CircularGenerationProof:
    """仅显式圆形路径允许已验证 Save 的 sketch 文件摘要转换。"""
    equal=staticmethod(authority.circular_state_equal);select=staticmethod(delta.select);compare_cl=staticmethod(delta.compare_cl)
    def __init__(self,backend,reference=None):self.backend=backend;self._mass_reference=deepcopy(reference)
    def verify_generation(self,before,after,ids,completed):
        require(after['sketch_state']['saved_file_sha256']==self.backend.source,'GTP snapshot source differs')
        return delta.verify_generation(authority.normalized(before),authority.normalized(authority.align_circular_mass(before,after)),ids,completed)
    def verify_saved(self,before,after):
        authority.pocket.verify_saved(before,after,self.backend.source)
        return dict(saved_capture_preserved=True,clean_document=True,reopen_persistence_verified=False)
    def save_comparison_state(self,state):
        if self._mass_reference is None:self._mass_reference=deepcopy(state)
        out=authority.normalized(authority.align_circular_mass(self._mass_reference,state));out['document']['needs_save']=False;out['sketch_state']['saved_file_sha256']='verified-source-transition';return out
    def cl_rows(self,before,after,ids,*,completed_ids=None):
        if not completed_ids:return delta.cl_rows(before,authority.align_circular_mass(before,after),ids)
        require(after['sketch_state']['saved_file_sha256']==self.backend.source,'Post-Save CL source differs')
        adjusted=deepcopy(after);adjusted['sketch_state']['saved_file_sha256']=before['sketch_state']['saved_file_sha256']
        return delta.cl_rows(authority.normalized(before),authority.normalized(authority.align_circular_mass(before,adjusted)),ids,completed_ids=completed_ids)


class CircularGenerationContext(NativeCircularContext):
    """捕获保留真实口袋；GTP、Save、CL及清理直接复用既有动作。"""
    _captured_state_equal=staticmethod(authority.circular_state_equal)
    def __init__(self,sw,clsid,tlb,args,loaded,report,persist,runtime_check):
        pocket=loaded['circular'];pins=[loaded['pin'],*loaded['pins'].values()]
        super().__init__(sw,clsid,tlb,_restore_request(pocket,args['expected_source_sha256']),pocket['original'],report,persist,runtime_check,restore=pocket['restore'],continuation_pins=pins)
        self.generation_loaded=loaded;self.args=args;self.attempted=[];self.last_document=None;self.entered=False;self.closed=False
        self.consumer_ids=deepcopy(loaded['state']['parameter_batch']['candidate_consumer_ids']);self.report.setdefault('native_read_count',0);self._capture_journal_managed=True
    def capture(self,label,partial):
        # native context 按实际已尝试 ID 验证生成计数；预先不猜测记录数。
        try:
            state=super().capture(label,self.consumer_ids,attempted_generation_ids=tuple(self.attempted))
            self.last_document=deepcopy(state['document']);return state
        finally:
            state=self.report.get(label,{})
            partial.clear();partial.update(deepcopy(state));self.persist()
    def generate(self,oid,state,*,pending,returned):
        original=self.loaded;self.loaded=self.generation_loaded
        try:return NativeGenerationContext.generate(self,oid,state,pending=pending,returned=returned)
        finally:self.loaded=original
    def save(self,*,returned):
        seen=[]
        def observe(value):seen.append(value);returned(value)
        super().save(lambda:require(self.report['actions']['SaveActiveDocument']['native_dispatch_pending'] is True,'Save pending must already be durable'),observe)
        require(len(seen)==1,'One actual Save return required');return seen[0]
    start=NativeGenerationContext.start
    adopt_saved_source=NativeGenerationContext.adopt_saved_source
    export_cl=NativeGenerationContext.export_cl
    parse_cl=NativeGenerationContext.parse_cl
    may_capture_failure=NativeGenerationContext.may_capture_failure
    finish=NativeGenerationContext.finish
    close=NativeGenerationContext.close
