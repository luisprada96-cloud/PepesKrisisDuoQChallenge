# Neon: almacenamiento persistente en el plan gratuito

La integración de Google Drive queda descartada y no se publica. El desarrollo local sigue con db.json.

1. Crear cuenta en https://console.neon.tech y un proyecto Free llamado PepesKrisisDuoQChallenge, preferiblemente en Europa. Mantener PostgreSQL y base de datos por defecto.
2. En Connect, copiar la cadena de conexión PostgreSQL (pooled si está disponible) en el archivo LOCAL ignorado `neon-setup/render-neon.env`, detrás de DATABASE_URL=. No copiar `psql`, comillas ni otros comandos. No pegar la cadena en el chat o GitHub.
3. Instalar dependencias: `python -m pip install -r requirements.txt`.
4. Preparar una exportación COMPLETA y validada del estado ACTUAL de Render. No sustituirla por la copia local antigua: los nuevos lanzamientos y castigos existen solo en producción. Mantener el servicio sin nuevas mutaciones durante el cambio y hacer una copia privada de respaldo.
5. Importar una sola vez: `python neon_setup.py --import-file RUTA_A_LA_COPIA_VALIDADA.json`. Si la tabla ya contiene datos, la herramienta se niega a sobrescribirlos.
6. En Render Environment añadir PEPES_STORAGE=neon y DATABASE_URL con la misma cadena privada. No guardar/desplegar hasta que el código compatible esté listo y la importación verificada. Mantener claves de Riot/Twitch en variables secretas de Render.
7. Publicar el commit nuevo y comprobar equipos, inventarios, castigos, ruleta y un reinicio controlado.

## Modelo y garantías

Una tabla `tournament_state` conserva el documento JSON completo en JSONB, su versión, la copia anterior y el identificador del último guardado. Una actualización condicional por versión evita sobrescribir otra transacción. PostgreSQL confirma el commit antes de responder éxito. Si se pierde una respuesta se comprueba el identificador de guardado; si no puede verificarse, se bloquean escrituras hasta reconciliar.

No se importa automáticamente seed-db.json en Neon. Si Neon no responde o está vacío, falla de forma explícita; nunca arranca un torneo nuevo en su lugar. La copia local pasa a ser caché desechable. El proceso mantiene caché de lectura de hasta 60 segundos; las escrituras siempre validan la versión con PostgreSQL. No se presupone cuota gratuita ilimitada: las consultas y tareas automáticas consumen cómputo del plan.

La copia anterior en la fila protege de una escritura accidental inmediata, no es un historial completo. Conservar exportaciones externas antes de las migraciones.
