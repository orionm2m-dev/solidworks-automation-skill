# Native MILL neck type2 profile

Observed with the installed CAMWorks type library 25.0 and ICWMillTool on 2026-10-31. This records a returned native silhouette, not a naming-based interpretation. Historical partial receipt SHA256: `ed6aebf4891d12bd4f46fd17621c80b10a2acd62dd9a652a1c3be87c2455373f`.

`MillToolShankType=2` has the following observed axial meaning, measured from the cutter tip:

- `EffCutlength` marks the cutting-length division but does not alone end the full cutting diameter in the CAM collision profile.
- `ShoulderLength` ends the cutting-diameter extension.
- The relieved diameter `ShoulderDia` runs from `ShoulderLength` to `ShankLength`.
- At `ShankLength` the silhouette steps radially to `ShankDia`; it remains at that diameter to `OverallLen`.
- No shoulder cone is implied. Native chains may contain a zero-length seam or omit it when `EffCutlength == ShoulderLength`.

For a cutter with cutting length 3 mm, relieved diameter 1.95 mm through 19.75 mm, and a 4 mm shank, the conservative step proposal uses `ShoulderLength=3`, `ShankLength=19.75`. The 4 mm step encloses the manufacturer's rounded and conical shoulder. It is a collision envelope, not a claim of exact manufacturer geometry. Its clearance assessment depends on the current machined stock and operation order; it must not be inferred from the original raw stock.

The first candidate creation stopped after its full profile was captured and before Save. Use `sw_cam_neck_tool_continuation` only with the exact failed receipt, complete returned actions, original module and marker pins, same owned process, unchanged saved source, and fresh full-profile reconciliation. The continuation rebinds the recorded tool ID, permits only the two length setters, checks all prior scalar tools and operation headers, then permits one Save. It cannot recreate a tool, assign a holder or tool, generate a path, or replay an uncertain setter.

The original writer and implicit-taper validator remain frozen as historical evidence. The continuation models the observed step separately. Production cutting parameters, holder collet seating, runout and physical tool qualification remain outside this nominal geometry result.
