FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/backend
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt
COPY backend/app ./backend/app
COPY scripts ./scripts
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]