# Sharing this repository

This repo is **Intel Internal** (see [../LICENSE](../LICENSE)). Share it only through
Intel-approved hosting. Do **not** commit raw silicon debug data (RPT, waveforms,
dumps) — those are excluded by [../.gitignore](../.gitignore).

## Option 1 — Intel Innersource (recommended)

Host on Intel's internal GitHub (`github.com/intel-innersource`).

```powershell
# From the repo root:
#   C:\...\Auto_HSD_analyser_RDT and UPI

# 1. Create an empty repo in the intel-innersource org via the web UI, then:
git remote add origin https://github.com/intel-innersource/<team>/auto-hsd-analyser.git
git branch -M main
git push -u origin main
```

Then share access by adding people/teams as collaborators in the repo **Settings ->
Collaborators & teams** on the Innersource web UI, and send them the repo URL.

## Option 2 — Any internal Git host (Gitea / GitLab / Azure DevOps)

```powershell
git remote add origin <your-internal-git-remote-url>
git branch -M main
git push -u origin main
```

## Option 3 — Share as a bundle (no server needed)

Produce a single portable file you can send over an approved channel:

```powershell
git bundle create auto-hsd-analyser.bundle --all
```

The recipient clones it with:

```powershell
git clone auto-hsd-analyser.bundle auto-hsd-analyser
```

## After publishing
- Add teammates as collaborators (Option 1/2) so they can push improvements.
- Point them at [../README.md](../README.md) for setup and
  [CONTRIBUTING.md](../CONTRIBUTING.md) for how to add cases.

## Reminder
Keep all sharing inside Intel. If anyone outside Intel needs access, get written
authorization first.
