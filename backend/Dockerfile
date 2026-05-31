FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright: instalar Chromium + dependencias de sistema (necesario para los
# scrapers de futbolfantasy y jornadaperfecta).
RUN playwright install --with-deps chromium

COPY . .
EXPOSE 8000
CMD ["python", "main.py"]
