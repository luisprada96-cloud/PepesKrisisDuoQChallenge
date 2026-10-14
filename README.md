# 🏆 Pepes Krisis Duo Q Challenge

Una aplicación web interactiva para torneos de League of Legends inspirada en la mecánica del **Caparazón Azul de Mario Kart**. 

Permite seguir en tiempo real la clasificación de varios dúos en Ranked Solo/Duo mediante sincronización automática con la **Riot Games API**, recompensando rachas de victorias y Pentakills con "Caparazones Azules" para imponer debuffs o penaltis a los equipos rivales.

---

## ✨ Características Principales

- **⏳ Calendario oficial (hora de Madrid)**: inicio el 15/10/2026 a las 18:00 y cierre el 15/11/2026 a las 23:59. La cuenta atrás de portada cambia automáticamente de inicio a cierre y después muestra el torneo finalizado. Las fechas se guardan con zona horaria explícita, incluyendo el cambio de horario de octubre; el formulario de administración siempre muestra y recibe horas de Madrid.

- **🎮 Sincronización en Tiempo Real con Riot API**: Seguimiento automático de Elo, Tier, División, LP, Victorias, Derrotas y Racha activa cada 5 minutos.
- **🐢 Sistema de Caparazones Azules**:
  - Cada bloque de 4 victorias consecutivas, pentakill, al menos 20 kills, al menos 30 asistencias o 0 muertes con más de 20 kills + asistencias otorga 1 caparazón. Los logros individuales no exigen victoria y no suman estadísticas entre jugadores.
  - Cada criterio se premia una vez por equipo y partida, con un máximo de 2 premios por partida (incluida la racha) y 5 caparazones en inventario. Los excedentes se pierden. Se priorizan racha, pentakill, kills, asistencias y KDA perfecto.
  - Los nuevos criterios se aplican a partidas incorporadas tras la migración; se conservan premios y marcas anteriores. El registro por partida evita duplicados al recalcular o completar estadísticas.
  - La tabla pública de requisitos utiliza las mismas constantes del servidor mediante `/api/config`.
  - Los equipos pueden lanzar caparazones contra sus rivales para imponer castigos aleatorios (*Sin Flash*, *Autofill*, etc.).
- **📊 Historial de Partidas Ordenado Cronológicamente**: Muestra los campeones jugados, KDA, duración y ganancia/pérdida de LP de cada partida.
- **🔐 Panel de Jugador & Panel de Administración**: Interfaz protegida para que los jugadores gestionen su inventario de caparazones y los administradores configuren el torneo.
- **🖼️ Avatares de Invocador Dinámicos**: Carga de iconos oficiales de LoL mediante Data Dragon CDN (v15.3.1).
- **🟣 Estado de Twitch**: Enlace individual por integrante y detección automática de emisiones en directo cada 5 minutos.

---

## 🚀 Estructura del Proyecto

- `index.html` / `app.js` — Página principal del ranking y modal de historial.
- `player.html` / `player.js` — Panel de control del jugador (gestión de caparazones y ataques).
- `admin.html` / `admin.js` — Panel de administración protegidos por PIN.
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

`discordLiveNotifications` guarda en la misma base (Neon en producción) el último identificador de directo y estado de envío por canal. Dos integrantes con canales distintos generan avisos independientes; compartir un canal no duplica el mensaje. Un directo confirmado no vuelve a anunciarse tras un reinicio o una interrupción de Twitch. Se procesan hasta cinco avisos por ciclo. Los errores de Discord no afectan al estado de Twitch: los pendientes se reintentan en ciclos posteriores respetando el tiempo de espera, solo mientras ese directo siga activo y su canal siga vinculado al equipo. Si se pierde una respuesta después de que Discord publique el mensaje, un reintento puede duplicarlo: el webhook no ofrece entrega exactamente una vez.

El panel de administración muestra el último envío confirmado y los errores, sin mostrar la URL privada. Los mensajes desactivan las menciones automáticas, incluido `@everyone`. No hace falta bot, EventSub ni otro proveedor de alojamiento.

Los avisos mantienen el enlace de Twitch clicable y desactivan su vista previa automática mediante `SUPPRESS_EMBEDS` de Discord. Este formato se aplica a los mensajes nuevos; los enviados anteriormente conservan su aspecto.

**Probar aviso de Discord**, en administración, envía un mensaje identificado como prueba mediante `POST /api/discord/test`, protegido con el PIN administrativo. No simula un directo ni cambia el registro de notificaciones del torneo.

## 🔐 Credenciales de producción

El PIN de administración y las contraseñas de los equipos se almacenan como hashes PBKDF2. Las claves de API no se guardan en `db.json`.

En Render configura estas variables de entorno:

- `RIOT_API_KEY`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

En local, las claves introducidas desde el panel de administración se guardan en `secrets.json`, que está excluido de Git.

---

## Tierlists de los equipos

`tierlist.html` permite clasificar los nueve equipos en S/A/B/C/D usando las imágenes originales de `assets/tierlist/`. Admite arrastrar, seleccionar un equipo y pulsar su fila, y mover con el teclado. El borrador y el autor opcional se recuerdan en ese navegador. Publicar requiere sesión de equipo, los nueve equipos colocados exactamente una vez y un autor de hasta 60 caracteres si se indica. Las listas publicadas son definitivas.

Las publicaciones se guardan en `tierlists` dentro de la misma base (`db.json` en local, Neon en producción), con equipo autor, nombre opcional, fecha, filas y orden. Son públicas, conservan el nombre del equipo al publicar y no participan en la limpieza semanal de clips. La galería muestra seis por página y permite ampliar cada tablero. Sin nombre opcional, el título utiliza el equipo.

`GET /api/tierlists?offset=0&limit=6` devuelve catálogo, publicaciones y estado para publicar; crea la cookie HttpOnly `pepes_tierlist_visitor`. `POST /api/tierlists` exige sesión Bearer y esa cookie, comprueba el origen y guarda todo en la mutación serializada existente. El servidor limita a dos publicaciones por equipo y una por navegador, incluso cambiando de equipo en ese navegador. Solo se guarda el hash del identificador de navegador y nunca se expone en las respuestas públicas. Cambiar o borrar cookies puede ocupar la segunda plaza del equipo, pero no permite superar el límite de dos. Un fallo al guardar o una lista incompleta no consume plaza.

## Fiabilidad y operación

`POST /api/admin/check-apis`, con `authPin`, verifica las credenciales actuales desde el servidor sin necesitar equipos: consulta `lol-status-v4` de Riot y obtiene un token nuevo de Twitch para consultar `helix/streams`. Solo devuelve resultado, fecha y códigos HTTP; nunca claves, secretos o tokens. Una respuesta válida de Riot actualiza la última llamada API OK. No crea partidas, equipos ni avisos de Discord.

La aplicación sirve el frontend y la API desde el mismo origen. Solo los archivos públicos de la interfaz se pueden descargar; la base de datos, copias, secretos y código Python nunca se sirven por HTTP.

- Las operaciones manuales de Riot, Twitch y cálculo de caparazones requieren el PIN administrativo. Riot y Twitch responden `202` y trabajan en segundo plano; `/api/sync/status` informa de ejecución, errores, última finalización correcta y trabajo pendiente. Ese estado operativo se reinicia al arrancar el proceso.
- Los paneles conservan en memoria los últimos datos confirmados cuando falla una lectura, muestran la desconexión y no guardan modificaciones locales como si hubieran llegado al servidor.
- `/api/duos` devuelve un resumen sin historial. `/api/duos/{id}/history?offset=0&limit=30` permite recorrerlo completo. Los eventos también admiten `offset` y `limit`; el límite máximo de página es 100.
- Las consultas no conceden recompensas. Las sincronizaciones y el cálculo administrativo las guardan de forma persistente. Se mantienen las reglas actuales de recompensas y la importación basada en el jugador 1.
- Los castigos necesitan evidencia válida y una partida iniciada después de su asignación. Reabrir un castigo conserva la corrección y descarta la partida que lo había completado automáticamente.

### Avisos personales de caparazones

Los participantes se identifican con las credenciales existentes en Mi Panel. En la clasificación y el panel aparece una barra personal para activar o silenciar el sonido, probarlo y cerrar sesión. La preferencia y los identificadores ya anunciados se guardan en `sessionStorage`, por pestaña y equipo; activar un aviso no cambia la preferencia del compañero ni muestra el estado públicamente.

`GET /api/player/events` abre un canal SSE autenticado mediante `Authorization: Bearer ...`. Envía solo los caparazones pendientes del equipo de esa sesión. Un lanzamiento guardado despierta las conexiones inmediatamente, sin consultas adicionales a Riot. La conexión se reintenta si se interrumpe; las sesiones caducadas o cerradas se desconectan. No se registra una lista pública de presencia.

El audio de `alerts.js` se sintetiza con Web Audio: unos ocho segundos de alarma acelerada y una explosión corta, con volumen reforzado. Requiere activar el sonido con un clic; si el navegador suspende el audio, la barra vuelve a ofrecer activarlo. Funciona también en segundo plano mientras el navegador mantenga la pestaña activa internamente. Una pestaña cerrada, suspendida o un dispositivo dormido no pueden garantizar avisos. Los caparazones que ya estaban pendientes al abrir la página se muestran sin volver a sonar.

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

El panel público `torneo.html`, accesible como «Torneo y premios» desde la navegación superior, reúne reglas, ruleta, requisitos de caparazones y trofeos. `torneo.js` actualiza estos datos cada 15 segundos; el principal conserva la clasificación y las estadísticas. Los avisos personales también funcionan en el panel nuevo.

### Evolución de ELO

El desplegable de cada dúo muestra la evolución diaria del ELO de ambos integrantes: amarillo para `player1`, verde discontinuo para `player2`, con leyenda y detalles al pasar, enfocar o tocar cada punto. Cada jugador guarda su propio `eloHistory` y `eloHistoryAccount`, con el último rango observado de cada día (fecha local del servidor), LP y victorias/derrotas si están disponibles. El historial antiguo del dúo se conserva para el primer jugador; el segundo empieza con su primer rango confirmado. No se reconstruyen LP anteriores a partir de victorias o derrotas. Cambiar una cuenta reinicia solamente su historial. Con un solo registro se muestra un punto, no una curva inventada. El `eloHistory` antiguo del dúo sigue manteniéndose por compatibilidad.

Docker incluye `seed-db.json`, una semilla vacía sin equipos ni credenciales, inaccesible desde HTTP. Solo se usa si no existe la base de datos local en `PEPES_DATA_DIR`; nunca sustituye datos existentes. `db.json` y `secrets.json` contienen los datos privados locales y no se versionan. En modo local se necesita almacenamiento persistente para conservar modificaciones entre despliegues; en producción esa persistencia la proporciona Neon.

### Neon (PostgreSQL)

Producción puede usar `PEPES_STORAGE=neon` y `DATABASE_URL` como variable privada de Render. El estado JSON se guarda en `tournament_state` con control de revisión y copia anterior; un conflicto nunca sobrescribe otra operación. No hay restauración automática de seed-db.json cuando Neon falla. El modo local continúa usando db.json. Consulta `NEON_SETUP.md` para importar una copia validada y cambiar el servicio sin perder avances.


### Clips semanales y likes por equipo

`clips.html` muestra vídeos grandes con ordenación por likes o fecha. Las publicaciones y los votos se guardan en el campo `clips` de la base existente: `db.json` en local y Neon en producción. No se almacenan vídeos, solo enlaces de clips de Twitch.

Los clips se pueden consultar sin sesión. Para votar se utiliza la sesión de «Mi Panel», guardada en `sessionStorage` y enviada en la cabecera `Authorization: Bearer`. El servidor obtiene el equipo de esa sesión; nunca confía en un `teamId` enviado para votar. La cookie `pepes_clips_visitor` identifica el navegador (`HttpOnly`, `SameSite=Lax`, un año; `Secure` detrás de HTTPS). Su hash se guarda en `teamVotes: {teamId: [browserHash, ...]}` por publicación.

`POST /api/clips/like` recibe `clipId` y el estado booleano `liked`. Un clic añade el like del navegador y otro lo retira; repetir la misma petición es idempotente. El servidor admite un voto por navegador y clip, y como máximo dos votos por equipo y clip entre todos sus navegadores. Cambiar de equipo en el mismo navegador no duplica el voto. Retirar un like solo afecta al voto identificado por esa cookie. Sin sesión válida no se pueden modificar likes. La API devuelve el total, el estado del like del navegador y el equipo autenticado; no publica los identificadores ni el contador de votos del equipo. La interfaz no muestra el límite interno ni botones adicionales. Los errores de almacenamiento no se presentan como votos confirmados y se consultan los totales cada cinco segundos mientras la pestaña está visible.

Los votos anónimos anteriores se conservan hasta cerrar y renovar su semana. Los contadores compartidos anteriores sin identidad de navegador mantienen sus votos reservados; los primeros navegadores del equipo que votan los reclaman sin incrementar el total. `clip_votes.py` calcula un único total para la interfaz, el premio y el resumen semanal. Al reiniciar el servidor hay que volver a iniciar sesión, pero los votos persistidos y la cookie se mantienen. Publicar clips y marcar vistos siguen disponibles sin sesión; los vistos permanecen exclusivamente en `localStorage`.

El listado muestra como máximo 15 clips por página, con controles anterior/siguiente arriba y abajo. Cambiar de filtro o publicar vuelve a la primera página; las actualizaciones mantienen la página actual mientras siga existiendo. El orden se calcula al cargar, cambiar de filtro o publicar. Dar/quitar likes y las consultas automáticas actualizan los contadores conservando las posiciones y los reproductores. Los clips nuevos recibidos durante una consulta automática se añaden al final hasta la siguiente ordenación.

El ojo en la esquina superior derecha marca o desmarca un clip como visto, sin requerir sesión ni enviar cambios al servidor. La pestaña «No vistos» filtra los pendientes y los ordena del más reciente al más antiguo. Las marcas se guardan en `localStorage` bajo `pepes_clips_seen`, para este navegador y la semana actual. Se conservan al cerrar/reabrir, se actualizan entre pestañas y se descartan para una nueva semana. Los clips vistos siguen disponibles en «Recientes» y «Más votados»; reproducir un vídeo no lo marca automáticamente. `test_clips_frontend.cjs` verifica paginación, persistencia, filtros, reducción de páginas y compatibilidad con likes/publicaciones.

La semana empieza el lunes a las 00:00 en `Europe/Madrid`, incluidos los cambios de horario de verano. Los clips y votos anteriores se eliminan al cambiar de semana, mediante el programador o al recibir una consulta/publicación, incluso después de que Render haya estado dormido. Antes se liquida cualquier premio pendiente. `PEPES_CLIPS_PREVIEW=1` habilita tres publicaciones de ejemplo con contadores reales que empiezan en cero, únicamente con almacenamiento local. Producción no crea ejemplos.

Cada publicación exige `teamId`, elegido en el formulario entre equipos existentes. El servidor guarda ese ID y el nombre del equipo, sin aceptar un nombre arbitrario enviado por el navegador. Los clips antiguos sin equipo y los ejemplos siguen visibles, pero no compiten por premios.

La votación cierra el domingo a las 23:59:00, hora de Madrid; durante el último minuto no se puede publicar ni cambiar likes. El clip elegible con más likes recibe un premio de 3 caparazones para su equipo; los empates se resuelven por fecha de publicación más antigua y, si también coincide, por ID. Hace falta al menos un like y un equipo existente. Este premio incrementa directamente `blueShells` y puede superar el límite normal de 5; las recompensas de partidas mantienen su límite y no recortan inventarios mayores.

`clipWeeklyRewards`, indexado por lunes de la semana, guarda ganador, equipo, votos, fecha prevista de cierre, fecha real de liquidación y cantidad. Inventario, resultado y evento se guardan juntos en la misma operación de almacenamiento. El programador calcula el siguiente cierre, y el arranque y las lecturas recuperan premios vencidos antes de limpiar clips. Si el servicio está dormido, la entrega física se realiza al reactivarse; los votos posteriores al cierre se rechazan. El registro por semana impide duplicados por reinicios, peticiones simultáneas o reintentos. La página muestra el resultado actual y el de la semana anterior sin exponer los identificadores de votantes.


### Ruleta en ventana para stream

Al pulsar «Girar ruleta» en el panel del jugador se solicita una ventana emergente de 680 × 460 con la ruleta, el equipo y el resultado. El panel mantiene su ruleta y la espera de 13,5 segundos tras revelar el castigo. La ventana conserva el resultado hasta el siguiente giro y puede moverse o redimensionarse para capturarla en OBS.

Ambas vistas animan el único resultado devuelto por `/api/player/spin-shell`, con el mismo instante de inicio. La ventana de stream no llama a la API ni necesita sesión de equipo. Los mensajes verifican origen, ventana emisora y canal; al cargar o reabrir se recupera el estado actual sin sortear otra vez. Una vez cargada, puede terminar la animación aunque se cierre el panel.

Si el navegador bloquea la apertura, la ruleta del panel continúa y aparece «Abrir ruleta para stream» para reintentarlo tras permitir ventanas emergentes. La ventana se reutiliza en los siguientes giros. `test_roulette_frontend.cjs` verifica estos casos con Playwright y Chrome, incluido el tiempo de revelación y la espera del resultado.


### Rango de cada integrante en la clasificación

La tabla principal muestra «Integrante 1» e «Integrante 2» con su rango Solo/Duo y LP actuales, sin LP netos en la fila. Riot confirma cada rango por separado y se guarda en `player1.rank` y `player2.rank` (`tier`, `division`, `lp`, `observedAt`). Los errores conservan el último rango confirmado; una respuesta correcta sin entrada Solo/Duo muestra «Sin clasificar». Hasta la primera consulta del segundo integrante se muestra «Pendiente». Las bases anteriores reutilizan el rango del dúo únicamente para el primer integrante. Cambiar la cuenta en administración invalida su rango individual.

La clasificación, winrate y evolución de ELO del dúo mantienen el cálculo existente a partir del jugador 1. En pantallas estrechas la tabla permite desplazamiento horizontal para consultar ambos integrantes.

### Nombres y Twitch de los participantes

Cada integrante guarda `displayName` (nombre visible, independiente del Riot ID), `twitchUrl` (opcional) y `twitchIsLive` (confirmado por Twitch). Administración permite introducirlos al crear un dúo y editar ambos perfiles en los equipos existentes. En la clasificación se muestra el nombre encima de su rango y su enlace de Twitch debajo; el botón rojo indica que ese integrante está en directo. El contador de equipos en directo cuenta un equipo si al menos uno de sus integrantes emite.

Los enlaces antiguos del equipo se reutilizan únicamente para el primer integrante hasta que se editen. Guardar un enlace individual vacío elimina su botón, incluso si existe un enlace antiguo. La sincronización consulta los dos canales y conserva el estado confirmado cuando Twitch falla. Cambiar estos perfiles no borra los rangos, historiales de ELO, partidas, castigos ni caparazones.

Las tarjetas inferiores muestran el Riot ID, KDA global individual `(asesinatos + asistencias) / max(1, muertes)`, rol principal configurado y campeón más jugado de las partidas registradas. Si faltan estadísticas se muestra «—» en KDA y «Sin datos» en el campeón.

### Castigos individuales: destinatario 50/50

Al abrir un nuevo castigo con `scope: ONE`, el servidor sortea una sola vez entre `player1` y `player2`, con igual probabilidad e independientemente del sorteo del castigo. `requirements.assignedPlayer` guarda el integrante; `assignedAccount` conserva su nombre visible, Riot ID y PUUID conocido. El campeón aleatorio, cuando corresponde, se sortea para ese mismo integrante. La asignación se guarda junto al castigo, el ataque y el evento de apertura, y se muestra en ambas ruletas, Mi Panel, administración e historial público.

La evaluación de Polivalente, Sin campeón favorito, Campeón aleatorio, Sin Flash exige que el integrante asignado cumpla su condición. Las estadísticas de Riot conservan el PUUID para verificar la cuenta. Si todavía no se conoce, se vincula al Riot ID configurado y se verifica su PUUID cuando se sincroniza. Los datos incompletos, las partidas de prueba y las partidas iniciadas antes de la asignación no acreditan cumplimiento. El castigo y la evidencia guardan quién debía cumplirlo y la partida que lo acreditó. Recargar, reiniciar o reabrir el castigo no cambia el integrante elegido.

Los castigos que ya estaban abiertos sin destinatario conservan la regla anterior (puede cumplirlos cualquiera); las asignaciones anteriores de campeón aleatorio también se conservan. Los castigos de AMBOS siguen exigiendo a ambos. `test_penalty_assignments.py` verifica todos los tipos, ambos destinatarios, persistencia, compatibilidad y una sincronización completa con respuestas de Riot simuladas.

### Caparazón reverso

«Devuelve el caparazón» crea un ataque `PENDING_SPIN` en la bandeja del equipo que lo lanzó. El receptor original devuelve el ataque sin gastar inventario y el atacante original debe girar su propia ruleta para recibir el castigo. No se devuelve una unidad al inventario; tener cero caparazones o el inventario lleno no impide recibirlo. El nuevo ataque activa las mismas notificaciones personales y aparece como «Caparazón devuelto por…» en Mi Panel.

El ataque inicial queda `RETURNED` y apunta al nuevo mediante `returnedAttackId`; el nuevo guarda `returnedFromAttackId`, `rootShellId` y `reflectionCount`. Conserva los porcentajes de la ruleta original. Si vuelve a salir reverso, rebota de nuevo, una sola vez por giro. Al salir un castigo, se asigna al equipo que acaba de girar y, si es de UNO, se aplica el sorteo de integrante 50/50. Los reversos históricos ya registrados conservan su resultado anterior.


### Sincronización incremental de Riot

La primera consulta del historial de cada cuenta conserva el recorrido completo con los mismos filtros existentes (Solo/Duo y desde 2026). Guarda `riotMatchDiscovery` como metadato interno del equipo: cuenta consultada, último ID descubierto y cola de partidas pendientes. Las siguientes sincronizaciones recorren únicamente las páginas recientes hasta alcanzar ese ID. Los detalles fallidos y las partidas que exceden el lote de 40 permanecen en la cola, incluso después de reiniciar el servidor. Si cambia la cuenta o no aparece el ID de referencia, se vuelve a recorrer el listado completo. Un fallo de paginación no adelanta la referencia.

Cada sincronización reutiliza las respuestas correctas de una misma URL de Riot para evitar repetir consultas compartidas entre equipos, iconos e historial. Esta caché dura únicamente ese trabajo; las respuestas fallidas no se cachean y los rangos se vuelven a consultar en la siguiente ejecución. La recuperación de estadísticas antiguas y las reglas de castigos y recompensas se conservan.


Si «Sin campeón favorito» se abre antes de disponer de estadísticas del integrante afectado, su referencia queda pendiente. Cada incorporación o recuperación de partidas recalcula los campeones más jugados y rellena las referencias vacías de los castigos activos. Se conserva el criterio de empates: todos los campeones empatados como más jugados quedan incluidos. Una vez establecida la referencia de cada integrante, permanece fija para ese castigo; los siguientes lanzamientos usan el historial actualizado. Esto también recupera castigos anteriores con listas vacías, sin volver a sortear quién debe cumplirlos. Las partidas de prueba y los campeones desconocidos no construyen favoritos.

El historial del modal usa un resumen desplegable por partida y dos filas de detalles. La importación conserva el Riot ID, campeón, nivel, rol, hechizos, K/D/A, CS de línea y jungla, oro, visión, los siete huecos de objetos finales y los asesinatos del equipo correspondiente a cada integrante. El KDA, CS/min y participación se calculan al mostrar la partida; la participación usa los asesinatos de todo su equipo, no solamente los del dúo. Una partida sin muertes muestra «Perfecto» y los datos ausentes aparecen como «—». No se almacena el resultado completo de Riot ni una puntuación OP Score.

`matchDetailsVersion` y `matchDetailsBackfill` permiten recuperar progresivamente los detalles de partidas antiguas en el lote existente de 40 por equipo, manteniendo el descubrimiento incremental y los marcadores de recompensas. Las partidas de prueba no se recuperan. Una cuenta identificada que no aparece entre los participantes se muestra como «No participó»; un fallo al identificar la segunda cuenta deja los detalles pendientes para reintentar. El parche (`gameVersion`) y la duración numérica quedan guardados por partida. Los nombres en español e iconos de objetos y hechizos proceden de Data Dragon, con caché por parche en el navegador; su carga no realiza consultas nuevas a la API de Riot ni guarda imágenes en la base de datos. Si esos recursos fallan, los datos siguen visibles y los objetos conservan su ID como etiqueta.

### Resumen semanal

Los avisos técnicos se muestran exclusivamente en la sección «Estado de los datos y sincronización» de administración, tras acceder con PIN. Incluye el estado de Riot/Twitch, conexión, partidas por importar, estadísticas y detalles pendientes, y logros sin registro de ingreso al inventario. El estado del archivo semanal y las explicaciones de recuperación, observaciones de ELO y almacenamiento de likes también quedan allí. Las pestañas públicas mantienen las reglas, información necesaria para interpretar sus datos y errores de acciones del participante, sin banners de sincronización ni contadores de recuperación. El refresco automático sigue funcionando.

El aviso «Riot: última llamada API OK» muestra, en hora de Madrid, la última respuesta HTTP correcta con JSON legible recibida de Riot durante una sincronización. Se guarda en `lastRiotApiSuccessAt` dentro del estado del torneo (Neon en producción) y se expone como `riot.lastApiSuccessAt` en `/api/sync/status`. Las respuestas reutilizadas de la caché, los errores y las sincronizaciones sin consultas no avanzan esa fecha. Se conserva aunque el resto del trabajo falle o se reinicie el servidor; antes de la primera respuesta real se indica que todavía no hay llamadas confirmadas.

Los fallos de Riot indican cuántas consultas devolvieron cada código HTTP, errores de conexión o datos no válidos, sin exponer claves ni URLs. El estado diferencia una sincronización parcial (hubo respuestas correctas) de una fallida (no hubo ninguna respuesta correcta en ese trabajo). Los datos importados previamente permanecen disponibles en ambos casos.

Los nombres visibles de campeones se resuelven con `championDisplayName` en `data.js`, usando los nombres oficiales en español de Data Dragon 16.19.1. Por ejemplo, `MonkeyKing` se muestra como Wukong en clasificación, historial, asignaciones de ruleta y resúmenes. Los identificadores originales se conservan en la base, los requisitos de castigos y las URLs de iconos. La tabla de nombres se sirve con la web sin llamadas adicionales a Riot; los identificadores sin alias se muestran tal cual.

`resumen.html` añade una pestaña pública con vista general, selección de equipo y archivo de semanas. La semana actual se actualiza desde la base; por defecto se abre la última archivada, si existe. Los informes de lunes a domingo usan `Europe/Madrid`, incluyendo los cambios de horario. El lunes a las 00:00 se guarda el resumen en `weeklySummaries`, junto con los totales y el ganador de clips, antes de renovar la lista de clips en la misma operación de persistencia. El premio de clips mantiene su cierre del domingo a las 23:59 y su registro independiente para evitar duplicados.

El scheduler existente realiza el cierre y recupera semanas pendientes al despertar; las lecturas también recuperan un archivo que no pudo guardarse. Se archiva desde la semana en que se habilita la función (o la semana del tablero de clips aún conservado), sin inventar archivos anteriores. Las sincronizaciones de Riot actualizan archivos si incorporan partidas atrasadas, y las correcciones administrativas recalculan los cumplimientos. Se conservan las etiquetas y resultados de cuentas sustituidas o equipos eliminados. Los resúmenes permanecen cuando se renueva la lista de clips.

Las partidas se asignan por `gameEndTimestamp`, excluyendo `isTest`, y se deduplican por `matchId` en el total general. Las estadísticas individuales usan únicamente los datos disponibles de cada participante; el KDA combinado se calcula con la suma de K/D/A y la mejor partida exige detalles de ambos. Los rangos comparan observaciones reales con sus fechas: las referencias incompletas se señalan como parciales y no participan en los destacados de subida/bajada. Los castigos automáticos se cuentan por la fecha de la partida que los acredita, separados de los marcados por administración. Los lanzamientos normales se distinguen de las devoluciones. `shellRewardCredits` registra desde esta versión qué logros ingresaron al inventario y cuáles toparon con el límite; los anteriores aparecen sin registro, no como cero inventado. No se añaden llamadas a Riot ni se cambian las reglas del torneo o de las recompensas.

`GET /api/weekly-summary?week=YYYY-MM-DD` devuelve únicamente el resumen público y las semanas disponibles; no expone credenciales, PUUID, identidades de votantes ni requisitos privados. Sin `week`, devuelve la semana actual. La página refresca cada minuto conservando la selección; los datos de un clip ganador permiten reproducirlo desde Twitch incluso después de limpiar la semana.

### Mis castigos en el panel del equipo

En «Mi Panel», las pestañas «Caparazones» y «Mis castigos» separan los lanzamientos y giros de la consulta de castigos. Los pendientes se agrupan por integrante y por ambos; los castigos individuales antiguos que podía cumplir cualquiera conservan su propio grupo. Las asignaciones a cuentas anteriores se distinguen de las del perfil actual. Se muestran todos los pendientes, mientras que «Historial» pagina los cumplidos y retirados en bloques de 20. Las actualizaciones automáticas conservan la pestaña, el filtro y la página abiertos. Esta vista usa los datos existentes de la base y no añade llamadas a Riot ni cambia las reglas de cumplimiento.

### Retirada del castigo de botas

Las variantes de UNO y AMBOS ya no participan en la ruleta. Al cargar la base se retiran sus pesos de la configuración y de los caparazones pendientes, conservando los pesos relativos del resto. Si una ruleta antigua solo tenía botas activas, se recupera con los pesos predeterminados vigentes. Los castigos de botas pendientes quedan `CANCELLED` (Retirado), sin fabricar cumplimiento ni borrar el historial; los cumplidos conservan su evidencia. Administración no puede reabrirlos. Ya no se consulta la timeline de Riot para este castigo. Los objetos finales de las partidas, incluidas las botas, siguen mostrándose.

### Flash al otro lado

`swap_flash_one` y `swap_flash_both` exigen Flash en el slot contrario al cómodo (D/F por defecto), dejando libre el otro hechizo. Pesos predeterminados: 12 para UNO y 6 para AMBOS, editables en administración. Al introducirlos se ajustan proporcionalmente los pesos restantes si la suma supera o no alcanza 100, respetando los castigos desactivados y sin volver a ajustar posteriores cambios administrativos. Los caparazones ya lanzados conservan su snapshot anterior. UNO usa el sorteo de integrante 50/50 existente; AMBOS exige cumplimiento de ambos en la misma partida.

La primera partida importada correctamente con dos hechizos válidos y Flash fija `player1.flashBaseline` o `player2.flashBaseline`, independientemente por cuenta. Se registra el slot original, la partida, su inicio y la identidad de Riot. No se infiere de las partidas ya guardadas al arrancar, ni cambia con posteriores sincronizaciones o partidas antiguas recuperadas. Partidas de prueba, sin Flash o incompletas no fijan referencia. Si el castigo se abre antes de conocerla, queda pendiente hasta que entre esa primera partida; esa partida únicamente establece la referencia y nunca acredita cumplimiento.

Los requisitos congelan las referencias e identidades al asignarlos o al completar las referencias pendientes. La partida válida debe comenzar después de la asignación y de la partida de referencia, corresponder a la cuenta afectada y contener Flash una sola vez en el slot opuesto. Cambiar la cuenta en administración descarta su referencia cómoda para futuras asignaciones y no transfiere un castigo anterior a la cuenta nueva. Los requisitos y la evidencia se guardan en la base, y el texto específico se muestra en las ruletas, Mi Panel, administración e historial. Se reutilizan `summoner1Id`/`summoner2Id` de Match v5; no hay llamadas adicionales. La API permite comprobar slots, pero no las teclas personalizadas del jugador.
