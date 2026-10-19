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

El overlay utiliza `/api/duos`, `/api/overlay/login`, `/api/overlay/state`,
`/api/player/events` y `/api/overlay/logout`. El servidor
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
   no consume inventario ni afecta al torneo. El panel permanece abierto tras la prueba.
6. Para abrir ajustes, haz doble clic en el fondo de la ventana **Interactuar**.
   Solo **Ocultar panel** deja el fondo transparente.
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
- La sesión de OBS no caduca a las 24 horas: se conserva al cerrar OBS y al
  reiniciar/desplegar el servidor. Solo permite leer avisos; no permite lanzar
  pepazos ni girar la ruleta. El servidor guarda un hash del token en el documento
  persistente del torneo, compatible con almacenamiento local y Neon.
  Cerrar sesión revoca ese dispositivo; cambiar la contraseña o eliminar el equipo
  revoca todos sus dispositivos. No se guarda la contraseña en OBS.
  Las sesiones antiguas aún válidas se convierten automáticamente; si ya habían
  caducado, hay que conectar una última vez tras este despliegue.
  Mantén la misma URL/instance y el almacenamiento del navegador de OBS: borrar
  sus datos, usar otro perfil o cambiar de equipo requiere conectar de nuevo.
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

## Biblioteca de animaciones y sorteo compartido

En Administración → Animaciones de pepazos, subir un WebM con VP8/VP9, fondo
transparente y audio Opus incorporado. La página permite revisar el vídeo antes
de enviarlo. Debe indicar una duración entre 0,5 y 30 s y ocupar como máximo
12 MiB. La biblioteca admite 30 efectos y 100 MiB de vídeo en total.

Los vídeos entran activos automáticamente. Todos los efectos activos, incluido
el misil integrado, tienen exactamente la misma probabilidad. Se pueden activar
o desactivar; debe quedar uno activo. La prueba del overlay también elige al azar.

El servidor sortea al crear cada ataque, incluidos los pepazos devueltos, y guarda
una copia del efecto en `shellAttacks[].overlayEffect`. Los dos integrantes reciben
la misma copia por SSE. Leer, reconectar o desactivar un efecto no cambia los
pepazos que ya lo tenían asignado. No se borran vídeos desde el panel, por lo que
sus URL siguen funcionando para avisos asignados anteriormente.

Cada vídeo se reproduce completo y después muestra el atacante durante 3,5 s.
El misil integrado mantiene sus 10 s originales. Si un vídeo falla al cargar o el
navegador no permite reproducirlo, se usa el misil como respaldo, sin repetir el
sorteo. El volumen y la cola también funcionan para vídeos. Los ataques antiguos
sin efecto guardado usan el misil.

El nuevo reproductor necesita cargarse una vez tras este despliegue (reiniciar OBS
o actualizar la fuente). Desde entonces, subir nuevas animaciones desde el panel
no requiere recargar, cambiar URL ni volver a iniciar sesión en los OBS conectados:
el siguiente pepazo lleva directamente la URL y duración de su efecto sorteado.

### Persistencia y despliegue (Luis)

La biblioteca guarda solo metadatos en el documento del torneo. Los bytes de los
vídeos se guardan por separado: en `overlay-media/` junto a `db.json` en local, y en
una tabla `overlay_media` de Neon en producción. La tabla se crea automáticamente
al subir el primer vídeo; el usuario de la base necesita permiso para crearla.
No se necesitan nuevos servicios, claves ni dependencias Python. Las URL de vídeo
usan el hash del archivo y caché inmutable, con soporte de peticiones Range.

La copia de seguridad local debe incluir también `overlay-media/`; una exportación
JSON no contiene los vídeos. En Neon, conservar la tabla `overlay_media` junto a
`tournament_state`. Los archivos de vídeo son públicos para reproducirlos en OBS;
la subida y el cambio de estado requieren PIN administrativo y mismo origen.

Dockerfile y `.dockerignore` ya incluyen el módulo y la nueva interfaz de
administración. El despliegue sigue siendo manual por Luis. No habilitar autodeploy.

### Pruebas de biblioteca

`python -B -m unittest test_overlay_effects` usa datos temporales: sorteo, persistencia,
autorización, límites, duplicados, errores, reproducción de bytes/rangos y que las
lecturas no vuelvan a sortear. La integración Neon se prueba con conexión simulada.
`node test_overlay_library_frontend.cjs` usa un WebM sintético transparente y un
servidor temporal: subida real desde administración, dos overlays conectados antes
de subirlo, mismo efecto, alfa, nombre, reconexión y vista móvil. No toca producción.
