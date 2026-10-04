(() => {
  'use strict';
  const channel = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  let popup = null;
  let state = null;
  let spinHandler = null;

  function send() {
    if (popup && !popup.closed && state) {
      popup.postMessage({type: 'pepes-roulette-state', channel, state}, location.origin);
    }
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== popup || event.data?.channel !== channel) return;
    if (event.data.type === 'pepes-roulette-ready') send();
    if (state && event.data.type === 'pepes-roulette-spin' && event.data.attackId === state.attackId &&
        (state.phase === 'prepared' || (state.phase === 'error' && state.canSpin))) {
      if (spinHandler) spinHandler(state.attackId);
    }
  });

  function open() {
    try {
      // Opening the display never requests a spin; the popup's button sends that action.
      popup = window.open(`roulette.html#${channel}`, `pepes-roulette-${channel}`, 'popup=yes,width=680,height=460,resizable=yes,scrollbars=yes');
      if (!popup) return false;
      popup.focus();
      send();
      return true;
    } catch (_) { return false; }
  }
  function update(next) { state = next; send(); }
  function onSpin(handler) { spinHandler = handler; }
  window.RouletteWindow = Object.freeze({open, update, onSpin});
})();
