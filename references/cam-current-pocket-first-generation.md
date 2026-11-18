# Current pocket Rough: settings and first diagnostic path

Pilot endpoint `solidworks_cam_configure_generate_current_pocket_rough` requires a completed saved current tool/context receipt and an exact ordered Rough/Contour pair with zero paths. It accepts one pinned recipe containing exactly seven existing fields with explicit expected/new values: entry type, spiral radius/pitch, first/subsequent depth, side and floor allowances. Tool assignment, start point, feeds, planes and the other operation are protected.

One current pair capture binds the actual selected operation. The existing setup-transform decoder reads all components before mutation; finite orthonormal axes, positive scale and exact operation origin/axis agreement are checked without claiming a CL/world mapping. Each changed field uses the existing typed setter with durable pending, raw integer return and immediate scalar readback; one complete final parameter comparison protects every other field and the observed floor alias.

The selected Rough alone receives one native GTP. Raw return and complete postcapture are persisted before generation-delta checks. Two complete generated captures must agree. One existing Save records its raw return/new source hash before later checks. A single CL export goes to an exclusively new local directory; it must contain one metric native-count-matched operation stream. Zero baseline paths require no preCL and confer no preCL preservation claim.

The current-context payload retains a complete saved snapshot, but the earlier GTP=false loader cannot consume this new generated scope. A later explicit generated-state verifier is required; flags are never relabeled. Failures after Save preserve actual Save facts and are uncertain. No automatic retry, rollback, regeneration, import, GOP or explicit rebuild is provided.

Native qualification is pending. D8/guide sweep, actual stock entry/exit, machining coverage, material cutting data, physical tool seating and production acceptance remain outside this diagnostic computation. Project IDs, source hashes, raw receipt paths and tooling identities are request/evidence data.
