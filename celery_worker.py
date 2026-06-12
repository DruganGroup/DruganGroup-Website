import os
from celery import Celery
from app import app

# Initialize Celery
celery = Celery(
    app.import_name,
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)
celery.conf.update(app.config)

# Ensure tasks run within Flask application context
class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask

# Import tasks so Celery discovers them
import tasks
