// Shared assignment text is used by the player panel, roulette, admin and log.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({window:{addEventListener(){}}, document:{addEventListener(){}}});
vm.runInContext(fs.readFileSync(require.resolve('./data.js'), 'utf8'), context);
const text = (scope, requirements) => context.penaltyAssignmentText({
  scope, penalty:{baseId:'autofill'}, requirements
}, {player1:{displayName:'Ana'}, player2:{displayName:'Luis'}});
assert.match(text('ONE', {assignedPlayer:'player1', randomPositions:{player1:'MIDDLE'}}), /Ana · Posición: Mid/);
assert.doesNotMatch(text('ONE', {assignedPlayer:'player1', randomPositions:{player1:'MIDDLE'}}), /Luis/);
assert.match(text('BOTH', {randomPositions:{player1:'BOTTOM', player2:'UTILITY'}}), /Ana · Posición: ADC.*Luis · Posición: Support/);
assert.match(text('ONE', {assignedPlayer:'player2', randomPositions:{}}), /Luis · Posición pendiente/);
assert.doesNotMatch(text('BOTH', {}), /Posición/);
assert.match(text('ONE', {assignedPlayer:'player1',roleSelectionVersion:2,randomPositions:{player1:'MIDDLE'},randomSecondaryPositions:{player1:'BOTTOM'}}), /Ana · Primer rol: Mid · Segundo rol: ADC/);
assert.match(text('ONE', {assignedPlayer:'player1',roleSelectionVersion:2,randomPositions:{},randomSecondaryPositions:{}}), /Roles pendientes.*ambos integrantes/);
// Exercise the production panel and roulette renderers with a small DOM adapter.
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {style:{}, hidden:true, classList:{toggle(){}}, addEventListener(){}});
  return elements.get(id);
};
context.document.getElementById = element;
context.setTimeout = () => 0;
context.clearTimeout = () => {};
vm.runInContext(fs.readFileSync(require.resolve('./roulette-core.js'), 'utf8'), context);
context.ShellRoulette = context.window.ShellRoulette;
context.RouletteWindow = {onSpin(){}};
vm.runInContext(fs.readFileSync(require.resolve('./player.js'), 'utf8'), context);
const target = {id:'target', player1:{displayName:'Ana'}, player2:{displayName:'Luis'}};
const penalty = {baseId:'autofill', name:'Polivalente · AMBOS', icon:'🎲', scope:'BOTH', desc:'Cada uno juega su posición sorteada.'};
const instance = {penalty, scope:'BOTH', status:'ACTIVE', requirements:{roleSelectionVersion:2,randomPositions:{player1:'MIDDLE',player2:'BOTTOM'},randomSecondaryPositions:{player1:'BOTTOM',player2:'UTILITY'}}};
context.fixture = {target, instance};
vm.runInContext('activeDuo = fixture.target; allDuos = [fixture.target];', context);
const card = context.playerPenaltyCard(instance);
assert.match(card, /Ana · Primer rol: Mid · Segundo rol: ADC.*Luis · Primer rol: ADC · Segundo rol: Support/);
assert.match(context.playerPenaltyCard({...instance,status:'COMPLETED'}), /penalty-status-completed/);
vm.runInContext(`activeDuo = {outgoingShellAttacks:[{targetTeamId:'target',targetName:'Rival',status:'PENALTY_ASSIGNED',result:fixture.instance.penalty,requirements:fixture.instance.requirements}]}; renderOutgoingShells();`, context);
assert.match(element('outgoing-shells-list').innerHTML, /Ana · Primer rol: Mid · Segundo rol: ADC.*Luis · Primer rol: ADC · Segundo rol: Support/);
const assignment = context.penaltyAssignmentText(instance, target);
const state = {phase:'spinning',teamName:'Demo',startedAt:Date.now(),holdMs:13500,penalty:{...penalty,assignment}};
context.showRouletteInline(state);
assert.equal(element('inline-roulette-assignment').hidden, true, 'position stays hidden during the spin');
state.startedAt -= context.ShellRoulette.revealMs;
context.showRouletteInline(state);
assert.equal(element('inline-roulette-assignment').hidden, false);
assert.equal(element('inline-roulette-assignment').textContent, assignment);

// The external popup consumes the same assignment after the reveal.
const handlers = {};
const popup = vm.createContext({window:{opener:{postMessage(){}},addEventListener(type,fn){handlers[type]=fn;}},
  document:{getElementById:element},location:{origin:'http://test',hash:'#'+'a'.repeat(32)},
  sessionStorage:{removeItem(){}},setTimeout:()=>0,clearTimeout(){}});
vm.runInContext(fs.readFileSync(require.resolve('./roulette-core.js'), 'utf8'), popup);
popup.ShellRoulette = popup.window.ShellRoulette;
vm.runInContext(fs.readFileSync(require.resolve('./roulette-popup.js'), 'utf8'), popup);
handlers.message({origin:'http://test',source:popup.window.opener,data:{type:'pepes-roulette-state',channel:'a'.repeat(32),state}});
assert.equal(element('roulette-assignment').hidden, false);
assert.equal(element('roulette-assignment').textContent, assignment);
console.log('Polivalente: shared text, pending/completed cards, outgoing attacks, inline reveal and external roulette OK');
