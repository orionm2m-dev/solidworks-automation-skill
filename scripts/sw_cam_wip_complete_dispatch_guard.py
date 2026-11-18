"""WIP-only bounded complete file guard; retains every inherited phase check.

The historical 128-pin guard remains unchanged. Each <=64-pin chunk is validated
by the original constructor, then all unique rows are held and hashed together
by one inherited scope. No chunk is entered or dispatched independently.
"""
from scripts import sw_cam_dispatch_guard as base
ScopedCamDispatchGuard=base.ScopedCamDispatchGuard
MAX_EVIDENCE_PINS=256
CHUNK_SIZE=64

class WipCompleteDispatchGuard(ScopedCamDispatchGuard):
    def __init__(self,sw,typelib_path,*,evidence_pins,**kwargs):
        if type(evidence_pins)is not list or not 1<=len(evidence_pins)<=MAX_EVIDENCE_PINS:
            raise ValueError('Complete WIP evidence must contain between 1 and 256 pins')
        super().__init__(sw,typelib_path,evidence_pins=evidence_pins[:CHUNK_SIZE],**kwargs)
        seen={canonical:digest for _,digest,canonical in self._rows}
        for start in range(CHUNK_SIZE,len(evidence_pins),CHUNK_SIZE):
            remaining=ScopedCamDispatchGuard(sw,typelib_path,evidence_pins=evidence_pins[start:start+CHUNK_SIZE],**kwargs)
            for path,digest,canonical in remaining._rows:
                if canonical in seen:
                    if seen[canonical]!=digest:raise ValueError('Conflicting hashes across complete WIP evidence chunks')
                else:
                    seen[canonical]=digest;self._rows.append((path,digest,canonical))
        self._wip_pin_preflight=dict(evidence_pin_count=len(evidence_pins),unique_file_count=len(self._rows),chunk_size=CHUNK_SIZE,validated_chunks=(len(evidence_pins)+CHUNK_SIZE-1)//CHUNK_SIZE,maximum_evidence_pins=MAX_EVIDENCE_PINS,all_unique_files_retained=True,native_calls=0)
    def summary(self):
        value=super().summary();value['wip_complete_evidence']=dict(self._wip_pin_preflight);return value