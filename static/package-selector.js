/* Follow the server-rendered package URL so price and checkout stay in sync. */
(function () {
  const select = document.getElementById('package-select');
  if (!select) return;
  select.addEventListener('change', function () {
    const target = new URL(select.value, window.location.origin);
    if (target.origin === window.location.origin) window.location.assign(target.href);
  });
})();
