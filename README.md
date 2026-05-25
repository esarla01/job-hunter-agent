# job-hunter-agent

An AI agent that automates LinkedIn job searching for graduate roles. It logs into LinkedIn, runs a set of targeted searches, scores each listing against your profile (1–10), saves strong matches to `digest.md`, and emails you the digest when done.

## How it works

```
run_agent()
  │
  ├─ initialize_driver()       Opens a Chrome window
  ├─ initialize_agent()        Creates a Claude-powered CodeAgent with 4 browser tools
  │
  └─ agent.run(HELIUM_INSTRUCTIONS)
       │
       ├─ STEP 0: Login        Navigates to linkedin.com/login, fills credentials, verifies /feed
       │
       └─ STEP 1 (×12 queries):
            ├─ Navigate        Builds a filtered search URL (entry-level, last 7 days, London)
            ├─ Scroll          Loads job cards in the left panel
            ├─ For each card:
            │    ├─ Click      Opens job details; URL updates to the job's permalink
            │    ├─ read_job_description()   Extracts "About the job" section via JS
            │    ├─ Score      Claude rates 1–10 against CV_SCORING rubric
            │    └─ Collect    Appends matches (score ≥ 6) to collected_jobs[]
            └─ save_jobs_to_digest()   Deduplicates against seen_jobs.json, appends to digest.md
  │
  └─ send_digest_email()       Emails digest.md via Gmail SMTP
```

**Deduplication:** every saved job URL is hashed (MD5) and stored in `seen_jobs.json` with a timestamp. Jobs are suppressed for 90 days, so daily runs don't produce duplicates.

**Token management:** after each agent step, the screenshot callback prunes `llm_output`, `action_output`, and `observations` from steps older than the last two. This keeps the context window flat regardless of how many steps the agent takes.

## Prerequisites

- Python 3.11+
- Google Chrome installed
- An [Anthropic API key](https://console.anthropic.com/)
- A LinkedIn account
- A Gmail account with an [app password](https://myaccount.google.com/apppasswords) for sending email (requires 2-Step Verification)

## Setup

```bash
conda create -n job-hunter python=3.11
conda activate job-hunter
pip install -r requirements.txt
cp .env.example .env  # then fill in your values
```

## Environment variables

Create a `.env` file in the project root:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `LINKEDIN_EMAIL` | LinkedIn login email (also the digest recipient) |
| `LINKEDIN_PASSWORD` | LinkedIn password |
| `GMAIL_SENDER` | Gmail address used to send the digest |
| `GMAIL_APP_PASSWORD` | 16-char app password for `GMAIL_SENDER` |

> **Gmail app password:** go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), create one named anything (e.g. `job-hunter`), and paste the 16-character result. Spaces are fine.

## Configuration

Edit `config.py` to customise the agent:

- **`SEARCH_QUERIES`** — list of LinkedIn search strings. Add, remove, or modify to match what you're looking for.
- **`CV_SCORING`** — the rubric the agent uses to score each job. Update this to reflect your own skills, target roles, and location preferences.
- **`RECENCY_DAYS`** — how old listings can be (default: 7 days).

## Running

```bash
python agent.py
```

A Chrome window opens. Leave it running — the agent will handle everything and close when done. Results are saved to `digest.md` and emailed to `LINKEDIN_EMAIL`.

## Scheduling (optional)

To run automatically every day at 8 AM:

```bash
pip install apscheduler
python scheduler.py
```

## Output

`digest.md` is generated fresh each run. Each matched job looks like:

```
## Software Engineer at Acme AI
**Match Score:** 8/10
**Why:** Entry-level, Python/LLM stack, London, AI product company
**Location:** London, UK
**Salary:** £40,000–£50,000/yr
**Apply:** https://linkedin.com/jobs/view/...

2-sentence summary of the role.
```

