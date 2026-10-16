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

// Each option owns its flag; shared +1 prefixes can select US or Canada.
const phonePrefix = document.getElementById('reg-phone-prefix');
const countryFlag = document.getElementById('reg-country-flag');
if (phonePrefix && countryFlag) {
  const updatePhoneFlag = () => {
    const selected = phonePrefix.selectedOptions[0];
    if (!selected) return;
    countryFlag.src = selected.dataset.flag;
    countryFlag.alt = selected.dataset.country;
  };
  phonePrefix.addEventListener('input', updatePhoneFlag);
  phonePrefix.addEventListener('change', updatePhoneFlag);
  window.addEventListener('pageshow', updatePhoneFlag);
  updatePhoneFlag();
}
