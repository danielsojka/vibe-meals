FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py seed.py entrypoint.sh ./
COPY static ./static

ENV MEALPLANNER_DB=/data/mealplanner.db
VOLUME /data

EXPOSE 8000

ENTRYPOINT ["sh", "entrypoint.sh"]
