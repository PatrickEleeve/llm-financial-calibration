# Project rules (read first)

Apart AI x Epistemics sprint project. Deadline: Mon 2026-11-16 05:59 America/Chicago (Sun 23:59 AoE).
See HANDOFF.md for status and next steps.

## Hard rules
- NEVER print, log, cat or commit `.env`, API keys, or the SEC_USER_AGENT contact (it contains the user's email). Code reads them only from environment / `.env`. Never hardcode an email anywhere, including README, results, reports.
- Do not fabricate results, numbers or citations. Every number in the report must come from a saved results file. Made-up results disqualify the project.
- Report text: user decision 2026-11-15 — Claude drafts (report/draft.md), the user edits and owns it; the LLM Usage Statement must disclose this accurately. Every number still comes from a saved results file; citations Claude has not verified are marked [VERIFY].
- Spend control: run a pilot first (<= 10 questions per model), log cost per call, and STOP for user approval before any run that could exceed $15. Total hard cap $60 unless the user raises it.
- Use `python -I`-style hygiene for downloaded data; keep raw SEC data out of git (data/raw is gitignored).
