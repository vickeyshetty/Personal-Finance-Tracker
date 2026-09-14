/* Progressive disclosure only: existing controls, IDs and handlers are retained. */
(()=>{
  function tabs(root,groups){
    const bar=document.createElement('div');bar.className='workspace-tabs';bar.setAttribute('aria-label','Sections');root.prepend(bar);
    const panels=groups.map(([name,nodes],i)=>{
      const panel=document.createElement('div');panel.id=root.id+'-panel-'+i;panel.hidden=i!==0;root.append(panel);nodes.filter(Boolean).forEach(n=>panel.append(n));
      const button=document.createElement('button');button.type='button';button.textContent=name;button.setAttribute('aria-controls',panel.id);button.setAttribute('aria-pressed',String(i===0));bar.append(button);
      button.onclick=()=>{panels.forEach(p=>p.hidden=p!==panel);[...bar.children].forEach(b=>b.setAttribute('aria-pressed',String(b===button)))};
      return panel;
    });
  }
  const imports=$('import'),cards=[...imports.children],upload=$('importForm').closest('.form-card'),history=$('importHistory').closest('.form-card'),gmail=$('gmailPanel');
  tabs(imports,[['Email inbox',[gmail]],['Upload statements',[upload]],['Import history',[history]],['Accounts & security',cards.filter(c=>![gmail,upload,history].includes(c))]]);
  tabs($('manage'),[['Categories',[$('categoryForm').closest('.form-card')]],['Keyword rules',[$('ruleForm').closest('.form-card')]],['Badges',[$('badgeManagement')]]]);
  const monthDetail=document.createElement('details');monthDetail.innerHTML='<summary>Explore category totals, food spending and individual entries</summary>';
  $('monthDetails').before(monthDetail);monthDetail.append($('monthDetails'));
  document.querySelector('aside .aside-foot').insertAdjacentHTML('beforebegin','<label class="developer-switch"><input id="developerToggle" type="checkbox"> Developer mode</label><button class="nav" id="developerNav" data-view="developer" hidden>Parser workspace</button>');
  document.querySelector('main').insertAdjacentHTML('beforeend',`<section id="developer" class="view hidden">
    <p class="empty-note">Build extraction rules for emails, PDF text and spreadsheets. No uploaded code is executed. Test with a redacted sample before enabling a parser.</p>
    <div class="form-card"><h2>Installed parsers</h2><div id="developerCatalog"></div></div>
    <div class="form-card"><h2>Parser editor</h2><div class="toolbar"><button data-template="email">New email parser</button><button data-template="pdf">New PDF parser</button><button data-template="table">New spreadsheet parser</button><label>Open definition JSON<input id="parserDefinitionFile" type="file" accept=".json"></label></div>
    <details><summary>How parser definitions work</summary><p>Use a unique custom.* ID. Email rules require an exact sender and literal text marker; PDF rules require a marker. Patterns use named groups date, amount, description and (emails only) last4. Table rules map exact column names. Debit makes amounts negative; credit makes them positive; signed preserves signs. Custom matches take precedence over built-ins. Ambiguous matches stop for review.</p><p>Dates support YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD Mon YYYY, DD Mon YY, DD/MM/YY and DD Mon, YYYY. PDF patterns can miss unmatched rows: compare extracted counts and totals with your source. Saving a definition never imports the test sample.</p></details>
    <label>Definition (JSON)<textarea id="parserDefinition" rows="16" spellcheck="false"></textarea></label>
    <label>Sample text or CSV<textarea id="parserSample" rows="5" placeholder="Use a redacted example"></textarea></label>
    <div class="toolbar"><label>Or test a file<input id="parserSampleFile" type="file" accept=".pdf,.xls,.xlsx,.csv,.txt"></label><label>Saved PDF password<select id="parserPassword"><option value="">None</option></select></label></div>
    <div class="toolbar"><button id="testParser">Test extraction</button><label class="check"><input id="enableParser" type="checkbox">Enable on save</label><button id="saveParser" disabled>Save tested parser</button></div>
    <p id="parserStatus" role="status"></p><pre id="parserOutput" class="parser-output"></pre></div></section>`);
  $('developer').append($('parserCatalog').closest('details'));
  let token=null,custom=[];
  const templates={
    email:{id:'custom.example-email',name:'Example bank alert',kind:'email',sender:'alerts@bank.example',issuer:'example',account_type:'bank',contains:'Example bank debit',pattern:'Example bank debit (?P<amount>[0-9.]+) on (?P<date>[0-9-]+) account (?P<last4>[0-9]{4})',description_fallback:'Example bank debit alert (merchant not supplied)',date_format:'%Y-%m-%d',amount_mode:'debit'},
    pdf:{id:'custom.example-pdf',name:'Example PDF statement',kind:'pdf',contains:'Example statement',pattern:'^(?P<date>[0-9-]+) +(?P<description>.+?) +(?P<amount>-?[0-9.]+)$',date_format:'%Y-%m-%d',amount_mode:'signed'},
    table:{id:'custom.example-table',name:'Example spreadsheet',kind:'table',columns:{date:'Date',description:'Merchant',amount:'Amount'},date_format:'%Y-%m-%d',amount_mode:'signed'}
  };
  function invalidate(){token=null;$('saveParser').disabled=true}
  function edit(d){$('parserDefinition').value=JSON.stringify(d,null,2);invalidate();$('parserOutput').textContent='';$('parserStatus').textContent='Test this definition before saving.'}
  async function refresh(){
    const data=await api('/api/developer/parsers');custom=data.custom;const root=$('developerCatalog');root.replaceChildren();
    [...data.builtins.map(d=>({definition:d,builtin:true})),...custom].forEach(p=>{const row=document.createElement('div');row.className='parser-row';const label=document.createElement('span');label.textContent=p.definition.name+' · '+p.definition.kind+' · '+(p.builtin?'Built-in':p.enabled?'Enabled':'Disabled');row.append(label);
      if(!p.builtin){[['Edit',()=>{edit(p.definition);$('enableParser').checked=!!p.enabled;$('parserDefinition').focus()}],[p.enabled?'Disable':'Enable',async()=>{await api('/api/developer/parsers/'+encodeURIComponent(p.id)+'/toggle',{method:'POST'});await refresh()}],['Remove',async()=>{if(confirm('Remove this parser definition? Existing transactions will not be changed.')){await api('/api/developer/parsers/'+encodeURIComponent(p.id),{method:'DELETE'});await refresh()}}]].forEach(([text,fn])=>{const b=document.createElement('button');b.textContent=text;b.onclick=async()=>{try{await fn()}catch(e){$('parserStatus').textContent=e.message}};row.append(b)})}root.append(row)});
    const dataAccounts=await api('/api/bootstrap');$('parserPassword').replaceChildren(new Option('None',''),...dataAccounts.accounts.map(a=>new Option(a.name,a.id)));
  }
  $('developerNav').onclick=()=>{show('developer');$('title').textContent='Your parser workspace.';refresh().catch(e=>$('parserStatus').textContent=e.message)};
  $('developerToggle').onchange=e=>{const on=e.target.checked;localStorage.setItem('ledger.developer',String(on));$('developerNav').hidden=!on;if(!on&&!$('developer').classList.contains('hidden'))show('dashboard')};
  $('developerToggle').checked=localStorage.getItem('ledger.developer')==='true';$('developerNav').hidden=!$('developerToggle').checked;
  document.querySelectorAll('[data-template]').forEach(b=>b.onclick=()=>edit(templates[b.dataset.template]));
  $('parserDefinition').oninput=invalidate;
  $('parserDefinitionFile').onchange=async e=>{try{const f=e.target.files[0];if(f.size>12000)throw Error('Definition must be under 12 KB.');edit(JSON.parse(await f.text()))}catch(err){$('parserStatus').textContent=err.message}};
  $('testParser').onclick=async()=>{invalidate();$('parserOutput').textContent='';$('testParser').disabled=true;try{const f=new FormData();f.set('definition',$('parserDefinition').value);f.set('sample_text',$('parserSample').value);if($('parserSampleFile').files[0])f.set('file',$('parserSampleFile').files[0]);if($('parserPassword').value)f.set('password_account_id',$('parserPassword').value);const d=await api('/api/developer/test',{method:'POST',body:f});token=d.test_token;$('saveParser').disabled=false;$('parserOutput').textContent=JSON.stringify(d.result,null,2);$('parserStatus').textContent=d.note}catch(e){$('parserStatus').textContent=e.message}finally{$('testParser').disabled=false}};
  $('saveParser').onclick=async()=>{try{await api('/api/developer/parsers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({definition:JSON.parse($('parserDefinition').value),test_token:token,enabled:$('enableParser').checked})});invalidate();await refresh();$('parserStatus').textContent='Parser saved. Existing transactions were not changed.'}catch(e){$('parserStatus').textContent=e.message}};
  edit(templates.email);
})();
