// Optional dev check: npm install --no-save jsdom; run Python fixture test first.
const fs=require('fs'),path=require('path'),os=require('os');const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync(path.join(os.tmpdir(),'kite-students-fixture.html'),'utf8'),{url:'http://localhost/admin#students',runScripts:'outside-only'});const w=dom.window,d=w.document;
w.matchMedia=()=>({matches:true,addEventListener:()=>{}});w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};w.alert=()=>{};w.confirm=()=>true;
const errors=[];for(const script of d.querySelectorAll('script:not([src])')){try{w.eval(script.textContent)}catch(e){errors.push(e.message)}}
w.eval(fs.readFileSync(path.join(__dirname,'static/admin-students.js'),'utf8'));
const assert=(v,m)=>{if(!v)throw Error(m)},rows=[...d.querySelectorAll('.admin-student-row')],visible=()=>rows.filter(r=>!r.hidden);
assert(rows.length===7&&visible().length===5,'Initial pagination');d.querySelector('#studentNextPage').click();assert(visible().length===2,'Next page');d.querySelector('#studentPrevPage').click();assert(visible().length===5,'Previous page');
d.querySelector('[data-credit-filter="positive"]').click();assert(visible().length&&visible().every(r=>Number(r.dataset.credits)>0),'Positive filter');
d.querySelector('[data-credit-filter="empty"]').click();assert(visible().every(r=>Number(r.dataset.credits)<=0),'Empty/negative filter');
d.querySelector('[data-credit-filter="all"]').click();const target=rows[0];const search=d.querySelector('#adminStudentSearch');search.value=target.querySelector('.student-card-email').textContent.trim();search.dispatchEvent(new w.Event('input'));assert(visible().length===1&&visible()[0]===target,'Email search');
search.value='NONEXISTENT-123';search.dispatchEvent(new w.Event('input'));assert(!visible().length&&!d.querySelector('#adminStudentNoResults').hidden,'Empty search');
search.value='';search.dispatchEvent(new w.Event('input'));
const btn=rows[0].querySelector('[data-adjust-url]');btn.click();assert(d.querySelector('#studentCreditsDialog').open,'Credits opens');assert(d.querySelector('#studentCreditsForm').action.endsWith(btn.dataset.adjustUrl),'Correct student adjustment endpoint');assert(d.querySelector('#studentCreditsForm [name="_csrf_token"]').value,'CSRF retained');
d.querySelector('#studentCreditAmount').value='-1';d.querySelector('#studentCreditNote').value='DO NOT SAVE';d.querySelector('#studentCreditsDialog [data-close-student-dialog]').click();
rows[1].querySelector('[data-adjust-url]').click();assert(!d.querySelector('#studentCreditAmount').value&&!d.querySelector('#studentCreditNote').value,'Reset per student avoids stale adjustment');d.querySelector('#studentCreditsDialog [data-close-student-dialog]').click();
d.querySelector('#openNewStudent').click();assert(d.querySelector('#newStudentDialog').open,'Create opens');const form=d.querySelector('#newStudentDialog form');assert(form.querySelector('[name="email"]')&&form.querySelector('[name="password"]')&&form.querySelector('[name="initial_service"]')&&form.querySelector('[name="_csrf_token"]'),'Original create fields');d.querySelector('#newStudentDialog [data-close-student-dialog]').click();
assert(!errors.length,errors.join(';'));
console.log('PASS DOM: search, positive/zero/negative filters, pagination, empty state, correct credit target/CSRF, reset on switch, create and cancel; no JS errors');w.close();
