# 🏆 Pepes Krisis Duo Q Challenge

Una aplicación web interactiva para torneos de League of Legends inspirada en la mecánica del **Caparazón Azul de Mario Kart**. 

Permite seguir en tiempo real la clasificación de varios dúos en Ranked Solo/Duo mediante sincronización automática con la **Riot Games API**, recompensando rachas de victorias y Pentakills con "Caparazones Azules" para imponer debuffs o penaltis a los equipos rivales.

---

## ✨ Características Principales

- **🎮 Sincronización en Tiempo Real con Riot API**: Seguimiento automático de Elo, Tier, División, LP, Victorias, Derrotas y Racha activa cada 5 minutos.
- **🐢 Sistema de Caparazones Azules**:
  - Cada bloque de 3 victorias consecutivas, pentakill, al menos 20 kills, al menos 30 asistencias o 0 muertes con más de 20 kills + asistencias otorga 1 caparazón. Los logros individuales no exigen victoria y no suman estadísticas entre jugadores.
  - Cada criterio se premia una vez por equipo y partida, con un máximo de 2 premios por partida (incluida la racha) y 5 caparazones en inventario. Los excedentes se pierden. Se priorizan racha, pentakill, kills, asistencias y KDA perfecto.
  - Los nuevos criterios se aplican a partidas incorporadas tras la migración; se conservan premios y marcas anteriores. El registro por partida evita duplicados al recalcular o completar estadísticas.
  - La tabla pública de requisitos utiliza las mismas constantes del servidor mediante `/api/config`.
  - Los equipos pueden lanzar caparazones contra sus rivales para imponer castigos aleatorios (*Sin Botas*, *Sin Flash*, *Autofill*, etc.).
- **📊 Historial de Partidas Ordenado Cronológicamente**: Muestra los campeones jugados, KDA, duración y ganancia/pérdida de LP de cada partida.
- **🔐 Panel de Jugador & Panel de Administración**: Interfaz protegida para que los jugadores gestionen su inventario de caparazones y los administradores configuren el torneo.
- **🖼️ Avatares de Invocador Dinámicos**: Carga de iconos oficiales de LoL mediante Data Dragon CDN (v15.3.1).
- **🟣 Estado de Twitch**: Enlace por equipo y detección automática de emisiones en directo cada 5 minutos.

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

## 🔐 Credenciales de producción

El PIN de administración y las contraseñas de los equipos se almacenan como hashes PBKDF2. Las claves de API no se guardan en `db.json`.

En Render configura estas variables de entorno:

- `RIOT_API_KEY`
- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

En local, las claves introducidas desde el panel de administración se guardan en `secrets.json`, que está excluido de Git.

---

## Fiabilidad y operación

La aplicación sirve el frontend y la API desde el mismo origen. Solo los archivos públicos de la interfaz se pueden descargar; la base de datos, copias, secretos y código Python nunca se sirven por HTTP.

- Las operaciones manuales de Riot, Twitch y cálculo de caparazones requieren el PIN administrativo. Riot y Twitch responden `202` y trabajan en segundo plano; `/api/sync/status` informa de ejecución, errores, última finalización correcta y trabajo pendiente. Ese estado operativo se reinicia al arrancar el proceso.
- Los paneles conservan en memoria los últimos datos confirmados cuando falla una lectura, muestran la desconexión y no guardan modificaciones locales como si hubieran llegado al servidor.
- `/api/duos` devuelve un resumen sin historial. `/api/duos/{id}/history?offset=0&limit=30` permite recorrerlo completo. Los eventos también admiten `offset` y `limit`; el límite máximo de página es 100.
- Las consultas no conceden recompensas. Las sincronizaciones y el cálculo administrativo las guardan de forma persistente. Se mantienen las reglas actuales de recompensas y la importación basada en el jugador 1.
- Los castigos necesitan evidencia válida y una partida iniciada después de su asignación. Si falta la cronología para las botas, se vuelve a intentar. Reabrir un castigo conserva la corrección y descarta la partida que lo había completado automáticamente.

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

El desplegable de cada dúo muestra `eloHistory`: último rango observado por día (fecha local del servidor), LP, victorias y derrotas. Se inicia con el rango guardado al activar la función y se actualiza tras lecturas confirmadas de Riot. No se reconstruyen LP anteriores a partir de victorias o derrotas. Cambiar la cuenta principal inicia un registro nuevo. La gráfica muestra detalles al pasar, enfocar o tocar cada punto.
