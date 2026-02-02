# Официальный образ Playwright с Python и Chromium
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Компилятор, cairo и Python dev для сборки pycairo из исходников (wheel под эту платформу нет)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config libcairo2-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Зависимости приложения
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Шрифт с эмодзи и библиотеки для mplcairo (cairo/pango уже в образе Playwright)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-color-emoji \
    libraqm0 \
    libfribidi0 \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Код приложения и фон для розы ветра
COPY config.py scraper.py weather_store.py wind_rose.py bot.py main.py cache.py ./
COPY assets/ ./assets/

CMD ["python", "main.py"]

