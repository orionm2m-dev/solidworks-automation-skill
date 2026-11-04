# TURN machine post parameter qualification probe

`solidworks_cam_probe_turn_post_parameter` is a pilot read-only probe of the selected TURN machine. It requires an explicitly connected process and its creation time, an exact saved part path and SHA-256, and exact operation, generated-operation and toolpath-record counts. `qualification_only=true` and `action="probe_index_zero"` select its fixed contract.

The reader validates the declared `ICWMachine5` IID and exact getter ABI before connecting to CAM. It calls `GetNumPostParam` once. Only a strict count from 1 through 512 permits one call of `GetPostParam(0)`. Zero count skips that call. Invalid count, an exception, invalid output shape or a CAM event stops the probe. A native `found=false` ends parameter access and preserves the converted output as diagnostic evidence. It does not try another index or another getter.

The accepted result shape is two BSTR outputs plus a strict Boolean retval. When found is true, both strings must be at most 1000 characters. Names and values remain raw strings. The bounded converted-output diagnostic is stored immediately after a getter returns, before checking CAM events. It does not claim to preserve original VARIANT or SAFEARRAY metadata.

The document, process lifetime, saved file, collected CAM inventory and all enumerated operation IDs are checked around the probe under one active CAM message session. Stable pre-existing unsaved memory is allowed and reported; the file hash does not identify all RAM state. Only SOLIDWORKS identity and file checks follow event disconnection. Inventory equality does not prove that all CAM parameters or full path coordinates are unchanged.

`observation_verified=true` means the bounded probe and its guards completed. `index_zero_acceptance_verified=true` means that single call returned found=true with bounded strings while those guards held. The result remains `review_required`. Because parameter getters are not repeated, `readback_verified` remains false. `catalog_complete`, `zero_based_catalog_verified`, `preset_values_verified`, units, coordinate frames and production qualification remain false. Runtime drift revokes verification flags while preserving the native evidence.

The SDK documents the count and indexed name/value/found contract but does not state the index base. This probe is an explicit qualification observation; one accepted index does not prove that the complete catalogue is zero-based. No continuation enumeration is implemented. The tool makes no setters, controller lookup or selection, tool/feature-contour reads, CL export, generation or Save calls.

Validation currently covers offline fake-CAM failures and exact installed type-library metadata. A live native run has not yet been performed. Native qualification must report its actual result before this capability can be marked as observed on SOLIDWORKS.
