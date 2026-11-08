---
name: ml-experiment-runs
description: Use when running local ML training jobs on the Mac.
metadata:
  source: own
  takeaway: "Check disk, swap and GPU jobs first; read back the PID, a launch call is not proof"
---

# Local ML experiment runs (Mac)

Covers pre-flight, launching, and debugging chance-level training.

## Pre-flight (every session, before any run)
1. Check storage in two places: `df -h /System/Volumes/Data` for internal scratch/swap, and `df -h` on the existing parent of the resolved output destination. Resolve output symlinks first; a guard on the working directory can measure the wrong drive. Moving checkpoints externally does not remove internal swap-space risk. Never delete user data to pass a storage guard.
2. Put run outputs on the external drive when mounted (`/Volumes/Transcend/outputs/<project>/`) and symlink the output folder into the code dir (`ln -s`). Never delete user files to make room; offer the choice (or ask) instead.
3. Check `pgrep -fl <trainer>` — one GPU job at a time; the Mac is also the user's workstation. Respect user rules (overnight-only runs, GPU tests of a few minutes, never touch the official test set).
4. For a width/memory check, exercise at least two real optimizer updates (including optimizer state) and an inference batch, not parameter-size arithmetic alone. Record MLX peak/active/cache memory, system swap before/after and free disk afterward. State which workload components were included: a student-only probe does not establish fit with a distillation teacher, calibration/export or sustained execution. A device-allocation pass does not prove the busy Mac avoided swapping; swap can consume the remaining disk.
5. Bound evaluation and calibration batches explicitly as well as the training batch. Existing defaults can be much larger than the requested training batch and invalidate a memory claim. Keep long-run launch approval separate from a successful short probe.

## Launching
- If a busy Mac trips its disk guard after the first updates, measure allocator active/cache/peak memory separately. An installed cache *limit* is not measured cache usage. Test a bounded or zero-cache configuration before changing the model or batch, apply it before allocation in only the opted-in job, and advance past the previous failure while recording losses, swap and disk. Preserve ordinary jobs' settings and qualify early improvement rather than declaring sustained fit from a setter query.
- Run the interpreter directly with output redirected to a file (`python -u x.py > run.log 2>&1`), then read the log. Keep short tests bounded inside the trainer so wrappers and streaming output do not change the execution path being diagnosed.
- For a short test of a long schedule, add a `--stop_epoch`-style flag so the LR schedule still spans the full run; shrinking `--epochs` changes the schedule and can hide the bug.
- Read bounded log/source sections and locate the relevant symbols before loading whole layer implementations — intermediate arrays and generated logs can overwhelm the diagnostic context.

- Record launch approval separately from any threshold override. A waived start-reserve gate does not waive a retained emergency floor. Read back the owned trainer PID and runtime status/log after detaching: startup can hit the emergency guard within seconds despite a passing preflight. A successful launcher call is not evidence that training remains running.
- Make queue STOP reporting independent of score parsing, rendering and git publication. Atomically replace score logs after checkpoint saves; preserve prior valid files on failure. Mark an output as owned only after acquiring the queue lock and successfully creating a fresh directory, and never overwrite an existing run's status from a rejected invocation. Regress publication failure and unowned-status preservation with isolated CPU fixtures; these tests do not establish GPU memory fit.

## Debugging a net stuck at chance (loss = ln(num_classes), acc 10%)
1. Inspect the current trainer, flags and prior logs before changing code. Preserve existing partial fixes; distinguish newly implemented changes from independently verified pre-existing controls.
2. Reproduce with the identical seed, data split, augmentation and full schedule first, using an early-stop flag to keep the test short. Compare actual losses with the failed run, then change one variable at a time.
3. Check activations and gradient norms on training images. An all-zero late ReLU stage plus zero upstream gradients supports collapse; chance accuracy alone does not identify its cause.
4. Test linear LR warmup (a useful starting point is ~300 steps) and global grad-norm clipping (a useful starting point is 1.0) separately when immediate peak Adam LR is implicated. Preserve the full schedule: a subset or shortened schedule can hide the instability.
5. Confirm recovery with a 1–2 epoch full-training-split run showing falling loss and validation above chance. Label a training-accuracy sample by its actual denominator, not the full training-set size.

## Model compatibility and export
Use `references/model-compatibility.md` when replacing a classifier or claiming that a trained model loads exactly into another implementation.

## Reporting
Keep chat to short status lines; results, commands, decisions and limits go in the project's task files/doc. Follow docs-over-chat to resolve document access without stopping independent local work. Distinguish completed code checks, unverified long-run accuracy, pending live-document sync and deliberately unlaunched runs.
