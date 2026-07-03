from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "dpb",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.forecast_tasks", "app.tasks.email_tasks", "app.tasks.upload_tasks"],
)
celery_app.conf.update(task_track_started=True, task_time_limit=3600)
