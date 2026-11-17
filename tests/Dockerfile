# Образ Playwright: браузеры и системные библиотеки для них уже внутри, версия совпадает с пакетом в requirements
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
WORKDIR /tests
ENV PYTHONDONTWRITEBYTECODE=1 PIP_BREAK_SYSTEM_PACKAGES=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# код тестов монтируется томом (docker-compose), поэтому правки не требуют пересборки
CMD ["sh", "run.sh"]
