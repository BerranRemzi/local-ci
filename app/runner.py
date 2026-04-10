import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from .pipeline import Pipeline, Step

# In-memory run store: run_id -> RunRecord
_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


def _run_meta_path(run_log_dir: str) -> str:
    return os.path.join(run_log_dir, "run.json")


def _write_run_meta(run: dict):
    log_dir = run.get("log_dir")
    if not log_dir:
        return
    os.makedirs(log_dir, exist_ok=True)
    meta_path = _run_meta_path(log_dir)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(run, f, indent=2)


def _infer_step_from_log(step_name: str, log_path: str) -> dict:
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return {"status": "unknown", "exit_code": None}

    exit_code = None
    marker = "[exit code:"
    idx = content.rfind(marker)
    if idx != -1:
        tail = content[idx + len(marker):]
        end = tail.find("]")
        if end != -1:
            raw = tail[:end].strip()
            try:
                exit_code = int(raw)
            except ValueError:
                exit_code = None

    if exit_code is None:
        status = "unknown"
    else:
        status = "success" if exit_code == 0 else "failed"

    return {"status": status, "exit_code": exit_code}


def _load_run_from_dir(run_id: str, run_log_dir: str) -> Optional[dict]:
    meta_path = _run_meta_path(run_log_dir)
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("id", run_id)
            data.setdefault("log_dir", run_log_dir)
            data.setdefault("steps", {})
            data.setdefault("status", "unknown")
            data.setdefault("pipeline", "unknown")
            data.setdefault("started_at", datetime.fromtimestamp(os.path.getmtime(run_log_dir), timezone.utc).isoformat())
            data.setdefault("finished_at", None)
            return data
        except Exception:
            pass

    try:
        names = sorted(n for n in os.listdir(run_log_dir) if n.endswith(".log"))
    except OSError:
        return None

    if not names:
        return None

    steps = {}
    any_failed = False
    all_success = True
    for name in names:
        step_name = os.path.splitext(name)[0]
        info = _infer_step_from_log(step_name, os.path.join(run_log_dir, name))
        steps[step_name] = info
        if info["status"] == "failed":
            any_failed = True
        if info["status"] != "success":
            all_success = False

    if any_failed:
        status = "failed"
    elif all_success:
        status = "success"
    else:
        status = "unknown"

    ts = datetime.fromtimestamp(os.path.getmtime(run_log_dir), timezone.utc).isoformat()
    return {
        "id": run_id,
        "pipeline": "unknown",
        "status": status,
        "started_at": ts,
        "finished_at": ts,
        "steps": steps,
        "log_dir": run_log_dir,
    }


def _load_runs_from_disk(logs_dir: str) -> dict[str, dict]:
    runs: dict[str, dict] = {}
    if not os.path.isdir(logs_dir):
        return runs

    for name in os.listdir(logs_dir):
        run_log_dir = os.path.join(logs_dir, name)
        if not os.path.isdir(run_log_dir):
            continue
        run = _load_run_from_dir(name, run_log_dir)
        if run:
            runs[run["id"]] = run
    return runs


def get_run(run_id: str, logs_dir: Optional[str] = None) -> Optional[dict]:
    with _runs_lock:
        run = _runs.get(run_id)
    if run:
        return run

    if logs_dir:
        run_log_dir = os.path.join(logs_dir, run_id)
        if os.path.isdir(run_log_dir):
            return _load_run_from_dir(run_id, run_log_dir)
    return None


def list_runs(logs_dir: Optional[str] = None) -> list[dict]:
    disk_runs: dict[str, dict] = {}
    if logs_dir:
        disk_runs = _load_runs_from_disk(logs_dir)

    with _runs_lock:
        merged = dict(disk_runs)
        merged.update(_runs)

    return sorted(merged.values(), key=lambda r: r["started_at"], reverse=True)


def list_runs_for_pipeline(pipeline_name: str, logs_dir: Optional[str] = None) -> list[dict]:
    runs = [r for r in list_runs(logs_dir) if r["pipeline"] == pipeline_name]
    return sorted(runs, key=lambda r: r["started_at"], reverse=True)


def trigger_run(pipeline: Pipeline, logs_dir: str) -> str:
    run_id = str(uuid.uuid4())[:8]
    run_log_dir = os.path.join(logs_dir, run_id)
    os.makedirs(run_log_dir, exist_ok=True)

    record = {
        "id": run_id,
        "pipeline": pipeline.name,
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "steps": {s.name: {"status": "pending", "exit_code": None} for s in pipeline.steps},
        "log_dir": run_log_dir,
    }
    with _runs_lock:
        _runs[run_id] = record
    _write_run_meta(record)

    thread = threading.Thread(target=_execute_run, args=(run_id, pipeline, run_log_dir), daemon=True)
    thread.start()
    return run_id


def _resolve_env(pipeline: Pipeline, step: Step) -> dict:
    """Merge system env with pipeline-level and step-level env vars."""
    env = os.environ.copy()
    env.update(pipeline.env)
    env.update(step.env)
    return env


def _execute_run(run_id: str, pipeline: Pipeline, run_log_dir: str):
    _update_run(run_id, {"status": "running"})

    overall_success = True
    for step in pipeline.steps:
        _update_step(run_id, step.name, {"status": "running"})

        workdir = step.workdir or pipeline.workspace or "."
        workdir = os.path.abspath(workdir)
        os.makedirs(workdir, exist_ok=True)

        log_path = os.path.join(run_log_dir, f"{step.name}.log")
        env = _resolve_env(pipeline, step)

        exit_code = _run_step(step, workdir, env, log_path)
        success = exit_code == 0

        step_result = {"status": "success" if success else "failed", "exit_code": exit_code}
        _update_step(run_id, step.name, step_result)

        if not success:
            overall_success = False
            if not step.continue_on_error:
                # Mark remaining steps as skipped
                remaining = False
                for s in pipeline.steps:
                    if remaining:
                        _update_step(run_id, s.name, {"status": "skipped"})
                    if s.name == step.name:
                        remaining = True
                break

    final_status = "success" if overall_success else "failed"
    _update_run(run_id, {"status": final_status, "finished_at": datetime.now(timezone.utc).isoformat()})


def _run_step(step: Step, workdir: str, env: dict, log_path: str) -> int:
    """Run a single step command, writing output to log_path. Returns exit code."""
    with open(log_path, "w", encoding="utf-8", buffering=1) as log_file:
        log_file.write(f"$ {step.command}\n\n")
        log_file.flush()
        try:
            proc = subprocess.Popen(
                step.command,
                shell=True,
                cwd=workdir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.stdout is not None:
                for line in proc.stdout:
                    log_file.write(line)
                    log_file.flush()
            proc.wait()
            log_file.write(f"\n[exit code: {proc.returncode}]\n")
            return proc.returncode
        except Exception as e:
            log_file.write(f"\n[error: {e}]\n")
            return 1


def _update_run(run_id: str, updates: dict):
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id].update(updates)
            _write_run_meta(_runs[run_id])


def _update_step(run_id: str, step_name: str, updates: dict):
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id]["steps"][step_name].update(updates)
            _write_run_meta(_runs[run_id])


def get_step_log(run_id: str, step_name: str, logs_dir: Optional[str] = None) -> Optional[str]:
    run = get_run(run_id, logs_dir)
    if not run:
        return None
    log_path = os.path.join(run["log_dir"], f"{step_name}.log")
    if not os.path.exists(log_path):
        return None
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def delete_run(run_id: str, logs_dir: str) -> bool:
    run_log_dir = os.path.join(logs_dir, run_id)
    if not os.path.isdir(run_log_dir):
        return False

    shutil.rmtree(run_log_dir, ignore_errors=True)
    with _runs_lock:
        _runs.pop(run_id, None)
    return True
