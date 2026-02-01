# Официальный образ Playwright с Python и Chromium
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Зависимости приложения
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY config.py scraper.py graph_generator.py weather_store.py bot.py main.py cache.py ./

CMD ["python", "main.py"]

