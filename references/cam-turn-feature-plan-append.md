# Append-only TURN feature operation plan

Status: staged software extension; no native application qualification recorded by this package.

The endpoint `solidworks_cam_qualify_turn_feature_plan_append` prepares or applies exactly one `ICWFeature.GenerateOpPlan(1)` to a copied TURN bore feature in an existing reverse setup. The RETAIN value is fixed. The endpoint cannot write the feature attribute, generate toolpaths, save a document, move or copy features, alter tools, call a setup/global plan, or retry.

The copied feature must already exist as the only feature in the exact reverse feature setup, and its linked operation setup must be empty. The original witness operation and original source feature remain pinned. Both setup pairs, process lifetime, saved qualification part, protected original and current archive, current CAM counts and event subscription are checked by existing guards.

`expected_copied_feature_sha256` is `_digest(copy_receipt["after"]["copied_feature"])`, using `scripts.sw_cam_turn_tool._digest`. It pins the copied native ID, feature setup ID, complete raw line/arc profile, attribute metadata and spindle metadata. After a deliberate save, use the current saved-part hash and an exact current archive; the feature observation must still match. No coordinate-frame conversion or source/copy machining equivalence follows from this digest.

`expected_new_operation_types` is a required ordered list of distinct reviewed types from `14`, `9`, `5`, `6`, with at most four elements. Supply the actual reviewed sequence explicitly; `[14, 9, 5, 6]` is a candidate recipe, not a guarantee. Any difference in count, order or type after the single call yields an uncertain receipt without rollback or replay.

Prepare takes two complete agreeing captures. Apply repeats those captures, checks the prepared digest, claims an exclusive durable once marker keyed by file identity and copied feature ID, writes the pending receipt, and performs a fresh full capture before its single dispatch. It then requires two agreeing post-call captures. `GenerateOpPlan` has an HRESULT-only signature, DISP 3, one IN `c_long` argument and no OUT argument. Python `None` is not a Boolean success/failure value; exact readback determines the outcome. Lost replies, events, capture drift and receipt or cleanup failures cannot qualify the result. A claimed attempt cannot be replayed, including after a partial mutation.

The allowed delta consists only of new unsuppressed operations in the exact target operation setup, in the explicit expected type order, each linked solely to the copied feature and with no generated toolpath. All old operation rows, order, links, tool IDs, generated flags and toolpath record-count lists must agree. Every feature ID and its order must agree. The original source and copied feature raw profiles and attribute metadata, observed stock type, and available setup frame observations must agree.

Each operation's own tool is read through the existing bounded profile helper. Observed insert and holder scalars must remain equal for old operations; equal IDs alone are not used to infer equal tool content. Unsupported TURN drill geometry is explicitly unavailable, without an interface fallback. Full tool/holder geometry, unobserved feature profiles, CL coordinate bytes, hidden settings, decoded transform matrices, persistence and physical machining suitability remain unqualified. A separate existing CL comparison can check old toolpath coordinates.

## Integration

Install `scripts/sw_cam_turn_feature_plan_append.py` and its two test modules. Merge only the two top-level AST nodes from `mcp-server/server_append.py` into the current server before its main guard. The nodes are `SolidWorksCamTurnFeaturePlanAppendInput` and `solidworks_cam_qualify_turn_feature_plan_append`; they reuse existing imports and the locked runtime/process dispatch. Do not replace the complete server with a staged snapshot. The staging `tests/conftest.py` is an overlay harness only and is not an installed test dependency.

The wrapper advertises a destructive, nonidempotent action. Prepare itself is read-only. The default action is prepare; apply requires the exact prepared state digest and a fresh absolute JSON receipt. The current process must be the explicitly connected instance. No connection or application call occurs during pure request validation.

## Software validation

The synthetic test graph uses actual bounded collection, inventory, source/copied profile, own-tool and lifecycle traversal with eleven old operations. It checks successful HRESULT-only return, exact appended sequence, old order/path/profile changes, same-ID insert/holder changes, event stops, lost replies, durable receipt ordering, no replay and ABI drift. MCP tests execute only the two staged AST nodes in an isolated test server and check strict fields, routing, locking, process/document/runtime guards and mutation annotations. These tests do not establish native CAM behavior.

## Post-call runtime identity drift

The public wrapper checks the runtime before and after core execution. A failed final check preserves the native outcome and observations, but revokes `readback_verified` and `apply_eligible`. Its status is `uncertain` when a mutation was attempted and `error` otherwise. The previous summary is retained as `outcome_before_runtime_check`; it is historical evidence, not a current qualification.

The core marks `receipt_created` and `receipt_path` only after exclusive creation. The wrapper durably rewrites only that invocation's owned receipt with the downgraded outcome, without further CAM calls. A failed rewrite is exposed as `receipt_write_error` and `runtime_drift_receipt_updated=false`; in that case the previous on-disk receipt is not authoritative. Pre-existing or unowned receipt files are never rewritten by this recovery path.

## TURN internal-feature discriminator

The source and copied feature must both have `feature_type_raw=2` and `turn_feature_type_raw=2`. These are separate fields: the generic type identifies TURN, and the latter is the internal-profile value observed in the validated bore workflow. Source and copied attribute ID/name and segment count must agree; raw coordinates may differ after reverse-setup copy. The copied raw profile remains independently digest-pinned.

The previous staged value `3` was a fixture-derived implementation error. The fixtures now use the validated value `2`, including the observed Rough-Finish strategy metadata. Separate negative tests reject `3` on the source, copy or both even when the copied digest matches. The method help declares a LONG result without naming its subtype enum; generic feature-category enum constants are not substituted for that missing declaration.
