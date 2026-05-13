# Use the official lightweight Python image.
FROM python:3.11-slim

# Allow statements and log messages to immediately appear in the logs
ENV PYTHONUNBUFFERED=True

# Copy local code to the container image.
ENV APP_HOME /app
WORKDIR $APP_HOME
COPY . ./

# Install production dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Initialize the database before starting
RUN python -c "from app import app, db; \
    import os; \
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///academi_connect.db'; \
    ctx = app.app_context(); ctx.push(); db.create_all(); ctx.pop()"

# Run the web service using gevent worker (required for SocketIO)
CMD exec gunicorn --bind :$PORT --workers 1 --worker-class eventlet --timeout 120 app:app
