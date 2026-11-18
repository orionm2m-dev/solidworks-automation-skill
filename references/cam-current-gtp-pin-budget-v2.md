# Current Rough GTP evidence budget v2

The saved tool-recovery chain has 57 unique current pins. The original GTP
preparation requires 68; the explicit versioned context/capture and guard pins
make this package's projected complete set 71. No original pin is dropped.
The projected Save roots are 69 and a subsequently loaded context has 72 pins.
These counts are topology estimates until the actual saved recovery is supplied.

The new explicit tool `solidworks_cam_configure_generate_current_pocket_rough_v2` inherits the existing request schema. The old tool/module and its recovery consumers remain byte-identical. The new tool emits
CURRENT_POCKET_SEVEN_FIELDS_FIRST_GTP_SAVE_CL_V2_PIN128 and the explicit saved
context CURRENT_SAVED_POCKET_CONTEXT_V2_PIN128. The once key retains the v1
namespace for the same target/source, so a consumed v1 attempt blocks v2.

ScopedCamDispatchGuard still defaults to 64; only strict integer limits 64 or
128 are accepted. This GTP path opts into 128 at the inherited dispatch guard,
full definition capture and pair read guard. The entire source/evidence set is
hashed at the existing boundaries. Read/QI budgets and native call allowlists
are unchanged. This option is internal, not an arbitrary request field.

The pinned original current-context, definition, pair-reader and tool modules
remain unchanged. The versioned definition adapter changes only its guard
budget. The versioned Save function is AST-identical to the original and calls
the same run_one_existing_save primitive. Its pin validator and scope are
versioned because the 69 unique roots cannot fit the legacy 64 limit. Local
bundle adaptation removes identical duplicate occurrences before Save while
proving equality of canonical unions and retaining every guarded file.

Seven field comparisons, selected GTP, Save and CL native primitives are
unchanged. Uncertain native returns still stop without retry. Generated receipts
are not accepted by either generic context loader; no false GTP flag or legacy
loader compatibility is claimed. A later recovery of a failed generated v2
state must be admitted separately against its actual evidence.

Offline tests cover 68 and projected 71-pin Save/loader chains, the 128/129
boundary, conflicting and missing pins, nested guards, wrong ownership,
content changes, cross-version once keys and native orchestration failures.
They do not qualify native GTP, CL geometry or production.
