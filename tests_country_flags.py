"""Exercise the actual flag-switch JavaScript with rendered country options (Node required)."""
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)/'app'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('_local_data','__pycache__','*.db','.local_secret_key','uploads','.venv'))
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('launcher_flags',root/'run_local.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    m=launcher.load_local_app();client=m.app.test_client()
    class Options(HTMLParser):
        def __init__(self): super().__init__();self.inside=False;self.items=[]
        def handle_starttag(self,tag,attrs):
            attrs=dict(attrs)
            if tag=='select' and attrs.get('id')=='reg-phone-prefix': self.inside=True
            if tag=='option' and self.inside: self.items.append(attrs)
        def handle_endtag(self,tag):
            if tag=='select': self.inside=False
    parser=Options();parser.feed(client.get('/register').get_data(as_text=True))
    assert len(parser.items)==49
    assert next(item for item in parser.items if 'selected' in item)['value']=='+30'
    for item in parser.items:
        assert client.get(item['data-flag']).status_code==200
    options=Path(folder)/'options.json';options.write_text(json.dumps(parser.items))
    script=Path(folder)/'flags-test.js';script.write_text('''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const options=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const rows=options.map(o=>({value:o.value,dataset:{flag:o['data-flag'],country:o['data-country']}}));
const handlers={},events={},flag={};
const select={selectedOptions:[rows[0]],addEventListener:(type,fn)=>handlers[type]=fn};
const document={querySelectorAll:()=>[],getElementById:id=>id==='reg-phone-prefix'?select:id==='reg-country-flag'?flag:null};
vm.runInNewContext(fs.readFileSync(process.argv[3],'utf8'),{document,window:{addEventListener:(type,fn)=>events[type]=fn}});
assert.equal(flag.src,'/static/flags/gr.svg');
for(const [country,code,prefix] of [['Κύπρος','cy','+357'],['Γαλλία','fr','+33'],['Ηνωμένο Βασίλειο','gb','+44'],['ΗΠΑ','us','+1'],['Καναδάς','ca','+1'],['Ελλάδα','gr','+30']]){
 const row=rows.find(r=>r.dataset.country===country);assert.ok(row);assert.equal(row.value,prefix);
 select.selectedOptions=[row];handlers.change();assert.equal(flag.src,`/static/flags/${code}.svg`);assert.equal(flag.alt,country);
}
select.selectedOptions=[rows.find(r=>r.dataset.country==='Γερμανία')];events.pageshow();assert.equal(flag.src,'/static/flags/de.svg');
select.selectedOptions=[rows.find(r=>r.dataset.country==='Κύπρος')];handlers.input();assert.equal(flag.src,'/static/flags/cy.svg');
console.log('PASS: all 49 local flags, real JS initial/change/input/pageshow, Greece/Cyprus/France/UK, distinct US/Canada +1 flags.');
''')
    subprocess.run(['node',str(script),str(options),str(root/'static/auth.js')],check=True)
