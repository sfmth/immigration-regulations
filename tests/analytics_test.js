#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../assets/site/analytics.js'), 'utf8');
function run(id, navigator = {}) {
  const scripts = [];
  const context = { URL, Date, navigator,
    window: { IMMIGRATION_SITE: { google_analytics_id: id }, location: { href: 'https://example.test/legal/?q=private-search#private-fragment' } },
    document: { title: 'Legal search', referrer: 'https://example.test/?email=private-referrer', createElement: () => ({}), head: { append: script => scripts.push(script) } } };
  vm.runInNewContext(source, context);
  return { scripts, queue: context.window.dataLayer || [] };
}
for (const [id, navigator] of [['', {}], ['invalid', {}], ['G-TEST000001', { globalPrivacyControl: true }], ['G-TEST000001', { doNotTrack: '1' }]]) {
  const result = run(id, navigator);
  assert.equal(result.scripts.length, 0);
  assert.equal(result.queue.length, 0);
}
const result = run('G-TEST000001');
assert.equal(result.scripts.length, 1);
assert.equal(result.scripts[0].src, 'https://www.googletagmanager.com/gtag/js?id=G-TEST000001');
const serialized = JSON.stringify(result.queue);
assert(!serialized.includes('private-search'));
assert(!serialized.includes('private-fragment'));
assert(!serialized.includes('private-referrer'));
assert.equal(result.queue.filter(event => event[1] === 'page_view').length, 1);
const config = result.queue.find(event => event[0] === 'config')[2];
assert.equal(config.allow_google_signals, false);
assert.equal(config.allow_ad_personalization_signals, false);
assert.equal(config.page_location, 'https://example.test/legal/');
console.log('Analytics privacy signals, activation, URL sanitization, and single page-view checks passed.');
