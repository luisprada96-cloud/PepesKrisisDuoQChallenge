/* The server owns the price, shared gold, inventory and purchase receipts. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('shop-confirm');
  const quotes = [
    'No vendo manos. Eso sigue siendo cosa tuya.',
    'Excelente inversión. Terrible persona.',
    'Tu rival financia mis vacaciones.',
    'No hay reembolso por llorar en el chat.',
    'Tengo pociones de maná, pero de macro no me quedan.',
    'Este pepazo estaba así cuando llegó.',
    'El jungla no viene, pero tu pedido sí.',
    'Compra tranquilo. El tilt viene incluido.',
    'Oro virtual, rencor real.',
    'No tengo cambio para un ego tan grande.',
    'El mapa no lo miras, pero el catálogo sí.',
    'Tu dúo lo habría aprobado. Probablemente.',
    'Si no puedes ganar la línea, gana enemigos.',
    'Hay wards más baratos, pero sé que no venías a por eso.',
    'Este negocio se sostiene gracias a los «última y me voy».',
    'No cura el tilt. Lo reparte.',
    'Gastas mejor el oro aquí que en tu última build.',
    'Oferta especial: te llevas un pepazo y pierdes un amigo.',
    'En esta tienda el único que está fed soy yo.',
    'Te iba a recomendar paciencia, pero no deja margen.',
    'Contra el rival, por favor. El monitor no tiene la culpa.'
  ];
  let state = null, busy = false, fresh = false, loadError = false, version = 0, quote = 0, attempt = null, confirmation = null;
  const token = () => { try { return sessionStorage.getItem('pepes_player_token') || ''; } catch (_) { return ''; } };
  const pendingKey = team => 'pepes_shop_pending_' + team;
  const quantity = () => Number($('shop-quantity').value);
  const price = () => state?.product.unitPrice || 70;
  const plural = n => n === 1 ? 'pepazo' : 'pepazos';

  function remember(value) {
    attempt = value;
    if (!state?.wallet) return;
    try {
      if (value) sessionStorage.setItem(pendingKey(state.wallet.teamId), JSON.stringify(value));
      else sessionStorage.removeItem(pendingKey(state.wallet.teamId));
    } catch (_) { /* In-memory retries still share the same receipt ID. */ }
  }
  function restore() {
    if (!state?.wallet) { attempt = null; return; }
    const inMemory = attempt?.teamId === state.wallet.teamId ? attempt : null;
    try {
      const saved = JSON.parse(sessionStorage.getItem(pendingKey(state.wallet.teamId)) || 'null');
      attempt = saved?.teamId === state.wallet.teamId && Number.isInteger(saved.quantity) && saved.quantity > 0 && typeof saved.requestId === 'string' ? saved : inMemory;
    } catch (_) { attempt = inMemory; }
    if (attempt) $('shop-quantity').value = String(attempt.quantity);
  }
  function feedback(text, error = false) {
    $('shop-feedback').textContent = text;
    $('shop-feedback').classList.toggle('is-error', error);
  }
  function render() {
    const wallet = state?.wallet, count = quantity(), total = count * price();
    const valid = Number.isSafeInteger(count) && count >= 1 && count <= 1000000;
    const max = Math.max(1, Math.min(1000000, Math.floor((wallet?.balance || 0) / price())));
    $('shop-team').textContent = wallet?.teamName || 'Oro de tu equipo';
    $('shop-balance').textContent = wallet ? wallet.balance : '—';
    $('shop-reserved').textContent = wallet ? `${wallet.reserved} oro reservado en apuestas` : 'El mismo saldo que en Apuestas';
    $('shop-stock').textContent = wallet ? `${wallet.inventory} ${plural(wallet.inventory)}` : '—';
    $('shop-price').textContent = price();
    $('shop-total').textContent = valid ? total : '—';
    $('shop-after').textContent = attempt ? 'Por comprobar' : wallet && valid ? `${Math.max(0, wallet.balance - total)} oro` : '—';
    $('shop-quantity').max = String(attempt ? Math.max(max, attempt.quantity) : max);
    $('shop-quantity').disabled = busy || !wallet || !fresh || !!attempt;
    $('shop-minus').disabled = busy || !wallet || !fresh || !!attempt || !valid || count <= 1;
    $('shop-plus').disabled = busy || !wallet || !fresh || !!attempt || !valid || count >= max;
    $('shop-buy').disabled = busy || !wallet || !fresh || (!attempt && (!valid || total > wallet.balance));
    $('shop-buy').textContent = attempt ? 'Comprobar compra pendiente' : `Comprar ${valid ? count : ''} ${plural(count)}`;
    $('shop-login').hidden = !!wallet || !fresh;
    $('shop-notice').textContent = !fresh ? 'No se ha podido consultar el saldo. Reintentando…'
      : !wallet ? 'Entra con tu equipo para usar vuestro oro.'
      : attempt ? 'Hay una compra pendiente de comprobar. Reintenta sin volver a pagar.'
      : wallet.balance < price() ? `Te faltan ${price() - wallet.balance} monedas para un pepazo.`
      : !valid ? 'Elige una cantidad entera de pepazos.'
      : total > wallet.balance ? 'No hay suficiente oro disponible para esta cantidad.'
      : 'Se añade al inventario de tu equipo.';
    $('shop-confirm-buy').disabled = busy || !wallet || !fresh;
    $('shop-cancel').disabled = busy;
    $('shop-confirm-buy').textContent = busy ? 'Cerrando el trato…' : attempt ? 'Comprobar compra' : 'Confirmar compra';
  }
  async function api(method, body, auth = token()) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/shop', {method, cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', ...(auth ? {Authorization: 'Bearer ' + auth} : {})},
        ...(body ? {body: JSON.stringify(body)} : {})});
      const data = await response.json();
      if (!response.ok) throw Object.assign(new Error(data.error || 'No se pudo completar la compra.'), {status: response.status});
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function refresh() {
    if (busy) return;
    const current = ++version, auth = token();
    try {
      const data = await api('GET', null, auth);
      if (current !== version || busy || auth !== token()) return;
      if (dialog.open && confirmation?.teamId !== data.wallet?.teamId) { dialog.close(); confirmation = null; }
      state = data; fresh = true; restore(); render();
      if (loadError) { feedback(''); loadError = false; }
    } catch (_) {
      if (current !== version || busy) return;
      fresh = false; loadError = true; render(); feedback('La tienda no puede consultar el saldo ahora. Tu oro está a salvo.', true);
    }
  }
  function talk(message) {
    $('shop-quote').textContent = message || quotes[quote++ % quotes.length];
  }
  function celebrate() {
    talk('Excelente inversión. Terrible persona.');
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const fly = (node, from, to, delay) => {
      node.style.left = `${from.x}px`; node.style.top = `${from.y}px`; document.body.append(node);
      const animation = node.animate([{transform: 'translate(0,0) scale(1)', opacity: 1},
        {transform: `translate(${to.x - from.x}px,${to.y - from.y}px) scale(.35)`, opacity: .1}],
        {duration: 900, delay, easing: 'cubic-bezier(.35,.05,.2,1)', fill: 'both'});
      animation.onfinish = () => node.remove();
      setTimeout(() => node.remove(), delay + 1500);
    };
    const wallet = $('shop-balance').getBoundingClientRect(), scene = $('shop-merchant').getBoundingClientRect();
    for (let i = 0; i < 5; i++) {
      const coin = document.createElement('span'); coin.className = 'shop-flying-coin'; coin.textContent = '✦'; coin.setAttribute('aria-hidden', 'true');
      fly(coin, {x: wallet.left + i * 4, y: wallet.top}, {x: scene.left + scene.width / 2, y: scene.bottom - 20}, i * 80);
    }
    const art = $('shop-item').getBoundingClientRect(), stock = $('shop-inventory').getBoundingClientRect();
    const shell = document.createElement('img'); shell.className = 'shop-flying-item'; shell.src = 'assets/shop/pepazo.webp'; shell.alt = '';
    fly(shell, {x: art.left + art.width / 2 - 37, y: art.top + art.height / 2 - 37}, {x: stock.left + 12, y: stock.top}, 200);
    $('shop-inventory').classList.remove('is-celebrating');
    requestAnimationFrame(() => $('shop-inventory').classList.add('is-celebrating'));
  }
  $('shop-talk').addEventListener('click', () => talk());
  $('shop-merchant').addEventListener('click', () => talk());
  $('shop-minus').addEventListener('click', () => { $('shop-quantity').value = String(quantity() - 1); render(); });
  $('shop-plus').addEventListener('click', () => { $('shop-quantity').value = String(quantity() + 1); render(); });
  $('shop-quantity').addEventListener('input', render);
  $('shop-form').addEventListener('submit', event => {
    event.preventDefault();
    if ($('shop-buy').disabled) return;
    confirmation = {...(attempt || {quantity: quantity(), teamId: state.wallet.teamId}), auth: token()};
    $('shop-confirm-description').textContent = attempt
      ? `Comprobaremos tu compra de ${confirmation.quantity} ${plural(confirmation.quantity)}. Si ya se cobró, recibirás el mismo justificante sin otro cargo.`
      : `Cambiar ${confirmation.quantity * price()} monedas de ${state.wallet.teamName} por ${confirmation.quantity} ${plural(confirmation.quantity)}.`;
    $('shop-confirm-note').textContent = attempt ? 'La cantidad queda bloqueada hasta comprobar esta compra.' : `Después tendrás ${state.wallet.inventory + confirmation.quantity} ${plural(state.wallet.inventory + confirmation.quantity)} en el inventario.`;
    $('shop-error').hidden = true; dialog.showModal(); $('shop-confirm-buy').focus(); render();
  });
  $('shop-cancel').addEventListener('click', () => { if (!busy) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  $('shop-confirm-buy').addEventListener('click', async () => {
    if (busy || !confirmation || !state?.wallet || confirmation.teamId !== state.wallet.teamId) return;
    if (confirmation.auth !== token()) { dialog.close(); confirmation = null; refresh(); return; }
    if (!attempt) remember({quantity: confirmation.quantity, teamId: confirmation.teamId,
      requestId: crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')});
    busy = true; ++version; render(); $('shop-error').hidden = true;
    const auth = token();
    try {
      const data = await api('POST', {quantity: attempt.quantity, requestId: attempt.requestId}, auth);
      if (auth !== token()) { state = {...state, wallet: null}; fresh = false; dialog.close(); return; }
      const count = data.purchase.quantity;
      remember(null); state = data; fresh = true; $('shop-quantity').value = '1';
      dialog.close(); confirmation = null;
      feedback(`Trato hecho: ${count} ${plural(count)} por ${data.purchase.total} monedas. Ya están en el inventario de tu equipo.`);
      celebrate();
    } catch (error) {
      if ([400, 409].includes(error.status)) { remember(null); confirmation = null; dialog.close(); }
      if (error.status === 401) { state = {...state, wallet: null}; dialog.close(); }
      $('shop-error').textContent = error.status ? error.message : 'No se pudo confirmar la respuesta. Reintenta para comprobar esta misma compra, sin duplicar el cargo.';
      $('shop-error').hidden = false;
      feedback(error.status ? error.message : 'Compra pendiente de comprobar. Puedes reintentar con el mismo justificante.', true);
    } finally {
      busy = false; render();
      if (!attempt || auth !== token()) refresh();
    }
  });
  window.addEventListener('focus', refresh);
  window.addEventListener('pageshow', refresh);
  document.addEventListener('player-session-changed', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(() => { if (!document.hidden) refresh(); }, 60000);
  refresh();
})();
