import os
from celery import Celery

# Initialize Celery WITHOUT importing the Flask app yet
celery = Celery(
    'app', # Hardcode the app name instead of using app.import_name
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)

# Optional: Add basic config without relying on Flask app.config initially
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Import tasks so Celery discovers them
import tasks

# Ensure tasks run within Flask application context (Lazy Import)
class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        # Lazy import: we only import the app when the task actually runs
        from app import app
        with app.app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask