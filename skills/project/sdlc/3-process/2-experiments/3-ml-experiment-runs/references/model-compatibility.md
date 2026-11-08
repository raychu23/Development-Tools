# Exact model compatibility and classifier replacement

Use for discrete or quantized models trained in one implementation and loaded into another.

## Procedure

1. **Read the target contract before designing the adapter.** Trace constructor fields, parameter orientation, sparse slot order, input/output quantization grids, calibration rules, padding and output scoring. Supply wiring explicitly when the target otherwise initializes it randomly.
2. **Validate the model configuration before allocation.** Enforce the requested connection count in every classifier layer; reject an undersized input or hidden dimension instead of silently reducing the count. Check grid divisibility and shared/per-channel calibration constraints.
3. **Make discrete decisions consistent.** Use the same single first-argmax option for hard inference, straight-through training and export. Equal option maxima must not activate multiple physical wires. Fold the actual fixed slope when one is configured, not an unused learned slope.
4. **Restore the full checkpoint strictly.** Require every expected parameter and running statistic with matching shapes, finite values and valid domains. Normalize only explicitly supported historical aliases/scalar statistics; reject conflicting duplicates, missing data, unexpected keys and invalid or duplicate wiring indices. Never let a full-model check silently retain random parameters.
5. **Expose intentional partial initialization separately.** A new incompatible classifier may reuse a complete validated convolution trunk through a clearly named trunk-only option. Keep full and trunk-only initialization mutually exclusive. Deliberately new head parameters are not a lossless conversion of the old head.
6. **Verify through actual target layers.** Batch the permitted validation split, including the final partial batch. Compare pooled features, quantized hidden activations and final discrete counts before comparing predictions. Check every winning-class tie mask as well as first argmax. Refuse mismatches, nonfinite values and incomplete coverage with a nonzero exit.
7. **Define the logit equivalence contract explicitly.** If final scores differ by a positive shared affine count mapping, numeric logits need not match. Prove exact counts, predictions and complete winning-class ties instead; do not call numeric logits identical.
8. **Exercise newly saved checkpoints.** Perform a bounded update/save/reload/export smoke in addition to checking a pre-existing checkpoint. Include negative regressions for malformed restoration, inconsistent slopes, wire ties, changed hidden values with unchanged accuracy and empty requests.
9. **Separate exactness from performance.** A low-accuracy exact-export candidate is not the historical high-accuracy model. Report each checkpoint's own accuracy, data scope and training history. Mark the old head's compatibility gap separately from the new candidate's proven export contract.
10. **Keep proof levels separate.** CPU/AST/mock-boundary checks establish shape, validation and orchestration contracts; they do not establish target kernels or serialization behavior. Pair them with real framework execution, record its revision/configuration and disclose any workload not exercised.

## Useful assertions

- Sparse index layout and threshold layout preserve corresponding wire slots, even when indices are nonidentity or unsorted
- Both requested classifier layers use the exact connection count
- Fixed shared slope survives folding and reload
- All requested examples are checked, including tail batches and tied predictions
- Full verification cannot silently succeed as a convolution-only check
- Warm-started trunk parameters are complete and the incompatible head is intentionally replaced
