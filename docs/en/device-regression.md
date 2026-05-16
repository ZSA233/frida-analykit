# Device Regression Flow

## Purpose

This document preserves the validated operating rules for `frida-analykit` device regression, especially for these scenarios:

- `make device-test-all`
- `pytest tests/device -m device`
- `frida-analykit doctor device-compat`
- pre-release device regression checks

The goal is not to "fix as soon as something turns red". The first step is to classify the failure as:

- device flakiness
- host-side test/toolchain problem
- real code regression

Only after classification should code changes be considered. This avoids turning temporary device instability into long-term code complexity.

## Basic Principles

- A single failure is evidence, not a root-cause conclusion.
- Preserve the failure scene first: device serial, failing stage, stdout/stderr, `adb devices -l`, and whether another device passed.
- Run multiple rounds before deciding to fix; do not add retries, timeouts, or defensive branches after the first red result.
- Device instability is acceptable only when the device can recover and the flow can continue.
- Recovery logic must be scoped to a clear stage and a clear error meaning. Do not turn every path into a long wait.

## Environment Variables And Control Entrypoints

### Environment Variables

| Variable | Main effect | Purpose |
|:--|:--|:--|
| `FRIDA_ANALYKIT_ENABLE_DEVICE=1` | `pytest tests/device -m device`, `make device-*` | Enables device tests; without it, device tests are skipped. |
| `ANDROID_SERIAL=<serial>` | `make device-test*`, server commands, default device selection for `doctor device-compat` | Pins the target device; recommended when multiple devices are online. |
| `FRIDA_ANALYKIT_DEVICE_APP=<package>` | app-backed device tests | Overrides the default test package `com.frida_analykit.test`. Use it when regressing a specific app. |
| `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1` | `pytest tests/device -m device` and equivalent `make device-*` wrappers | Skips app-dependent device tests and keeps server, attach probe, and REPL handle flows. |
| `FRIDA_ANALYKIT_DEVICE_LOCAL_SERVER=<path>` | `tests/device/test_server_install.py` | Provides a local `frida-server` file for `--local-server` install-path tests; those tests skip when unset. |
| `FRIDA_ANALYKIT_DEVICE_FRIDA_VERSION=<version>` | `DeviceTestContext`, multi-version Frida device regression | Explicitly chooses the managed Python/Frida version for device regression; defaults to the device profile when unset. |

### `make` Parameters And Command Arguments

- `make device-test DEVICE_TEST_SKIP_APP=1`
  Passes `FRIDA_ANALYKIT_DEVICE_SKIP_APP_TESTS=1` to pytest. Use it for quick regression of flows that do not depend on an app.
- `make device-test DEVICE_TEST_APP=<package>`
  Passes `FRIDA_ANALYKIT_DEVICE_APP=<package>` to pytest. Use it to run the device suite against a specific app.
- `frida-analykit doctor device-compat --serial <serial>`
  Pins compatibility sampling to one device and avoids accidental selection when multiple devices are online.
- `frida-analykit doctor device-compat --all-devices`
  Runs minimal injection-based compatibility sampling on every currently online device.
- `frida-analykit doctor device-compat --app <package>`
  Explicitly chooses the app for compatibility sampling; without it the command checks config first, then falls back to the default test package.

Recommended interpretation:

- When running `pytest tests/device -m device` directly, prefer environment variables.
- When running through `make device-*`, prefer shorter parameters such as `ANDROID_SERIAL`, `DEVICE_TEST_APP`, and `DEVICE_TEST_SKIP_APP`.
- When device regression fails, record these variables and parameters before classifying the failure. Otherwise it is hard to distinguish device differences, config differences, and code regressions.

## Recommended Order

### Baseline Regression Before Release Or Device-Related Changes

1. Run one full device regression:

```sh
make device-test-all
```

2. If the change touches any of these paths or flows, run at least one more stability-confirmation round:

- `src/frida_analykit/device/`
- `src/frida_analykit/server/`
- `src/frida_analykit/development/device_*`
- `tests/device/`
- `spawn` / `attach` / `server boot` / `server install` / `doctor device-compat`

3. If the first round fails, do not edit code immediately. Classify the failure first.

### Classification Flow After Failure

1. Record the failing device serial, failing test, and failing stage.
2. Immediately inspect:

```sh
adb devices -l
```

3. If the failure is concentrated on one device, prefer a targeted rerun for that device instead of changing global logic.
4. If the failure is unrelated to the device, inspect the host-side test flow first.
5. Treat it as a real code regression only after it reproduces repeatedly.

## Failure Classification

### 1. Device Flakiness

Typical signals:

- It appears on only one device while another device passes the same stage.
- The target device briefly disappears from `adb devices -l`, or its transport id changes.
- The failure happens around `server stop`, `server boot`, attach probe, or app launch transitions.
- The error contains:
  - `ServerNotRunningError`
  - `unable to connect to remote frida-server`
  - `connection reset`
  - `connection closed`
  - `requested config.server.device ... but connected devices are ...`
- A targeted rerun passes after the device returns to ready state.

Handling rules:

- Accept a single failure as flakiness evidence.
- Prefer narrow recovery logic that continues after the device has recovered.
- Do not globally raise all timeouts or retry counts.

### 2. Host-Side Test/Toolchain Problem

Typical signals:

- Two devices fail at the same host-side stage.
- The failure happens before touching the device, for example:
  - `npm pack`
  - `npm install`
  - workspace build
  - local dependency resolution
  - release metadata download
- A single-device rerun may pass, but the failure is not fundamentally tied to ROM or device state.

Handling rules:

- Fix host-side concurrency, cache, download, or dependency-resolution semantics first.
- Do not hide host-side races behind device retries.

### 3. Real Code Regression

Typical signals:

- Two devices fail consistently at the same test point.
- Targeted reruns still reproduce while the device is ready.
- The failure is independent of online/offline device state and strongly tied to a specific behavior, such as:
  - a fixed attach/spawn path failure
  - a fixed doctor/probe semantic error
  - a fixed runtime/build/install breakage

Handling rules:

- Converge on the root cause before fixing.
- After the fix, run at least one single-device validation and one multi-device validation.

## Retry And Recovery Constraints

Recovery is allowed only when it satisfies these constraints:

- It must be staged, for example:
  - host-side npm packaging/build
  - brief device disconnect after `server boot`
  - remote server temporarily unreachable during attach probe
- It must be triggered by clear evidence, not by all failures.
- It must have a bounded retry count. The default is one recovery chance; increase it only when evidence supports doing so.
- Waiting must be short and bounded. Prefer targeted waits in the 5 to 20 second range, not a global timeout increase.
- Host-side deterministic errors such as missing dependencies, build failures, or protocol semantic errors must not enter device recovery.

## Pre-Release Device Gate

When a release touches the device path, complete this gate before tagging or publishing:

1. Finish at least two rounds of `make device-test-all`.
2. If any round fails, classify it before continuing:
   - Device flakiness: wait for recovery, run one targeted verification, and continue only after it passes.
   - Host-side problem: fix it first, then rerun the full regression.
   - Real code regression: stop the release and fix the regression first.
3. Do not package a single intermittent red result as a final code-fix conclusion.

## Recommended Record Items

For each abnormal device regression, record at least:

- command
- time
- failing device serial
- failing test or stage
- `adb devices -l` output at failure time
- whether only one device failed
- whether rerun passed
- final classification: device flakiness / host-side problem / real code regression

If the final classification is a code issue, also fold the conclusion into:

- long-term rules in `AGENTS.MD`
- release gates in `docs/release-process.md`
- implementation constraints in `src/frida_analykit/DESIGN_SPEC.MD`

