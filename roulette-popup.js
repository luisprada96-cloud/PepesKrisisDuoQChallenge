(() => {
  'use strict';
  const channel = location.hash.slice(1);
  const parent = window.opener;
  let stop = () => {};
  let currentState = null;
  const spinButton = document.getElementById('roulette-spin');
  if (parent) {
    // window.open clones sessionStorage: this display has no need for a team session.
    sessionStorage.removeItem('pepes_player_token');
    sessionStorage.removeItem('pepes_player_session');
  }
  function valid(state) {
    if (!state || typeof state.teamName !== 'string') return false;
    if (state.phase === 'prepared') return typeof state.attackId === 'string' && typeof state.message === 'string';
    if (state.phase === 'unavailable') return typeof state.message === 'string';
    if (state.phase === 'waiting') return true;
    if (state.phase === 'error') return typeof state.message === 'string';
    return state.phase === 'spinning' && Number.isFinite(state.startedAt) && Number.isFinite(state.holdMs) && state.holdMs >= 0 &&
      state.penalty && (state.penalty.assignment === undefined || typeof state.penalty.assignment === 'string') && ['name', 'icon', 'desc'].every(key => typeof state.penalty[key] === 'string');
  }
  window.addEventListener('message', event => {
    if (event.origin !== location.origin || event.source !== parent || event.data?.channel !== channel || event.data.type !== 'pepes-roulette-state') return;
    const state = event.data.state;
    if (!valid(state)) return;
    stop();
    currentState = state;
    spinButton.hidden = !(state.phase === 'prepared' || (state.phase === 'error' && state.canSpin && typeof state.attackId === 'string'));
    spinButton.disabled = false;
    document.getElementById('roulette-team').textContent = state.teamName || 'RULETA';
    stop = ShellRoulette.animate(state, current => {
      document.getElementById('roulette-icon').textContent = current.icon;
      document.getElementById('roulette-name').textContent = current.name;
      document.getElementById('roulette-desc').textContent = current.desc;
      const assignment = document.getElementById('roulette-assignment');
      assignment.textContent = current.assignment || '';
      assignment.hidden = !current.revealed || !current.assignment;
      document.getElementById('roulette-box').classList.toggle('revealed', current.revealed);
    });
  });
  spinButton.addEventListener('click', () => {
    if (!parent || parent.closed || !currentState || spinButton.disabled) return;
    spinButton.disabled = true;
    parent.postMessage({type: 'pepes-roulette-spin', channel, attackId: currentState.attackId}, location.origin);
  });
  if (parent && /^[a-f0-9]{32}$/.test(channel)) {
    parent.postMessage({type: 'pepes-roulette-ready', channel}, location.origin);
  }
})();
