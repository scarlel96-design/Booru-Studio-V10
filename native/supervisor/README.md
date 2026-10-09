# Native Supervisor (Sprint 10 source)

Windows-only Rust bootstrap/containment root. No third-party Rust crate is required by this source.
It owns the Job Object, starts Core suspended, assigns Core before resume, inherits only the heartbeat
write HANDLE via STARTUPINFOEX handle-list, and measures lease age with QueryUnbiasedInterruptTime so
sleep/hibernate time does not become a false hang interval.

This Linux environment has no Rust toolchain and cannot certify the Windows binary. `tools/sprint10_windows_runtime_smoke.ps1` is the Windows build/E2E gate.
