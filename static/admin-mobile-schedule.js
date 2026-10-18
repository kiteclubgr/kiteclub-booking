(()=>{
 const mobile=window.matchMedia('(max-width:900px)');
 const slots=document.querySelector('.mobile-slots');
 if(slots){slots.open=!mobile.matches;mobile.addEventListener('change',event=>{slots.open=!event.matches;});}
 const details=document.getElementById('mobileBookingDetails');
 const slotDialog=document.getElementById('mobileSlotDetails');
 if(!details) return;
 let selected=null,selectedSlot=null,previousFocus=null;
 const set=(id,value)=>{document.getElementById(id).textContent=value;};
 const show=dialog=>{previousFocus=document.activeElement;dialog.showModal();};
 const close=dialog=>{dialog.close();if(previousFocus)previousFocus.focus();};
 document.querySelectorAll('[data-booking-info]').forEach(button=>button.addEventListener('click',()=>{
  selected=JSON.parse(button.dataset.bookingInfo);
  set('mobileDetailName',selected.name);set('mobileDetailStatus',selected.label);
  const start=selected.time.slice(0,5),[hours,minutes]=start.split(':').map(Number);
  const endMinutes=hours*60+minutes+Number(selected.duration)*60;
  const end=String(Math.floor(endMinutes/60)%24).padStart(2,'0')+':'+String(endMinutes%60).padStart(2,'0');
  set('mobileDetailTime',selected.date.split('-').reverse().join('/')+' · '+start+'–'+end+' · '+selected.duration+' ώρες (κράτηση)');
  set('mobileDetailInstructor','Εκπαιδευτής: '+selected.instructor);set('mobileDetailSpot','Spot: '+selected.spot);
  const editable=['confirmed','pending_payment','booked'].includes(selected.status);
  document.getElementById('mobileEditBooking').hidden=!editable;
  document.getElementById('mobileBookingLocked').hidden=editable;
  document.getElementById('mobileBookingHistory').href=selected.history;show(details);
 }));
 document.getElementById('mobileEditBooking').addEventListener('click',()=>{
  if(!selected || !['confirmed','pending_payment','booked'].includes(selected.status)) return;
  close(details);
  window.openEditBooking(selected.id,selected.studentId,selected.date,selected.time,selected.instructorId,selected.duration,selected.payment==='pending'||selected.status==='pending_payment'?'pending':'booked');
 });
 document.querySelectorAll('[data-slot-id]').forEach(button=>button.addEventListener('click',()=>{
  selectedSlot=button.dataset.slotId;
  set('mobileSlotCaption',button.dataset.slotTime+' · '+button.dataset.slotInstructor+' · '+button.textContent.trim());
  document.getElementById('mobileSlotForm').action='/admin/slot/'+selectedSlot+'/manual-state';
  const state=document.getElementById('mobileSlotState');state.value=button.dataset.slotStatus==='standby'?'open':button.dataset.slotStatus;
  document.getElementById('mobileSlotForm').hidden=!['open','closed','standby'].includes(button.dataset.slotStatus);
  document.getElementById('mobileBookSlot').hidden=!['open','closed','standby'].includes(button.dataset.slotStatus);
  show(slotDialog);
 }));
 document.getElementById('mobileBookSlot').addEventListener('click',()=>{close(slotDialog);window.openBookingModal(Number(selectedSlot));});
 document.querySelectorAll('[data-close-mobile-dialog]').forEach(button=>button.addEventListener('click',()=>close(button.closest('dialog'))));
 [details,slotDialog].forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientY<r.top||event.clientY>r.bottom||event.clientX<r.left||event.clientX>r.right)close(dialog);}}));
})();
