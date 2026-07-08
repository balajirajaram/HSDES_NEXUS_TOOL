# Contributing

Thanks for helping the Auto HSD Analyser get smarter.

## Ways to contribute
1. **Improve the prompt** — edit [prompts/auto-hsd-analyser.prompt.md](prompts/auto-hsd-analyser.prompt.md).
   Keep the section A–H report contract intact.
2. **Curate KB cases** — when you confirm a root cause, make sure the agent's
   write-back followed [docs/KB_SCHEMA.md](docs/KB_SCHEMA.md). Correct any entry that
   HSDES later contradicts.
3. **Refine docs** — clarify anything in `docs/`.

## Ground rules
- **Never commit raw silicon data** (RPT, `.rpt.gz`, waveforms, dumps) or credentials.
  These are excluded in [.gitignore](.gitignore) — keep it that way.
- **No fabricated content.** Only cite HSD IDs, registers, and commands that actually
  exist. Tag anything unproven as a hypothesis.
- **Stay scoped.** Entries and guidance must stay GNR/SRF/CWF-specific and
  stepping-aware.
- **HSDES is source of truth.** When it conflicts with the KB, fix the KB.

## Workflow
```powershell
git checkout -b feature/<short-description>
# make changes
git add -A
git commit -m "<concise message>"
git push -u origin feature/<short-description>
# open a pull request for review
```

## Commit style
Short, imperative subject lines, e.g. `Add UPI CRC-error KB signature` or
`Clarify KB confidence tagging`.
