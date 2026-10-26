# 🏆 Pepes Krisis Duo Q Challenge

Una aplicación web interactiva para torneos de League of Legends con una mecánica de **pepazos**: ataques que permiten imponer castigos a los equipos rivales.

Permite seguir en tiempo real la clasificación de varios dúos en Ranked Solo/Duo mediante sincronización automática con la **Riot Games API**, recompensando rachas de victorias y Pentakills con "Pepazos" para imponer debuffs o penaltis a los equipos rivales.

---

## ✨ Características Principales

### Terminología y compatibilidad

La interfaz, ruletas, avisos, Discord y documentación utilizan «pepazo» y «pepazos». Los textos de sistema históricos se normalizan únicamente al mostrarlos mediante `terminology.py`: no se reescriben votos, registros, nombres de equipos o jugadores ni publicaciones de los usuarios. Para conservar la compatibilidad se mantienen las rutas HTTP, los IDs del DOM, las claves de almacenamiento y los tipos de evento existentes (`blueShells`, `shellAttacks`, `return_shell`, `SHELL_LAUNCHED`, etc.). No se reinician inventarios, castigos ni premios y no se requiere una migración de la base de datos.

- **⏳ Calendario oficial (hora de Madrid)**: inicio el 15/10/2026 a las 18:00 y cierre el 15/11/2026 a las 23:59. La cuenta atrás de portada cambia automáticamente de inicio a cierre y después muestra el torneo finalizado. Las fechas se guardan con zona horaria explícita, incluyendo el cambio de horario de octubre; el formulario de administración siempre muestra y recibe horas de Madrid.

- **Clasificación por ELO medio**: cada dúo se ordena por `(puntos de P1 + puntos de P2) / 2`, usando exclusivamente la cuenta seleccionada para ELO de cada integrante en administración. La escala es Hierro IV = 0, Bronce IV = 400, Plata IV = 800, Oro IV = 1200, Platino IV = 1600, Esmeralda IV = 2000, Diamante IV = 2400 y Master+ = 2800; se suman 100 puntos por división y los LP actuales (en Master+ solo los LP). No es MMR oculto ni LP ganados desde el inicio. Se conservan los medios puntos; desempate por winrate conjunto de las dos cuentas seleccionadas. Una cuenta sin rango confirmado o Unranked deja la media pendiente, sin sustituirla por otra cuenta. La tabla, el filtro de rango medio y los trofeos usan ese criterio; los Pick’em pendientes conservan la última observación semanal de cada cuenta seleccionada antes del cierre. No se recalculan resultados ya resueltos ni se reescriben rangos o historiales individuales. Si faltan rangos, no se congela la clasificación final ni la porra hasta tenerlos. No requiere nuevas llamadas a Riot ni migración destructiva.

- **🎮 Sincronización en Tiempo Real con Riot API**: Seguimiento automático de Elo, Tier, División, LP, Victorias, Derrotas y Racha activa cada 5 minutos.
  - Solo se importan partidas iniciadas desde el **15 de octubre de 2026 a las 00:00, hora de Madrid** (14 de octubre a las 22:00 UTC), en todas las cuentas. Se filtra tanto la consulta a Riot como cada detalle recibido, incluidos reintentos antiguos. Una partida iniciada antes del corte no cuenta aunque termine después. Sin fecha confirmada, se reintenta en lugar de contarla.
  - Las partidas con duración confirmada inferior a 10 minutos se excluyen del historial del challenge antes de calcular rachas, estadísticas, premios o castigos. `excludedRiotMatches` conserva sus IDs para no reimportarlas ni dejarlas pendientes; exactamente 10 minutos sí cuenta. Los rangos y los totales oficiales de Riot no se reescriben.
- **🐢 Sistema de Pepazos**:
  - Cada bloque de 4 victorias consecutivas, pentakill, al menos 20 kills, al menos 30 asistencias o 0 muertes con más de 20 kills + asistencias otorga 1 pepazo. Los logros individuales no exigen victoria y no suman estadísticas entre jugadores.
  - Cada criterio se premia una vez por equipo y partida, con un máximo de 2 premios por partida (incluida la racha) y 5 pepazos en inventario. Los excedentes se pierden. Se priorizan racha, pentakill, kills, asistencias y KDA perfecto.
  - Los nuevos criterios se aplican a partidas incorporadas tras la migración; se conservan premios y marcas anteriores. El registro por partida evita duplicados al recalcular o completar estadísticas.
  - La tabla pública de requisitos utiliza las mismas constantes del servidor mediante `/api/config`.
  - Los equipos pueden lanzar pepazos contra sus rivales para imponer castigos aleatorios (*Sin Flash*, *Autofill*, etc.).
- **📊 Historial de Partidas Ordenado Cronológicamente**: Muestra los campeones jugados, KDA, duración y ganancia/pérdida de LP de cada partida.
- **🔐 Panel de Jugador & Panel de Administración**: Interfaz protegida para que los jugadores gestionen su inventario de pepazos y los administradores configuren el torneo.
- **🖼️ Avatares de Invocador Dinámicos**: Carga de iconos oficiales de LoL mediante Data Dragon CDN (v15.3.1).
- **🟣 Estado de Twitch**: Enlace individual por integrante y detección automática de emisiones en directo cada 5 minutos.

---

## 🚀 Estructura del Proyecto

### Rol principal automático

La posición principal de cada integrante es la más jugada en las Solo/Duo registradas desde el inicio del reto, sumando sus cuentas registradas e independientemente de la cuenta seleccionada para el ELO. Se excluyen pruebas, remakes de menos de 10 minutos, partidas excluidas o previas al corte del torneo, posiciones desconocidas y participantes ajenos; cada partida cuenta una vez por persona. En empate se usa la posición empatada jugada más recientemente; sin evidencia el rol queda pendiente. El admin lo muestra en modo lectura y crear un equipo ya no requiere elegir roles. Los campos de rol enviados por clientes antiguos se ignoran y se recalculan desde el historial.

El acordeón, los trofeos por posición y los nuevos resúmenes usan esa misma referencia. Polivalente guarda el rol más jugado al asignar el castigo, sin mover esa referencia si cambia después. Las referencias automáticas vacías se completan cuando llega evidencia; los castigos antiguos mantienen sus condiciones y los premios/resúmenes ya archivados no se reescriben. No requiere consultas adicionales a Riot ni alterar inventarios o resultados.

### Comentarios de clips

Cada clip tiene un desplegable de comentarios públicos, sin login. El nombre es opcional (máximo 15 caracteres; vacío se muestra como «Anónimo») y el texto obligatorio admite de 1 a 200 caracteres. Los nombres no están verificados. Se valida en el servidor y se muestra como texto, sin ejecutar HTML. Las lecturas se paginan de 10 en 10 mediante `GET /api/clips/comments?week=...&clipId=...&offset=0&limit=10`; la lista principal solo incluye `commentCount`.

`POST /api/clips/comments` recibe `week`, `clipId`, `name`, `text` y un `requestId` de reintento. Usa la cookie anónima que ya crea `/api/clips`, no una sesión de equipo. Los envíos repetidos con el mismo identificador y navegador no duplican comentarios. Protección básica por navegador: 15 segundos entre comentarios, 20 por hora y un máximo interno de 50 por clip, sin mostrar ese máximo en la interfaz ni en el mensaje de cierre. No sustituye a una protección antibot completa. Los identificadores privados no se incluyen en la respuesta pública.

Los comentarios se guardan dentro del clip y se conservan en sus archivos semanales. Se puede comentar un clip archivado sin reabrir su votación, alterar likes o conceder premios. La página mantiene el borrador y el reproductor al refrescar, y conserva el envío para reintentarlo si falla la conexión. No hay dependencias nuevas ni migración destructiva.

### Álbum de campeones

La pestaña `campeones.html` muestra todo el catálogo local de campeones, con un selector para ordenar de mayor a menor por apariciones, KDA acumulado o winrate total de los integrantes inscritos. El orden se conserva al buscar y actualizar. Por KDA o winrate, los campeones con al menos 3 apariciones preceden a los de menos de 3; dentro de cada grupo, los datos pendientes quedan al final y los empates se resuelven por apariciones y nombre. Los ya jugados aparecen en gris y con una marca; al pasar el ratón, enfocar con teclado o tocar se ve su recuento. `GET /api/champions` calcula los totales en lectura, sin nuevas llamadas a Riot ni modificar premios. Filtra fechas del torneo, Solo/Duo, partidas de prueba, exclusiones y duración inferior a 10 minutos, y deduplica partidas y participantes. No cuenta los rivales externos. Si faltan estadísticas o importaciones muestra un aviso de recuento parcial. Al pulsar un campeón se abre un panel con cada participante, su dúo, partidas, porcentaje de victorias, KDA acumulado y totales K/D/A. El winrate utiliza el resultado individual confirmado; los resultados pendientes no se consideran derrotas. Agrupa las cuentas del mismo integrante y usa las mismas apariciones deduplicadas del álbum. El KDA se calcula con estadísticas completas; los datos pendientes o parciales se indican. El panel se actualiza cada 30 segundos y conserva el último resultado si falla la conexión.

- `index.html` / `app.js` — Página principal del ranking y modal de historial.
- `player.html` / `player.js` — Panel de control del jugador (gestión de pepazos y ataques).
- `admin.html` / `admin.js` — Panel de administración protegidos por PIN.
- `torneo.html` / `torneo.js` — Reglas, castigos y probabilidades, y requisitos para conseguir pepazos.
- `premios.html` / `premios.js` — Trofeos y sus clasificaciones; se conceden al finalizar el torneo.
- `navigation.js` — Menú móvil de la cabecera común; conserva enlaces accesibles sin JavaScript.
- `server.py` — Servidor HTTP en Python con daemon en segundo plano para sincronizar con la Riot Games API.
- `db.json` — Base de datos JSON ligera y persistente.
- `styles.css` — Sistema de estilos moderno y fluido (dark mode con estética Hextech).

---

## 🛠️ Cómo Ejecutar Localmente

1. **Clonar el repositorio**:
   ```bash
   git clone https://github.com/tu-usuario/PepesKrisisDuoQChallenge.git
   cd PepesKrisisDuoQChallenge
   ```

2. **Ejecutar el Servidor**:
   ```bash
   python server.py
   # O python3 server.py
   ```

3. **Abrir en el Navegador**:
   Navega a `http://localhost:8085`.

## 🟣 Configurar Twitch

1. Registra una aplicación en [Twitch Developers](https://dev.twitch.tv/console/apps).
2. Copia el **Client ID** y genera un **Client Secret** desde la pantalla de administración de la aplicación.
3. Entra en `http://localhost:8085/admin.html`, introduce ambas credenciales y guarda la configuración.
4. Usa **Comprobar Twitch ahora** para probarlas sin esperar al siguiente ciclo automático.

El Client Secret se almacena localmente en `secrets.json`, un archivo ignorado por Git. En despliegues se recomienda configurar las variables de entorno `TWITCH_CLIENT_ID` y `TWITCH_CLIENT_SECRET`.

### Avisos de directos en Discord

En el canal de texto elegido, abre **Editar canal → Integraciones → Webhooks → Nuevo webhook** y copia su URL. Configura `DISCORD_LIVE_WEBHOOK_URL` como variable privada de Render (o del proceso local). No se introduce en el código ni en la configuración pública. Sin esa variable, los avisos están desactivados.

La sincronización existente de Twitch, cada cinco minutos mientras el servidor está activo, reutiliza la respuesta de Get Streams y envía nombre del integrante, equipo, título y enlace del canal. No añade consultas a Twitch. Si Render gratuito está dormido, al abrir la web se reanudan las comprobaciones; no se pueden detectar directos que hayan terminado entre comprobaciones. La primera comprobación con el webhook configurado también anuncia los directos que ya estén activos.

`discordLiveNotifications` guarda en la misma base (Neon en producción) el último identificador de directo y estado de envío por canal. Cada canal cuenta con un tiempo de enfriamiento (*cooldown*) de 2 horas (`DISCORD_LIVE_COOLDOWN_SECONDS=7200`): si el streamer sufre microcortes o reinicia su emisión en menos de 2 horas, se actualiza el identificador del directo pero no se repite el aviso en Discord. Dos integrantes con canales distintos generan avisos independientes; compartir un canal no duplica el mensaje. Un directo confirmado no vuelve a anunciarse tras un reinicio o una interrupción de Twitch. Se procesan hasta cinco avisos por ciclo. Los errores de Discord no afectan al estado de Twitch: los pendientes se reintentan en ciclos posteriores respetando el tiempo de espera, solo mientras ese directo siga activo y su canal siga vinculado al equipo. Si se pierde una respuesta después de que Discord publique el mensaje, un reintento puede duplicarlo: el webhook no ofrece entrega exactamente una vez.

El panel de administración muestra el último envío confirmado y los errores, sin mostrar la URL privada. Los mensajes desactivan las menciones automáticas, incluido `@everyone`. No hace falta bot, EventSub ni otro proveedor de alojamiento.

Los avisos mantienen el enlace de Twitch clicable y desactivan su vista previa automática mediante `SUPPRESS_EMBEDS` de Discord. Este formato se aplica a los mensajes nuevos; los enviados anteriormente conservan su aspecto.

**Probar aviso de Discord**, en administración, envía un mensaje identificado como prueba mediante `POST /api/discord/test`, protegido con el PIN administrativo. No simula un directo ni cambia el registro de notificaciones del torneo. Tanto esa prueba como la del canal de un equipo (`POST /api/player/discord-webhook/test`) validan la sesión y capturan los datos necesarios bajo el bloqueo de la base, pero esperan a Discord fuera de él. Las consultas y modificaciones del torneo siguen disponibles durante un envío lento; la prueba no guarda una copia antigua del estado al terminar. Las demás mutaciones conservan su serialización. Las pruebas de concurrencia usan Discord simulado y una base temporal, sin enviar mensajes reales ni generar lanzamientos o castigos.

## 🔐 Credenciales de producción

El PIN de administración y las contraseñas de los equipos se almacenan como hashes PBKDF2. Las claves de API no se guardan en `db.json`.

En Render configura estas variables de entorno:

- `RIOT_API_KEY`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

En local, las claves introducidas desde el panel de administración se guardan en `secrets.json`, que está excluido de Git.

---

## Tierlists de equipos e integrantes

`tierlist.html` incluye dos modalidades en el selector «Equipos / Integrantes»: los nueve equipos y los 18 participantes por habilidad, con filas S/A/B/C/D. Las imágenes de `assets/tierlist/` mantienen el formato 400×400, fondo oscuro y nombre centrado. El catálogo de integrantes usa sus nombres públicos (no el nombre de su cuenta de LoL) y conserva identificadores estables, como el catálogo original de equipos. `generate_tierlist_players.py` permite recrear esas 18 tarjetas con Pillow y una fuente TrueType en desarrollo; no añade dependencias al servidor. Admite arrastrar, seleccionar una tarjeta y pulsar su fila, y mover con el teclado. Cada modalidad conserva su propio borrador y autor opcional en ese navegador. Publicar requiere sesión de equipo, todos los elementos del catálogo correspondiente colocados exactamente una vez y un autor de hasta 60 caracteres si se indica. Las listas publicadas son definitivas.

Las publicaciones se guardan en `tierlists` dentro de la misma base (`db.json` en local, Neon en producción), con modalidad (`kind`: `teams` o `players`), equipo autor, nombre opcional, fecha, filas y orden. Las publicaciones antiguas sin `kind` siguen siendo de equipos y conservan sus cupos y contenido. Son públicas, conservan el nombre del equipo al publicar y no participan en la limpieza semanal de clips. Cada modalidad tiene su propia galería de seis publicaciones por página y permite ampliar cada tablero. Sin nombre opcional, el título utiliza el equipo.

`GET /api/tierlists?kind=players&offset=0&limit=6` devuelve catálogo, publicaciones y estado para publicar de Integrantes (`kind=teams`, por defecto, para Equipos); crea la cookie HttpOnly `pepes_tierlist_visitor`. `POST /api/tierlists` recibe `kind`, exige sesión Bearer y esa cookie, comprueba el origen y guarda todo en la mutación serializada existente. El servidor limita a dos publicaciones por equipo y una por navegador **en cada modalidad**, incluso cambiando de equipo en ese navegador. Publicar una tierlist de equipos no gasta los cupos de integrantes y viceversa. Se rechazan modalidades desconocidas y mezclas de elementos de los dos catálogos. El enlace `tierlist.html?tipo=integrantes#crear` abre directamente el editor de integrantes. Solo se guarda el hash del identificador de navegador y nunca se expone en las respuestas públicas. Cambiar o borrar cookies puede ocupar la segunda plaza del equipo, pero no permite superar el límite de dos. Un fallo al guardar o una lista incompleta no consume plaza.

## Fiabilidad y operación

`POST /api/admin/check-apis`, con `authPin`, verifica las credenciales actuales desde el servidor sin necesitar equipos: consulta `lol-status-v4` de Riot y obtiene un token nuevo de Twitch para consultar `helix/streams`. Solo devuelve resultado, fecha y códigos HTTP; nunca claves, secretos o tokens. Una respuesta válida de Riot actualiza la última llamada API OK. No crea partidas, equipos ni avisos de Discord.

La aplicación sirve el frontend y la API desde el mismo origen. Solo los archivos públicos de la interfaz se pueden descargar; la base de datos, copias, secretos y código Python nunca se sirven por HTTP.

- Las operaciones manuales de Riot, Twitch y cálculo de pepazos requieren el PIN administrativo. Riot y Twitch responden `202` y trabajan en segundo plano; `/api/sync/status` informa de ejecución, errores, última finalización correcta y trabajo pendiente. Ese estado operativo se reinicia al arrancar el proceso.
- Los paneles conservan en memoria los últimos datos confirmados cuando falla una lectura, muestran la desconexión y no guardan modificaciones locales como si hubieran llegado al servidor.
- `/api/duos` devuelve un resumen sin historial. `/api/duos/{id}/history?offset=0&limit=30` permite recorrerlo completo. Los eventos también admiten `offset` y `limit`; el límite máximo de página es 100.
- Las consultas no conceden recompensas. Las sincronizaciones y el cálculo administrativo las guardan de forma persistente. Se mantienen las reglas actuales de recompensas y la importación basada en el jugador 1.
- Los castigos necesitan evidencia válida y una partida iniciada después de su asignación. Reabrir un castigo conserva la corrección y descarta la partida que lo había completado automáticamente.

### Avisos personales de pepazos

Los participantes se identifican con las credenciales existentes en Mi Panel. En la clasificación y el panel aparece una barra personal para activar o silenciar el sonido, probarlo y cerrar sesión. La preferencia y los identificadores ya anunciados se guardan en `sessionStorage`, por pestaña y equipo; activar un aviso no cambia la preferencia del compañero ni muestra el estado públicamente.

`GET /api/player/events` abre un canal SSE autenticado mediante `Authorization: Bearer ...`. Envía solo los pepazos pendientes del equipo de esa sesión. Un lanzamiento guardado despierta las conexiones inmediatamente, sin consultas adicionales a Riot. La conexión se reintenta si se interrumpe; las sesiones caducadas o cerradas se desconectan. No se registra una lista pública de presencia.

El audio de `alerts.js` se sintetiza con Web Audio: unos ocho segundos de alarma acelerada y una explosión corta, con volumen reforzado. Requiere activar el sonido con un clic; si el navegador suspende el audio, la barra vuelve a ofrecer activarlo. Funciona también en segundo plano mientras el navegador mantenga la pestaña activa internamente. Una pestaña cerrada, suspendida o un dispositivo dormido no pueden garantizar avisos. Los pepazos que ya estaban pendientes al abrir la página se muestran sin volver a sonar.

### Overlay transparente para OBS

Administración incluye una biblioteca de WebM con sonido. Todas las animaciones activas tienen la misma probabilidad; el servidor guarda el sorteo en cada pepazo para compartirlo entre los dos integrantes. Los nuevos vídeos se utilizan en los overlays conectados sin cambiar su URL ni recargarlos. Los archivos se conservan en Neon en producción y en un directorio de medios en local.

`overlay.html` muestra un misil con Pepo, sirena tipo alarma nuclear, voces y explosión en una secuencia de 10 segundos; el atacante queda destacado al final. Utiliza el canal autenticado de avisos del equipo para mostrar una animación con sonido cuando recibe un pepazo, sin esperar a abrirlo. Admite todos los equipos y los ataques devueltos, cola de avisos, deduplicación y reconexión. Incluye una prueba local de imagen y sonido que no lanza ataques ni modifica el torneo. La configuración de la fuente y sus límites están en [OVERLAY_OBS.md](OVERLAY_OBS.md).

### Almacenamiento y recuperación

`storage.py` escribe primero un archivo temporal, lo sincroniza y lo sustituye atómicamente. Antes conserva la versión válida anterior en `db.json.previous.bak` (y lo mismo para secretos). Si detecta JSON corrupto, se detiene con un error y conserva tanto el original como la copia; nunca lo reemplaza por datos vacíos. Esta copia rotatoria debe complementarse con copias externas periódicas.

Para recuperar datos: detener el servidor, conservar aparte el archivo dañado, comprobar que la copia contiene JSON válido y restaurarla como `db.json` antes de arrancar. Las copias contienen información privada y deben permanecer fuera del directorio público.

En local se usa la carpeta del proyecto. `PEPES_DATA_DIR` permite seleccionar un directorio persistente que contenga `db.json` y `secrets.json`. El Compose incluido monta la carpeta actual en `/data`, conservando los archivos existentes. Se monta un **directorio**, porque la sustitución atómica no funciona con un archivo montado individualmente. La imagen Docker solo contiene código y recursos públicos.

En despliegues remotos hay que proporcionar un directorio persistente y configurar `PEPES_DATA_DIR` con su ruta. El `render.yaml` existente no configura un disco. Ejecutar una sola instancia del proceso Python: los bloqueos coordinan sus hilos, no varios procesos ni réplicas. `sync_jobs.py` coordina los trabajos; las consultas de red se hacen fuera de las transacciones que actualizan la base.

### Pruebas

```bash
python -B -m unittest discover -v
```

La suite utiliza datos temporales y respuestas de Riot simuladas. `test_sync.py` no realiza ninguna operación al importarse; su comprobación manual necesita `python -B test_sync.py --live` y sí modifica los datos reales.

Las pruebas opcionales de navegador usan Playwright y un Chromium disponible: `node test_frontend.cjs`. Se puede seleccionar Chrome instalado mediante `PLAYWRIGHT_CHANNEL=chrome`. Todas las respuestas se simulan; no se consulta Riot ni el servidor real.

---

## 🤝 Cómo Contribuir

¡Las contribuciones son bienvenidas!
1. Haz un **Fork** de este repositorio.
2. Crea una rama para tu función (`git checkout -b feature/nueva-funcionalidad`).
3. Realiza tus cambios y haz commit (`git commit -m 'Añade nueva funcionalidad'`).
4. Haz push a la rama (`git push origin feature/nueva-funcionalidad`).
5. Abre un **Pull Request**.

---

## 📜 Licencia

Este proyecto está bajo la Licencia MIT. Libre para su uso y modificación.


### Trofeos

La sección pública muestra siete premios: campeón por rango/división/LP (desempate por winrate), mejor KDA para cada uno de los cinco roles y pin de la deshonra al último dúo. Cada jugador opta solo a su rol principal configurado y solo se cuentan sus partidas en ese rol, excluyendo pruebas y partidas sin estadísticas o rol identificado. KDA = (kills + asistencias acumuladas) / max(1, muertes acumuladas); no exige mínimo de partidas. Los empates de KDA se ordenan por partidas y, si persisten, quedan pendientes de desempate.

`/api/trophies` devuelve las clasificaciones provisionales. Al alcanzar `config.endDate`, el servidor guarda `awardedTrophies` en db.json con los últimos datos sincronizados; un proceso comprueba el cierre cada 15 segundos, incluso sin visitantes. El resultado queda congelado ante sincronizaciones posteriores. No se modifican los límites temporales de las llamadas Riot. Si el servidor está apagado durante el cierre, guardará los datos disponibles al arrancar. Las fechas sin zona horaria usan la hora local del servidor, igual que la configuración existente; debe coincidir con la hora del torneo.

El panel público `torneo.html`, accesible como «Torneo y premios» desde la navegación superior, reúne reglas, ruleta, requisitos de pepazos y trofeos. `torneo.js` actualiza estos datos cada 15 segundos; el principal conserva la clasificación y las estadísticas. Los avisos personales también funcionan en el panel nuevo.

### Evolución de ELO

El desplegable de cada dúo muestra la evolución diaria del ELO de ambos integrantes: amarillo para `player1`, verde discontinuo para `player2`, con leyenda y detalles al pasar, enfocar o tocar cada punto. Cada jugador guarda su propio `eloHistory` y `eloHistoryAccount`, con el último rango observado de cada día (fecha local del servidor), LP y victorias/derrotas si están disponibles. El historial antiguo del dúo se conserva para el primer jugador; el segundo empieza con su primer rango confirmado. No se reconstruyen LP anteriores a partir de victorias o derrotas. Cambiar una cuenta reinicia solamente su historial. Con un solo registro se muestra un punto, no una curva inventada. El `eloHistory` antiguo del dúo sigue manteniéndose por compatibilidad.

Docker incluye `seed-db.json`, una semilla vacía sin equipos ni credenciales, inaccesible desde HTTP. Solo se usa si no existe la base de datos local en `PEPES_DATA_DIR`; nunca sustituye datos existentes. `db.json` y `secrets.json` contienen los datos privados locales y no se versionan. En modo local se necesita almacenamiento persistente para conservar modificaciones entre despliegues; en producción esa persistencia la proporciona Neon.

### Neon (PostgreSQL)

Producción puede usar `PEPES_STORAGE=neon` y `DATABASE_URL` como variable privada de Render. El estado JSON se guarda en `tournament_state` con control de revisión y copia anterior; un conflicto nunca sobrescribe otra operación. No hay restauración automática de seed-db.json cuando Neon falla. El modo local continúa usando db.json. Consulta `NEON_SETUP.md` para importar una copia validada y cambiar el servicio sin perder avances.


### Clips semanales y likes por equipo

`clips.html` muestra vídeos grandes con ordenación por likes o fecha. Las publicaciones y los votos se guardan en el campo `clips` de la base existente: `db.json` en local y Neon en producción. No se almacenan vídeos, solo enlaces de clips de Twitch.

Los clips se pueden consultar sin sesión. Para votar se utiliza la sesión de «Mi Panel», guardada en `sessionStorage` y enviada en la cabecera `Authorization: Bearer`. El servidor obtiene el equipo de esa sesión; nunca confía en un `teamId` enviado para votar. La cookie `pepes_clips_visitor` identifica el navegador (`HttpOnly`, `SameSite=Lax`, un año; `Secure` detrás de HTTPS). Su hash se guarda en `teamVotes: {teamId: [browserHash, ...]}` por publicación.

`POST /api/clips/like` recibe `clipId` y el estado booleano `liked`. Un clic añade el like del navegador y otro lo retira; repetir la misma petición es idempotente. El servidor admite un voto por navegador y clip, y como máximo dos votos por equipo y clip entre todos sus navegadores. Cambiar de equipo en el mismo navegador no duplica el voto. Retirar un like solo afecta al voto identificado por esa cookie. Sin sesión válida no se pueden modificar likes. La API devuelve el total, el estado del like del navegador y el equipo autenticado; no publica los identificadores ni el contador de votos del equipo. La interfaz no muestra el límite interno ni botones adicionales. Los errores de almacenamiento no se presentan como votos confirmados y se consultan los totales cada cinco segundos mientras la pestaña está visible.

Los votos anónimos anteriores se conservan también al archivar la ronda. Los contadores compartidos anteriores sin identidad de navegador mantienen sus votos reservados; los primeros navegadores del equipo que votan los reclaman sin incrementar el total. `clip_votes.py` calcula un único total para la interfaz, el premio y el resumen semanal. Al reiniciar el servidor hay que volver a iniciar sesión, pero los votos persistidos y la cookie se mantienen. Publicar clips y marcar vistos siguen disponibles sin sesión; los vistos permanecen exclusivamente en `localStorage`.

El listado muestra como máximo 15 clips por página, con controles anterior/siguiente arriba y abajo. Cambiar de filtro o publicar vuelve a la primera página; las actualizaciones mantienen la página actual mientras siga existiendo. El orden se calcula al cargar, cambiar de filtro o publicar. Dar/quitar likes y las consultas automáticas actualizan los contadores conservando las posiciones y los reproductores. Los clips nuevos recibidos durante una consulta automática se añaden al final hasta la siguiente ordenación.

El ojo en la esquina superior derecha marca o desmarca un clip como visto, sin requerir sesión ni enviar cambios al servidor. La pestaña «No vistos» filtra los pendientes y los ordena del más reciente al más antiguo. Las marcas se guardan en `localStorage` bajo `pepes_clips_seen`, separadas por ronda para este navegador. Se conservan al cerrar/reabrir, al consultar archivos y entre pestañas; una ronda nueva comienza sin marcas. Los clips vistos siguen disponibles en «Recientes» y «Más votados»; reproducir un vídeo no lo marca automáticamente. `test_clips_frontend.cjs` verifica paginación, persistencia, filtros, reducción de páginas y compatibilidad con likes/publicaciones.

La primera ronda abarca desde el inicio configurado del torneo (15 de octubre de 2026 a las 18:00) hasta el domingo siguiente al primer domingo: cierra el **25 de octubre a las 23:59, hora de Madrid**. La siguiente comienza el lunes 26 a las 00:00 y, desde entonces, cada ronda dura de lunes a domingo. Los límites usan `Europe/Madrid` e incluyen el cambio de hora. Al renovar, se liquida el premio pendiente y se conserva el tablero completo en `clipArchives`, con publicaciones, enlaces, votos y resultado, incluso si Render estuvo dormido. `PEPES_CLIPS_PREVIEW=1` habilita tres publicaciones de ejemplo con contadores reales que empiezan en cero, únicamente con almacenamiento local. Producción no crea ejemplos.

Cada publicación exige `teamId`, elegido en el formulario entre equipos existentes. El servidor guarda ese ID y el nombre del equipo, sin aceptar un nombre arbitrario enviado por el navegador. Los clips antiguos sin equipo y los ejemplos siguen visibles, pero no compiten por premios.

La votación cierra el domingo a las 23:59:00, hora de Madrid; durante el último minuto no se puede publicar ni cambiar likes. El clip elegible con más likes recibe un premio de 1 pepazo para su equipo; los empates se resuelven por fecha de publicación más antigua y, si también coincide, por ID. Hace falta al menos un like y un equipo existente. Este premio incrementa directamente `blueShells` y puede superar el límite normal de 5; las recompensas de partidas mantienen su límite y no recortan inventarios mayores. Los premios ya entregados conservan su cantidad original y no se vuelven a calcular.

`clipWeeklyRewards`, indexado por fecha de inicio de la ronda (15 de octubre para la inaugural y lunes para las siguientes), guarda ganador, equipo, votos, fecha prevista de cierre, fecha real de liquidación y cantidad. Inventario, resultado y evento se guardan juntos en la misma operación de almacenamiento. El programador calcula el siguiente cierre, y el arranque y las lecturas recuperan premios vencidos antes de limpiar clips. Si el servicio está dormido, la entrega física se realiza al reactivarse; los votos posteriores al cierre se rechazan. El registro por ronda impide duplicados por reinicios, peticiones simultáneas o reintentos. El selector consulta `GET /api/clips?week=FECHA` y permite volver a ver los clips archivados y sus likes finales. Las rondas cerradas no admiten votos ni publicaciones y no compiten por el premio de la ronda actual. Los enlaces con `?week=` conservan la selección al recargar; el sondeo respeta la ronda elegida. El servidor rechaza escrituras dirigidas a una ronda archivada aunque se fuerce la petición. No se exponen identificadores de votantes.


### Ruleta en ventana para stream

Al pulsar «Girar ruleta» en el panel del jugador se solicita una ventana emergente de 680 × 460 con la ruleta, el equipo y el resultado. El panel mantiene su ruleta y la espera de 13,5 segundos tras revelar el castigo. La ventana conserva el resultado hasta el siguiente giro y puede moverse o redimensionarse para capturarla en OBS.

Ambas vistas animan el único resultado devuelto por `/api/player/spin-shell`, con el mismo instante de inicio. La ventana de stream no llama a la API ni necesita sesión de equipo. Los mensajes verifican origen, ventana emisora y canal; al cargar o reabrir se recupera el estado actual sin sortear otra vez. Una vez cargada, puede terminar la animación aunque se cierre el panel.

Si el navegador bloquea la apertura, la ruleta del panel continúa y aparece «Abrir ruleta para stream» para reintentarlo tras permitir ventanas emergentes. La ventana se reutiliza en los siguientes giros. `test_roulette_frontend.cjs` verifica estos casos con Playwright y Chrome, incluido el tiempo de revelación y la espera del resultado.


### Rango de cada integrante en la clasificación

La tabla principal muestra «Integrante 1» e «Integrante 2» con su rango Solo/Duo y LP actuales, sin LP netos en la fila. Riot confirma cada rango por separado y se guarda en `player1.rank` y `player2.rank` (`tier`, `division`, `lp`, `observedAt`). Los errores conservan el último rango confirmado; una respuesta correcta sin entrada Solo/Duo muestra «Sin clasificar». Hasta la primera consulta del segundo integrante se muestra «Pendiente». Las bases anteriores reutilizan el rango del dúo únicamente para el primer integrante. Cambiar la cuenta en administración invalida su rango individual.

La clasificación, winrate y evolución de ELO del dúo mantienen el cálculo existente a partir del jugador 1. En pantallas estrechas la tabla permite desplazamiento horizontal para consultar ambos integrantes.

### Nombres y Twitch de los participantes

Cada participante también puede guardar `opggUrl`, una URL HTTPS opcional de OP.GG que introduce el administrador al crear o editar el equipo. En su tarjeta del acordeón aparece el botón OP.GG, que abre el perfil en otra pestaña. El botón se oculta si no hay enlace; dejar el campo vacío lo elimina y omitirlo en una actualización conserva el anterior. Frontend y servidor validan el dominio, sin consultar ni importar estadísticas de OP.GG.

Cada integrante guarda `displayName` (nombre visible, independiente del Riot ID), `twitchUrl` (opcional) y `twitchIsLive` (confirmado por Twitch). Administración permite introducirlos al crear un dúo y editar ambos perfiles en los equipos existentes. En la clasificación se muestra el nombre encima de su rango y su enlace de Twitch debajo; el botón rojo indica que ese integrante está en directo. El contador de equipos en directo cuenta un equipo si al menos uno de sus integrantes emite.

Los enlaces antiguos del equipo se reutilizan únicamente para el primer integrante hasta que se editen. Guardar un enlace individual vacío elimina su botón, incluso si existe un enlace antiguo. La sincronización consulta los dos canales y conserva el estado confirmado cuando Twitch falla. Cambiar estos perfiles no borra los rangos, historiales de ELO, partidas, castigos ni pepazos.

Las tarjetas inferiores muestran el Riot ID, KDA global individual `(asesinatos + asistencias) / max(1, muertes)`, rol principal configurado y campeón más jugado de las partidas registradas. Si faltan estadísticas se muestra «—» en KDA y «Sin datos» en el campeón.

### Castigos individuales: destinatario 50/50

Al abrir un nuevo castigo con `scope: ONE`, el servidor sortea una sola vez entre `player1` y `player2`, con igual probabilidad e independientemente del sorteo del castigo. `requirements.assignedPlayer` guarda el integrante; `assignedAccount` conserva su nombre visible, Riot ID y PUUID conocido. El campeón aleatorio, cuando corresponde, se sortea para ese mismo integrante. La asignación se guarda junto al castigo, el ataque y el evento de apertura, y se muestra en ambas ruletas, Mi Panel, administración e historial público.

La evaluación de Polivalente, Sin campeón favorito, Campeón aleatorio, Sin Flash exige que el integrante asignado cumpla su condición. Las estadísticas de Riot conservan el PUUID para verificar la cuenta. Si todavía no se conoce, se vincula al Riot ID configurado y se verifica su PUUID cuando se sincroniza. Los datos incompletos, las partidas de prueba y las partidas iniciadas antes de la asignación no acreditan cumplimiento. El castigo y la evidencia guardan quién debía cumplirlo y la partida que lo acreditó. Recargar, reiniciar o reabrir el castigo no cambia el integrante elegido.

Los castigos que ya estaban abiertos sin destinatario conservan la regla anterior (puede cumplirlos cualquiera); las asignaciones anteriores de campeón aleatorio también se conservan. Los castigos de AMBOS siguen exigiendo a ambos. `test_penalty_assignments.py` verifica todos los tipos, ambos destinatarios, persistencia, compatibilidad y una sincronización completa con respuestas de Riot simuladas.

### Campeón aleatorio: pendientes del álbum y reparación de Locke

Los nuevos sorteos de campeón aleatorio se realizan entre los campeones todavía no jugados por ningún participante del torneo, usando el mismo catálogo y los mismos filtros del álbum (fechas del torneo, Solo/Duo, duración mínima, exclusiones y partidas reales). Al completar el álbum, vuelve a estar disponible el catálogo completo. AMBOS recibe dos campeones distintos; si solo queda uno pendiente, se sortea qué integrante lo recibe y el otro obtiene uno diferente del catálogo completo. Cada asignación conserva el campeón y `randomChampionPool` (`unplayed`, `all` o `last_unplayed`), y la web muestra el criterio junto al resultado de ambas ruletas y los castigos. Las asignaciones ya existentes no se vuelven a sortear; sortear un campeón no lo marca como jugado.

Locke y Vex son campeones distintos. Se elimina la conversión antigua entre ambos de la importación, el texto visible y las claves de predicciones/álbum. El ID numérico de Riot también se conserva en las nuevas importaciones. La corrección confirmada por el participante se limita a JaGenau#JOYAS y a las partidas EUW1_8014333109 y EUW1_8017228945: sus registros antiguos de Vex sin ID verificado pasan a Locke al cargar la base de datos, dejando constancia del valor anterior y recalculando sus resúmenes. Las partidas de otros jugadores, las futuras partidas de JaGenau y los registros con identidad numérica verificada no se convierten. No se reparten otra vez recompensas ya procesadas. Las predicciones ya cerradas no se recalculan automáticamente.

### Polivalente: posición sorteada

Los nuevos Polivalente sortean también una posición entre las cuatro distintas del rol principal, calculado con las partidas del participante. UNO sortea únicamente para el integrante elegido; AMBOS hace un sorteo independiente por integrante. `requirements.randomPositions` conserva las posiciones junto al rol principal de referencia. Las posiciones no cambian al recargar, reiniciar ni actualizar el historial. Si falta historial para conocer el rol principal, la web indica «Posición pendiente»; la siguiente sincronización con datos suficientes fija la referencia y realiza el sorteo una sola vez.

La posición aparece junto al jugador al revelar el resultado en las ruletas del panel y de la ventana externa, en sus castigos pendientes y cumplidos, en administración, en el historial público y en los últimos lanzamientos del atacante. Una partida posterior a la asignación completa el pepazo solo si cada afectado juega la posición sorteada; jugar otra posición fuera de su principal no basta. La evidencia conserva las posiciones requeridas. Los Polivalente anteriores conservan sus condiciones originales. `test_polivalente.py` y `test_polivalente_frontend.cjs` verifican selección, persistencia, cumplimiento y presentación.

### Pepazo reverso

«Devuelve el pepazo» crea un ataque `PENDING_SPIN` en la bandeja del equipo que lo lanzó. El receptor original devuelve el ataque sin gastar inventario y el atacante original debe girar su propia ruleta para recibir el castigo. No se devuelve una unidad al inventario; tener cero pepazos o el inventario lleno no impide recibirlo. El nuevo ataque activa las mismas notificaciones personales y aparece como «Pepazo devuelto por…» en Mi Panel.

El ataque inicial queda `RETURNED` y apunta al nuevo mediante `returnedAttackId`; el nuevo guarda `returnedFromAttackId`, `rootShellId` y `reflectionCount`. Conserva los porcentajes de la ruleta original. Si vuelve a salir reverso, rebota de nuevo, una sola vez por giro. Al salir un castigo, se asigna al equipo que acaba de girar y, si es de UNO, se aplica el sorteo de integrante 50/50. Los reversos históricos ya registrados conservan su resultado anterior.


### Sincronización incremental de Riot

La primera consulta del historial de cada cuenta conserva el recorrido completo con los mismos filtros existentes (Solo/Duo y desde 2026). Guarda `riotMatchDiscovery` como metadato interno del equipo: cuenta consultada, último ID descubierto y cola de partidas pendientes. Las siguientes sincronizaciones recorren únicamente las páginas recientes hasta alcanzar ese ID. Los detalles fallidos y las partidas que exceden el lote de 40 permanecen en la cola, incluso después de reiniciar el servidor. Si cambia la cuenta o no aparece el ID de referencia, se vuelve a recorrer el listado completo. Un fallo de paginación no adelanta la referencia.

Cada sincronización reutiliza las respuestas correctas de una misma URL de Riot para evitar repetir consultas compartidas entre equipos, iconos e historial. Esta caché dura únicamente ese trabajo; las respuestas fallidas no se cachean y los rangos se vuelven a consultar en la siguiente ejecución. La recuperación de estadísticas antiguas y las reglas de castigos y recompensas se conservan.


Si «Sin campeón favorito» se abre antes de disponer de estadísticas del integrante afectado, su referencia queda pendiente. Cada incorporación o recuperación de partidas recalcula los campeones más jugados y rellena las referencias vacías de los castigos activos. Se conserva el criterio de empates: todos los campeones empatados como más jugados quedan incluidos. Una vez establecida la referencia de cada integrante, permanece fija para ese castigo; los siguientes lanzamientos usan el historial actualizado. Esto también recupera castigos anteriores con listas vacías, sin volver a sortear quién debe cumplirlos. Las partidas de prueba y los campeones desconocidos no construyen favoritos.

El historial del modal usa un resumen desplegable por partida y dos filas de detalles. La importación conserva el Riot ID, campeón, nivel, rol, hechizos, K/D/A, CS de línea y jungla, oro, visión, los siete huecos de objetos finales y los asesinatos del equipo correspondiente a cada integrante. El KDA, CS/min y participación se calculan al mostrar la partida; la participación usa los asesinatos de todo su equipo, no solamente los del dúo. Una partida sin muertes muestra «Perfecto» y los datos ausentes aparecen como «—». No se almacena el resultado completo de Riot ni una puntuación OP Score.

`matchDetailsVersion` y `matchDetailsBackfill` permiten recuperar progresivamente los detalles de partidas antiguas en el lote existente de 40 por equipo, manteniendo el descubrimiento incremental y los marcadores de recompensas. Las partidas de prueba no se recuperan. Una cuenta identificada que no aparece entre los participantes se muestra como «No participó»; un fallo al identificar la segunda cuenta deja los detalles pendientes para reintentar. El parche (`gameVersion`) y la duración numérica quedan guardados por partida. Los nombres en español e iconos de objetos y hechizos proceden de Data Dragon, con caché por parche en el navegador; su carga no realiza consultas nuevas a la API de Riot ni guarda imágenes en la base de datos. Si esos recursos fallan, los datos siguen visibles y los objetos conservan su ID como etiqueta.

### Resumen semanal

La navegación pública separa «Torneo» y «Premios» en todas las páginas. La cabecera muestra marca y accesos a los paneles arriba, con las secciones en una fila inferior. Hasta 900 px las secciones se abren desde un menú accesible, con cierre mediante Escape, clic fuera y adaptación al cambiar de tamaño; los paneles siguen disponibles. Las pantallas de Torneo y Premios consultan únicamente configuración y trofeos, respectivamente. Los enlaces anteriores a `torneo.html#trophies` redirigen a `premios.html#trophies`.

Los avisos técnicos se muestran exclusivamente en la sección «Estado de los datos y sincronización» de administración, tras acceder con PIN. Incluye el estado de Riot/Twitch, conexión, partidas por importar, estadísticas y detalles pendientes, y logros sin registro de ingreso al inventario. El estado del archivo semanal y las explicaciones de recuperación, observaciones de ELO y almacenamiento de likes también quedan allí. Las pestañas públicas mantienen las reglas, información necesaria para interpretar sus datos y errores de acciones del participante, sin banners de sincronización ni contadores de recuperación. El refresco automático sigue funcionando.

El aviso «Riot: última llamada API OK» muestra, en hora de Madrid, la última respuesta HTTP correcta con JSON legible recibida de Riot durante una sincronización. Se guarda en `lastRiotApiSuccessAt` dentro del estado del torneo (Neon en producción) y se expone como `riot.lastApiSuccessAt` en `/api/sync/status`. Las respuestas reutilizadas de la caché, los errores y las sincronizaciones sin consultas no avanzan esa fecha. Se conserva aunque el resto del trabajo falle o se reinicie el servidor; antes de la primera respuesta real se indica que todavía no hay llamadas confirmadas.

Los fallos de Riot indican cuántas consultas devolvieron cada código HTTP, errores de conexión o datos no válidos, sin exponer claves ni URLs. El estado diferencia una sincronización parcial (hubo respuestas correctas) de una fallida (no hubo ninguna respuesta correcta en ese trabajo). Los datos importados previamente permanecen disponibles en ambos casos.

Los nombres visibles de campeones se resuelven con `championDisplayName` en `data.js`, usando los nombres oficiales en español de Data Dragon 16.19.1. Por ejemplo, `MonkeyKing` se muestra como Wukong en clasificación, historial, asignaciones de ruleta y resúmenes. Los identificadores originales se conservan en la base, los requisitos de castigos y las URLs de iconos. La tabla de nombres se sirve con la web sin llamadas adicionales a Riot; los identificadores sin alias se muestran tal cual.

`resumen.html` añade una pestaña pública con vista general, selección de equipo y archivo de semanas. El selector empieza en la semana que contiene el inicio configurado del torneo; oculta las semanas anteriores de pruebas y añade las siguientes normalmente. Los archivos anteriores se conservan en la base, pero no se exponen en el resumen público ni se regeneran. Los enlaces antiguos a una semana oculta vuelven a un resumen disponible. Antes de llegar a la semana inaugural se muestra esa semana como próxima. La semana actual se actualiza desde la base; por defecto se abre la última archivada del torneo, si existe. Los informes de lunes a domingo usan `Europe/Madrid`, incluyendo los cambios de horario. El lunes a las 00:00 se guarda el resumen en `weeklySummaries`, junto con los totales y el ganador de clips, antes de renovar la lista de clips en la misma operación de persistencia. El premio de clips usa su propio calendario (primera ronda hasta el 25 de octubre y después lunes a domingo), con cierre a las 23:59 y registro independiente para evitar duplicados. Los resúmenes mantienen sus semanas naturales y reparten los clips según su fecha; el ganador figura solo en la semana de cierre de su ronda.

El scheduler existente realiza el cierre y recupera semanas pendientes al despertar; las lecturas también recuperan un archivo que no pudo guardarse. Se archiva desde la semana en que se habilita la función (o la semana del tablero de clips aún conservado), sin inventar archivos anteriores. Las sincronizaciones de Riot actualizan archivos si incorporan partidas atrasadas, y las correcciones administrativas recalculan los cumplimientos. Se conservan las etiquetas y resultados de cuentas sustituidas o equipos eliminados. Los resúmenes permanecen cuando se renueva la lista de clips.

Las partidas se asignan por `gameEndTimestamp`, excluyendo `isTest`, y se deduplican por `matchId` en el total general. Las estadísticas individuales usan únicamente los datos disponibles de cada participante; el KDA combinado se calcula con la suma de K/D/A y la mejor partida exige detalles de ambos. Los rangos comparan observaciones reales con sus fechas: las referencias incompletas se señalan como parciales y no participan en los destacados de subida/bajada. Los castigos automáticos se cuentan por la fecha de la partida que los acredita, separados de los marcados por administración. Los lanzamientos normales se distinguen de las devoluciones. `shellRewardCredits` registra desde esta versión qué logros ingresaron al inventario y cuáles toparon con el límite; los anteriores aparecen sin registro, no como cero inventado. No se añaden llamadas a Riot ni se cambian las reglas del torneo o de las recompensas.

`GET /api/weekly-summary?week=YYYY-MM-DD` devuelve únicamente el resumen público y las semanas disponibles; no expone credenciales, PUUID, identidades de votantes ni requisitos privados. Sin `week`, devuelve la semana actual. La página refresca cada minuto conservando la selección; los datos de un clip ganador permiten reproducirlo desde Twitch incluso después de limpiar la semana.

### Mis castigos en el panel del equipo

En «Mi Panel», las pestañas «Pepazos» y «Mis castigos» separan los lanzamientos y giros de la consulta de castigos. Los pendientes se agrupan por integrante y por ambos; los castigos individuales antiguos que podía cumplir cualquiera conservan su propio grupo. Las asignaciones a cuentas anteriores se distinguen de las del perfil actual. Se muestran todos los pendientes, mientras que «Historial» pagina los cumplidos y retirados en bloques de 20. Las actualizaciones automáticas conservan la pestaña, el filtro y la página abiertos. Esta vista usa los datos existentes de la base y no añade llamadas a Riot ni cambia las reglas de cumplimiento.

### Retirada del castigo de botas

Las variantes de UNO y AMBOS ya no participan en la ruleta. Al cargar la base se retiran sus pesos de la configuración y de los pepazos pendientes, conservando los pesos relativos del resto. Si una ruleta antigua solo tenía botas activas, se recupera con los pesos predeterminados vigentes. Los castigos de botas pendientes quedan `CANCELLED` (Retirado), sin fabricar cumplimiento ni borrar el historial; los cumplidos conservan su evidencia. Administración no puede reabrirlos. Ya no se consulta la timeline de Riot para este castigo. Los objetos finales de las partidas, incluidas las botas, siguen mostrándose.

### Flash al otro lado

`swap_flash_one` y `swap_flash_both` exigen Flash en el slot contrario al cómodo (D/F por defecto), dejando libre el otro hechizo. Pesos predeterminados: 12 para UNO y 6 para AMBOS, editables en administración. Al introducirlos se ajustan proporcionalmente los pesos restantes si la suma supera o no alcanza 100, respetando los castigos desactivados y sin volver a ajustar posteriores cambios administrativos. Los pepazos ya lanzados conservan su snapshot anterior. UNO usa el sorteo de integrante 50/50 existente; AMBOS exige cumplimiento de ambos en la misma partida.

La primera partida importada correctamente con dos hechizos válidos y Flash fija `player1.flashBaseline` o `player2.flashBaseline`, independientemente por cuenta. Se registra el slot original, la partida, su inicio y la identidad de Riot. No se infiere de las partidas ya guardadas al arrancar, ni cambia con posteriores sincronizaciones o partidas antiguas recuperadas. Partidas de prueba, sin Flash o incompletas no fijan referencia. Si el castigo se abre antes de conocerla, queda pendiente hasta que entre esa primera partida; esa partida únicamente establece la referencia y nunca acredita cumplimiento.

Los requisitos congelan las referencias e identidades al asignarlos o al completar las referencias pendientes. La partida válida debe comenzar después de la asignación y de la partida de referencia, corresponder a la cuenta afectada y contener Flash una sola vez en el slot opuesto. Cambiar la cuenta en administración descarta su referencia cómoda para futuras asignaciones y no transfiere un castigo anterior a la cuenta nueva. Los requisitos y la evidencia se guardan en la base, y el texto específico se muestra en las ruletas, Mi Panel, administración e historial. Se reutilizan `summoner1Id`/`summoner2Id` de Match v5; no hay llamadas adicionales. La API permite comprobar slots, pero no las teclas personalizadas del jugador.

### Pick’em semanal

El duelo semanal «¿Quién hará más kills esta semana: Chicha o Fogell?» suma exclusivamente los asesinatos individuales de esos dos participantes en las Solo/Duo registradas dentro de la semana y del torneo. Ambos nombres se vinculan a sus cuentas de Riot al crear las opciones; los cambios de perfil no transfieren las predicciones. Descuenta duplicados, excluye pruebas y otras colas, espera datos incompletos y acepta ambas respuestas en empate. Si ninguno tiene partidas válidas, no suma un acierto. Como en los otros duelos, la primera respuesta del equipo fija la elección para sus dos quinielas; cada integrante debe confirmarla. Se repite cada semana y contribuye al premio de la quiniela: un pepazo con 3–4 aciertos y dos con 5 o más.

«¿Qué campeón tendrá mejor winrate?» permite buscar y seleccionar cualquiera de los campeones del catálogo oficial de Data Dragon (`assets/pickem/champions.json`, versión 16.20.1, 173 campeones). El selector filtra nombres e identificadores sin distinguir mayúsculas, tildes, espacios ni apóstrofos, admite ratón y teclado y conserva la búsqueda durante los refrescos. Guarda el ID oficial y muestra el nombre en español, por ejemplo Wukong (`MonkeyKing`) y Kai’Sa (`Kaisa`). La categoría se añade a semanas abiertas sin borrar quinielas; los archivos cerrados no cambian.

Para resolverla se agrupan las partidas individuales de todos los participantes por campeón dentro de la semana y del torneo. Se excluyen pruebas, otras colas y duplicados por partida y cuenta; se usa el resultado individual `win`, nunca el de otro integrante. Solo compiten campeones con al menos tres partidas. Se compara `victorias / partidas` exactamente, sin redondear antes de decidir, y cualquier campeón empatado en el mejor porcentaje cuenta como acierto. Si ninguno llega al mínimo, la categoría no suma un acierto; si faltan estadísticas o importaciones, espera. Reutiliza el historial de Riot existente, sin consultas adicionales. Su acierto contribuye al premio por quiniela: un pepazo con 3–4 aciertos y dos con 5 o más.

`pickem.html` incluye la primera categoría: campeones distintos de los participantes en las partidas Solo/Duo registradas de cada semana. Cuenta `player1Stats.championName` y `player2Stats.championName`, sin los otros jugadores y sin repetir campeón; se excluyen pruebas y partidas fuera de la semana o del torneo usando `gameEndTimestamp`. Se reutiliza el historial que ya importa Riot, sin consultas nuevas. Los rangos son menos de 20, 20–29, 30–39…110–119 y 120 o más, sin solapamientos.

Cada equipo dispone de dos quinielas por periodo y cada navegador de una, mediante una cookie HttpOnly cuyo hash se guarda en la base. Hace falta una sesión del equipo. Las respuestas son definitivas; un reintento idéntico del envío es seguro. El autor es opcional. Las próximas categorías pueden añadirse a la misma quiniela sin consumir otro intento. Cambiar de navegador puede ocupar la segunda plaza del equipo; no identifica personas. Cada equipo puede consultar sus dos quinielas desde cualquier navegador autenticado; las predicciones ajenas permanecen ocultas hasta finalizar el periodo de juego. El periodo siguiente renueva las plazas y conserva el archivo.

### Calendario y consulta de Pick’em

`config.pickemSchedule` separa el plazo para responder (`closesAt`) del periodo de partidas (`startsAt` / `endsAt`). El primer periodo va del 16 de octubre de 2026 a las 00:00 al 25 a las 23:59, con respuestas hasta el viernes 16 a las 23:59. Incluye ambos domingos y el cambio de hora de Madrid. A partir del 26 los periodos son de lunes a domingo, con respuestas hasta el lunes a las 23:59. Se incluye el minuto completo de las 23:59; internamente el cierre exclusivo es la medianoche siguiente. Las fechas generales del torneo no cambian. Las bases que todavía no han activado este calendario conservan el comportamiento anterior hasta el reinicio explícito.

Al cerrar el plazo, los botones sin respuesta quedan deshabilitados, incluso si la página permanece abierta; las respuestas ya guardadas siguen disponibles en modo consulta. El servidor también rechaza envíos tardíos. El cierre del viernes o del lunes no resuelve categorías ni entrega premios: se esperan el final del periodo y la sincronización completa con el margen existente de cinco minutos.

«Las quinielas de mi equipo» permite consultar ambas selecciones, sus autores y fechas sin exponer identificadores de navegador. Administración muestra todas las quinielas antes del cierre mediante `POST /api/admin/pickem`, protegido con el PIN, con filtros de periodo y equipo y descarga CSV. El CSV usa nombres de opciones, fechas de Madrid y celdas protegidas frente a fórmulas; no incluye PIN, PUUID, cookies ni hashes de visitante.

El reinicio autorizado se aplica una sola vez con `python reset_pickem.py --target neon --apply`, después del despliegue. Sin `--apply` solo consulta el estado. Verifica que producción sirve la nueva vista, guarda una copia privada en `backups/`, reinicia únicamente Pick’em y activa el calendario; conserva equipos, partidas, inventarios y las otras funciones. Se niega a repetir el borrado si el calendario ya está activado o hay premios anteriores que requieran revisar inventarios. Para la copia local, parar primero su servidor y usar `--target local --apply`. Las pruebas `test_pickem_calendar.py` y `test_pickem_calendar_frontend.cjs` cubren plazos, cambio horario, privacidad, consulta y CSV sin modificar producción.

En todas las categorías `kind: duel`, la primera respuesta confirmada del equipo fija una única opción para sus dos quinielas. El compañero ve «Elección del equipo», con la respuesta preseleccionada y bloqueada; debe confirmarla para que cuente en su propia quiniela. El resto de categorías sigue permitiendo respuestas distintas. El servidor verifica la elección bajo el bloqueo habitual de escritura: dos navegadores que envíen opciones opuestas a la vez no pueden guardarlas ambas. Los rechazos no consumen una plaza. No se crean quinielas automáticamente ni se comparten datos entre equipos antes del cierre. Se reutilizan las respuestas persistidas, sin migraciones destructivas; si existen respuestas antiguas contradictorias, se bloquean nuevos envíos del duelo y se avisa para revisión administrativa, sin reescribir votos ni premios anteriores.

Cada quiniela con **3–4 aciertos recibe 1 pepazo** y con **5 o más recibe 2 pepazos en total**, incluso por encima del inventario normal de cinco. Con 0–2 aciertos no hay premio. Las dos quinielas del equipo se evalúan por separado y no combinan sus aciertos: pueden conseguir como máximo cuatro pepazos por periodo si ambas llegan a cinco. El cierre usa `Europe/Madrid`, incluyendo cambios de horario. La resolución espera a una sincronización de Riot completa que empiece al menos cinco minutos después del fin de la semana, sin consultas fallidas ni partidas pendientes. Se comprueban también las estadísticas de ambos integrantes; una cuenta identificada ausente de esa partida es válida. El resultado, los premios y los eventos `PICKEM_REWARD` se guardan juntos con el mecanismo de persistencia habitual (Neon en producción). `results` conserva el resultado por categoría, sin entregar premios individuales. `rewardRule` guarda los escalones 3→1 y 5→2 de cada periodo; `ballotRewards`, indexado por quiniela, conserva el total entregado y evita duplicados tras reinicios, reintentos o sincronizaciones posteriores. Si cobra uno con tres aciertos y todavía puede llegar a cinco, queda pendiente de mejora. Al confirmar el quinto acierto se entrega únicamente la diferencia de uno, con su evento independiente; nunca se entregan tres pepazos por sumar ambos escalones. Las quinielas activas sin pagos adoptan la nueva regla sin perder respuestas. Los periodos históricos que ya tenían premios guardados conservan su regla original. Los premios antiguos ya entregados se conservan sin añadir otro bajo la nueva regla. Si no hay partidas válidas no se reparten pepazos. `test_pickem.py` y `test_pickem_frontend.cjs` verifican límites, cierre, importación simulada, premios e interacción.

La quiniela incluye también «Primer equipo de la semana» y «Partida individual con mejor KDA», con desplegables de todos los equipos e integrantes. La semana abierta incorpora nuevas categorías y participantes sin borrar respuestas; las semanas cerradas conservan sus opciones. Cada navegador responde una vez por categoría dentro de su misma quiniela; los dos cupos del equipo son compartidos entre todas las categorías.

El primer equipo usa rango, división, LP y winrate, igual que la clasificación principal. `rankObservations` conserva la última observación real del ELO de cada equipo anterior al fin semanal durante las sincronizaciones existentes, para impedir que el ELO del lunes reescriba al ganador del domingo. No usa LP netos ni reconstruye rangos a partir de victorias. Si falta una observación semanal de algún equipo, queda «Sin datos suficientes» y no premia esa categoría. La mejor partida compara exactamente `(kills + assists) / max(deaths, 1)` por jugador y partida, con las mismas fechas y filtros de las otras categorías; las estadísticas incompletas dejan pendiente el resultado. Guarda la partida y K/D/A que acreditan al ganador. Los empates exactos de ELO más winrate o de KDA aceptan cualquiera de los participantes empatados. Cada categoría acertada suma un acierto a la quiniela; tres o cuatro aciertos confirmados dan un pepazo y cinco o más dan dos en total. Las categorías sin datos no suman. Si aún faltan resultados y la quiniela tiene menos de tres aciertos, queda pendiente. El listado público muestra el total de aciertos y el premio por quiniela, además del resultado de cada respuesta.

Las opciones de jugadores se vinculan a la cuenta Riot que representan; sustituir una cuenta no hereda sus pronósticos o partidas. Los identificadores de cuenta usados para verificarlo permanecen en el servidor y no se exponen en la respuesta pública de las opciones.

«Winrate negativo en las primeras cinco ranked» es una categoría única del estreno del torneo, con opciones de 0 a 9. Se añade solo a la semana que contiene el inicio del torneo y utiliza los mismos cupos y cierre; su acierto cuenta para el umbral de tres de la quiniela. Para cada equipo conserva el listado de participantes de esa categoría, recorre el historial Solo/Duo registrado desde el inicio del torneo, descarta pruebas y duplicados por `matchId`, ordena por `gameEndTimestamp` y toma las cinco primeras partidas. Cuenta al equipo si hay como máximo dos victorias (0 %, 20 % o 40 %); las posteriores no alteran el resultado. Usa los `WIN`/`LOSS` que ya guarda la importación, sin consultas nuevas a Riot ni cambios en el criterio general de partidas de dúo.

Si un equipo no ha completado cinco partidas al cerrar la semana inaugural, esta categoría sigue pendiente. Una quiniela que ya tenga tres aciertos confirmados en otras categorías puede cobrar un pepazo; si este resultado posterior eleva el total a cinco, recibe uno adicional. Si depende de esta categoría para llegar a tres, espera su resolución. Puede resolverse en una semana posterior sin reabrir las predicciones originales. Solo tras una sincronización completa posterior al final del torneo se excluyen del recuento los equipos que todavía no llegaron a cinco; si ninguno completó cinco, no se entrega premio. Los resultados desconocidos y las partidas pendientes de importar no se convierten en derrotas. El resultado guarda por equipo las cinco partidas, victorias, derrotas y winrate que lo acreditan. El valor cero es una respuesta válida y los premios conservan la protección contra duplicados.


### Pick’em: último equipo de la primera semana

`first_week_last` aparece solo en la semana inaugural y ofrece todos los equipos registrados. Se incorpora a las quinielas abiertas sin gastar otro intento. Gana el equipo con menor rango, división y LP al cierre, con menor winrate como desempate; no cuenta LP netos ni la caída desde el inicio. Los empates exactos aceptan cualquiera de los equipos empatados.

Reutiliza `rankObservations` y las sincronizaciones existentes, sin llamadas adicionales a Riot. Conserva el último ELO observado dentro de esa primera semana para que las partidas del lunes no alteren el resultado. Si falta un equipo, una observación válida o se ha sustituido su cuenta, no inventa un último puesto: queda sin datos suficientes. Se resuelve con el mismo cierre y sincronización completa que el resto de categorías semanales. Acertarla suma un acierto hacia los escalones de tres y cinco aciertos de la quiniela.


### Pick’em: mejor KDA individual acumulado de la semana

`weekly_player_kda` pregunta «¿Quién tendrá el mejor KDA de la semana?» y ofrece todos los integrantes registrados, identificados por nombre y equipo. Se repite cada semana y es independiente de `best_game_kda`, que busca la mejor partida individual. Suma asesinatos, asistencias y muertes de cada cuenta en todas sus Solo/Duo registradas de la semana y compara `(asesinatos totales + asistencias totales) / max(muertes totales, 1)`, sin promediar los KDA de las partidas ni sumar al compañero. Hace falta al menos una partida válida; los empates se comparan con fracciones exactas y aceptan a todos los empatados.

Reutiliza los datos de Riot existentes, con límites semanales y del torneo en hora de Madrid, exclusión de pruebas y otras colas, deduplicación por partida y participante, y vinculación a la cuenta original. Los datos incompletos o importaciones pendientes retrasan la resolución, mientras que una ausencia confirmada de la partida es válida. El resultado conserva las partidas y K/D/A acumulados del ganador. Acertar suma una categoría a los escalones de tres y cinco aciertos de la quiniela; la categoría no tiene premio independiente. La categoría se añade a la semana abierta sin borrar respuestas ni consumir otro cupo y no se inserta en semanas ya cerradas. `test_weekly_player_kda.py` verifica el cálculo, identidades, privacidad, premios e incorporación; las pruebas de navegador verifican el desplegable con 18 integrantes.

### Pick’em: primer pepazo individual del torneo

La categoría `first_individual_shell` aparece solo en la semana inaugural, con todos los integrantes registrados (18 con los nueve equipos actuales). Cada opción identifica a la persona y su equipo; conserva la cuenta de Riot y el PUUID para impedir que una sustitución herede su predicción. El resultado se resuelve tras el cierre y una sincronización completa, usando la primera **partida finalizada** del torneo en la que un participante activo cumpla pentakill (`pentaKills > 0` o `largestMultiKill >= 5`), al menos 20 kills, al menos 30 asistencias o 0 muertes con kills + asistencias estrictamente mayores que 20. No exige victoria ni suma estadísticas entre compañeros. No intervienen rachas, clips, Pick’em ni el orden de importación. Se evalúa el logro aunque el inventario esté lleno o el límite por partida impida otro ingreso. `shell_rules.py` comparte los criterios y umbrales con las recompensas normales.

Se excluyen pruebas, otras colas y partidas fuera del torneo; los pendientes de importar o las estadísticas incompletas anteriores al primer logro impiden resolver prematuramente. Si varios participantes lo consiguen en la misma partida, o en partidas con idéntica hora de finalización, todas sus opciones son válidas: los datos finales no permiten establecer el instante exacto de cada logro dentro de la partida. El resultado conserva jugador, partida, fecha, criterios activados y K/D/A como evidencia. Solo suma un acierto a la quiniela: tres o cuatro aciertos dan un pepazo y cinco o más dan dos en total.

Si nadie lo consigue en la primera semana, permanece pendiente y puede resolverse después, conservando las predicciones originales. Solo una sincronización completa posterior al final del torneo puede cerrar la categoría sin aciertos si nadie logró un criterio. Se guardan `pentaKills` y `largestMultiKill` individualmente al importar las partidas. Los historiales antiguos con `pentaKill: true` y sin detalle por persona se completan mediante el backfill existente; un indicador global del dúo no se atribuye arbitrariamente a ninguno de sus miembros. Los partidos antiguos sin pentakill confirmada (`pentaKill: false`) no requieren nuevas consultas para este dato.


### Pick’em: Joji vs. Parradise, muertes de la primera semana

`joji_parradise_deaths` es un evento único de la semana inaugural. Ofrece solo «Joji» y «Parradise» y vincula cada nombre con el integrante identificado por su nombre público, guardando equipo, cuenta de Riot y PUUID. La vinculación se conserva aunque después se edite el perfil, para no trasladar predicciones a otro jugador. Si falta un nombre o hay duplicados, su opción queda deshabilitada hasta poder identificarlo sin ambigüedad.

Tras el cierre y una sincronización completa, suma `player1Stats.deaths` o `player2Stats.deaths` de cada participante, según su identidad, en las Solo/Duo registradas desde el inicio del torneo hasta el final de su primera semana (hora de Madrid y `gameEndTimestamp`). No suma las muertes del compañero ni usa medias o KDA. Descarta pruebas, otras colas, duplicados por `matchId` y partidas fuera del periodo. Las importaciones o estadísticas pendientes retrasan el resultado; una ausencia confirmada no se convierte en una partida de cero muertes. Gana quien acumule más; un empate con partidas válidas acepta ambas opciones. Sin partidas de ninguno, no hay acierto. El resultado conserva totales de muertes, número de partidas y evidencia por partida; las semanas posteriores no lo modifican. Acertar este evento suma un acierto hacia el mínimo de tres de la quiniela, sin premio independiente.


### Porra de clasificación final

`porra.html`, junto a Tierlist en la navegación, permite ordenar a todos los equipos del primero al último con un podio de tres puestos, arrastre con ratón y botones de subir/bajar accesibles en móvil y con teclado. El borrador y la firma opcional se conservan en `localStorage`; la publicación requiere la sesión del equipo y guarda el orden completo, autor, equipo publicador y fecha de servidor. Cada publicación muestra fecha y hora de Madrid de forma permanente. **No hay cierre temporal:** se permite publicar antes, durante y después del torneo. Los pronósticos publicados son definitivos y públicos. Hay dos por equipo y uno por navegador, con cookie propia y cupos independientes de Tierlist; reintentar el mismo envío no gasta otro cupo.

`GET/POST /api/final-predictions` usa `final_predictions.py` y conserva `finalPredictions` dentro del mismo documento de Neon, sin borrar equipos, tierlists ni quinielas semanales. La galería muestra seis pronósticos por página, del más reciente al más antiguo. Los identificadores de visitante se guardan como hash y nunca se publican. El servidor valida el equipo de la sesión, el origen de la petición, los cupos y que aparezcan todos los equipos exactamente una vez; fecha, equipo y puntuación no se aceptan del cliente.

Al congelarse los trofeos al finalizar el torneo, la porra copia el orden completo de la clasificación oficial (`awardedTrophies`, tarjeta `champion`) y lo mantiene fijo. Se usa el mismo orden de puestos que esa clasificación, incluidos sus desempates, sin calcular otro ranking ni consultar Riot de nuevo. Cada equipo situado en el puesto exacto cuenta como un acierto. El detalle compara el puesto previsto con el real y muestra el total; no otorga pepazos ni cambia inventarios. Una publicación posterior al final se compara inmediatamente y sigue mostrando su fecha real. Si cambia el listado de equipos y no coincide con el pronóstico guardado, se indica que no es comparable, sin inventar resultados. La conservación de la clasificación y las publicaciones sobrevive a reinicios.

`test_final_predictions.py`, `test_porra_frontend.cjs` y `test_navigation_frontend.cjs` verifican persistencia, permisos, cupos concurrentes, reintentos, independencia de Tierlist, ausencia de límites temporales, comparación final, borradores, arrastre, paginación, fechas, XSS y pantallas móviles.


### Varias cuentas de LoL por integrante

En administración, dentro de cada equipo, «Cuentas de LoL» permite añadir cuentas a cada integrante y marcar una para su ELO. Guarda con «Guardar integrantes y cuentas». Con una sola cuenta se utiliza esa automáticamente; no es necesario editar los equipos existentes. Las cuentas guardadas se conservan para mantener la atribución histórica.

Todas las cuentas registradas del equipo con varias fuentes aportan partidas Solo/Duo al mismo historial, sin duplicados por `matchId`; se mantienen las exclusiones de duración y las reglas que requieren que estén ambos integrantes. Las estadísticas, campeones, rachas, logros, castigos y opciones individuales de Pick’em pertenecen a la persona. Cada partida conserva la cuenta utilizada. Las importaciones son incrementales por cuenta, con reintento persistente de detalles pendientes y un presupuesto compartido de 40 detalles por equipo y sincronización.

Cada cuenta mantiene su rango, historial de ELO y referencia de Flash. El rango público del integrante y su gráfica utilizan la cuenta seleccionada; la clasificación del equipo continúa utilizando al primer integrante. Cambiar la selección restaura la gráfica de esa cuenta, sin unir rangos de cuentas distintas. El progreso parte de la referencia propia de la cuenta elegida, conservando la referencia original de los equipos existentes.

Añadir una fuente importa también su historial disponible con los filtros existentes. Los resultados ya resueltos de Pick’em y los premios concedidos se conservan; los resúmenes archivados existentes mantienen los datos anteriores a la incorporación de nuevas fuentes o cambios de cuenta de ELO posteriores a su cierre. Las sincronizaciones descartan resultados de un equipo si su configuración de cuentas cambia durante las consultas.


### Limpieza selectiva de partidas anteriores al torneo

`repair_riot_history.py --target neon --team-id ID` simula la retirada de partidas anteriores al 15 de octubre de 2026, sin guardar cambios. Con `--apply`, crea primero una copia privada en `backups/` y guarda usando la revisión de Neon para no sobrescribir operaciones concurrentes. También admite `--target local` con el servidor local detenido.

Solo se limpia el equipo indicado: conserva partidas válidas y sus marcas de premios, cuentas, ELO, inventario, castigos, quinielas y otros equipos. Recalcula rachas y estadísticas derivadas, y deja los IDs retirados en `excludedRiotMatches` para impedir que vuelvan a entrar, incluso desde una sincronización ya iniciada. No elimina partidas de prueba ni filas sin fecha fiable. Si las partidas retiradas tienen premios registrados o resolvieron un castigo, se detiene para revisar esa situación, sin modificar inventarios automáticamente.


### Evolución individual de estadísticas

Debajo del salón de la fama y la vergüenza, la tarjeta «Evolución individual» alterna entre kills, asistencias y muertes acumuladas. Cada integrante tiene una línea y un color compartido entre las tres vistas. El eje X cuenta sus propias partidas en orden de finalización; el eje Y suma la estadística hasta esa partida. Las cuentas de una misma persona aportan a su única línea, independientemente de la cuenta elegida para ELO.

La leyenda permite resaltar o fijar un integrante; al pasar por una línea se muestran nombre, equipo, partida y total. Incluye navegación con teclado y desplazamiento horizontal de la gráfica en móvil. Los integrantes sin partidas permanecen en la leyenda.

`GET /api/stats/progression` calcula las tres series a partir del historial guardado, sin consultar Riot ni modificar datos. Excluye pruebas, duplicados, otras colas, partidas anteriores al 15 de octubre de 2026, partidas cortas y resultados posteriores al cierre del torneo. Las estadísticas incompletas se indican como pendientes y no se convierten en ceros. Reutiliza la actualización de la portada cada 15 segundos; cambiar de métrica no solicita datos y un fallo de conexión conserva la última lectura confirmada. `test_stat_progression.py` y `test_stat_progression_frontend.cjs` verifican acumulados, identidades, filtros, privacidad e interacción.


### W/L del historial del challenge

La barra pública de W/L, su porcentaje, la ordenación por winrate o partidas y el contador de partidas de portada usan `tournamentRecord`, calculado desde el historial válido del equipo. Cada `matchId` cuenta una vez aunque proceda de varias cuentas; se excluyen pruebas, otras colas, partidas cortas, exclusiones y partidas anteriores al 15 de octubre. Sin resultados registrados muestra 0W / 0L. Los resultados pendientes no cuentan como derrotas. Se calcula al leer, sin reparar datos guardados ni consultar Riot. Los totales oficiales de temporada permanecen en el rango de las cuentas y en los campos internos usados por el desempate de la clasificación.


### Corrección del primer cierre de clips

`repair_clip_calendar.py --recovery backups/COPIA.json` comprueba sin guardar la recuperación de la ronda cortada el 18 de octubre. Valida el premio, el inventario disponible, el clip ganador y los totales de publicaciones y votos contra el resumen archivado. `--apply` crea una copia privada en `backups/` y guarda en Neon con control de revisión: retira exactamente los tres pepazos del premio adelantado, reduce su contador de premios de clips, marca el premio anterior como `REVOKED`, corrige su evento y el ganador del resumen y recupera el tablero completo en un archivo. No borra el registro que impide volver a entregar el premio antiguo. Repetir la corrección no vuelve a descontar.

Al cargar el nuevo código, `clipsCalendarVersion=2` reúne los tableros recuperados de la primera ronda con cualquier publicación posterior, conserva IDs y votos y utiliza el cierre correcto. El tablero activo prevalece si se repite un ID. La primera ronda puede recibir su premio definitivo al cerrar el 25. `test_clip_calendar.py`, `test_clips_archive_frontend.cjs` y las regresiones existentes verifican calendario, cambio horario, idempotencia, recuperación, privacidad, archivo, rechazo de votos tardíos y móvil.


### Apuestas con oro virtual por equipo

`apuestas.html` añade una pestaña pública entre Clips y Pick’em. Crear o participar requiere la sesión de «Mi Panel»; el oro pertenece al equipo y ambos integrantes comparten el saldo. Cada equipo recibe **10 monedas iniciales una sola vez** al activar la función o incorporarse al torneo, y **10 monedas cada día a las 23:59 de Madrid**. La fecha inicial y el siguiente reparto pendiente se guardan por equipo; un reinicio o una lectura repetida no duplican el ingreso. Si Render duerme, al despertar recupera los días debidos desde la activación, sin conceder días anteriores. Usa el mantenimiento y el programador existentes. El oro, su inventario reservado y su contabilidad viven en `betting`, separados de los pepazos.

El formulario permite win/lose (solo equipo y oro, creando el lado WIN), kills, muertes o asistencias. Las estadísticas individuales piden equipo, integrante, línea y más/menos. La línea admite cifras de **0,5 a 49,5** terminadas en medio punto, con placeholder `5,5`; el servidor valida también el rango, el formato, el integrante y las monedas enteras positivas. Las cuentas vinculadas aportan al integrante elegido. Una sustitución del integrante o la eliminación del equipo objetivo devuelve el oro pendiente.

Cada confirmación reserva el oro inmediatamente y registra su propia espera de **20 minutos**. Cuenta la primera partida nueva y válida incorporada al historial del servidor después de esa espera; exactamente 20 minutos sí cuenta. El registro persistente de recepción por equipo y `matchId` impide que duplicados, reintentos o enriquecimientos reinicien la hora. Las partidas ya existentes al crear la apuesta no pueden resolverla. Si llegan varias a la vez, se ordenan por finalización e ID. Se excluyen pruebas, otras colas, partidas cortas, exclusiones y partidas anteriores al corte del challenge. Una ausencia confirmada pasa a la siguiente partida; las estadísticas incompletas esperan evidencia sin inventar ceros ni saltar a un resultado posterior.

Los mercados agrupan condiciones iguales, pero **cada partida forma su propio bote** con las apuestas cuya espera ya se había cumplido al recibirse. Las más recientes quedan pendientes para otra partida. Las aportaciones elegibles se emparejan **1 a 1 por orden de llegada** entre los dos lados de esa misma partida, conservando el orden persistido si coinciden sus fechas. Solo se arriesga el oro con contrapartida; el sobrante se devuelve al resolver. Con 10 contra 1 se juegan 1 por lado y se devuelven 9: el ganador del par cobra 2, recuperando 1 y ganando 1. Se permite aportar desde 1 moneda. No hay comisión; todo el oro queda en pagos o devoluciones enteros. Las rondas guardan el importe reservado, el bote realmente emparejado, los pares y las devoluciones; cada aportación conserva su parte emparejada, devolución, cobro y beneficio neto. Los pares y los identificadores de apuestas ajenas permanecen privados. Las rondas ya liquidadas con la regla anterior conservan sus importes; las aportaciones pendientes adoptan la nueva liquidación al desplegar. Los importes de los botones muestran oro pendiente, no una ganancia garantizada. El historial conserva recepción, partida, resultado, bote y cobros propios.

`GET /api/bets?view=open|history&offset=0&limit=12` ofrece el mercado paginado y, con sesión, el saldo y apuestas del equipo. `POST /api/bets` admite `action=create|join` y un `requestId`; repetir un mismo envío devuelve la misma apuesta sin otro descuento, y reutilizarlo con otros datos se rechaza. El servidor obtiene al propietario de la sesión, comprueba el origen, valida el saldo y guarda apuesta, reserva, resultado e ingresos dentro de la misma operación de almacenamiento, con el bloqueo local y el control de revisión de Neon. Las consultas no exponen credenciales, PUUIDs ni la contabilidad privada de otros equipos. No se añaden consultas a Riot. `test_betting.py` y `test_betting_frontend.cjs` verifican conservación del oro, reloj, cambio de hora, varias cuentas, privacidad, concurrencia, fallos de guardado, formulario, reintentos y móvil.

## Tienda: El Chiringuito de Pepe

`tienda.html` intercambia el oro compartido de Apuestas por pepazos a **70 monedas por unidad**. La navegación conserva su estilo; la ilustración de la Grieta, la tipografía del tendero, las luces, partículas y animaciones de compra se limitan a esta página mediante `tienda.css`. Las imágenes originales generadas para la tienda se sirven localmente como WebP (unos 408 KiB entre ambas); no hay vídeo, consultas externas de imágenes ni dependencia de un servicio de generación en ejecución. [Dirección artística y prompts](assets/shop/art-direction.md).

`GET /api/shop` publica el producto y su precio; con la sesión de Mi Panel devuelve únicamente el saldo disponible, oro reservado en apuestas e inventario del equipo autenticado. `POST /api/shop` acepta `quantity` entero positivo y `requestId` de 16–80 caracteres alfanuméricos, guion o guion bajo. El servidor decide el precio y el propietario, valida el origen y descuenta el oro disponible mientras suma `blueShells`, registra `shellsPurchasedTotal`, un justificante en `shop.purchases` y una entrada negativa `SHOP_PURCHASE` en la misma contabilidad `betting.ledger`. Se usa el bloqueo y la escritura atómica/optimista existentes. No se puede gastar el oro ya reservado en apuestas. La compra suma al inventario, como los premios especiales; el límite de 5 para recompensas de partidas no borra ni limita los pepazos comprados. No se modifica `shellsEarnedTotal`, los criterios de premios ni el lanzamiento de pepazos.

Repetir un `requestId` con la misma cantidad devuelve el justificante original sin otro cargo; reutilizarlo con otra cantidad devuelve 409. La interfaz confirma cantidad e importe, bloquea dobles envíos y conserva una compra pendiente en `sessionStorage`, separada por equipo, para poder comprobarla incluso tras recargar si se pierde la respuesta. Con saldo sin confirmar no permite nuevas compras. El modo de movimiento reducido desactiva las animaciones y partículas. `test_shop.py`, `test_shop_frontend.cjs` y la navegación cubren precio, sesión, inventario utilizable, compras simultáneas, reintentos, fallos de guardado, saldo compartido, móvil y accesibilidad de los controles.

Pepe dispone de 52 frases generales, incluido el monólogo largo proporcionado por Luis, en texto plano sin hiperenlaces. Al arrancar cada despliegue o reiniciar el servidor, `shop_service.QUOTE_SEED` genera una semilla pública nueva que `/api/shop` devuelve como `quoteSeed`. La interfaz baraja el repertorio con esa semilla: mantiene el orden durante las consultas y recargas de la misma versión, recorre todas las frases antes de repetir y cambia de orden en el siguiente arranque. Los comentarios de saldo insuficiente y compra confirmada conservan sus condiciones. Un clic o toque en cualquier punto de la imagen de la tienda, incluido el bocadillo, pasa a la siguiente frase. El bocadillo solo muestra el texto, sin enlaces de conversación. El monólogo amplía el bocadillo dentro de la escena y permite desplazamiento con teclado; el botón invisible de toda la imagen también se activa con Enter o espacio. Los controles de compra quedan fuera de esa zona y conservan su comportamiento. No requiere ejecutar pasos manuales de mezcla al desplegar.
