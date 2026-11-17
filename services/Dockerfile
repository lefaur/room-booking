# Один образ на все сервисы: общий код в common/, сервис выбирается командой в docker-compose
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
