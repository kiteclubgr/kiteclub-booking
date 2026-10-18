const fs=require('fs');const {JSDOM}=require('jsdom');
const dom=new JSDOM(fs.readFileSync(require('path').join(require('os').tmpdir(),'kite-mobile-fixture.html'),'utf8'),{url:'http://localhost/admin?date=17%2F10%2F2026#day',runScripts:'outside-only'});const w=dom.window;
w.matchMedia=()=>({matches:true,addEventListener:()=>{}});w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
const errors=[];w.alert=()=>{};w.confirm=()=>true;
for(const script of dom.window.document.querySelectorAll('script:not([src])')) {try{w.eval(script.textContent)}catch(e){errors.push(e.message)}}
w.eval(fs.readFileSync(require('path').join(__dirname,'static/admin-mobile-schedule.js'),'utf8'));
const d=w.document;const assert=(v,m)=>{if(!v)throw Error(m)};
assert(!d.querySelector('.mobile-slots').open,'Mobile slots must start collapsed');
const buttons=[...d.querySelectorAll('[data-booking-info]')];
const active=buttons.find(b=>JSON.parse(b.dataset.bookingInfo).status==='confirmed');const locked=buttons.find(b=>JSON.parse(b.dataset.bookingInfo).status==='completed');
active.click();assert(d.querySelector('#mobileBookingDetails').open,'Details should open');assert(!d.querySelector('#mobileEditBooking').hidden,'Active edit visible');assert(d.querySelector('#mobileBookingHistory').href.endsWith('/history'),'History URL');
d.querySelector('#mobileEditBooking').click();assert(d.querySelector('#editBookingModal').classList.contains('open'),'Existing edit modal');assert(d.querySelector('#editBookingForm').action.includes('/admin/booking/'),'Existing edit endpoint');assert(d.querySelector('#editOriginalDuration').value==='1','Stale edit guard');
w.closeEditBookingModal();locked.click();assert(d.querySelector('#mobileEditBooking').hidden,'Completed cannot edit');assert(!d.querySelector('#mobileBookingLocked').hidden,'Completed lock message');
d.querySelector('#mobileBookingDetails [data-close-mobile-dialog]').click();assert(!d.querySelector('#mobileBookingDetails').open,'Close works');
assert(errors.length===0,errors.join(';'));
console.log('PASS DOM: compact date labels and spots, collapsed creation, booking details, edit routes/CSRF/stale-duration field, history, locked completion, dialog close; no JS errors');
w.close();
