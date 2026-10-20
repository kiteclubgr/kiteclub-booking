"""User-facing validation messages for the public purchase journey."""
from flask import request, session

MESSAGES = {
 'Πολλές αποτυχημένες προσπάθειες. Δοκίμασε ξανά σε 15 λεπτά.': 'Too many failed attempts. Try again in 15 minutes.',
 'Λάθος email ή password': 'Incorrect email or password.',
 'Συμπληρώστε σωστά όνομα, επώνυμο, email και τηλέφωνο.': 'Enter a valid first name, last name, email and mobile number.',
 'Ο κωδικός πρέπει να έχει τουλάχιστον 8 χαρακτήρες, γράμματα και αριθμούς και να ταιριάζει με την επιβεβαίωση.': 'Use at least 8 characters, including letters and numbers. Both passwords must match.',
 'Αποδεχτείτε τους Όρους Χρήσης, επιβεβαιώστε την ενημέρωση για το Απόρρητο και διαβάστε την ενημέρωση κινδύνων.': 'Accept the Terms of Use, acknowledge the Privacy Policy and read the participation agreement.',
 'Τα νομικά κείμενα ενημερώθηκαν. Ανανεώστε τη φόρμα και διαβάστε τις τρέχουσες εκδόσεις.': 'The legal documents have changed. Refresh the form and read the current versions.',
 'Έχουν γίνει πολλές εγγραφές. Δοκιμάστε ξανά αργότερα.': 'Too many registration attempts. Please try again later.',
 'Το email χρησιμοποιείται ήδη. Δοκιμάστε σύνδεση.': 'This email is already in use. Try logging in.',
 'Δεν ήταν δυνατή η εγγραφή. Ελέγξτε τα στοιχεία.': 'Registration could not be completed. Check your details.',
}

def journey_text(message):
    if request.args.get('lang', session.get('purchase_language')) == 'en':
        return MESSAGES.get(message, message)
    return message
