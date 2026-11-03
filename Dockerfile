FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn backend.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
