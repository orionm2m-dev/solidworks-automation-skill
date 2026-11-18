"""Bounded complete evidence guard without changing historical guard implementation."""
from scripts.sw_cam_dispatch_guard import ScopedCamDispatchGuard


class CompleteCamDispatchGuard(ScopedCamDispatchGuard):
    """Preserve every file and inherited phase check for up to 128 evidence pins.

    Each chunk is validated by the original constructor. The resulting rows are
    merged before entry; one inherited scope then holds and hashes all rows at
    every boundary. No validation or dispatch boundary is removed.
    """
    def __init__(self,sw,typelib_path,*,evidence_pins,**kwargs):
        if type(evidence_pins)is not list or not 1<=len(evidence_pins)<=128:
            raise ValueError('Complete evidence must contain between 1 and 128 pins')
        super().__init__(sw,typelib_path,evidence_pins=evidence_pins[:64],**kwargs)
        if len(evidence_pins)>64:
            remainder=ScopedCamDispatchGuard(sw,typelib_path,evidence_pins=evidence_pins[64:],**kwargs)
            seen={canonical:digest for path,digest,canonical in self._rows}
            for path,digest,canonical in remainder._rows:
                if canonical in seen:
                    if seen[canonical]!=digest:
                        raise ValueError('Conflicting hashes across evidence chunks')
                else:
                    seen[canonical]=digest
                    self._rows.append((path,digest,canonical))
