FROM python:3.12

WORKDIR /app

# Копирование и установка зависимостей
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Создание непривилегированного пользователя
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Копирование исходного кода
COPY . .

# Установка прав доступа
RUN chown -R appuser:appuser /app

# Переключение на непривилегированного пользователя
USER appuser

# Порт приложения
EXPOSE 8000

# Запуск приложения
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]