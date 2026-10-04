(() => {
  'use strict';
  const options = [
    {name: 'POLIVALENTE', icon: '🎲'}, {name: 'SIN CAMPEÓN FAVORITO', icon: '🚫'},
    {name: 'CAMPEÓN ALEATORIO', icon: '🎯'}, {name: 'SIN FLASH', icon: '⚡'},
    {name: 'FLASH AL OTRO LADO', icon: '🔄'},
    {name: 'DEVUELVE EL CAPARAZÓN', icon: '↩️'}
  ];
  // Keep the original 22-step slowdown, measured from one shared start time.
  const steps = [0];
  for (let i = 1; i < 22; i++) steps.push(steps[i - 1] + 70 + i * 14);
  const revealMs = steps[steps.length - 1];

  function frame(state, now = Date.now()) {
    if (state.phase === 'prepared') return {name: 'LISTA PARA GIRAR', icon: '🎰', desc: state.message, revealed: false, done: false, nextIn: null};
    if (state.phase === 'unavailable') return {name: 'VUELVE AL PANEL', icon: '🐢', desc: state.message, revealed: false, done: true, nextIn: null};
    if (state.phase === 'waiting') return {name: 'PREPARANDO...', icon: '🎰', desc: '', revealed: false, done: false, nextIn: null};
    if (state.phase === 'error') return {name: 'NO SE PUDO GIRAR', icon: '⚠️', desc: state.message, revealed: true, done: true, nextIn: null};
    const elapsed = Math.max(0, now - state.startedAt);
    if (elapsed >= revealMs) {
      return {name: (state.penalty.name || 'CASTIGO').toUpperCase(), icon: state.penalty.icon || '⚡', desc: state.penalty.desc || '', assignment: state.penalty.assignment || '', revealed: true,
        done: elapsed >= revealMs + state.holdMs, nextIn: Math.max(0, revealMs + state.holdMs - elapsed)};
    }
    let i = 0;
    while (i + 1 < steps.length && elapsed >= steps[i + 1]) i++;
    return {...options[i % options.length], desc: '', revealed: false, done: false, nextIn: steps[i + 1] - elapsed};
  }

  function animate(state, render, onDone) {
    let timer;
    let stopped = false;
    function tick() {
      if (stopped) return;
      const current = frame(state);
      render(current);
      if (current.done) {
        stopped = true;
        if (onDone) onDone();
      } else if (current.nextIn !== null) {
        timer = setTimeout(tick, Math.max(1, current.nextIn));
      }
    }
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }
  window.ShellRoulette = Object.freeze({frame, animate, revealMs});
})();
