// node --test: the Overview page's disk line, the yellow warning (80%) and the red banner (90%) naming the biggest users.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {biggestText, diskBanner, diskLine, diskNotice, reportLine, size} from './diskView.ts';

const G = 1024 ** 3;
const biggest = [
  {key: 'images', label: 'Docker images', bytes: 38 * G}, {key: 'releases', label: 'Release folders', bytes: 21 * G},
  {key: 'backups', label: 'Backups', bytes: 7.5 * G}, {key: 'media', label: 'Media (videos, stills, voice)', bytes: 2.7 * G},
];
const d = (over: any = {}) => ({size: 96 * G, used: 87 * G, free: 9.6 * G, percent: 91, level: 'critical', biggest,
  report: {age_days: 0.2, stale: false, mode: 'dry-run', would_free: {total: 30 * G}}, ...over});

test('sizes are shown as df -h counts them', () => {
  assert.equal(size(0), '0 B');
  assert.equal(size(9.6 * G), '9.6 GB');
  assert.equal(size(96 * G), '96 GB');
  assert.equal(size(65 * 1024 ** 2), '65 MB');
  assert.equal(size(undefined), '—');
});

test('the disk line: used, size, percent and free', () => {
  assert.equal(diskLine(d()), '87 GB used of 96 GB (91%) · 9.6 GB free');
  assert.equal(diskLine(null), '');
});

test('no banner below 90%: the yellow level (80%) is a line in the card; a red banner from 90% naming the biggest users', () => {
  assert.equal(diskBanner(d({level: 'ok', percent: 54})), null);
  assert.equal(diskNotice(d({level: 'ok', percent: 54})), '');
  assert.equal(diskBanner(d({level: 'warn', percent: 82, free: 17 * G})), null, 'not a banner');
  assert.match(diskNotice(d({level: 'warn', percent: 82, free: 17 * G})), /^The disk is 82% full \(17 GB free\)\. On the server, maintenance\.sh without options \(a dry run\)/);
  assert.equal(diskNotice(d()), '', 'at 90% it is the banner instead');
  const b = diskBanner(d());
  assert.equal(b?.tone, 'bad');
  assert.match(b!.text, /91% full \(9\.6 GB free\): deploys and new clips can fail\./);
  assert.match(b!.text, /Biggest: docker images 38 GB, release folders 21 GB, backups 7\.5 GB, media \(videos, stills, voice\) 2\.7 GB\./);
  assert.match(b!.text, /about 30 GB could be freed/);
});

test('the red banner says when there is no report, or when it is old', () => {
  assert.match(diskBanner(d({biggest: [], report: null}))!.text, /No housekeeping report yet/);
  assert.match(diskBanner(d({report: {age_days: 10.2, stale: true, mode: 'dry-run', would_free: {}}}))!.text, /\(report 10 days old\)/);
});

test('the report line under the card', () => {
  assert.equal(reportLine(d()), 'Housekeeping report from today (dry run) · --apply would free about 30 GB');
  assert.equal(reportLine(d({report: {age_days: 3, stale: false, mode: 'apply', freed: {total: 11 * G}}})), 'Housekeeping report from 3 day(s) ago (applied) · freed 11 GB');
  assert.match(reportLine(d({report: {age_days: 10, stale: true, mode: 'dry-run', would_free: {total: 0}}})), /old: the weekly report has not run/);
  assert.equal(reportLine(d({report: null, report_problem: 'No housekeeping report yet.'})), 'No housekeeping report yet.');
  assert.equal(biggestText(d(), 2), 'docker images 38 GB, release folders 21 GB');
});
