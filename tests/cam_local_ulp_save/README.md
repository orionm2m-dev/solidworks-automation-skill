# Bounded floating-point save continuation tests

The synthetic fixtures cover eight observed NC values, a fixed nominal anchor with at most one adjacent floating-point value, rejection of other changes, raw-value preservation, one Save, no generation or parameter writes, and refusal to replay an uncertain result.

From the repository root:

```sh
python -B -m pytest tests/cam_local_ulp_save -p no:cacheprovider
```

The repository is the default implementation root. `SOLIDWORKS_SKILL_ROOT` can select another installed checkout. No project receipt, CAD connection or staged implementation is required.
