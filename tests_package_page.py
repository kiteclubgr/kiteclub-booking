import sqlite3, tempfile, unittest
from pathlib import Path
from flask import Flask
from package_pages import setup_package_pages

class PackagePageTest(unittest.TestCase):
 def test_public_read_only_page(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'test.db'
   def db():
    c=sqlite3.connect(path); c.row_factory=sqlite3.Row; return c
   c=db(); c.execute('CREATE TABLE packages(id INTEGER,name TEXT,hours REAL,price REAL,active INTEGER,package_type TEXT)'); c.execute("INSERT INTO packages VALUES(1,'8 hours',8,399,1,'lesson')"); c.commit(); before=list(c.iterdump()); c.close()
   app=Flask(__name__); app.template_folder=str(Path(__file__).parent/'templates')
   for endpoint in ('login','register','terms_page','privacy_page'):
    app.add_url_rule('/'+endpoint, endpoint, lambda: '')
   app.jinja_env.globals.update(stripe_test_enabled=lambda:False,app_version='45')
   setup_package_pages(app,db,lambda:None)
   client=app.test_client(); response=client.get('/packages/private-8h'); self.assertEqual(response.status_code,200)
   text=response.get_data(as_text=True); self.assertIn('399€',text); self.assertIn('Δημιουργία λογαριασμού',text); self.assertNotIn('Συνέχεια στην αγορά TEST',text)
   c=db(); self.assertEqual(list(c.iterdump()),before); c.execute('UPDATE packages SET active=0'); c.commit(); c.close()
   self.assertEqual(client.get('/packages/private-8h').status_code,404)

if __name__=='__main__': unittest.main()
