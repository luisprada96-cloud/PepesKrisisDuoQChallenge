# 🏆 Pepes Krisis Duo Q Challenge

Una aplicación web interactiva para torneos de League of Legends inspirada en la mecánica del **Caparazón Azul de Mario Kart**. 

Permite seguir en tiempo real la clasificación de varios dúos en Ranked Solo/Duo mediante sincronización automática con la **Riot Games API**, recompensando rachas de victorias y Pentakills con "Caparazones Azules" para imponer debuffs o penaltis a los equipos rivales.

---

## ✨ Características Principales

- **🎮 Sincronización en Tiempo Real con Riot API**: Seguimiento automático de Elo, Tier, División, LP, Victorias, Derrotas y Racha activa cada 5 minutos.
- **🐢 Sistema de Caparazones Azules**:
  - Ganar 3 partidas consecutivas o lograr una **Pentakill** otorga 1 Caparazón Azul.
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
