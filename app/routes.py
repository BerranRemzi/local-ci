import hashlib
import hmac
import json
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from .pipeline import Pipeline, load_pipelines
from .runner import (
    get_run,
    get_step_log,
    list_runs,
    list_runs_for_pipeline,
    trigger_run,
)

PIPELINES_DIR = os.environ.get("LOCAL_CI_PIPELINES_DIR", "./pipelines")
LOGS_DIR = os.environ.get("LOCAL_CI_LOGS_DIR", "./logs")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.environ.get("LOCAL_CI_SECRET", "local-ci-secret")

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        pipelines = load_pipelines(PIPELINES_DIR)
        recent_runs = list_runs()[:20]
        return render_template("index.html", pipelines=pipelines, runs=recent_runs)

    # ── Pipeline detail ────────────────────────────────────────────────────────

    @app.route("/pipeline/<name>")
    def pipeline_detail(name):
        pipelines = load_pipelines(PIPELINES_DIR)
        pipeline = pipelines.get(name)
        if not pipeline:
            abort(404)
        runs = list_runs_for_pipeline(name)
        return render_template("pipeline.html", pipeline=pipeline, runs=runs)

    # ── Trigger run ────────────────────────────────────────────────────────────

    @app.route("/pipeline/<name>/run", methods=["POST"])
    def run_pipeline(name):
        pipelines = load_pipelines(PIPELINES_DIR)
        pipeline = pipelines.get(name)
        if not pipeline:
            abort(404)
        run_id = trigger_run(pipeline, LOGS_DIR)
        return redirect(url_for("run_detail", run_id=run_id))

    # ── Run detail ─────────────────────────────────────────────────────────────

    @app.route("/run/<run_id>")
    def run_detail(run_id):
        run = get_run(run_id)
        if not run:
            abort(404)
        return render_template("run.html", run=run)

    # ── Step log ───────────────────────────────────────────────────────────────

    @app.route("/run/<run_id>/log/<step_name>")
    def step_log(run_id, step_name):
        log = get_step_log(run_id, step_name)
        if log is None:
            abort(404)
        return log, 200, {"Content-Type": "text/plain; charset=utf-8"}

    # ── API ────────────────────────────────────────────────────────────────────

    @app.route("/api/runs")
    def api_runs():
        return jsonify(list_runs())

    @app.route("/api/run/<run_id>")
    def api_run(run_id):
        run = get_run(run_id)
        if not run:
            abort(404)
        return jsonify(run)

    @app.route("/api/pipelines")
    def api_pipelines():
        pipelines = load_pipelines(PIPELINES_DIR)
        return jsonify([
            {
                "name": p.name,
                "description": p.description,
                "steps": [s.name for s in p.steps],
                "source_file": p.source_file,
            }
            for p in pipelines.values()
        ])

    @app.route("/api/pipeline/<name>/run", methods=["POST"])
    def api_run_pipeline(name):
        pipelines = load_pipelines(PIPELINES_DIR)
        pipeline = pipelines.get(name)
        if not pipeline:
            abort(404)

        # Allow inline pipeline definition via JSON body
        body = request.get_json(silent=True)
        if body and "steps" in body:
            pipeline = Pipeline.from_dict(body)

        run_id = trigger_run(pipeline, LOGS_DIR)
        return jsonify({"run_id": run_id, "status": "started"}), 202

    # ── Webhooks ───────────────────────────────────────────────────────────────

    @app.route("/webhook/github", methods=["POST"])
    def webhook_github():
        secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
        if secret:
            sig_header = request.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(
                secret.encode(), request.data, hashlib.sha256
            ).hexdigest()  # hmac.new is the correct stdlib call
            if not hmac.compare_digest(sig_header, expected):
                abort(403)

        event = request.headers.get("X-GitHub-Event", "")
        if event != "push":
            return jsonify({"status": "ignored", "event": event}), 200

        payload = request.get_json(force=True)
        repo_name = payload.get("repository", {}).get("name", "")
        pipelines = load_pipelines(PIPELINES_DIR)
        pipeline = pipelines.get(repo_name)
        if not pipeline:
            return jsonify({"status": "no pipeline found", "repo": repo_name}), 200

        run_id = trigger_run(pipeline, LOGS_DIR)
        return jsonify({"run_id": run_id, "status": "started"}), 202

    @app.route("/webhook/gitlab", methods=["POST"])
    def webhook_gitlab():
        secret = os.environ.get("GITLAB_WEBHOOK_SECRET", "")
        if secret:
            token = request.headers.get("X-Gitlab-Token", "")
            if token != secret:
                abort(403)

        event = request.headers.get("X-Gitlab-Event", "")
        if event != "Push Hook":
            return jsonify({"status": "ignored", "event": event}), 200

        payload = request.get_json(force=True)
        repo_name = payload.get("project", {}).get("name", "")
        pipelines = load_pipelines(PIPELINES_DIR)
        pipeline = pipelines.get(repo_name)
        if not pipeline:
            return jsonify({"status": "no pipeline found", "repo": repo_name}), 200

        run_id = trigger_run(pipeline, LOGS_DIR)
        return jsonify({"run_id": run_id, "status": "started"}), 202

    return app
