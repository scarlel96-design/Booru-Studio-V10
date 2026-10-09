from __future__ import annotations

import threading
import time

import booru_studio.ui.remote_backend as remote


class _FakeConnection:
    def close(self):
        pass


class _FakeClient:
    def __init__(self, _connection, *, client_instance_id=None):
        self.jobs=[]
        self.client_instance_id=client_instance_id

    def snapshot(self):
        return {"revision": 1, "downloads": [], "queue": [], "history": []}

    def create_job(self, **kwargs):
        self.jobs.append(kwargs)
        return {"ok": True}

    def cancel_job(self, job_id, **kwargs): return {"job_id": job_id}
    def pause_job(self, job_id, **kwargs): return {"job_id": job_id}
    def resume_job(self, job_id, **kwargs): return {"job_id": job_id}
    def move_queue_job(self, job_id, direction, **kwargs): return {"job_id": job_id, "direction": direction}


def test_remote_backend_runs_transport_off_caller_thread_and_reports_commit(monkeypatch):
    caller=threading.get_ident(); transport_threads=[]; projected=[]; successes=[]; idle=threading.Event()
    monkeypatch.setattr(remote, "connect_local_socket", lambda endpoint, timeout_ms: transport_threads.append(threading.get_ident()) or object())
    monkeypatch.setattr(remote, "QtLocalEnvelopeConnection", lambda *a, **k: _FakeConnection())
    monkeypatch.setattr(remote, "UiCoreClient", _FakeClient)
    backend=remote.RemoteUiBackend(
        "opaque-endpoint",
        projected.append,
        on_error=lambda *args: (_ for _ in ()).throw(AssertionError(args)),
        on_idle=idle.set,
        on_success=lambda op, ctx: successes.append((op,ctx)),
    )
    backend.submit(" https://example.invalid/video ")
    assert idle.wait(2)
    backend.close()
    assert transport_threads and all(t != caller for t in transport_threads)
    assert projected
    assert successes == [("submit", " https://example.invalid/video ")]


def test_remote_backend_has_bounded_queue_and_no_blind_mutation_retry_contract():
    text=__import__("pathlib").Path("src/booru_studio/ui/remote_backend.py").read_text(encoding="utf-8")
    assert "Queue(maxsize=128)" in text
    assert "exact same durable command_id" in text
    assert "self._client_instance_id" in text
    assert "self._disconnect()" in text
    assert "threading.Thread" in text



def test_remote_mutation_reconnect_replays_same_client_and_command_identity(monkeypatch):
    attempts=[]; clients=[]; projected=[]; errors=[]; idle=threading.Event(); success=[]
    class ReplayClient:
        def __init__(self, _connection, *, client_instance_id=None):
            self.client_instance_id=client_instance_id; clients.append(str(client_instance_id))
        def create_job(self, **kwargs):
            attempts.append(str(kwargs["command_id"]))
            if len(attempts)==1:
                raise TimeoutError("simulated lost reply")
            return {"ok":True}
        def snapshot(self): return {"revision": 1, "downloads": [], "queue": [], "history": []}
    monkeypatch.setattr(remote,"connect_local_socket",lambda *a,**k: object())
    monkeypatch.setattr(remote,"QtLocalEnvelopeConnection",lambda *a,**k:_FakeConnection())
    monkeypatch.setattr(remote,"UiCoreClient",ReplayClient)
    backend=remote.RemoteUiBackend("ep",projected.append,on_error=lambda *a: errors.append(a),on_idle=idle.set,on_success=lambda *a: success.append(a))
    backend.submit("https://example.invalid/a")
    assert idle.wait(2); backend.close()
    assert len(attempts)==2 and attempts[0]==attempts[1]
    assert len(clients)>=2 and len(set(clients))==1
    assert errors==[] and success and projected
