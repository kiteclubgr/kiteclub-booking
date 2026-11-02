// Regression: in-page dashboard links must activate the requested Admin section.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const source = fs.readFileSync('templates/admin.html', 'utf8');
const start = source.indexOf("  const buttons=[...document.querySelectorAll('.admin-tab[data-tab]')];");
const end = source.indexOf("  const modal=document.getElementById('bookingModal');", start);
assert(start >= 0 && end > start, 'Admin navigation block must be present');
const html = ['today', 'day', 'students', 'instructors'].map(name =>
  `<button class="admin-tab" data-tab="${name}">${name}</button><section class="tab-panel" id="tab-${name}"></section>`
).join('') + '<a id="students-link" href="#students">Students</a>';
async function check() {
  const dom = new JSDOM(html, { url: 'http://localhost/admin', runScripts: 'outside-only' });
  const w = dom.window;
  w.eval('(function(){' + source.slice(start, end) + '})();');
  const active = () => w.document.querySelector('.tab-panel.active')?.id;
  assert.equal(active(), 'tab-today');
  w.document.querySelector('[data-tab=day]').click();
  assert.equal(active(), 'tab-day');
  w.document.querySelector('#students-link').click();
  await new Promise(resolve => w.setTimeout(resolve, 20));
  assert.equal(w.location.hash, '#students');
  assert.equal(active(), 'tab-students', 'Same-page anchor must reveal Students');
  w.location.hash = '#instructors';
  await new Promise(resolve => w.setTimeout(resolve, 20));
  assert.equal(active(), 'tab-instructors');
  w.location.hash = '#unknown';
  await new Promise(resolve => w.setTimeout(resolve, 20));
  assert.equal(active(), 'tab-instructors', 'Unknown hash must not hide every section');
  dom.window.close();
  console.log('PASS: Admin tab clicks, same-page anchors, hash navigation and unknown-hash safety');
}
check().catch(error => { console.error(error); process.exitCode = 1; });
