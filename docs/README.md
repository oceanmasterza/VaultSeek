# VaultSeek documentation

Start here when onboarding or before architectural work.

## Essential reading (order)

1. [../README.md](../README.md) — project landing page
2. [ARCHITECTURAL_UPDATE_001.md](ARCHITECTURAL_UPDATE_001.md) — Acquisition Engine model (supersedes older “search engine” wording)
3. [PROJECT_PLAN.md](PROJECT_PLAN.md) — product vision
4. [ARCHITECTURE.md](ARCHITECTURE.md) — layers and pipelines
5. [DECISIONS.md](DECISIONS.md) — ADRs
6. [ROADMAP.md](ROADMAP.md) — public roadmap
7. [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) — internal engineering notebook (AI sessions)
8. [AI_RULES.md](AI_RULES.md) — coding and documentation rules
9. [TECH_STACK.md](TECH_STACK.md) — languages, libraries, tooling
10. [NICOTINE_PLUS.md](NICOTINE_PLUS.md) — Nicotine+ provider setup (HTTP vs socket)

## Terminology (use consistently)

| Use | Avoid as architecture name |
|-----|----------------------------|
| Acquisition Engine | Search Engine |
| AcquisitionJob | — |
| Provider | Soulseek app / downloader |
| Verification Pipeline | — |
| Import Pipeline | — |

## Detailed architecture (MusicVault heritage)

The `architecture/` folder contains deeper design docs from the MusicVault fork. They are being aligned with the Acquisition Engine model; when in doubt, prefer **ARCHITECTURAL_UPDATE_001.md** and **DECISIONS.md**.
