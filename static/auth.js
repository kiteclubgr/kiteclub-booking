// Password visibility is local to the form; it never submits or stores a value.
document.querySelectorAll('.kc-password-toggle').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(visible));
    button.setAttribute('aria-label', visible ? 'Απόκρυψη κωδικού' : 'Εμφάνιση κωδικού');
  });
});
