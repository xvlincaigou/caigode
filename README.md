# caigode

`caigode` is a local coding-agent CLI with:

- stateful chat sessions
- file and command tools (`list_dir`, `read_file`, `write_file`, `run_command`)
- local state/review artifacts under `.caigode/`
- CI + tag-based GitHub Release + PyPI publish workflow

## Requirements

- Python `>=3.11`
- `uv` (recommended) or `pip`

## Install

### Option A: `uv sync`

```bash
uv sync --dev
```

### Option B: editable install

```bash
uv pip install -e .
```

Then run with either:

```bash
uv run caigode --help
```

or after activating virtualenv:

```bash
caigode --help
```

## Configuration

Required environment variables:

- `OPENAI_MODEL`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

Optional:

- `OPENAI_TIMEOUT_SECONDS` (default `120`)
- `CAIGODE_WORKSPACE` (default current directory)
- `CAIGODE_STATE_DIR` (default `.caigode`)

Example:

```bash
export OPENAI_MODEL="gpt-5.4"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_API_KEY="sk-..."
export OPENAI_TIMEOUT_SECONDS="120"
```

You can also pass these by CLI arguments:

- `--model`
- `--base-url`
- `--api-key`
- `--timeout-seconds`

## Usage

### Chat (stateful)

```bash
caigode chat
```

Chat keeps appending messages in-memory for the current process.
Each turn is persisted to `.caigode/sessions/<session_id>.jsonl`.

### Run one-shot task

```bash
caigode run "update README based on current project"
```

### Status

```bash
caigode status
```

### Review artifact

```bash
caigode review
```

## Tooling Behavior

Available tools:

- `list_dir(path=".", recursive=false, max_entries=200)`
- `read_file(path, offset?, limit?, start_line?, end_line?)`
- `write_file(path, content)`
- `run_command(command)`

Notes:

- `read_file` supports both byte-like slicing (`offset`/`limit`) and line-window slicing (`start_line`/`end_line`).
- tool outputs are trimmed before returning to the model to reduce context growth.

## Persistence Model

Session files are append-only JSONL:

- `.caigode/sessions/<session_id>.jsonl`

Each line stores the latest session snapshot (result/error/messages/etc).
`status` and `review` read the latest entry per session.

## Tests

```bash
uv run pytest -q
```

## CI / Release / PyPI

This repo includes:

- `.github/workflows/ci.yml`
  - runs tests on push/PR (Python 3.11/3.12)
- `.github/workflows/release.yml`
  - triggers on `v*` tags
  - builds `sdist` + `wheel`
  - publishes GitHub Release
  - publishes to PyPI via Trusted Publisher (`id-token: write`)

### One-time PyPI setup

1. Create the project on PyPI (name: `caigode` if available).
2. In PyPI, configure Trusted Publisher for this GitHub repo and workflow.
3. Push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

That tag will trigger both GitHub Release and PyPI publish.
