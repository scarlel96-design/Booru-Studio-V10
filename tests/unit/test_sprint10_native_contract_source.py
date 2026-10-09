from pathlib import Path


def test_native_supervisor_source_contains_required_containment_primitives():
    s=Path("native/supervisor/src/main.rs").read_text(encoding="utf-8")
    for token in ["CreateJobObjectW","JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE","AssignProcessToJobObject","CREATE_SUSPENDED","ResumeThread","PROC_THREAD_ATTRIBUTE_HANDLE_LIST","QueryUnbiasedInterruptTime","TerminateJobObject"]:
        assert token in s
    assert "booru_studio.domain" not in s and "JobId" not in s and "URL" not in s


def test_windows_worker_bootstrap_uses_raw_handle_not_parent_fd_number():
    s=Path("src/booru_studio/core/worker_launcher.py").read_text(encoding="utf-8")
    assert '"--worker-bootstrap-handle", str(read_handle)' in s
    assert "os.set_handle_inheritable(read_handle, False)" in s


def test_native_supervisor_uses_windows_argv_quoting_for_core_and_opaque_args():
    s=Path("native/supervisor/src/main.rs").read_text(encoding="utf-8")
    assert "fn quote_windows_arg" in s
    assert "slashes*2+1" in s
    assert "slashes*2" in s
    assert "quote_windows_arg(&args[1])" in s
    assert 'format!(" {}",quote_windows_arg(v))' in s
    assert "replace('\\\"'" not in s
