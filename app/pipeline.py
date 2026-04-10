import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    name: str
    command: str
    workdir: Optional[str] = None
    env: dict = field(default_factory=dict)
    continue_on_error: bool = False


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


def load_pipelines(pipelines_dir: str) -> dict[str, Pipeline]:
    """Load all JSON pipeline configs from a directory."""
    pipelines = {}
    if not os.path.isdir(pipelines_dir):
        return pipelines
    for fname in os.listdir(pipelines_dir):
        if fname.endswith(".json"):
            path = os.path.join(pipelines_dir, fname)
            try:
                p = Pipeline.from_file(path)
                pipelines[p.name] = p
            except Exception as e:
                print(f"Warning: could not load pipeline {path}: {e}")
    return pipelines
