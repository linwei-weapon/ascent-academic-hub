"""Isolated, bounded processes supervised independently of slow business work."""
from __future__ import annotations
import hashlib
import logging
import multiprocessing
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from . import store

log = logging.getLogger(__name__)


def _assignment_valid(payload):
    """Fail closed independently of a stalled supervising thread."""
    try:
        uri = Path(payload['store_path']).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as conn:
            row = conn.execute('SELECT status,lease_generation,lease_until,deadline FROM er_run WHERE id=?',
                               (payload['run_id'],)).fetchone()
        return bool(row and row[0] == 'running' and row[1] == payload['lease_generation']
                    and row[2] > time.time() and row[3] > time.time())
    except (OSError, sqlite3.Error, KeyError, TypeError):
        return False


def _try_execution_slot(store_path, slot):
    """OS-owned locks, released on process death, not when a DB lease expires.

    Windows named mutexes require no files. Unix advisory locks use dedicated
    adjacent lock files; stale files do not retain a lock after process exit.
    """
    target = Path(store_path).resolve()
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        key = hashlib.sha256(os.path.normcase(str(target)).encode('utf-8')).hexdigest()
        handle = kernel.CreateMutexW(None, False, 'Global\\ExpertResearch-' + key + '-' + str(slot))
        if not handle:
            raise OSError(ctypes.get_last_error(), 'execution_slot_unavailable')
        acquired = kernel.WaitForSingleObject(handle, 0)
        if acquired in (0, 0x80):  # acquired or abandoned by a terminated owner
            def release():
                kernel.ReleaseMutex(handle)
                kernel.CloseHandle(handle)
            return release
        kernel.CloseHandle(handle)
        if acquired != 0x102:
            raise OSError('execution_slot_wait_failed')
        return None
    import fcntl
    handle = open(str(target) + '.slot-' + str(slot), 'a+b')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    def release():
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
    return release


def _worker(sender, payload, executor=None, authorizer=None):
    """Only this subprocess runs analysis and final live permission checks."""
    done = threading.Event()
    parent = multiprocessing.parent_process()
    def watchdog():
        while not done.wait(0.2):
            if (time.time() >= payload['deadline'] or (parent is not None and not parent.is_alive())
                    or not _assignment_valid(payload)):
                # Only this isolated process exits. Never touches unrelated services.
                os._exit(124)
    threading.Thread(target=watchdog, name='analysis-budget-guard', daemon=True).start()
    release_slot = None
    try:
        while release_slot is None:
            if not _assignment_valid(payload):
                raise RuntimeError('assignment_expired')
            for slot in range(payload.get('execution_slots', store.DEFAULTS['global_running'])):
                release_slot = _try_execution_slot(payload['store_path'], slot)
                if release_slot:
                    break
            if release_slot is None:
                time.sleep(0.05)
        if executor is None or authorizer is None:
            from . import service
            executor = executor or service.execute
            authorizer = authorizer or service.authorize
        authorizer(payload)
        output = executor(payload)
        if not isinstance(output, dict):
            raise ValueError('invalid_execution_output')
        result = output.get('result', output)
        bundle = output.get('source_bundle') or {}
        live = dict(payload)
        live['dependency_plan_ids'] = sorted(set(result.get('dependency_plan_ids', [])) | set(bundle.get('plan_ids', [])))
        live['actual_experts'] = output.get('actual_experts', result.get('actual_experts', []))
        # Done after all source/analysis steps; it is itself inside the hard budget.
        authorizer(live)
        sender.send({'ok': True, 'output': output})
    except BaseException as exc:
        # Do not send a traceback, prompts or raw database diagnostics to clients.
        code = getattr(exc, 'status_code', None)
        reason = 'authorization_revoked' if code in (401, 403) else ('method_unavailable' if code == 409 else 'execution_failed')
        try:
            sender.send({'ok': False, 'reason': reason})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        done.set()
        if release_slot:
            release_slot()
        sender.close()


class Runtime:
    def __init__(self, path=None, executor=None, authorizer=None, config=None):
        self.path = Path(path) if path is not None else store.path()
        self.config = {**store.DEFAULTS, **(config or {})}
        if (not 1 <= self.config['global_running'] <= store.DEFAULTS['global_running'] or self.config['lease_seconds'] <= 0
                or self.config['heartbeat_seconds'] >= self.config['lease_seconds']
                or self.config['poll_seconds'] <= 0):
            raise ValueError('invalid_runtime_budget')
        self.executor, self.authorizer = executor, authorizer
        self.worker_id = 'research-' + str(uuid.uuid4())
        self._stop = threading.Event()
        self._thread = None
        self._children = {}
        self._context = multiprocessing.get_context('spawn')

    def start(self):
        if store.is_read_only():
            return self
        if self._thread and self._thread.is_alive():
            return self
        with closing(store.connect(self.path)) as conn:
            store.reap_expired(conn)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.worker_id, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return not self._thread or not self._thread.is_alive()

    @property
    def running_processes(self):
        return len(self._children)

    def _launch(self, claim):
        receiver, sender = self._context.Pipe(duplex=False)
        payload = {**claim['payload'], 'store_path': str(self.path.resolve()),
                   'execution_slots': self.config['global_running']}
        process = self._context.Process(target=_worker, args=(sender, payload, self.executor, self.authorizer),
                                        name='expert-analysis-' + claim['id'], daemon=True)
        try:
            process.start()
        except BaseException:
            receiver.close(); sender.close()
            with closing(store.connect(self.path)) as conn:
                store.finish_failure(conn, claim['id'], claim['lease_generation'], 'worker_start_failed')
            raise
        sender.close()
        self._children[claim['id']] = dict(process=process, pipe=receiver, claim=claim, last_heartbeat=time.monotonic())

    def _dispose(self, run_id):
        child = self._children[run_id]
        process = child['process']
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)
        if process.is_alive():
            # Keep resource occupancy until actual reclamation has succeeded.
            return False
        child['pipe'].close()
        process.close()
        del self._children[run_id]
        return True

    def _finish_reclaimed(self, conn, run_id, generation, reason):
        # Cancellation can win after our last row read but before finalization.
        # This method is only called after the corresponding process is gone.
        if not store.finish_failure(conn, run_id, generation, reason):
            store.finish_cancel(conn, run_id, self.worker_id)

    def _inspect(self, conn):
        for run_id, child in list(self._children.items()):
            row = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
            claim, clock = child['claim'], time.time()
            invalid = (row is None or row['status'] != 'running'
                       or row['lease_generation'] != claim['lease_generation'])
            if invalid:
                if self._dispose(run_id) and row and row['status'] == 'cancel_requested':
                    store.finish_cancel(conn, run_id, self.worker_id)
                continue
            if clock >= row['deadline'] or clock >= row['lease_until']:
                reason = 'run_timeout' if clock >= row['deadline'] else 'lease_expired'
                if self._dispose(run_id):
                    self._finish_reclaimed(conn, run_id, claim['lease_generation'], reason)
                continue
            message = child.get('pending_message')
            if message is None:
                try:
                    if child['pipe'].poll():
                        message = child['pipe'].recv()
                except (EOFError, OSError):
                    # Windows may signal a crashed peer from poll(), not recv().
                    message = {'ok': False, 'reason': 'worker_interrupted'}
            if message is not None:
                child['pending_message'] = message
                if not self._dispose(run_id):
                    continue
                if message.get('ok'):
                    try:
                        published = store.publish(conn, run_id, claim['lease_generation'], self.worker_id, message['output'])
                    except (ValueError, TypeError, KeyError):
                        self._finish_reclaimed(conn, run_id, claim['lease_generation'], 'invalid_result')
                    else:
                        if not published:
                            latest = conn.execute('SELECT * FROM er_run WHERE id=?', (run_id,)).fetchone()
                            if latest and latest['status'] == 'cancel_requested':
                                store.finish_cancel(conn, run_id, self.worker_id)
                            elif latest and latest['status'] == 'running':
                                reason = ('service_stopped' if store.is_read_only() else
                                    'run_timeout' if time.time() >= latest['deadline'] else
                                    'lease_expired' if time.time() >= latest['lease_until'] else 'publication_rejected')
                                self._finish_reclaimed(conn, run_id, claim['lease_generation'], reason)
                else:
                    reason = 'run_timeout' if time.time() >= row['deadline'] else message.get('reason', 'execution_failed')
                    self._finish_reclaimed(conn, run_id, claim['lease_generation'], reason)
                continue
            if not child['process'].is_alive():
                self._dispose(run_id)
                self._finish_reclaimed(conn, run_id, claim['lease_generation'], 'worker_interrupted')
                continue
            if time.monotonic() - child['last_heartbeat'] >= self.config['heartbeat_seconds']:
                store.heartbeat(conn, run_id, claim['lease_generation'], self.worker_id, self.config['lease_seconds'])
                child['last_heartbeat'] = time.monotonic()

    def _loop(self):
        try:
            while not self._stop.is_set():
                if store.is_read_only():
                    break
                try:
                    with closing(store.connect(self.path)) as conn:
                        # Reclaim our timed-out processes before releasing their rows.
                        self._inspect(conn)
                        # Locally owned slots remain active until actual process
                        # reclamation, even if the clock crosses a deadline here.
                        store.reap_expired(conn, excluded_run_ids=self._children)
                        while not self._stop.is_set() and len(self._children) < self.config['global_running']:
                            claim = store.claim_next(conn, self.worker_id, self.config)
                            if claim is None:
                                break
                            self._launch(claim)
                except Exception as exc:
                    # Supervisor stays responsive; never logs query text or result data.
                    log.warning('expert_research_supervisor_cycle_failed error_type=%s', type(exc).__name__)
                self._stop.wait(self.config['poll_seconds'])
        finally:
            for run_id, child in list(self._children.items()):
                claim = child['claim']
                if self._dispose(run_id):
                    try:
                        with closing(store.connect(self.path)) as conn:
                            row = conn.execute('SELECT status FROM er_run WHERE id=?', (run_id,)).fetchone()
                            if row and row['status'] == 'cancel_requested':
                                store.finish_cancel(conn, run_id, self.worker_id)
                            else:
                                store.finish_failure(conn, run_id, claim['lease_generation'], 'service_stopped')
                    except Exception:
                        log.warning('expert_research_stop_record_failed')


_default = None
_lock = threading.Lock()

def start():
    global _default
    with _lock:
        if _default is None:
            _default = Runtime()
        return _default.start()

def stop():
    global _default
    with _lock:
        if _default is None:
            return True
        stopped = _default.stop()
        if stopped:
            _default = None
        return stopped
