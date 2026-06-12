# Deployment

This project uses GitHub Actions in two separate stages:

- CI runs automatically on pull requests and pushes to `main`.
- Deployment is manual and must be started from the GitHub Actions UI.

The deployment workflow updates code on the server, installs dependencies with `uv`, restarts the systemd service, and checks the local health URL.

## Required GitHub Secrets

Configure these repository secrets in GitHub:

- `DEPLOY_HOST`: server hostname or IP address.
- `DEPLOY_USER`: SSH user for deployment.
- `DEPLOY_SSH_KEY`: private SSH key for `DEPLOY_USER`.
- `DEPLOY_PATH`: absolute project path on the server, for example `/opt/bili2text`.
- `DEPLOY_PORT`: optional SSH port. If omitted, the workflow uses `22`.

Keep application secrets on the server. Do not store `.env`, `cookies.txt`, `cookies.json`, the SQLite database, logs, or temporary audio files in GitHub.

## Server Prerequisites

Install and configure these once on the server:

- `git`
- `uv`
- `ffmpeg`
- `curl`
- Python compatible with the project, currently tested with Python 3.12 in CI
- A checked-out copy of this repository at `DEPLOY_PATH`
- A valid `.env`
- `cookies.txt` and `cookies.json` if Bilibili access needs them
- A systemd service, default name `bili2text`
- Nginx reverse proxy if exposing the service publicly

The deployment user must be able to run:

```bash
sudo systemctl restart bili2text
```

For unattended deploys, configure sudoers for only that command rather than granting broad sudo access.

## CI

The CI workflow runs on GitHub-hosted `ubuntu-latest` and uses only `uv` for Python package management:

```bash
uv venv
uv pip install -r requirements.txt
uv run python -m py_compile ...
uv run python -c "import main; print(main.app.title)"
```

The existing `tests/test_longcat_api.py` script calls an external LLM API and requires `LONGCAT_API_KEY`, so it is compiled but not executed by default CI.

## Manual Deployment

Open GitHub Actions, select `Deploy`, then run the workflow manually.

Inputs:

- `ref`: branch, tag, or commit to deploy. Defaults to `main`.
- `service_name`: systemd service name. Defaults to `bili2text`.
- `health_url`: URL checked from the server after restart. Defaults to `http://127.0.0.1:8000/`.

## Rollback Behavior

Before deployment, the workflow records the current server commit in `.last_deploy`.

If checkout, dependency installation, service restart, or health check fails, the workflow:

```bash
git checkout --force <previous_sha>
uv venv
uv pip install -r requirements.txt
sudo systemctl restart bili2text
```

This rollback protects tracked code. It does not modify untracked runtime files such as `.env`, cookies, the database, logs, or `temp_audio`.
