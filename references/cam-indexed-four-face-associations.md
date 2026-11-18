# Optional four named face associations

Use the existing `solidworks_cam_inspect_mill_profile_indexed` tool with optional `face_association_names`: exactly four unique names, each present in the explicit five-entry `index_mapping` and pinned five-name PROFILE headers; selected island count must be four. Omit the option for unchanged legacy behavior.

The option repeats the existing indexed-chain reads in two bounded snapshots. It then reads only the four named SOLIDWORKS Attributes and their linked planar face loops, using the existing face-association helper. Exact CAM headers are compared before and after the face reads. The existing source/header, clean-document, PID, event and 4096-read guards remain active; SW interface conversions consume the same budget. Generated SW interface source files are pinned and watched during capture. No setters, selection, rebuild, Save, CAM creation or process generation are added.

Each snapshot includes `face_associations` with raw model-space metre coordinates, curve trim parameters and senses. Both snapshots must match. Missing, ambiguous, non-face, nonplanar or nonanalytic associations reject acceptance and preserve partial diagnostics. `face_associations_read_complete` means completed stable raw observations; it does not prove geometric roles, CAM-to-world transform, analytic profile congruence, axial machining depth or production suitability. These claims remain false.

The low-level `read_face_associations` helper retains its six-name default and exact legacy result keys. Only an explicit `expected_count=4` returns four-face keys. It preserves the total edge limit of 128.

Validation is offline: synthetic interfaces, legacy regression tests, actual handler schema dispatch, changed header/name/source/metadata and shared SW-QI budget negatives. The real four names must come from the current header/indexed receipts; no fallback names or indices are tried.
