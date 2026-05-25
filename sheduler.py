# scheduler.py

import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from agent import run_agent

logging.basicConfig(level=logging.INFO)
scheduler = BlockingScheduler()

@scheduler.scheduled_job("cron", hour=8, minute=0)
def scheduled_run():
    print("Running daily job search...")
    run_agent()

if __name__ == "__main__":
    print("Scheduler started. Agent will run daily at 8am.")
    scheduler.start()