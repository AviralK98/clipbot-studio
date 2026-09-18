import asyncio

from celery import Celery

from .config import get_settings
from .jobs import due_jobs, execute
from .pipeline import sweep

cfg = get_settings()
app = Celery("clipbot", broker=cfg.redis_url)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_time_limit=1500,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 1800},
    beat_schedule={"dispatch-every-15-seconds": {"task": "clipbot.dispatch", "schedule": 15.0}},
)


@app.task(name="clipbot.execute")
def execute_task(job_id):
    asyncio.run(execute(job_id))


@app.task(name="clipbot.dispatch")
def dispatch():
    sweep()
    for job_id in due_jobs():
        execute_task.delay(job_id)
