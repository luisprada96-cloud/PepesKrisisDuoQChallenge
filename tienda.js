/* The server owns the price, shared gold, inventory and purchase receipts. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('shop-confirm');
  const longQuote = `En realidad no hay limite de caracteres aqui puedo poner lo que quiera por ejemplo: El Partido Socialista Obrero Español se fundó en Madrid el 2 de mayo de 1879 por el tipógrafo ferrolano Pablo Iglesias Posse,[35] constituyendo uno de los partidos obreros más antiguos de Europa, solo superado por el Partido Socialdemócrata de Alemania. Desde sus inicios, aspiraba a agrupar al proletariado industrial español bajo la ideología marxista. No obstante, su implementación fue muy irregular: sus principales núcleos se desarrollaron en Madrid, Asturias y el País Vasco, disponiendo de poca presencia en Cataluña, el mayor foco industrial de España. El atraso de la sociedad española y el frágil desarrollo industrial, así como la fuerza del anarquismo y el anarcosindicalismo entre los sectores obreros barceloneses, explican la poca relevancia que el PSOE alcanzó en los primeros años tras su fundación, al contrario que sus homólogos europeos.[cita requerida]

El PSOE celebró su primer congreso en Barcelona en 1888, aunque no logró representación parlamentaria hasta el 8 de mayo de 1910, cuando la Conjunción Republicano-Socialista permitió a Pablo Iglesias obtener 40 899 sufragios y el acta de diputado a Cortes.[36] Fue reelegido en 1914, en vísperas del asesinato de Jean Jaurès, con 21 956 sufragios, esta vez presentándose por Oviedo.

A partir de la alianza con los republicanos y la entrada en el parlamento, su presencia y su importancia en la sociedad española fue en aumento, tanto por su propia actividad como partido como por la fuerza de la Unión General de Trabajadores (UGT), sindicato socialista fundado por Pablo Iglesias en 1888 en la ciudad de Barcelona e íntimamente ligado al PSOE, ya que hasta la década de 1980 la sindicación a UGT suponía la afiliación al PSOE y viceversa.

Aunque históricamente la lucha contra el clericalismo no les había parecido a los dirigentes e ideólogos socialistas que fuese la causa del movimiento obrero, el contacto con la cultura política republicana junto con el crecimiento de los sindicatos católicos «amarillos», le hizo adoptar una postura anticlerical como se pudo comprobar en el programa de 1918 en el que, además de propugnar la «supresión del presupuesto del clero y confiscación de sus bienes» y la enseñanza «gratuita y laica» (reivindicaciones que aparecían en el programa de 1888), se defendía «la disolución de todas las órdenes religiosas» (la máxima reivindicación anticlerical del republicanismo). Precisamente cuando la oleada anticlerical de la primera década del siglo XX remitió, los socialistas se convirtieron en «los mejores custodios de la tradición laicista de la izquierda española».[37]

El 9 de abril de 1916, Pablo Iglesias repitió escaño con 18 054 sufragios. Debido al papel activo que tuvieron durante la huelga general de 1917, los futuros líderes socialistas Francisco Largo Caballero y Julián Besteiro fueron detenidos, juzgados y encarcelados con una condena a cadena perpetua, aunque eso no impidió que en las elecciones generales españolas de febrero de 1918 todos fueran elegidos diputados. En 1919, Pablo Iglesias empezó a abandonar sus obligaciones políticas debido a problemas de salud, falleciendo en 1925.`;
  const quotes = [
    "He visto tu siguiente partida. Prefiero que me pagues antes.",
    "Hay wards más baratos, pero sé que no venías a por eso.",
    "Te iba a recomendar paciencia, pero no deja margen.",
    "Los supports convocan una huelga: cobrar en «gj» ya no paga las wards.",
    "La organización recuerda que ganar una discusión en Discord no otorga LP.",
    "un torneo para volverlos locos a todos",
    "Tu dúo lo habría aprobado. Probablemente.",
    "Un jugador consigue mirar el minimapa. Sus compañeros piden repetir el experimento.",
    "Contra el rival, por favor. El monitor no tiene la culpa.",
    "Un equipo asegura que está escalando. Se refería a la tensión en Discord.",
    "En esta tienda el único que está fed soy yo.",
    "El mapa no lo miras, pero el catálogo sí.",
    "Aumenta la demanda de pepazos. Los psicólogos del torneo solicitan refuerzos.",
    "Tu rival financia mis vacaciones.",
    "El Banco de la Grieta desaconseja invertir todos tus ahorros en un Yasuo.",
    "Excelente inversión. Terrible persona.",
    "El jungla no viene, pero tu pedido sí.",
    "Oro virtual, rencor real.",
    "Este negocio se sostiene gracias a los «última y me voy».",
    "Un dúo atribuye su derrota al lag. Ambos estaban en la misma habitación.",
    "Este pepazo estaba así cuando llegó.",
    "No hay reembolso por llorar en el chat.",
    "La Asociación de Minions denuncia abandono reiterado de oleadas.",
    "Pepe declara beneficios récord y recomienda mantener las rivalidades.",
    "El redactor de estos rumores pide cobrar en oro. Pepe le ofrece exposición.",
    "Me dicen que alguno ha perdido la cabeza ya",
    "Oferta especial: te llevas un pepazo y pierdes un amigo.",
    "Pepe niega estar financiando ambos bandos. Procede a vender otro pepazo.",
    "Has conseguido una pentakill. Pepe te ofrece exactamente el mismo precio.",
    "Tengo pociones de maná, pero de macro no me quedan.",
    "Compra tranquilo. El tilt viene incluido.",
    "Cierran una academia de coaching: convertía oro en confianza injustificada.",
    "Otro pepazo no arreglará vuestro dúo, pero entiendo que queráis probar.",
    "Gastas mejor el oro aquí que en tu última build.",
    longQuote,
    "No cura el tilt. Lo reparte.",
    "Reportalos a todosss",
    "Logro desbloqueado: has ganado una discusión en Discord. La derrota sigue contando.",
    "Vas mejorando. Ya solo te falta todo lo demás.",
    "Última hora: un jungla visita top. Se investigan los hechos.",
    "La Grieta pierde altura por la cantidad de jugadores que se están hundiendo solos.",
    "El Ministerio del Tilt recomienda no escribir «?» después de una muerte.",
    "No vendo manos. Eso sigue siendo cosa tuya.",
    "Un jugador anuncia «última y me voy». Lleva seis partidas más.",
    "Científicos descubren que comprar wards permite ver cosas.",
    "Si no puedes ganar la línea, gana enemigos.",
    "Lo que empezó como un torneo entre amigos ya requiere mediación internacional.",
    "Detectado un support con oro. Las autoridades buscan al ADC.",
    "Has vuelto a darle a buscar partida. El problema empieza a parecer voluntario.",
    "Enhorabuena por subir de rango. Tu familia pregunta si eso permite llamarte ahora.",
    "No tengo cambio para un ego tan grande.",
    "Encuentran una pink sin usar en el inventario. La familia pide privacidad."
  ];
  const goldQuotes = {
    poor: 'Equipo sin oro anuncia que la tienda está carísima.',
    purchase: 'Pepe mejora sus previsiones económicas.'
  };
  let state = null, busy = false, fresh = false, loadError = false, version = 0, quote = 0, attempt = null, confirmation = null, goldContext = null;
  let mixedQuotes = quotes.slice(), quoteSeed = null;
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
      state = data; fresh = true; mixQuotes(data.quoteSeed); restore(); render(); updateGoldQuote();
      if (loadError) { feedback(''); loadError = false; }
    } catch (_) {
      if (current !== version || busy) return;
      fresh = false; loadError = true; render(); feedback('La tienda no puede consultar el saldo ahora. Tu oro está a salvo.', true);
    }
  }
  function mixQuotes(seed) {
    if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff || seed === quoteSeed) return;
    quoteSeed = seed;
    let random = seed || 0x9e3779b9;
    mixedQuotes = quotes.slice();
    for (let i = mixedQuotes.length - 1; i > 0; i--) {
      random ^= random << 13; random ^= random >>> 17; random ^= random << 5;
      const j = Math.floor((random >>> 0) / 0x100000000 * (i + 1));
      [mixedQuotes[i], mixedQuotes[j]] = [mixedQuotes[j], mixedQuotes[i]];
    }
    quote = 0;
  }
  function talk(message) {
    const text = message || mixedQuotes[quote++ % mixedQuotes.length], rambling = text.length > 500;
    $('shop-quote').textContent = text;
    $('shop-quote').scrollTop = 0;
    $('shop-speech').classList.toggle('is-rambling', rambling);
    if (rambling) {
      $('shop-quote').setAttribute('tabindex', '0');
      $('shop-quote').setAttribute('role', 'region');
      $('shop-quote').setAttribute('aria-label', 'El larguísimo discurso de Pepe');
    } else {
      for (const attr of ['tabindex', 'role', 'aria-label']) $('shop-quote').removeAttribute(attr);
    }
  }
  function updateGoldQuote(afterPurchase = false) {
    const wallet = state?.wallet;
    const context = wallet ? `${wallet.teamId}:${wallet.balance < price() ? 'poor' : 'funded'}` : null;
    if (context === goldContext) return;
    goldContext = context;
    if (afterPurchase) return;
    if (wallet && wallet.balance < price()) talk(goldQuotes.poor);
    else if ($('shop-quote').textContent === goldQuotes.poor) talk();
  }
  function celebrate() {
    updateGoldQuote(true);
    talk(goldQuotes.purchase);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const fly = (node, from, to, delay) => {
      node.style.left = `${from.x}px`; node.style.top = `${from.y}px`; document.body.append(node);
      const animation = node.animate([{transform: 'translate(0,0) scale(1)', opacity: 1},
        {transform: `translate(${to.x - from.x}px,${to.y - from.y}px) scale(.35)`, opacity: .1}],
        {duration: 900, delay, easing: 'cubic-bezier(.35,.05,.2,1)', fill: 'both'});
      animation.onfinish = () => node.remove();
      setTimeout(() => node.remove(), delay + 1500);
    };
    const wallet = $('shop-balance').getBoundingClientRect(), scene = $('shop-scene').getBoundingClientRect();
    for (let i = 0; i < 5; i++) {
      const coin = document.createElement('span'); coin.className = 'shop-flying-coin'; coin.textContent = '✦'; coin.setAttribute('aria-hidden', 'true');
      fly(coin, {x: wallet.left + i * 4, y: wallet.top}, {x: scene.left + scene.width * .33, y: scene.top + scene.height * .64}, i * 80);
    }
    const art = $('shop-item').getBoundingClientRect(), stock = $('shop-inventory').getBoundingClientRect();
    const shell = document.createElement('img'); shell.className = 'shop-flying-item'; shell.src = 'assets/shop/pepazo.webp'; shell.alt = '';
    fly(shell, {x: art.left + art.width / 2 - 37, y: art.top + art.height / 2 - 37}, {x: stock.left + 12, y: stock.top}, 200);
    $('shop-inventory').classList.remove('is-celebrating');
    requestAnimationFrame(() => $('shop-inventory').classList.add('is-celebrating'));
  }
  $('shop-scene').addEventListener('click', () => talk());
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
