FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY terminology.py /app/
COPY overlay.html overlay.js overlay.css overlay-pepazo.mp3 /app/
COPY campeones.html campeones.js campeones.css champions_service.py /app/
COPY server.py player_accounts.py riot_accounts_sync.py final_predictions.py shell_rules.py tierlists_service.py discord_live.py discord_shells.py weekly_summary.py clips_service.py clip_votes.py postgres_storage.py storage.py sync_jobs.py trophies.py elo_history.py match_details.py /app/
COPY tierlist.html tierlist.js tierlist.css pickem.html pickem.js pickem.css pickem_service.py /app/
COPY premios.html premios.js navigation.js porra.html porra.js porra.css /app/
COPY assets/tierlist/ /app/assets/tierlist/
COPY assets/pickem/ /app/assets/pickem/
COPY resumen.html resumen.js resumen.css roulette.html roulette.css roulette-core.js roulette-window.js roulette-popup.js clips.html clips.css clips.js torneo.html torneo.js index.html admin.html player.html app.js match-history.js admin.js player.js data.js alerts.js styles.css /app/
COPY seed-db.json /app/seed-db.json
ENV PEPES_DATA_DIR=/data
RUN mkdir -p /data
EXPOSE 8085
CMD ["python", "server.py"]
