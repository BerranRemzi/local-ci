# Local CI

A lightweight, self-hosted CI pipeline runner built with Python Flask. Run pipelines defined as JSON files, triggered manually via the web UI, REST API, or GitHub/GitLab webhooks.

## Features

- **Universal & configurable** — pipelines are plain JSON files, no hardcoded steps
- **Web dashboard** — view pipelines, trigger runs, browse logs in browser
- **Per-step log files** — each step's output is stored in `logs/<run-id>/<step>.log`
- **REST API** — trigger and query runs programmatically
- **Webhook support** — GitHub and GitLab push event webhooks
- **Windows executable** — build a single `.exe` with PyInstaller

## Quick Start

```bash
pip install -r requirements.txt
python main.py
# Open http://localhost:5000
```

## Pipeline Config (JSON)

Place `.json` files in the `pipelines/` directory. Each file defines one pipeline.

```json
{
  "name": "sample-pipeline",
  "description": "User-defined pipeline",
  "workspace": "./workspace/sample",
  "env": {
    "EXAMPLE_VAR": "value"
  },
  "steps": [
    {
      "name": "step-01",
      "command": "echo first command",
      "workdir": "./workspace/sample"
    },
    {
      "name": "step-02",
      "command": "echo second command",
      "workdir": "./workspace/sample",
      "continue_on_error": false
    }
  ]
}
```

### Step Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Unique step identifier; used as the log filename |
| `command` | ✅ | Shell command to run (supports env var substitution) |
| `workdir` | ❌ | Working directory (defaults to pipeline `workspace`) |
| `env` | ❌ | Step-level env vars (merged over pipeline-level env) |
| `continue_on_error` | ❌ | If `true`, subsequent steps still run after failure (default: `false`) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_CI_HOST` | `0.0.0.0` | Bind host |
| `LOCAL_CI_PORT` | `5000` | Bind port |
| `LOCAL_CI_DEBUG` | _(off)_ | Set to `1` to enable Flask debug mode |
| `LOCAL_CI_PIPELINES_DIR` | `./pipelines` | Path to pipeline JSON configs |
| `LOCAL_CI_LOGS_DIR` | `./logs` | Path to store step logs |
| `GITHUB_WEBHOOK_SECRET` | _(none)_ | Secret for GitHub webhook HMAC verification |
| `GITLAB_WEBHOOK_SECRET` | _(none)_ | Token for GitLab webhook verification |

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/pipelines` | List all pipelines |
| POST | `/api/pipeline/<name>/run` | Trigger a run (optionally pass inline pipeline JSON body) |
| GET | `/api/runs` | List all runs |
| GET | `/api/run/<run_id>` | Get run status |
| GET | `/run/<run_id>/log/<step>` | Get raw step log text |

### Trigger run via API

```bash
curl -X POST http://localhost:5000/api/pipeline/my-project/run
```

### Inline pipeline (no config file needed)

```bash
curl -X POST http://localhost:5000/api/pipeline/any/run \
  -H "Content-Type: application/json" \
  -d '{
    "name": "quick",
    "steps": [
      {"name": "hello", "command": "echo Hello World"}
    ]
  }'
```

## Webhooks

### GitHub

1. Go to your repo → Settings → Webhooks → Add webhook
2. Payload URL: `http://your-server:5000/webhook/github`
3. Content type: `application/json`
4. Set a secret and export it: `GITHUB_WEBHOOK_SECRET=your-secret`
5. The pipeline name must match the GitHub repository name

### GitLab

1. Go to your project → Settings → Webhooks
2. URL: `http://your-server:5000/webhook/gitlab`
3. Set a secret token and export it: `GITLAB_WEBHOOK_SECRET=your-token`
4. The pipeline name must match the GitLab project name

## Build Windows Executable

Prerequisites:
- Windows host
- Python 3.10+ available in PATH

Build:

```powershell
.\build.ps1
```

If PowerShell blocks script execution, run once in the current shell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Output:
- `dist/local-ci.exe`

Notes:
- The build script installs dependencies from `requirements.txt` into a local virtual environment.
- Pipeline behavior is fully configurable; commands and step names come from pipeline JSON only.

Run the executable — it includes the `templates/`, `static/`, and `pipelines/` directories bundled in.

## Logs

Each run creates a directory `logs/<run-id>/` containing one `.log` file per step:

```
logs/
  a1b2c3d4/
    clone.log
    pull.log
    build.log
    test.log
```
