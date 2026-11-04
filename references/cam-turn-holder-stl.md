# Existing TURN boring-holder STL qualification

`solidworks_cam_qualify_turn_holder_stl` prepares or applies an STL file to the existing own tool of an exact TURN finish-bore operation. This is a pilot definition change. It does not qualify holder clearance, physical fit, file units, machine coordinates or machining.

The narrow contract requires a clean saved single-part qualification session, an exact process ID and creation time, saved source path/SHA-256, selected operation/tool native IDs, holder catalogue ID, observed standard shape 0, and LEFT_UP orientation 5. Every affected operation must be explicitly listed with setup/operation indices, native operation ID and ordered linked feature IDs. Only finish-bore type 6 with no generated path is supported. All operations sharing the tool must match both the full operation/tool native-ID scan and the tool station usage list. Canonical IUnknown equality is retained as telemetry and is not required to be true.

The input STL is immutable and SHA-pinned. The command reads it; it does not overwrite it, create tools, assign a different tool, modify the insert, write TechDB, generate paths, or Save. The input file must already have a reviewed geometry/frame manifest. The command does not validate the physical meaning of arbitrary mesh contents.

## Native contract

On `ICWTurnTool`, the two allowlisted methods are:

- `SetTurnHolderSTLFile(BSTR)`, DISPID 5, HRESULT-only with no OUT value. Its type-library help states that it also selects STL shape.
- `SetTurnHolderSTLFileUnit(c_int)`, DISPID 6, HRESULT-only with no OUT value.

A normal `None` return is not Boolean failure. The tool records return evidence and verifies state separately.

The own `ICWTurnToolHolder` provides these declared property getters: `HolderShape` (DISPID 11, native integer), `HolderShapeFilePath` (25, BSTR), and `HolderShapeFileUnit` (26, native integer). The generated ABI is checked before application access. A null/empty standard-holder path is retained exactly. After assignment the absolute file path must match, a positive changed shape value must be observed, and the unit field must equal the requested raw value.

Only raw unit value 2 is accepted in this pilot. The installed `CWLengthUnits_e` declares `CW_METER=2`, but the setter takes an untyped native integer and the local SDK does not explicitly bind that field to this enum. Matching raw unit readback is therefore not proof of physical scale. No inferred semantic label is attached to the observed shape number.

The bundled holder documentation specifies boring-bar LEFT_UP, origin at the mounted insert nose centre, Z parallel to the turning axis, STL in metres, and no translation into positive coordinate space. These file conventions do not prove the current machine/setup frame or native import transformation.

## Prepare and apply

Prepare performs two equal complete captures. It returns the exact state/recipe digest and no mutation receipt. Apply requires that digest, the same explicit affected-operation list and a fresh JSON receipt. It repeats the complete captures before claiming a persistent attempt marker keyed to source file identity and tool ID.

Apply calls the file setter once, reads and checks the complete state, then calls the units setter once. Each call has durable intent before native entry, a scoped file/process/document/event guard, and another complete state check after intent publication. The two setters are not atomic. A failed or uncertain first call prevents the units call. A failed second call preserves the first outcome. Neither automatic retry nor implicit rollback is supported; a new receipt cannot bypass the attempt marker.

Two final captures, event cleanup, process lifetime, document identity and immutable file checks are required before file-field readback can be reported successful. Post-call runtime drift preserves native evidence, revokes success and updates only the receipt created by that call.

Preservation comparison covers operation order and native IDs, linked feature IDs, selected feature profile, station usage, observed own-tool scalars and holder file/shape/unit fields for every supported assigned holder, plus collected toolpath record counts. Only target-holder file/shape/unit, the dirty flag and derived target tool-info strings may differ. Unexpected metadata changes stop with an uncertain result for review. Hidden geometry and old CL coordinates are not read or proven unchanged; compare independent CL evidence where needed. Unassigned tools and unknown holder types are outside the preservation claim.

## Qualification boundary

The software tests exercise actual shared-tool snapshot traversal, two setup collections, native-ID station usage, false canonical equality telemetry, exact source/STL pins, partial failures, events, no replay and durable runtime-drift handling. These are software checks, not a native assignment test.

A successful apply remains `review_required`, with geometry scale, coordinate frame, units semantics, physical holder and production qualification all false. Before GTP, independently read the imported holder geometry and compare scale, nose-centre origin, handedness and control points to the reviewed mesh. The existing bounded contour reader may be used only if the custom-holder native getter succeeds within its declared limits; its current successful standard-holder captures do not establish support for STL geometry. The declared native `ICWTurnToolHolder.CreateSTL(BSTR)` can support a separate bounded export/readback capability, but this endpoint does not expose it.
