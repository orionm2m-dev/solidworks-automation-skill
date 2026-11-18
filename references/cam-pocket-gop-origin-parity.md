# Exact GOP origin parity

The existing file-only GOP verifier now mirrors definition.capture: add definition_authority.origin_kind for saved_cam_caps or a genuine creator origin. Legacy recovered definitions keep their previous exact schema. Missing or wrong receipt origin fails exact equality; the verified context supplies the expected value. No original receipt, once marker, native getter/setter, Save/GOP dispatch, or guard is changed.

42 offline tests pass, including actual-branch, wrong/missing origin and legacy cases. New portable tests reuse installed test_pocket_gop_evidence.py fixtures. The actual GOP receipt is separately validated read-only; a prior failed Save prepare remains immutable and is never treated as a GOP retry permission.
