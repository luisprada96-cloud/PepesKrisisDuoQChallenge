FROM python:3.12-slim
WORKDIR /app
COPY server.py storage.py sync_jobs.py trophies.py elo_history.py /app/
COPY torneo.html torneo.js index.html admin.html player.html app.js admin.js player.js data.js alerts.js styles.css /app/
ENV PEPES_DATA_DIR=/data
RUN mkdir -p /data
EXPOSE 8085
CMD ["python", "server.py"]
