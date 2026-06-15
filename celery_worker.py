import os
import sys
from celery import Celery

# 1. Force Python to look in the current directory for app.py
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 2. Import the app safely at the top level
from app import app

# 3. Initialize Celery
celery = Celery(
    app.import_name,
    backend=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
    broker=os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)
celery.conf.update(app.config)

# 4. Bind the Flask App Context
class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

celery.Task = ContextTask

# 5. Import tasks
import tasks