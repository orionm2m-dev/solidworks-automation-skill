# Prepared profile snapshot comparison

Scope: pilot qualification sketch creation in one exact saved part. This extension changes the pre-dispatch comparison only. It does not qualify CAM generation, machining geometry, Save, persistence, or production use.

Call `solidworks_cam_create_profile_sketch` with `action="prepare"` and retain its raw `before` object and `state_sha256`. For the subsequent `action="apply"`, pass the same ordinary fields, a new receipt path, `expected_state_sha256` from prepare and optional `expected_state` equal to the complete raw `before` object. The hash must match this payload. The existing source/path/PID and clean-part gates remain in force.

With `expected_state`, all fields except `solids[*].mass_raw` compare as exact canonical JSON. Every mass component, including trailing inertia terms, uses the unchanged existing relative tolerance `1e-10`, absolute tolerance zero. Counts, array lengths, bounding boxes, transforms, flags, feature names/types, specification and file SHA remain exact. Strict finite numbers and bounded dict/list shapes are checked before comparison; booleans cannot be numeric coordinates or mass values. Tuples and non-JSON containers are rejected.

The optional field is apply-only. Omitting it preserves the previous exact digest gate, including the existing 11-significant-digit digest. The raw expected snapshot and its hash are retained in the apply receipt. No automatic retry, save, rebuild, CAM or deletion is introduced.

Offline tests: `tests/test_sw_cam_profile_prepared_state.py` plus the existing profile sketch, existing-profile verification, APT/sketch schema and existing-profile endpoint suites. The saved regression fixtures demonstrate native mass noise within the established tolerance that crosses the old digest boundary. Tests do not connect to CAD. A successful test run is software qualification, not evidence of an executed native sketch operation.
