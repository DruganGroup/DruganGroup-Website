# 1. Use an official Python runtime as a parent image
FROM python:3.9-slim

# 2. Install the system packages WeasyPrint needs
# (This fixes the crash you would otherwise get on Render)
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory in the container
WORKDIR /app

# 4. Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your app's code
COPY . .

# 6. Run the application using Gunicorn (Standard for Production)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]