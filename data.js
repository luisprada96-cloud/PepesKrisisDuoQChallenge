/* ==========================================================================
   Pepes Krisis Duo Q Challenge - Data & API Services Layer
   ========================================================================== */

const API_BASE_URL = '/api';

const DEFAULT_CONFIG = {
  challengeTitle: "Pepes Krisis Duo Q Challenge",
  startDate: "2026-08-01T00:00:00",
  endDate: "2026-08-31T23:59:59",
  prizePool: "Bote: 500€ + Cena de Ganadores 🏆",
  server: "EUW",
  adminPin: "1234",
  riotApiKey: ""
};

const DataStore = {
  async getDuos() {
    try {
      const res = await fetch(`${API_BASE_URL}/duos`);
      if (res.ok) {
        return await res.json();
      }
    } catch (e) {
      console.warn("API REST inaccesible, usando respaldo local:", e);
    }
    const local = localStorage.getItem('pepes_duoq_teams_v1');
    return local ? JSON.parse(local) : [];
  },

  async saveDuo(duo) {
    try {
      const res = await fetch(`${API_BASE_URL}/duos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(duo)
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Error guardando en API REST:", e);
    }
    const duos = await this.getDuos();
    duos.unshift(duo);
    localStorage.setItem('pepes_duoq_teams_v1', JSON.stringify(duos));
  },

  async deleteDuo(id) {
    try {
      const res = await fetch(`${API_BASE_URL}/duos/${id}`, { method: 'DELETE' });
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
      console.warn("API config inaccesible:", e);
    }
    const local = localStorage.getItem('pepes_duoq_config_v1');
    return local ? JSON.parse(local) : DEFAULT_CONFIG;
  },

  async saveConfig(config) {
    try {
      const res = await fetch(`${API_BASE_URL}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
      });
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Error guardando config:", e);
    }
    localStorage.setItem('pepes_duoq_config_v1', JSON.stringify(config));
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

  async launchShell(attackerId, targetId) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/launch-shell`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attackerId, targetId })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error de conexión al enviar el Caparazón Azul" };
    }
  },

  async resolveDebuff(teamId, timestamp, penaltyId) {
    try {
      const res = await fetch(`${API_BASE_URL}/player/resolve-debuff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ teamId, timestamp, penaltyId })
      });
      return await res.json();
    } catch (e) {
      return { success: false, error: "Error de conexión al resolver castigo" };
    }
  },

  async getEvents() {
    try {
      const res = await fetch(`${API_BASE_URL}/events`);
      if (res.ok) return await res.json();
    } catch (e) {
      console.warn("Error obteniendo eventos:", e);
    }
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
