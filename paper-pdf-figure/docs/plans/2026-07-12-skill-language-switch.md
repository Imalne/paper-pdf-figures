# SKILL.md Language Switch Fix

## Goal
Interactive install option to choose which language version is the active `SKILL.md` (the one Claude Code reads). Default: English (SKILL.md = EN, ZH saved as SKILL_ZH.md). Optional: Chinese (SKILL.md = ZH, EN saved as SKILL_EN.md).

## Design
- `ask_skill_language(non_interactive) -> str`: returns "en" (default) or "zh". Interactive: 1) English (default) 2) 中文.
- `switch_skill_language(skill_dir, lang)`: if lang=="zh" and SKILL_ZH.md exists: rename SKILL.md -> SKILL_EN.md, rename SKILL_ZH.md -> SKILL.md. If lang=="en": no-op (already default). Idempotent (if SKILL_EN.md exists and lang=="zh", swap back).
- Called in main() after extract, before patch_skill_md (patch must apply to whichever SKILL.md is active).
- `--skill-lang en|zh` flag for non-interactive.
- Tests: switch to ZH (SKILL.md becomes Chinese, SKILL_EN.md exists), switch to EN (no-op), idempotent.

## Task 1: ask_skill_language + switch_skill_language + main wiring + tests
- `ask_skill_language(non_interactive=False) -> str`: "en" default, "zh" option.
- `switch_skill_language(skill_dir, lang)`: rename files.
- main(): call after extract, before generate_run_sh/patch_skill_md.
- `--skill-lang` argparse flag.
- Tests: ZH switch, EN no-op, idempotent, dry-run skip.
