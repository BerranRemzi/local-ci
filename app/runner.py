import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from .pipeline import Pipeline, Step

# In-memory run store: run_id -> RunRecord
_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


def get_run(run_id: str) -> Optional[dict]:
    with _runs_lock:
        return _runs.get(run_id)


def list_runs() -> list[dict]:
    with _runs_lock:
        return sorted(_runs.values(), key=lambda r: r["started_at"], reverse=True)


def list_runs_for_pipeline(pipeline_name: str) -> list[dict]:
    with _runs_lock:
        return sorted(
            [r for r in _runs.values() if r["pipeline"] == pipeline_name],
            key=lambda r: r["started_at"],
            reverse=True,
        )


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


def _update_step(run_id: str, step_name: str, updates: dict):
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id]["steps"][step_name].update(updates)


def get_step_log(run_id: str, step_name: str) -> Optional[str]:
    run = get_run(run_id)
    if not run:
        return None
    log_path = os.path.join(run["log_dir"], f"{step_name}.log")
    if not os.path.exists(log_path):
        return None
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()
