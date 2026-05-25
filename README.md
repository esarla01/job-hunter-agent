# job-hunter-agent

An AI agent that searches LinkedIn for graduate roles, scores each listing against your profile (1–10), and emails you a digest of the best matches.

## How it works

It opens Chrome, logs into LinkedIn, and runs through a set of search queries. For each result it reads the job description, has Claude score it, and collects anything scoring 6 or above. At the end it saves the matches to `digest.md` and emails it to you.

A few things worth knowing:

- **Deduplication** — job URLs are hashed and stored in `seen_jobs.json`. Anything seen in the last 90 days is skipped, so daily runs don't repeat themselves.
- **Context management** — older agent steps are pruned after each iteration to keep the context window from growing unbounded.

## Prerequisites

- Python 3.11+
- Google Chrome
- An [Anthropic API key](https://console.anthropic.com/)
- A LinkedIn account
- A Gmail account with an [app password](https://myaccount.google.com/apppasswords) (requires 2-Step Verification)

## Setup

```bash
conda create -n job-hunter python=3.11
conda activate job-hunter
pip install -r requirements.txt
cp .env.example .env  # then fill in your values
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `LINKEDIN_EMAIL` | LinkedIn login email (also where the digest is sent) |
| `LINKEDIN_PASSWORD` | LinkedIn password |
| `GMAIL_SENDER` | Gmail address used to send the digest |
| `GMAIL_APP_PASSWORD` | 16-char app password for `GMAIL_SENDER` |

## Configuration

Edit `config.py` to tailor the agent to you:

- **`SEARCH_QUERIES`** — the LinkedIn search strings to run. Add or remove to match what you're looking for.
- **`CV_SCORING`** — the rubric Claude uses to score each job. Update it to reflect your skills, target roles, and location.
- **`RECENCY_DAYS`** — how old listings can be (default: 7 days).

## Running

```bash
python agent.py
```

A Chrome window opens — just leave it. The agent handles everything and closes when done. Results go to `digest.md` and your inbox.

## Scheduling (optional)

To run automatically every day at 8 AM:

```bash
pip install apscheduler
python scheduler.py
```

## Output

Each matched job in `digest.md` looks like:

```
## Software Engineer at Acme AI
**Match Score:** 8/10
**Why:** Entry-level, Python/LLM stack, London, AI product company
**Location:** London, UK
**Salary:** £40,000–£50,000/yr
**Apply:** https://linkedin.com/jobs/view/...

2-sentence summary of the role.
```
