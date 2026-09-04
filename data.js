/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Data & API Services Layer
   ========================================================================== */

const API_BASE_URL = window.PEPES_API_URL || '/api';

function normalizeTwitchUrl(value) {
  const rawValue = String(value || '').trim();
  if (!rawValue) return '';

  try {
    const url = new URL(rawValue);
    const hostname = url.hostname.toLowerCase().replace(/^www\./, '');
    const pathParts = url.pathname.split('/').filter(Boolean);

    if (url.protocol !== 'https:' || hostname !== 'twitch.tv' || pathParts.length !== 1) {
      return '';
    }

    const channel = pathParts[0];
    if (!/^[a-zA-Z0-9_]{4,25}$/.test(channel)) return '';

    return `https://www.twitch.tv/${channel}`;
  } catch (error) {
    return '';
  }
}

const DEFAULT_CONFIG = {
  challengeTitle: "Pepes Krisis Duo Q Challenge",
  startDate: "2026-08-01T00:00:00",
  endDate: "2026-08-31T23:59:59",
  prizePool: "Bote: 500€ + Cena de Ganadores 🏆",
  server: "EUW",
  adminPin: "1234",
  riotApiKey: "",
  twitchClientId: ""
};

const DataStore = {
  async getDuos() {
    try {
      const res = await fetch(`${API_BASE_URL}/duos`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn("API REST inaccesible, intentando db.json de respaldo:", e);
    }
    try {
      const resDb = await fetch('db.json');
      if (resDb.ok) {
        const data = await resDb.json();
        if (data && data.duos) return data.duos;
      }
    } catch (e) {
      console.warn("Respaldo db.json inaccesible:", e);
    }
    const local = localStorage.getItem('pepes_duoq_teams_v1');
    return local ? JSON.parse(local) : [];
  },

  async saveDuo(duo, authPin) {
    try {
      const res = await fetch(`${API_BASE_URL}/duos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duo, authPin })
      });
      const result = await res.json();
      if (res.ok) return result;
      return { success: false, error: result.error || 'No se pudo guardar el equipo.' };
    } catch (e) {
      console.warn("Error guardando en API REST:", e);
    }
    const duos = await this.getDuos();
    duos.unshift(duo);
    localStorage.setItem('pepes_duoq_teams_v1', JSON.stringify(duos));
  },

  async deleteDuo(id, authPin) {
    try {
      const res = await fetch(`${API_BASE_URL}/duos/${id}`, {
        method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ authPin })
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Error eliminando en API REST:", e);
    }
    let duos = await this.getDuos();
    duos = duos.filter(d => d.id !== id);
    localStorage.setItem('pepes_duoq_teams_v1', JSON.stringify(duos));
  },

  async getConfig() {
    try {
      const res = await fetch(`${API_BASE_URL}/config`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn("API config inaccesible, intentando db.json de respaldo:", e);
    }
    try {
      const resDb = await fetch('db.json');
      if (resDb.ok) {
        const data = await resDb.json();
        if (data && data.config) {
          const { adminPin, riotApiKey, twitchClientSecret, ...safeConfig } = data.config;
          return safeConfig;
        }
      }
    } catch (e) {
      console.warn("Respaldo config en db.json inaccesible:", e);
    }
    const local = localStorage.getItem('pepes_duoq_config_v1');
    return local ? JSON.parse(local) : DEFAULT_CONFIG;
  },

  async getAdminConfig(pin) {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin })
      });
      const data = await res.json();
      return { ok: res.ok, ...data };
    } catch (e) {
      return { ok: false, success: false, error: "No se pudo conectar con el servidor" };
    }
  },

  async saveConfig(config, authPin) {
    try {
      const res = await fetch(`${API_BASE_URL}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, authPin })
      });
      const data = await res.json();
      if (res.ok) return data;
      return { success: false, error: data.error || "No se pudo guardar la configuración" };
    } catch (e) {
      console.warn("Error guardando config:", e);
    }
    return { success: false, error: "No se pudo conectar con el servidor" };
  },

  async triggerRiotSync() {
    try {
      const res = await fetch(`${API_BASE_URL}/sync`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        return data.duos || [];
      }
    } catch (e) {
      console.error("Error en sincronización con Riot:", e);
    }
    return await this.getDuos();
  },

  async triggerTwitchSync(authPin) {
    try {
      const res = await fetch(`${API_BASE_URL}/twitch/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ authPin })
      });
      const data = await res.json();
      return { ok: res.ok, ...data };
    } catch (e) {
      return { ok: false, success: false, error: "No se pudo conectar con Twitch" };
    }
  },

  async loginPlayer(teamId, password) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teamId, password })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error de red al conectar al servidor" };
    }
  },

  async getPlayerState(sessionToken) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/state`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionToken })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error al actualizar el panel" };
    }
  },

  async launchShell(targetId, sessionToken) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/launch-shell`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targetId, sessionToken })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error de conexión al enviar el Caparazón Azul" };
    }
  },

  async spinShell(attackId, sessionToken) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/spin-shell`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attackId, sessionToken })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error de conexión al girar la ruleta" };
    }
  },

  async adminResolvePenalty(penaltyInstanceId, action, note, authPin) {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/resolve-penalty`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ penaltyInstanceId, action, note, authPin })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error al corregir el castigo" };
    }
  },

  async getEvents() {
    try {
      const res = await fetch(`${API_BASE_URL}/events`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("API de eventos inaccesible, intentando db.json de respaldo:", e);
    }
    try {
      const resDb = await fetch('db.json');
      if (resDb.ok) {
        const data = await resDb.json();
        if (data && data.events) return data.events;
      }
    } catch (e) {}
    return [];
  },

  async calculateShells() {
    try {
      const res = await fetch(`${API_BASE_URL}/calculate-shells`, { method: 'POST' });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Error calculando caparazones:", e);
    }
    return { success: false, newShells: 0, duos: await this.getDuos() };
  }
};
