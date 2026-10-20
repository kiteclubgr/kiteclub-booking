/* Read local confirmation only; all grants remain in the signed webhook. */
(function () {
  const root = document.querySelector('[data-poll-url]');
  if (!root) return;
  const copy = document.getElementById('payment-status-copy');
  const deadline = Date.now() + 60000;
  let timer;
  function stop() { clearTimeout(timer); }
  function delayed() {
    stop();
    if (copy) copy.textContent = root.dataset.language === 'en' ? 'Confirmation is taking longer than expected. This does not mean payment failed. Check the status or contact the school. Do not pay again.' : 'Η επιβεβαίωση καθυστερεί. Αυτό δεν σημαίνει ότι η πληρωμή απέτυχε. Πάτησε «Έλεγχος κατάστασης» ή επικοινώνησε με τη σχολή. Μην επαναλάβεις την πληρωμή.';
  }
  async function check() {
    if (Date.now() >= deadline) return delayed();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(root.dataset.pollUrl, {cache:'no-store', credentials:'same-origin', signal:controller.signal});
      if (response.status === 401 || response.status === 403 || response.redirected) return delayed();
      if (response.ok) {
        const state = await response.json();
        if (state.confirmed === true || ['failed','expired'].includes(state.state)) {
          stop(); location.reload(); return;
        }
      }
    } catch (_) { /* Retry transient network errors within the bounded window. */ }
    finally { clearTimeout(timeout); }
    timer = setTimeout(check, 2000);
  }
  timer = setTimeout(check, 1500);
  window.addEventListener('pagehide', stop, {once:true});
})();

