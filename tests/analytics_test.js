#!/usr/bin/env node
'use strict';
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '..');
function render(id) {
  return execFileSync('python3', ['-c',
    'import sys; from scripts.build_discovery import analytics_tag; print(analytics_tag({"google_analytics_id":sys.argv[1]}))', id],
    { cwd: root, encoding: 'utf8' }).trim();
}
assert.equal(render(''), '', 'A missing ID must emit no Analytics scripts');
const id = 'G-TEST000001';
const markup = render(id);
const scripts = [...markup.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.filter(script => script[1].includes('src=')).length, 1);
assert(markup.includes(`<script async src="https://www.googletagmanager.com/gtag/js?id=${id}"></script>`));
assert(markup.includes(`gtag('config', '${id}');`), 'Search Console needs the literal standard config call');
assert(!markup.includes('__GA4_MEASUREMENT_ID__'));
function run(navigator = {}) {
  const context = { URL, Date, navigator,
    location: { href: 'https://example.test/legal/?q=private-search#private-fragment' },
    document: { title: 'Legal search', referrer: 'https://example.test/?email=private-referrer' } };
  context.window = context;
  vm.createContext(context);
  for (const script of scripts) if (!script[1].includes('src=')) vm.runInContext(script[2], context);
  return context;
}
for (const navigator of [{}, { globalPrivacyControl: true }, { doNotTrack: '1' }]) {
  const context = run(navigator);
  const optedOut = navigator.globalPrivacyControl === true || navigator.doNotTrack === '1';
  assert.equal(context['ga-disable-' + id], optedOut);
  const queue = context.dataLayer;
  const serialized = JSON.stringify(queue);
  for (const privateValue of ['private-search', 'private-fragment', 'private-referrer']) {
    assert(!serialized.includes(privateValue));
  }
  assert.equal(queue.filter(event => event[0] === 'config').length, 1);
  assert.equal(queue.filter(event => event[0] === 'event').length, 0, 'No duplicate manual page view');
  assert.equal(queue[0][0], 'set', 'Privacy defaults must precede Google configuration');
  assert.equal(queue[0][1].page_location, 'https://example.test/legal/');
  assert.equal(queue[0][1].page_referrer, 'https://example.test/');
  assert.equal(queue[0][1].allow_google_signals, false);
  assert.equal(queue[0][1].allow_ad_personalization_signals, false);
  assert.equal(queue.find(event => event[0] === 'config').length, 2, 'Preserve the unmodified standard config call');
}
console.log('Standard Google snippet, privacy defaults, opt-out flags, URL sanitization, and single configuration checks passed.');
