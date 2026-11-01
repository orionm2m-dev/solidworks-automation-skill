# Reading the selected TURN controller

`solidworks_cam_inspect_turn_controller` uses the declared `ICWTurnMachine.GetController` interface. It does not fall back to another controller, select a post, change settings, generate paths, or save documents.

The caller provides the explicitly connected process ID, an exact clean saved part path and its SHA-256. The reader verifies the TURN machine type, document and inventory before and after reading. The name is an observation, not proof of the loaded post file or of machining safety.

Optional `include_parameters=true` requires an already observed exact non-APT `.ctl` name in `expected_controller_name`. The reader compares it to the current name and calls `ICWMachine5.GetControllerParameters(False, name)` once. It does not strip extensions or substitute another name. Keys and values remain native; no units or coordinate frames are inferred.

## Verified native scope

A selected TURN machine returned a nonempty controller name through `GetController` while the newer `GetController2` reader had returned no name. These are distinct native observations; an empty result from one interface does not prove absence of a selection.

For the observed controller, parameter lookup returned `(None, None, True)`. The Boolean alone does not establish that parameter values are available. The reader records the bounded converted output shape and reports the parameters unavailable. Do not repeat this lookup for unchanged inputs or invent preset values from the name.

The output-shape collector shares the existing bounded conversion diagnostics. It preserves unknown types without invoking their string conversion, bounds nesting and output count, and represents non-finite values safely for JSON.

## Continuation

Keep a successful name read separate from preset access, preset units, a setting change, and engineering qualification. Return positions remain unqualified until actual values and their coordinate frame are established. The tool never authorizes manufacturing or automatically advances to a setter.
