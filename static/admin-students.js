(()=>{
 const search=document.getElementById('adminStudentSearch');if(!search)return;
 const rows=[...document.querySelectorAll('.admin-student-row')];const size=5;let page=0,filter='all',opener=null;
 const normalized=value=>value.toLocaleLowerCase('el-GR').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
 function render(){
  const q=normalized(search.value.trim());
  const selected=rows.filter(row=>{const c=Number(row.dataset.credits);return(!q||normalized(row.dataset.search).includes(q))&&(filter==='all'||(filter==='positive'?c>0:c<=0));});
  const count=Math.max(1,Math.ceil(selected.length/size));page=Math.min(page,count-1);
  rows.forEach(row=>row.hidden=true);selected.slice(page*size,(page+1)*size).forEach(row=>row.hidden=false);
  document.getElementById('adminStudentNoResults').hidden=selected.length!==0;
  document.getElementById('studentPageLabel').textContent=selected.length?'Εμφανίζονται '+(page*size+1)+'–'+Math.min((page+1)*size,selected.length)+' από '+selected.length:'0 αποτελέσματα';
  document.getElementById('studentPrevPage').disabled=page===0;document.getElementById('studentNextPage').disabled=page>=count-1;
 }
 search.addEventListener('input',()=>{page=0;render();});
 document.querySelectorAll('[data-credit-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.creditFilter;page=0;document.querySelectorAll('[data-credit-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();}));
 document.getElementById('studentPrevPage').addEventListener('click',()=>{page--;render();});document.getElementById('studentNextPage').addEventListener('click',()=>{page++;render();});
 const credits=document.getElementById('studentCreditsDialog'),create=document.getElementById('newStudentDialog');
 document.getElementById('openNewStudent').addEventListener('click',event=>{opener=event.currentTarget;create.showModal();});
 document.querySelectorAll('[data-adjust-url]').forEach(button=>button.addEventListener('click',()=>{
  opener=button;const form=document.getElementById('studentCreditsForm');form.reset();form.action=button.dataset.adjustUrl;
  document.getElementById('studentCreditsName').textContent=button.dataset.studentName;
  document.getElementById('studentCreditsBalance').textContent='Διαθέσιμο υπόλοιπο: '+button.dataset.balance+' ώρες';credits.showModal();
 }));
 [credits,create].forEach(dialog=>{dialog.addEventListener('close',()=>{if(opener)opener.focus();});dialog.querySelector('[data-close-student-dialog]').addEventListener('click',()=>dialog.close());dialog.addEventListener('click',event=>{const box=dialog.getBoundingClientRect();if(event.target===dialog&&(event.clientY<box.top||event.clientY>box.bottom||event.clientX<box.left||event.clientX>box.right))dialog.close();});});
 render();
})();
