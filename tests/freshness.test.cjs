const test = require('node:test');
const assert = require('node:assert/strict');
const freshness = require('../site/freshness.js');

test('browser hides expired snapshots even without another deployment', () => {
  const data = {jobs: [
    {id: 'open', active: true, visible_until: '2026-10-13T00:00:00Z'},
    {id: 'closed', active: false, visible_until: '2026-10-13T00:00:00Z'},
    {id: 'legacy', active: true},
    {id: 'invalid', active: true, visible_until: 'invalid'},
    {id: 'deadline', active: true, visible_until: '2026-10-10T00:00:00Z'},
  ], freshness: {hidden_unverified: 3}};
  assert.deepEqual(freshness.currentJobs(data, Date.parse('2026-10-10T00:00:00Z')).map(j => j.id), ['open']);
  assert.equal(freshness.hiddenCount(data, Date.parse('2026-10-10T00:00:00Z')), 7);
  assert.deepEqual(freshness.currentJobs(data, Date.parse('2026-10-13T00:00:00Z')), []);
});
