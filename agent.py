# agent.py

import json
import hashlib
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from time import sleep

import helium
import PIL.Image
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.keys import Keys

from smolagents import CodeAgent, tool
from smolagents.agents import ActionStep
from smolagents.models import LiteLLMModel

from config import SEARCH_QUERIES, CV_SCORING

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SEEN_JOBS_FILE = "seen_jobs.json"
DIGEST_FILE = "digest.md"

# --- Deduplication helpers ---

SEEN_EXPIRY_DAYS = 90

# Loads the seen-job hash table from disk, migrating old list format if needed, and drops entries older than SEEN_EXPIRY_DAYS.
def load_seen() -> dict:
    if not os.path.exists(SEEN_JOBS_FILE):
        return {}
    with open(SEEN_JOBS_FILE, "r") as f:
        content = f.read().strip()
    if not content:
        return {}
    data = json.loads(content)
    seen = data.get("seen", {})
    # migrate old list format — use current time so entries aren't immediately pruned
    if isinstance(seen, list):
        now = datetime.now(timezone.utc).timestamp()
        seen = {h: now for h in seen}
    cutoff = datetime.now(timezone.utc).timestamp() - SEEN_EXPIRY_DAYS * 86400
    return {h: ts for h, ts in seen.items() if ts > cutoff}

# Persists the seen-job hash table to disk.
def save_seen(seen: dict):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump({"seen": seen}, f, indent=2)

# Returns an MD5 hash of a URL, used as the deduplication key.
def hash_url(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# --- Screenshot callback ---

# Step callback: captures a screenshot for the current step, prunes old step data to keep context small,
# appends the current URL to observations, and auto-flushes any unsaved collected jobs.
def save_screenshot(memory_step: ActionStep, agent: CodeAgent) -> None:
    sleep(1.0)
    driver = helium.get_driver()
    current_step = memory_step.step_number
    if driver is not None:
        for prev_step in agent.memory.steps:
            if isinstance(prev_step, ActionStep) and prev_step.step_number <= current_step - 2:
                prev_step.observations_images = None
                prev_step.observations = None
                prev_step.llm_output = None
                prev_step.action_output = None
                prev_step.tool_calls = None
        png_bytes = driver.get_screenshot_as_png()
        image = PIL.Image.open(BytesIO(png_bytes))
        image = image.resize((image.width // 2, image.height // 2))
        logger.info(f"Screenshot captured: {image.size} pixels")
        memory_step.observations_images = [image.copy()]

    url_info = f"Current url: {driver.current_url}"
    memory_step.observations = (
        url_info if memory_step.observations is None
        else memory_step.observations + "\n" + url_info
    )

    # Flush any jobs the agent collected in its local variables but hasn't saved yet
    local_vars = getattr(agent.python_executor, "state", {})
    for var in ("collected_jobs", "all_jobs", "current_search_jobs", "second_search_jobs"):
        jobs = local_vars.get(var)
        if jobs and isinstance(jobs, list):
            result = save_jobs_to_digest(json.dumps(jobs))
            if "new jobs" in result:
                logger.info(f"Auto-flushed {var}: {result}")
                local_vars[var] = []

# --- Tools ---

@tool
def read_job_description() -> str:
    """
    Extracts the full text of the job description from the current LinkedIn job page.
    Use this instead of scrolling through the description. Returns up to 4000 characters.
    """
    driver = helium.get_driver()
    text = driver.execute_script("return document.body.innerText;")
    if not text:
        return "Could not extract page text."
    idx = text.lower().find("about the job")
    if idx == -1:
        return text[:3000].strip()
    return text[idx + len("about the job"):idx + 4000].strip()


@tool
def go_back() -> None:
    """Goes back to the previous page."""
    helium.get_driver().back()


@tool
def close_popups() -> str:
    """Closes any visible modal or pop-up on the page."""
    webdriver.ActionChains(helium.get_driver()).send_keys(Keys.ESCAPE).perform()
    return "Sent ESC."


@tool
def save_jobs_to_digest(jobs_json: str) -> str:
    """
    Saves a JSON string of job listings to digest.md and deduplicates against seen_jobs.json.
    Args:
        jobs_json: A JSON string representing a list of dicts, each with keys:
                   title, company, location, salary, url, summary, match_score, match_reason
    Returns:
        A summary string of how many new jobs were saved.
    """
    if not jobs_json or not jobs_json.strip():
        return "No jobs provided (empty input)."
    try:
        jobs = json.loads(jobs_json)
    except json.JSONDecodeError:
        try:
            jobs = json.loads(jobs_json.rstrip(",") + "]")
        except json.JSONDecodeError as e:
            return f"Failed to parse jobs JSON: {e}"

    seen = load_seen()
    new_jobs = []
    now = datetime.now(timezone.utc).timestamp()

    for job in jobs:
        url = job.get("url", "")
        h = hash_url(url)
        if h in seen:
            logger.debug(f"Duplicate skipped: {job.get('title')}")
            continue
        seen[h] = now
        new_jobs.append(job)

    save_seen(seen)

    if not new_jobs:
        return "No new listings found (all duplicates)."

    with open(DIGEST_FILE, "a") as f:
        for job in new_jobs:
            score = job.get('match_score', 'N/A')
            f.write(f"## {job.get('title', 'N/A')} at {job.get('company', 'N/A')}\n")
            f.write(f"**Match Score:** {score}/10  \n")
            f.write(f"**Why:** {job.get('match_reason', '')}  \n")
            f.write(f"**Location:** {job.get('location', 'N/A')}  \n")
            f.write(f"**Salary:** {job.get('salary', 'Not listed')}  \n")
            f.write(f"**Apply:** {job.get('url', 'N/A')}  \n\n")
            f.write(f"{job.get('summary', '')}  \n\n---\n\n")

    return f"Saved {len(new_jobs)} new jobs to digest.md."


# --- Helium instructions ---

HELIUM_INSTRUCTIONS = """
You are a LinkedIn job search agent. Your goal: search for graduate roles, score them, and save matches.

=== SCORING CRITERIA ===
{cv_scoring}
=== END ===

=== STEP 0 — LOGIN ===
import os
go_to("https://www.linkedin.com/login")
sleep(2)
write(os.getenv("LINKEDIN_EMAIL"), into="Email or phone")
write(os.getenv("LINKEDIN_PASSWORD"), into="Password")
click("Sign in")
sleep(4)
# Verify: if current URL does not contain /feed or /jobs, stop and report login failure.

=== STEP 1 — FOR EACH QUERY ===
Repeat for every query in: {search_queries}

a) Navigate:
   import urllib.parse
   url = f"https://www.linkedin.com/jobs/search/?keywords={{urllib.parse.quote_plus(query)}}&location=London&f_TPR=r604800&f_E=1%2C2&sortBy=DD"
   go_to(url)
   sleep(2)
   close_popups()

b) If the page shows "No matching jobs found" or the job list is empty, skip to next query.

c) Scroll the job listing panel to load results:
   scroll_down(num_pixels=1500)
   sleep(1)

d) Initialise: collected_jobs = []

e) For each visible job card in the left panel:
   - Click the card to open it (the right panel and URL update)
   - Immediately capture: job_url = driver.current_url
   - If job_url contains an external domain (not linkedin.com), call go_back() and skip.
   - Call: description = read_job_description()
   - Skip if title contains a senior/lead/principal/staff/director/manager/VP/experienced term.
   - Skip if description clearly requires 2+ years of experience.
   - Score 1-10 using the scoring criteria above.
   - If score >= 6, append to collected_jobs:
     collected_jobs.append({{
       "title": title, "company": company, "location": location,
       "salary": salary or "Not listed", "url": job_url,
       "summary": "2-sentence summary", "match_score": score, "match_reason": "1 sentence"
     }})

f) After processing all visible cards (or after 10 jobs), save and reset:
   if collected_jobs:
       save_jobs_to_digest(json.dumps(collected_jobs))
       collected_jobs = []

g) Move to next query.

=== FINISHING ===
After all {num_queries} queries are done:
final_answer("Done. Results written to digest.md.")

=== RULES ===
- Never click Apply or fill any application form.
- If a CAPTCHA or verification screen appears, stop immediately and report it.
- If you get redirected to a login page mid-run, stop and report it.
""".format(
    cv_scoring=CV_SCORING,
    search_queries=SEARCH_QUERIES,
    num_queries=len(SEARCH_QUERIES),
)


# --- Driver and agent setup ---

# Launches a visible Chrome window with fixed dimensions suitable for LinkedIn's layout.
def initialize_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--force-device-scale-factor=1")
    chrome_options.add_argument("--window-size=1000,1350")
    chrome_options.add_argument("--disable-pdf-viewer")
    chrome_options.add_argument("--window-position=0,0")
    return helium.start_chrome(headless=False, options=chrome_options)


# Builds the smolagents CodeAgent with the four browser tools, screenshot callback, and a generous step budget.
def initialize_agent(model):
    return CodeAgent(
        tools=[go_back, close_popups, save_jobs_to_digest, read_job_description],
        model=model,
        additional_authorized_imports=["helium", "time", "json", "urllib.parse", "os"],
        step_callbacks=[save_screenshot],
        max_steps=80,
        verbosity_level=2,
    )


# Emails the contents of digest.md from GMAIL_SENDER to LINKEDIN_EMAIL using Gmail SMTP with an app password.
def send_digest_email():
    sender = os.getenv("GMAIL_SENDER")
    recipient = os.getenv("LINKEDIN_EMAIL")
    password = (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    if len(password) != 16:
        logger.warning("GMAIL_APP_PASSWORD missing or invalid — skipping email.")
        return

    with open(DIGEST_FILE, "r") as f:
        body = f.read()

    if not body.strip():
        logger.info("Digest is empty — skipping email.")
        return

    subject = f"Job Digest — {datetime.now().strftime('%A, %d %B %Y')}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(body, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    logger.info(f"Digest emailed to {recipient}.")


# Entry point: initialises the digest file, launches Chrome, runs the agent, then sends the email digest.
def run_agent():
    model = LiteLLMModel(model_id="anthropic/claude-haiku-4-5-20251001")

    from datetime import datetime
    with open(DIGEST_FILE, "w") as f:
        f.write(f"# Daily Job Digest — {datetime.now().strftime('%A, %d %B %Y')}\n\n")

    initialize_driver()
    agent = initialize_agent(model)
    agent.python_executor("from helium import *")
    agent.python_executor("from time import sleep")
    agent.python_executor("import urllib.parse")
    agent.python_executor("import os")

    task = HELIUM_INSTRUCTIONS

    agent.run(task)
    logger.info("Agent run complete. Check digest.md for results.")
    send_digest_email()


if __name__ == "__main__":
    run_agent()