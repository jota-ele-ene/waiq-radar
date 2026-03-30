# WAIQ Technology Radar

## Project Overview

Automated news pipeline for Web3, AI, and Quantum technology topics. Searches web sources, filters and summarizes with an LLM, and publishes to email and a Hugo/GitHub site.

## Architecture

- **Language**: Python 3.12
- **Type**: CLI pipeline tool (no web frontend)
- **Entry point**: `run.py`
- **Config**: `config.yaml` (queries, LLM settings, email, GitHub)
- **Secrets**: `.env` file (not committed)

## Pipeline Phases

1. **search** — Web search via DuckDuckGo/Serper/Tavily/SearXNG
2. **filter** — LLM-based relevance filtering
3. **verify** — URL content verification
4. **compose** — Editorial angle + opinion article (LLM)
5. **email** — Send radar email via SMTP
6. **publish** — Publish to GitHub (Hugo .md files)
7. **diagnostic** — Send diagnostic email with logs

## Source Structure

```
src/
├── config_loader.py      # Loads config.yaml + .env
├── search.py             # Web search abstraction
├── llm.py                # LLM abstraction (OpenAI/Anthropic/Google)
├── filter_and_compose.py # Filtering + article composition
├── email_sender.py       # SMTP email sending
└── publisher.py          # GitHub/Hugo publishing
```

## Environment Variables Required

Set these in `.env` (copy from `.env.example`):

- `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` / `GOOGLE_API_KEY` depending on `config.yaml`)
- `SMTP_USERNAME` — Gmail address
- `SMTP_PASSWORD` — Gmail App Password
- `WAIQ_GITHUB_TOKEN` — GitHub token with `repo` scope
- `SEARXNG_URL` (optional, if using SearXNG search provider)

## Workflow

- **Start application**: `python run.py --help` (console output type)
- To run the full pipeline: `python run.py`
- To run a dry-run (no email/GitHub): `python run.py --dry-run`
- To run specific phases: `python run.py --phase search,filter`

## Dependencies

Installed via pip from `requirements.txt`:
- openai, anthropic, google-genai
- duckduckgo-search, httpx
- pyyaml, jinja2, python-dotenv
- gitpython, beautifulsoup4
