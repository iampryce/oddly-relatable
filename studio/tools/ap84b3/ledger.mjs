#!/usr/bin/env node
// AP-84B3 session ledger command line (cumulative limits, owner decision A2). Runs on the LOCAL machine.
//
//   ledger.mjs init     --run <folder> --run-id r-YYYYMMDD-HHMMSS          start the ledger in a new, empty run folder
//   ledger.mjs fund     --run <folder> --before <balance> --after <balance> record the single $10 deposit
//   ledger.mjs prepare  --run <folder> --balance <current balance>        prepare the next session (gives only what remains)
//   ledger.mjs close    --run <folder> --gpu "<GPU>" --rate <$/h> --start <ISO> --end <ISO> --consumed <$> --reason "<text>"
//   ledger.mjs close    --run <folder> --not-started --reason "<text>"    close a prepared session that was never deployed
//   ledger.mjs status   --run <folder>                                     print the verified ledger and the remaining allowance
//   ledger.mjs recover  --run <folder> --workflow Q|S --reason "<text>"   owner-approved frozen-graph recovery (see the runbook)
//
// Balances and consumption are read by a person from the provider's console: no account API key is used, so this
// tool cannot read billing itself. "consumed" is the higher of the balance method and the usage method.
// Every command refuses to run unless the experiment lock is owner-approved.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock, DECISIONS_FILE} from '../../lib/experiment-spec.mjs';
import * as L from '../../lib/experiment-ledger.mjs';

export function main(argv) {
  const arg = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : undefined; };
  const cmd = argv[0], runDir = arg('--run');
  if (!cmd || !runDir) throw new Error('usage: ledger.mjs init|fund|prepare|close|status|recover --run <run folder> [options]; see the header of this file');
  const {lock, sha256} = loadLock();                                            // refuses unless the lock is owner-approved
  switch (cmd) {
    case 'init': return summary(L.initLedger({runDir, lock, lockSha256: sha256, runId: arg('--run-id')}), lock);
    case 'fund': return summary(L.recordFunding({runDir, lock, balanceBeforeUSD: arg('--before'), balanceAfterUSD: arg('--after')}), lock);
    case 'prepare': { const p = L.prepareSession({runDir, lock, currentBalanceUSD: arg('--balance')}); return {...summary(p.ledger, lock), session: p.session, sessionEnv: p.sessionEnv}; }
    case 'close': {
      const c = argv.includes('--not-started')
        ? L.closeSession({runDir, lock, notStarted: true, reason: arg('--reason')})
        : L.closeSession({runDir, lock, gpu: arg('--gpu'), gpuRateUSDPerHour: arg('--rate'), startedAt: arg('--start'), endedAt: arg('--end'), consumedUSD: arg('--consumed'), reason: arg('--reason')});
      return {...summary(c.ledger, lock), closed: c.session, totals: c.totals, overLimit: c.overLimit,
        ...(c.overLimit ? {warning: 'The recorded totals exceed an approved limit. Return to the owner.'} : {})};
    }
    case 'status': return summary(L.readLedger(runDir, lock), lock);
    case 'recover': return summary(L.recoverFreeze({runDir, lock, workflow: arg('--workflow'), reason: arg('--reason'), decisionsFile: DECISIONS_FILE}), lock);
    default: throw new Error(`unknown command ${cmd}`);
  }
}
function summary(led, lock) {
  const a = L.allowance(lock, led.state), open = led.state.sessions.find(s => s.status === 'prepared');
  return {ledgerHead: led.head, runId: led.state.runId, funded: led.state.funded, sessions: led.state.sessions.map(s => ({number: s.number, status: s.status, ...(s.closed ? {runtimeSeconds: s.closed.runtimeSeconds, consumedUSD: s.closed.consumedUSD, reason: s.closed.reason} : {})})),
    freezes: Object.fromEntries(['Q', 'S'].map(w => [w, led.state.freezes[w] ? {graphSha256: led.state.freezes[w].graphSha256, fileSha256: led.state.freezes[w].fileSha256} : null])),
    sessionInProgress: open ? {number: open.number, ...open.prepared} : null, nextSession: a};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(main(process.argv.slice(2)), null, 1)); }
  catch (e) { console.error(`ledger: ${e.message}`); process.exit(1); }
}
