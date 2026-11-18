# Read the current circular cutting context

`solidworks_cam_read_circular_cutting_context` reads one already generated circular MILL operation from an exact saved qualification history. It remains a pilot: one native case and software tests do not qualify arbitrary operations, cutting conditions or production output.

## Admission and limits

Supply the selected process ID and lifetime, exact active part path and current SHA256, an independently verified saved-CL reconciliation path and hash, the operation native ID, and a fresh receipt path. The reconciliation must bind the current saved source, native Save result, clean readbacks, feature/tool identity and complete saved operation inventory. `qualification_only` must be true. File paths are caller inputs; no project-specific location is inferred.

The bounded reader makes two complete cheap inventories and two targeted NC captures. Counts, generated/suppressed flags, target feature/tool links, source, process lifetime, document, event state and runtime identity must remain unchanged. Only a fixed getter allowlist is used, with a total budget of 1024 getter/interface reads. There are no setters, Save, GTP, GOP, AFR, retry or rollback actions.

## Feed modes and owned output storage

Read a feed as a value **and its mode**. `GetLeadinFeedrate` is called with owned DOUBLE and VARIANT_BOOL output storage. Untouched, non-finite, noncanonical boolean or unsuccessful HRESULT outputs are rejected. `GetZFeedrate2` is validated independently. The stored `GetLeadinFeedratePercent` field does not override a returned absolute mode. Likewise, `LinkToTool` is an observed boolean, not evidence that a particular feed was refreshed or that machining conditions are suitable.

## Observed native qualification

One completed native read used 640 reads and returned identical before/after captures, with clean document, unchanged source and runtime and no mutation. Observed fields were spindle 200, XY feed 1000, lead-in value 2 with `is_percent=false`, Z feed value 2 with `is_percent=false`, speed/feed method 0 and `LinkToTool=true`. The separately stored lead-in-percent field was 30. These are captured settings, **not recommended cutting conditions**. The exact native receipt and source hashes belong in the project evidence manifest, not in reusable code.

The reader deliberately leaves physical-unit and feed-to-CL binding qualification false. Interpret absolute units only alongside the separately verified MILL/CL unit convention. This observation explains why an inactive percentage field cannot be used to reinterpret an absolute feed; it does not by itself validate toolpath coordinates, holder/fixture clearance, stock removal, reopen persistence or production.

## Reuse and subsequent changes

Reuse this saved read before requesting an explicitly bounded parameter change. Preserve its receipt and all historical CL bytes. A later setter, regeneration or Save requires its own admission, readback, one-shot action guards and engineering review; this read endpoint provides no mutation authority. See [cam-circular-gtp-save](cam-circular-gtp-save.md) and [cam-cl-axial-metadata](cam-cl-axial-metadata.md).
