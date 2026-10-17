/* Overlay library: admin-only writes; media are immutable, active effects are equiprobable. */
async function refreshOverlayLibrary() {
  if (!adminSessionPin || !document.getElementById('admin-overlay-effects')) return;
  document.getElementById('admin-overlay-effects').hidden = false;
  try {
    const result = await overlayAdminRequest('/api/admin/overlay', {authPin:adminSessionPin});
    renderOverlayLibrary(result.effects);
  } catch (error) { document.getElementById('overlay-library-status').textContent = error.message; }
}

async function overlayAdminRequest(url, body, headers) {
  const response = await fetch(url, {
    method:'POST', headers:headers || {'Content-Type':'application/json'},
    body:headers ? body : JSON.stringify(body), signal:AbortSignal.timeout(60000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'No se pudo guardar la biblioteca.');
  return result;
}

function renderOverlayLibrary(effects = []) {
  const list = document.getElementById('overlay-library-list'); list.replaceChildren();
  const active = effects.filter(effect => effect.active).length;
  document.getElementById('overlay-library-status').textContent = `${active} animaciones activas · misma probabilidad: ${active ? (100/active).toLocaleString('es-ES',{maximumFractionDigits:1}) : 0} % cada una`;
  for (const effect of effects) {
    const card = document.createElement('article'); card.className = 'overlay-library-card';
    const title = document.createElement('h3'); title.textContent = effect.name;
    const description = document.createElement('p');
    description.textContent = effect.kind === 'builtin' ? 'Misil Pepo con alarma nuclear · 10 segundos' : `Vídeo de ${(effect.durationMs/1000).toLocaleString('es-ES')} s + 3,5 s para mostrar el atacante`;
    card.append(title, description);
    if (effect.kind === 'video' && /^\/api\/overlay\/media\/[a-f0-9]{64}$/.test(effect.url)) {
      const video = document.createElement('video'); video.controls = true; video.preload = 'none'; video.src = effect.url;
      video.setAttribute('aria-label', `Previsualizar ${effect.name}`); card.append(video);
    }
    const button = document.createElement('button'); button.type = 'button'; button.className = 'btn-refresh';
    button.textContent = effect.active ? 'Desactivar' : 'Activar'; button.setAttribute('aria-pressed', String(effect.active));
    button.disabled = effect.active && active === 1;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { renderOverlayLibrary((await overlayAdminRequest('/api/admin/overlay',{authPin:adminSessionPin,action:'toggle',id:effect.id,active:!effect.active})).effects); }
      catch (error) { document.getElementById('overlay-library-status').textContent = error.message; button.disabled = false; }
    });
    card.append(button); list.append(card);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('overlay-upload-form');
  if (!form) return;
  const fileInput = document.getElementById('overlay-upload-file'), name = document.getElementById('overlay-upload-name');
  const preview = document.getElementById('overlay-upload-preview'), submit = document.getElementById('overlay-upload-submit');
  const status = document.getElementById('overlay-upload-status');
  let objectUrl, duration = 0;
  fileInput.addEventListener('change', () => {
    duration = 0; submit.disabled = true; preview.hidden = true;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    const file = fileInput.files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.webm') || file.size > 12*1024*1024) {
      status.textContent = 'Selecciona un WebM de hasta 12 MiB.'; return;
    }
    name.value = file.name.replace(/\.webm$/i, '').slice(0,80);
    objectUrl = URL.createObjectURL(file); preview.src = objectUrl; preview.hidden = false;
    preview.onloadedmetadata = () => {
      duration = Math.round(preview.duration*1000);
      if (!Number.isFinite(duration) || duration < 500 || duration > 30000) {
        status.textContent = 'El WebM debe indicar una duración entre 0,5 y 30 segundos.'; return;
      }
      status.textContent = 'Revisa imagen, transparencia y sonido. Al subirlo entrará activo en el sorteo.';
      submit.disabled = false;
    };
    preview.onerror = () => { status.textContent = 'El navegador no puede reproducir este WebM.'; submit.disabled = true; };
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); const file = fileInput.files[0];
    if (!file || !duration || !adminSessionPin) return;
    submit.disabled = true; status.textContent = 'Guardando animación…';
    try {
      const result = await overlayAdminRequest('/api/admin/overlay/upload', file, {
        'Content-Type':'video/webm', 'X-Admin-Pin':adminSessionPin,
        'X-Overlay-Name':encodeURIComponent(name.value.trim()), 'X-Overlay-Duration':String(duration)
      });
      renderOverlayLibrary(result.effects);
      preview.pause(); preview.removeAttribute('src'); preview.load(); preview.hidden = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null; duration = 0; form.reset();
      status.textContent = 'Animación guardada y activa. Los siguientes pepazos podrán seleccionarla.';
    } catch (error) { status.textContent = error.message; submit.disabled = false; }
  });
});
