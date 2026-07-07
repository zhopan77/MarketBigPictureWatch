FROM python:3.12-slim
WORKDIR /srv/marketwatch
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Persist ./data as a volume on your hosting service so the nightly
# update survives restarts:  docker run -v mwdata:/srv/marketwatch/data ...
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
