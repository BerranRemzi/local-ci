import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# GitLab CI top-level keywords that are NOT job definitions
_GITLAB_CI_RESERVED_KEYS = {
    "stages",
    "variables",
    "image",
    "services",
    "before_script",
    "after_script",
    "include",
    "workflow",
    "cache",
    "default",
    "pages",
}


# Characters invalid in Windows filenames.
_INVALID_STEP_CHARS = re.compile(r'[<>:"/\\|?*]')


@dataclass
class Step:
    name: str
    command: str
    workdir: Optional[str] = None
    env: dict = field(default_factory=dict)
    continue_on_error: bool = False
    allow_to_fail: bool = False
    success: Optional[str] = None
    fail: Optional[str] = None


@dataclass
class Pipeline:
    name: str
    steps: list[Step]
    workspace: Optional[str] = None
    env: dict = field(default_factory=dict)
    description: str = ""
    source_file: Optional[str] = None

    @staticmethod
    def from_file(path: str) -> "Pipeline":
        lower = path.lower()
        if lower.endswith(".yml") or lower.endswith(".yaml"):
            return Pipeline.from_yaml_file(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Pipeline.from_dict(data, source_file=path)

    @staticmethod
    def from_dict(data: dict, source_file: Optional[str] = None) -> "Pipeline":
        steps = [
            Step(
                name=s["name"],
                command=s["command"],
                workdir=s.get("workdir"),
                env=s.get("env", {}),
                continue_on_error=s.get("continue_on_error", False),
                allow_to_fail=s.get("allow_to_fail", False),
                success=s.get("success"),
                fail=s.get("fail"),
            )
            for s in data.get("steps", [])
        ]
        return Pipeline(
            name=data["name"],
            steps=steps,
            workspace=data.get("workspace"),
            env=data.get("env", {}),
            description=data.get("description", ""),
            source_file=source_file,
        )

    @staticmethod
    def from_yaml_file(path: str) -> "Pipeline":
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "pyyaml is required to load YAML pipeline files. "
                "Run: pip install pyyaml"
            )
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return Pipeline.from_yaml_dict(data, source_file=path, path=path)

    @staticmethod
    def from_yaml_dict(
        data: dict,
        source_file: Optional[str] = None,
        path: Optional[str] = None,
    ) -> "Pipeline":
        if not isinstance(data, dict):
            raise ValueError("YAML pipeline data must be a mapping/object")
        if _looks_like_github_actions(data):
            return Pipeline._from_github_actions_dict(data, source_file=path, path=path)
        return Pipeline._from_gitlab_ci_dict(data, source_file=path, path=path)

    @staticmethod
    def _from_github_actions_dict(
        data: dict,
        source_file: Optional[str] = None,
        path: Optional[str] = None,
    ) -> "Pipeline":
        """Convert a parsed GitHub Actions workflow dict to a Pipeline."""
        workflow_name = data.get("name")
        if isinstance(workflow_name, str) and workflow_name.strip():
            name = workflow_name.strip()
        elif path:
            basename = os.path.basename(path)
            name = re.sub(r"\.(yml|yaml)$", "", basename, flags=re.IGNORECASE)
            if not name:
                name = "github-actions"
        else:
            name = "github-actions"

        global_env = _normalise_env(data.get("env"))

        global_run_defaults = {}
        raw_defaults = data.get("defaults", {})
        if isinstance(raw_defaults, dict):
            raw_run = raw_defaults.get("run", {})
            if isinstance(raw_run, dict):
                global_run_defaults = raw_run

        jobs = data.get("jobs", {})
        if not isinstance(jobs, dict):
            jobs = {}

        ordered_jobs = _order_jobs_by_needs(jobs)

        steps: list[Step] = []
        for job_name in ordered_jobs:
            job = jobs.get(job_name)
            if not isinstance(job, dict):
                continue

            job_env = _normalise_env(job.get("env"))

            job_run_defaults = global_run_defaults
            raw_job_defaults = job.get("defaults", {})
            if isinstance(raw_job_defaults, dict):
                raw_job_run = raw_job_defaults.get("run", {})
                if isinstance(raw_job_run, dict):
                    job_run_defaults = raw_job_run

            default_workdir = job_run_defaults.get("working-directory")
            if default_workdir is not None:
                default_workdir = str(default_workdir)

            raw_steps = job.get("steps", [])
            if not isinstance(raw_steps, list):
                continue

            for i, raw_step in enumerate(raw_steps, start=1):
                if not isinstance(raw_step, dict):
                    continue

                display_name = raw_step.get("name") or raw_step.get("id") or f"step-{i:02d}"
                safe_name = _safe_step_name(str(display_name), fallback=f"step-{i:02d}")
                step_name = f"{_safe_step_name(str(job_name), fallback='job')}__{safe_name}"

                if "run" in raw_step:
                    command = str(raw_step.get("run") or "")
                    if not command.strip():
                        command = "echo Empty run step"
                elif "uses" in raw_step:
                    uses = str(raw_step.get("uses"))
                    command = f"echo Skipping action step '{uses}' (uses is not executed locally)"
                else:
                    command = "echo Skipping step with no run/uses definition"

                step_env = dict(job_env)
                step_env.update(_normalise_env(raw_step.get("env")))

                step_workdir = raw_step.get("working-directory")
                if step_workdir is None:
                    step_workdir = default_workdir
                if step_workdir is not None:
                    step_workdir = str(step_workdir)

                continue_on_error = bool(raw_step.get("continue-on-error", False))

                steps.append(
                    Step(
                        name=step_name,
                        command=command,
                        workdir=step_workdir,
                        env=step_env,
                        allow_to_fail=continue_on_error,
                    )
                )

        return Pipeline(
            name=name,
            steps=steps,
            env=global_env,
            source_file=source_file,
        )

    @staticmethod
    def _from_gitlab_ci_dict(
        data: dict,
        source_file: Optional[str] = None,
        path: Optional[str] = None,
    ) -> "Pipeline":
        """Convert a parsed .gitlab-ci.yml dict to a Pipeline."""
        # Derive a pipeline name from the file path or a fallback
        if path:
            basename = os.path.basename(path)
            # For .gitlab-ci.yml  → "gitlab-ci"
            # For myapp.gitlab-ci.yml → "myapp.gitlab-ci"
            # For ci.yml / ci.yaml → "ci"
            name = re.sub(r"\.(yml|yaml)$", "", basename, flags=re.IGNORECASE)
            # Leading dot on hidden files (e.g. ".gitlab-ci") → drop the dot
            if name.startswith("."):
                name = name[1:]
            if not name:
                name = "gitlab-ci"
        else:
            name = "gitlab-ci"

        # Global variables
        global_vars: dict[str, str] = {}
        raw_vars = data.get("variables", {})
        if isinstance(raw_vars, dict):
            for k, v in raw_vars.items():
                if isinstance(v, dict):
                    # GitLab supports {value: ..., description: ...} form
                    global_vars[str(k)] = str(v.get("value", ""))
                else:
                    global_vars[str(k)] = str(v) if v is not None else ""

        # Global before_script / after_script
        global_before = _normalise_script(data.get("before_script"))
        global_after = _normalise_script(data.get("after_script"))

        # Default overrides (GitLab 13.4+)
        default_section = data.get("default", {}) or {}
        if isinstance(default_section, dict):
            if "before_script" in default_section:
                global_before = _normalise_script(default_section["before_script"])
            if "after_script" in default_section:
                global_after = _normalise_script(default_section["after_script"])

        # Stage ordering
        stages: list[str] = data.get("stages") or []

        # Collect job definitions (everything that is not a reserved key and is a dict)
        jobs: dict[str, dict] = {}
        for key, value in data.items():
            if key in _GITLAB_CI_RESERVED_KEYS:
                continue
            if not isinstance(value, dict):
                continue
            # Jobs that start with a dot are hidden/template jobs – skip them
            if key.startswith("."):
                continue
            jobs[key] = value

        # Sort jobs by stage order; jobs with no stage come first (implicit "test" stage)
        def _stage_order(job_name: str) -> tuple:
            stage = jobs[job_name].get("stage", "test")
            try:
                idx = stages.index(stage)
            except ValueError:
                idx = len(stages)
            return (idx, job_name)

        sorted_job_names = sorted(jobs.keys(), key=_stage_order)

        steps: list[Step] = []
        for job_name in sorted_job_names:
            job = jobs[job_name]

            # Skip jobs explicitly set to never run
            when = job.get("when", "on_success")
            if when == "never":
                continue

            # Build the effective script
            job_before = _normalise_script(job.get("before_script"))
            job_after = _normalise_script(job.get("after_script"))

            effective_before = job_before if "before_script" in job else global_before
            effective_after = job_after if "after_script" in job else global_after

            main_script = _normalise_script(job.get("script"))

            all_commands = effective_before + main_script + effective_after
            if not all_commands:
                all_commands = ["echo 'no script defined'"]

            command = _join_commands(all_commands)

            # Job-level variables
            job_vars: dict[str, str] = {}
            raw_job_vars = job.get("variables", {})
            if isinstance(raw_job_vars, dict):
                for k, v in raw_job_vars.items():
                    if isinstance(v, dict):
                        job_vars[str(k)] = str(v.get("value", ""))
                    else:
                        job_vars[str(k)] = str(v) if v is not None else ""

            allow_to_fail = bool(job.get("allow_failure", False))

            steps.append(
                Step(
                    name=job_name,
                    command=command,
                    env=job_vars,
                    allow_to_fail=allow_to_fail,
                )
            )

        return Pipeline(
            name=name,
            steps=steps,
            env=global_vars,
            source_file=source_file,
        )


def _normalise_script(value) -> list[str]:
    """Return a flat list of shell command strings from a YAML script value."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, list):
                result.extend(str(x) for x in item)
            else:
                result.append(str(item))
        return result
    return [str(value)]


def _normalise_env(value) -> dict[str, str]:
    """Return a string-key/string-value env dict from YAML env values."""
    if not isinstance(value, dict):
        return {}
    env = {}
    for k, v in value.items():
        env[str(k)] = "" if v is None else str(v)
    return env


def _safe_step_name(value: str, fallback: str = "step") -> str:
    """Sanitize step names so they are safe as log file names on Windows."""
    cleaned = _INVALID_STEP_CHARS.sub("-", value).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip(".-")
    return cleaned or fallback


def _order_jobs_by_needs(jobs: dict) -> list[str]:
    """Return GitHub Actions jobs ordered by their `needs` dependencies."""
    ordered: list[str] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(job_name: str):
        if job_name in permanent:
            return
        if job_name in temporary:
            # Cycles are invalid in GitHub Actions; keep deterministic order and stop recursion.
            return

        temporary.add(job_name)
        raw_job = jobs.get(job_name, {})
        if isinstance(raw_job, dict):
            raw_needs = raw_job.get("needs", [])
            if isinstance(raw_needs, str):
                needs = [raw_needs]
            elif isinstance(raw_needs, list):
                needs = [str(n) for n in raw_needs]
            else:
                needs = []

            for dep in needs:
                if dep in jobs:
                    visit(dep)

        temporary.remove(job_name)
        permanent.add(job_name)
        ordered.append(job_name)

    for name in jobs.keys():
        visit(name)
    return ordered


def _looks_like_github_actions(data: dict) -> bool:
    """Heuristic: workflow has `jobs` dict with at least one job-like definition."""
    if not isinstance(data, dict):
        return False
    jobs = data.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return False
    return any(isinstance(v, dict) and ("steps" in v or "runs-on" in v) for v in jobs.values())


def _join_commands(commands: list[str]) -> str:
    """Join multiple shell commands into a single command string."""
    if not commands:
        return "true"
    if len(commands) == 1:
        return commands[0]
    return " && ".join(commands)


def load_pipelines(pipelines_dir: str) -> dict[str, Pipeline]:
    """Load all pipeline configs (JSON and GitLab CI YAML) from a directory."""
    pipelines = {}
    if not os.path.isdir(pipelines_dir):
        return pipelines
    for root, _, files in os.walk(pipelines_dir):
        for fname in files:
            lower = fname.lower()
            if not (lower.endswith(".json") or lower.endswith(".yml") or lower.endswith(".yaml")):
                continue

            path = os.path.join(root, fname)
            try:
                p = Pipeline.from_file(path)
                pipelines[p.name] = p
            except Exception as e:
                print(f"Warning: could not load pipeline {path}: {e}")
    return pipelines
