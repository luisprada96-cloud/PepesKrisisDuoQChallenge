# Overlay de pepazos para todos los equipos

## Para quien publica la web

Publicar `overlay.html`, `overlay.css`, `overlay.js` y `overlay-pepazo.mp3` en la raíz del proyecto.
En `server.py`, junto a las líneas `public_files.update(...)`, añadir:

```python
public_files.update({'overlay.html', 'overlay.js', 'overlay.css', 'overlay-pepazo.mp3'})
```

El servidor actual ya incluye esa línea. No sustituirlo por una copia antigua.
Reiniciar/desplegar el servicio como habitualmente. No hay migraciones ni nuevas
dependencias. No modificar contraseñas, claves de Twitch, Riot ni la base de datos.

Si se usa Docker, añadir `COPY overlay.html overlay.js overlay.css overlay-pepazo.mp3 /app/` al
Dockerfile y permitir esos cuatro archivos en `.dockerignore` mediante
`!overlay.html`, `!overlay.js`, `!overlay.css`, `!overlay-pepazo.mp3`. Los archivos del proyecto ya incluyen estos cambios.

El overlay utiliza las rutas existentes `/api/duos`, `/api/player/login`,
`/api/player/state`, `/api/player/events` y `/api/player/logout`. El servidor
selecciona los avisos según la sesión autenticada. No lanza ni abre pepazos.
También recibe los pepazos devueltos por la mecánica de reverso.

## Para cada streamer

En **Mi Panel → Alertas OBS**, cada equipo tiene su URL, el botón **Copiar URL**
y un acceso para probar el overlay. Ese enlace preselecciona el equipo y separa
su configuración local mediante `instance`, pero no autentica ni contiene secretos:
hay que introducir la contraseña dentro de OBS.

1. Configura la fuente en una escena que no estés emitiendo, ya que inicialmente
   se ve el formulario. En OBS, añade **Fuente → Navegador**.
2. URL: `https://duoqchallenge.luisjourney.xyz/overlay.html`.
   Tamaño: **1920 × 1080**. Colócala encima de la captura de juego.
3. Desmarca **Apagar fuente cuando no sea visible** y **Actualizar navegador cuando
   la escena se active**. Así mantendrás la conexión y la cola de avisos.
4. Clic derecho en la fuente → **Interactuar**. Selecciona tu equipo y escribe
   su contraseña habitual. Pulsa **Conectar equipo** y espera el estado **Conectado**.
5. Ajusta el volumen y pulsa **Probar animación y sonido**. Es una simulación local;
   no consume inventario ni afecta al torneo. El panel se oculta para ver la prueba.
6. Para abrir ajustes, haz doble clic en el fondo de la ventana **Interactuar**.
   **Ocultar panel** o **Escape** deja el fondo transparente.
7. Comprueba imagen y sonido con una grabación corta antes de emitir. Si activas
   **Controlar audio a través de OBS**, revisa en el mezclador que la fuente esté
   sin silenciar y que salga por la pista utilizada en la emisión.

Todos los equipos usan la misma URL y eligen su propio equipo al entrar. Ambos
integrantes pueden conectarse desde sus respectivos OBS con la contraseña del dúo.
Los equipos nuevos aparecen automáticamente al abrir el overlay.

Si necesitas dos fuentes con equipos distintos dentro del mismo OBS, utiliza URLs
distintas: `overlay.html?instance=canal-uno` y `overlay.html?instance=canal-dos`.
El parámetro identifica la configuración local, no concede acceso a un equipo.

## Comportamiento y límites

- La fuente permanece transparente salvo durante los avisos o al mostrar ajustes.
- Cada aviso dura 10 segundos; varios avisos se reproducen por orden.
- Usa los eventos autenticados en tiempo real. No consulta Riot ni Twitch.
- Guarda la sesión y el volumen en el almacenamiento local del navegador de OBS,
  nunca la contraseña ni credenciales en la URL. No compartas el perfil de OBS si
  contiene sesiones abiertas. Cerrar sesión revoca esa sesión en el servidor.
- Las sesiones actuales duran **24 horas** y se pierden al reiniciar el servidor.
  Si caducan, aparece un aviso discreto: vuelve a entrar mediante **Interactuar**.
  Comprueba la conexión antes de cada directo.
- Tras una recarga, si el navegador bloquea el sonido automático, abre **Interactuar**
  y pulsa **Probar animación y sonido**. Los eventos se conectan aunque el audio
  espere ese clic. El volumen se conserva entre recargas.
- Una reconexión conserva los identificadores vistos y no repite avisos recibidos.
  Al recargar la fuente, los pepazos que ya estaban pendientes se consideran
  antiguos y no se animan. Los avisos son para el directo; no sustituyen la bandeja
  de pepazos del panel del equipo.
- Mientras haya una desconexión, solo se recuperan los pepazos que continúen
  pendientes al reconectar. Un pepazo abierto durante el corte puede no aparecer.
- Al apagar o suspender el PC o cerrar OBS no se pueden mostrar avisos.

## Validación local

`node test_overlay_frontend.cjs` (Playwright y Chrome) verifica selección de equipos,
autenticación, aislamiento, eventos fragmentados, duplicados, cola, recarga,
reconexión y caducidad con respuestas simuladas. No toca producción.

`python -B -m unittest test_notifications` verifica el canal existente con una
base temporal. Antes de publicar, hacer además la grabación de prueba en OBS.

`node test_overlay_live.cjs` arranca un servidor HTTP temporal sin cron, conecta
Chrome al SSE real y comprueba imagen, generación de audio, recepción antes del
giro y ausencia de repetición tras recargar. Solo usa equipos ficticios y guarda
una captura transparente en `preview/overlay-live.png`; no accede a la base real.

## Animación de misil / alarma nuclear

El misil con Pepo recorre una curva continua y explota a los 6.2 segundos.
El nombre del equipo atacante aparece destacado y estable de 6.5 a 9.9 segundos.
Se conserva el fondo transparente, la cola por equipo y los enlaces desde Mi Panel.

`overlay-pepazo.mp3` contiene una única mezcla sincronizada: sirena mecánica grave
con ciclos lentos, motor y ruido, «Soy un misil» de 0.250 a 3.412 s, el segundo
clip de voz de 4.407 a 6.145 s, y la explosión distorsionada desde 6.2 s.
Las voces están completas y a velocidad original. El volumen del panel controla
la mezcla también durante la reproducción. Cerrar sesión detiene el sonido.

La mezcla se carga desde el mismo servidor; no requiere servicios externos ni
nuevas dependencias de producción. Si el MP3 no carga, el panel muestra un aviso
y permite reintentar con Probar. La animación y la recepción de eventos siguen
funcionando cuando el navegador espera un clic para permitir audio.

Para reconstruir el MP3 en desarrollo, `build_overlay_audio.py` acepta
`--ffmpeg`, `--first` y `--second` con las rutas locales de FFmpeg y los dos clips
originales. No sube archivos ni necesita claves. Los clips originales no son
necesarios para ejecutar la web; la mezcla final está incluida en el repositorio.
