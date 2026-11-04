# Reconcile one proven owned startup after its ROT timeout

The read-only `solidworks_reconcile_owned_startup` tool accepts only the existing executable-launch receipt with status `uncertain`, phase `waiting_for_exact_pid_rot`, a recorded new PID, launch time and process identity, and the precise `SW_PROCESS_NOT_FOUND` connection outcome. It pins that original file by SHA-256 and never rewrites it.

An exact PID, executable path and creation FILETIME are required. The same retained OS process handle is checked before and after a strict PID-only connection and two empty-session observations. All open and hidden documents must be absent; ActiveDoc must be absent and UserControl must already be true. Visibility is observed without any setter; visible false or unknown is accepted. No launch, termination, ExitApp, unload, CAM load, document open/close/save or UI action is performed.

The separate output records successful ownership reconciliation with the original startup SHA, its historical error and exact current identity. The top-level historical `launch_attempted:true` comes from the original launch; `launch_attempted_by_reconciliation:false` makes the distinction explicit. It does not claim that the original startup finished successfully at its original time or that CAM is available.

The existing owned-exit validation is unchanged. Offline tests confirm that the new successful ownership receipt is accepted by `prepare_verified_empty`. Exit still independently needs its pinned current source, a separate fresh empty inspection receipt and two live empty/process checks. A batch containing reconciliation is not an accepted empty-inspection batch: save a separate inspection result, or its exact parsed tool payload.

Install the new module, test and this document. Add only the two nodes from SERVER_NODES.py and one registry name `solidworks_reconcile_owned_startup`. Never replace the entire staged server. Root alone performs live calls.
