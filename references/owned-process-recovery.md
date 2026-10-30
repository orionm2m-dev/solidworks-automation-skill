# Recovery from a last known clean inventory

The solidworks_recover_owned_process tool can accept an empty known_unsaved_items
list only with a hash-pinned complete native document inventory and explicit
clean_inventory_is_last_known and no_known_unsaved_changes_since_inventory
assertions. The recovery manifest supplies clean_inventory_evidence as a path and
SHA256 pair.

The native solidworks_inspect_open_documents result must have the exact owned PID,
an exact document count, mutation_attempted=false, and needs_save=false for every
document. Its document paths must exactly equal the saved checkpoint set. Batch
evidence must contain exactly one inventory result; text, parsed and structured
representations must agree without Boolean/numeric coercion.

All existing ownership, exact creation FILETIME, executable path, native save
receipt, current saved-file hash, same-handle identity, one-shot termination intent
and post-exit checkpoint checks remain required. Apply uses the explicit empty
acknowledged_discard_ids list for this clean case. An empty list by itself is not
proof. The nonempty dirty case still requires exact acknowledgement of every
evidenced discard item.

This is historical evidence, not live COM inspection. The report explicitly sets
live_document_state_verified=false. It cannot prove that an unrecorded change did
not occur after the inventory. The last-known assertions must be grounded in the
operator's operation history. The tool neither connects to CAD nor saves,
restarts or enumerates arbitrary processes.

## Qualified clean recovery case

A saved one-document CAM qualification session was recovered after a close
request exceeded its 600-second orchestration deadline without a returned
CloseDoc result. The last completed native inventory contained exactly one clean
part. Its native save receipt and saved-file SHA were checked again before
recovery. A separate query-only OS record supplied the exact 100 ns creation
FILETIME; a rounded startup timestamp was not used as exact identity.

The guarded apply completed one termination of the owned process and verified
process exit and preservation of the saved checkpoint. Its receipt records zero
COM and UI calls, no unsaved discard items, and no restart. This qualifies that
bounded OS recovery case; it does not establish general CloseDoc reliability,
current live document state after a timeout, CAM correctness, or a completed
restart/reopen sequence. Keep the last-known inventory distinction explicit.

A timeout, a caller-side exception, an enabled main window, or absence of a
visible modal dialog does not establish that CloseDoc returned. Preserve the
pending call and inspect its saved result before any recovery decision. Do not
replay CloseDoc automatically. Inspect and prepare remain separate from apply;
restart and saved-file reopen require their own receipts.

The project knowledge index holds the exact case receipts and hashes. The
implementation remains generic: never copy a historical PID, creation time,
file path or prepared digest into a new recovery request.

## Prefer the qualified CAM lifecycle before process recovery

For a normal, unblocked CAM qualification copy that matches the qualified
lifecycle branch, prefer solidworks_cam_document_lifecycle over a generic
solidworks_close_documents call. This is a workflow preference supported by one
selected-feature MILL close/reopen case, not a universal CloseDoc fix. Do not
enter the CAM lifecycle while an earlier CloseDoc is still pending or blocked.

In that case, the guarded CAM CloseActiveDocument returned integer S_OK=0 and
close_verified=true; the target was absent from the bounded document inventory.
The close receipt retained status=review_required and persistence_verified=false.
A separate exact-path reopen and read-only CAM capture then confirmed the saved
feature axis/depth, selected tool diameter, one generated rough-operation record
count and an ungenerated finish sibling, with the saved-file SHA unchanged. A second guarded CAM close after that
reopen also verified closure of the same copy. This is repetition on one fixture,
not a second independent model qualification.

Keep these receipts separate: generic CloseDoc timed out in the earlier case;
CAM CloseActiveDocument completed in the later qualified case. Neither finding
proves a general cause or fix. Reopened inventory/record-count persistence does
not establish physical cutting depth, complete trajectory geometry, holder
clearance, units, manufacturing readiness or all CAM Save/Restore combinations.
