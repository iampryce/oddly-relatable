#!/usr/bin/env node
// AP-84B3 local stop timer (D1-6, addition A1: the manual stop backup required by owner decision D1-5).
//
// Runs on the LOCAL machine. It has no network access and uses no credential. It prints an alert at each
// approved milestone and at each console checkpoint, so the operator can stop the Pod by hand in the RunPod web
// console. It is independent of the Pod and of the on-Pod watchdog: it works if the watchdog never started,
// crashed or could not authenticate. It cannot stop the Pod itself, and none of its alerts extends a limit.
//
//   node studio/tools/ap84b3/stop-timer.mjs --start <Pod start time, ISO 8601>
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadLock} from '../../lib/experiment-spec.mjs';

const hms = s => `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')} min`;

// The full alert schedule for a Pod started at startMs (milliseconds since the epoch).
export function schedule(lock, startMs) {
  const L = lock.limits, M = L.milestoneSeconds, out = [];
  const add = (seconds, kind, message) => out.push({seconds, at: new Date(startMs + seconds * 1000).toISOString(), kind, message});
  for (let s = L.consoleCheckpointSeconds; s < M.watchdogStop; s += L.consoleCheckpointSeconds) {
    add(s, 'checkpoint', `Console checkpoint (${hms(s)}): read the balance and displayed usage, reconcile with the watchdog estimate. Stop the Pod if either cannot be read, they differ by more than $${L.reconciliationToleranceUSD}, or either has reached $${L.watchdogEstimateStopUSD}.`);
  }
  add(M.noNewGeneration, 'milestone', `${hms(M.noNewGeneration)}: no new generation or retry may start.`);
  add(M.transfersComplete, 'milestone', `${hms(M.transfersComplete)}: all transfers must be complete and verified. Anything not verified locally is not retained.`);
  add(M.timerAlert, 'alert', `${hms(M.timerAlert)}: prepare to stop the Pod manually. Open the RunPod web console now.`);
  add(M.watchdogStop, 'milestone', `${hms(M.watchdogStop)}: the watchdog stops the Pod now. Confirm in the console that it has stopped.`);
  add(M.manualStop, 'stop', `${hms(M.manualStop)}: IF THE POD IS STILL RUNNING, STOP IT IN THE WEB CONSOLE NOW (Stop, then Terminate).`);
  add(M.absoluteLimit, 'limit', `${hms(M.absoluteLimit)}: ABSOLUTE LIMIT. The Pod must not be running. Terminate it and confirm no Pod, volume or network storage remains.`);
  return out.sort((a, b) => a.seconds - b.seconds || a.kind.localeCompare(b.kind));
}

// Alerts that are due at nowMs and have not been announced yet (announced: a Set of "seconds:kind").
export function due(alerts, startMs, nowMs, announced) {
  return alerts.filter(a => nowMs >= startMs + a.seconds * 1000 && !announced.has(`${a.seconds}:${a.kind}`));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const i = process.argv.indexOf('--start');
    const startMs = i >= 0 ? Date.parse(process.argv[i + 1]) : NaN;
    if (Number.isNaN(startMs)) throw new Error('usage: stop-timer.mjs --start <Pod start time, ISO 8601, e.g. 2026-11-20T14:05:00Z>');
    if (startMs > Date.now()) throw new Error('the Pod start time is in the future');
    const {lock} = loadLock();                                                  // refuses unless the lock is owner-approved
    const alerts = schedule(lock, startMs), announced = new Set();
    console.log(`AP-84B3 stop timer. Pod started ${new Date(startMs).toISOString()}. This timer cannot stop the Pod: you stop it in the web console.`);
    for (const a of alerts) console.log(`  ${a.at}  ${a.message}`);
    const tick = () => {
      for (const a of due(alerts, startMs, Date.now(), announced)) {
        announced.add(`${a.seconds}:${a.kind}`);
        console.log(`\u0007\n>>> ${new Date().toISOString()}  ${a.message}`);
      }
      if (announced.size === alerts.length) { console.log('All alerts announced. Confirm the Pod is terminated.'); process.exit(0); }
    };
    tick();
    setInterval(tick, 1000);
  } catch (e) { console.error(`stop-timer: ${e.message}`); process.exit(1); }
}
