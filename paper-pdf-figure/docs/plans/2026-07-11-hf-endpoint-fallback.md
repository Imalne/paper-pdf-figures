# HF Endpoint Selection + Auto-Fallback Fix

## Goal
(A) Install asks which download endpoint (direct / mirror / custom) and writes it into run.sh. (B) model_detect.load() tries the current endpoint, auto-falls-back to the other on 10s timeout.

## Design
- `install.py`: `ask_hf_endpoint(non_interactive, ml) -> str|None` - returns URL or None (direct). Only asked when ML deps installed. Written into run.sh as `export HF_ENDPOINT=...` before the exec.
- `run.sh`: if endpoint chosen, prepend `export HF_ENDPOINT=<url>` before exec.
- `model_detect.py`: `load()` wraps `hf_hub_download` in try/except with 10s timeout (via `socket.setdefaulttimeout` or `urllib3` timeout). On failure, switches `HF_ENDPOINT` to the other (huggingface.co <-> hf-mirror.com) and retries once.

## Task 1: install.py ask_hf_endpoint + run.sh export
- `ask_hf_endpoint(non_interactive, ml) -> str|None`: only if ML; choices: 1) direct (None), 2) hf-mirror.com, 3) custom URL. Non-interactive -> None.
- `generate_run_sh(skill_dir, python, hf_endpoint)`: if hf_endpoint, prepend `export HF_ENDPOINT=<url>` to run.sh content.
- `main()`: call `ask_hf_endpoint` after ML env selection; pass to `generate_run_sh`.
- Tests: ask_hf_endpoint (interactive pick mirror, non-interactive None, custom); run.sh contains export when endpoint set.

## Task 2: model_detect.py auto-fallback
- `load()`: wrap `hf_hub_download` in try/except; on exception (any), switch HF_ENDPOINT to the other URL and retry once. Use `socket.setdefaulttimeout(10)` before the call.
- Tests: mock hf_hub_download to raise on first call, succeed on second; verify endpoint switched.
