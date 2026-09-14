// Gmail only stages email items; statement posting always requires a preview and confirmation.
(() => {
  $('import').insertAdjacentHTML('afterbegin', `<div class="form-card" id="gmailPanel">
    <h2>Gmail statement inbox</h2>
    <p>Read-only access to your dedicated mailbox. Choose all senders or an approved list; Ledger classifies messages for review or ignores them. Nothing is sent, deleted or marked read. No email links are followed automatically.</p>
    <p id="gmailStatus" role="status">Checking connection…</p>
    <div class="toolbar"><button id="gmailConnect">Connect with Google</button><button id="gmailRefresh">Refresh status</button><button id="gmailSync">Sync and review</button><button id="gmailDisconnect">Disconnect</button></div>
    <p id="gmailAuth"></p><p id="gmailMessage" role="status"></p>
    <details><summary>One-time Gmail setup / edit settings</summary>
      <p>Use your own Google Cloud project: enable Gmail API, configure an External consent screen with your dedicated mailbox as a test user, then create a <b>Desktop app</b> OAuth client and download its JSON. <a href="https://developers.google.com/workspace/gmail/api/quickstart/python" target="_blank" rel="noopener noreferrer">Google setup instructions</a></p>
      <p>Read-only permission covers the entire connected mailbox, not just your filters. In Google’s Testing mode you may need to reconnect after seven days. Sign in only to your new forwarding mailbox.</p>
      <form id="gmailSetup"><label>Dedicated Gmail address<input id="gmailEmail" type="email" required autocomplete="off"></label>
      <label class="check"><input id="gmailAllSenders" type="checkbox" checked>Read emails from all senders</label>
      <p>Includes Google and other non-bank messages. Recognized security/verification messages and unrelated emails are ignored; uncertain financial messages stay in review.</p>
      <label class="check"><input id="gmailAllHistory" type="checkbox" checked>Scan all available history</label>
      <label id="gmailDateLabel" hidden>Collect emails received from<input id="gmailStart" type="date" disabled></label>
      <p>All history includes archived mail in this mailbox, but excludes Spam and Trash. It cannot retrieve old messages that were never forwarded here.</p>
      <label id="gmailSendersLabel" hidden>Approved sender email addresses (one per line)<textarea id="gmailSenders" rows="5" disabled placeholder="Exact From addresses copied from your statement emails"></textarea></label>
      <p>Use exact email addresses, not bank names or domains. Forwarded emails usually preserve the original From address. This is a filtering rule, not proof of sender authenticity.</p>
      <label>Google Desktop OAuth client JSON<input id="gmailClient" type="file" accept=".json,application/json" required></label>
      <button>Save configuration securely</button></form>
      <p>OAuth client details and tokens go in Windows Credential Manager. Do not paste passwords or tokens into chat. Saving new filters resets the scan and rechecks previously ignored emails.</p>
    </details>
    <p>Sync automatically adds supported IDFC, IndusInd and HDFC card alerts for confirmed account endings. Suspected duplicates go to transaction Review; unknown accounts and unsupported emails stay here. Missing merchant names remain placeholders. PDF statements still need preview and confirmation; strong matches reconcile existing email entries. HDFC bank links remain manual.</p>
    <details><summary>Developer: email parser registry</summary><p>Trusted application modules, not uploaded scripts. Each parser returns transaction fields; the app owns credentials, account selection, review and posting. See parsers/README.md in the project for the extension contract.</p><div id="parserCatalog"></div></details>
    <label>Show<select id="gmailFilter"><option value="attention">Needs attention</option><option value="all">Collected items (up to 500, attention first)</option><option value="ignored">Ignored</option><option value="imported">Imported</option></select></label>
    <div id="gmailItems"></div>
  </div>`);
  let mailItems=[], poll=null, statementRules=[];
  $('gmailFilter').closest('label').insertAdjacentHTML('beforebegin',`<details id="statementRuleSettings"><summary>Statement identification rules</summary><p>Match an exact sender plus a subject or attachment filename keyword. All filled conditions must match (case-insensitive). A single match selects the destination and saved password below. These are suggestions, not proof of sender authenticity; the PDF parser still detects its layout/account and you must preview and confirm. Multiple matches require manual selection. Rules apply to pending PDFs already collected as well as future emails; they do not import anything automatically.</p><form id="statementRuleForm"><input type="hidden" name="id"><label>Rule name<input name="name" maxlength="80" placeholder="e.g. SBI monthly statement" required></label><label>Exact From email address<input name="sender" type="email" required></label><label>Subject contains<input name="subject_keyword" maxlength="200" placeholder="A stable phrase, not a month/date"></label><label>PDF filename contains (optional)<input name="filename_keyword" maxlength="200" placeholder="Leave blank if filenames change"></label><label>Destination account<select name="account_id" id="statementRuleAccount" required></select></label><label>Saved PDF password account<select name="password_account_id" id="statementRulePassword"></select></label><button>Save statement rule</button><button type="reset">Clear / new rule</button></form><div id="statementRuleList"></div></details>`);
  $('statementRuleForm').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await api('/api/gmail/statement-rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});e.target.reset();message('Rule saved. Matching pending PDFs now have suggested accounts/passwords. Preview before confirming.');await refresh()}catch(err){message(err.message)}finally{b.disabled=false}};
  $('statementRuleList').onclick=async e=>{const b=e.target.closest('button');if(!b)return;const r=statementRules.find(r=>r.id==b.dataset.ruleEdit||r.id==b.dataset.ruleDelete);if(!r)return;try{if(b.dataset.ruleDelete){if(!confirm(`Remove statement rule "${r.name}"? Imported transactions are unchanged.`))return;await api('/api/gmail/statement-rules/'+r.id,{method:'DELETE'});await refresh()}else{const f=$('statementRuleForm').elements;for(const key of ['id','name','sender','subject_keyword','filename_keyword','account_id','password_account_id'])f[key].value=r[key]??'';f.name.focus()}}catch(err){message(err.message)}};
  function updateScope(){const all=$('gmailAllSenders').checked,history=$('gmailAllHistory').checked;$('gmailSendersLabel').hidden=all;$('gmailSenders').disabled=all;$('gmailSenders').required=!all;$('gmailDateLabel').hidden=history;$('gmailStart').disabled=history;$('gmailStart').required=!history}
  $('gmailAllSenders').onchange=updateScope;$('gmailAllHistory').onchange=updateScope;
  const message=text=>$('gmailMessage').textContent=text;
  async function refresh(){
    try {
      const s=await api('/api/gmail/status');
      const labels={waiting:'Waiting for Google sign-in (up to five minutes).',wrong_mailbox:'Wrong mailbox selected. Reconnect using your configured address.',failed:'Sign-in failed. Check Google setup and try again.',timed_out:'Sign-in timed out. Click Connect to retry.'};
      $('gmailStatus').textContent=(s.connected?`Connected: ${s.email}. `:s.configured?'Configured, not connected. ':'Not configured. Open one-time setup below. ')+(labels[s.oauth_status]||'')+(s.last_sync?' Last scan: '+new Date(s.last_sync).toLocaleString()+'.':'');
      $('gmailConnect').disabled=!s.configured||s.oauth_status==='waiting';
      $('gmailSync').disabled=!s.connected||s.oauth_status==='waiting';
      $('gmailDisconnect').disabled=!s.connected||s.oauth_status==='waiting';
      $('gmailSync').textContent=s.has_more?'Continue sync (next 50 emails)':'Sync & add alerts';
      if(s.configured&&!$('gmailEmail').value){$('gmailEmail').value=s.email;$('gmailStart').value=s.start_date;$('gmailSenders').value=s.senders.join('\n');$('gmailAllSenders').checked=!!s.all_senders;$('gmailAllHistory').checked=!s.start_date;updateScope()}
      if(s.oauth_status!=='waiting'&&poll){clearInterval(poll);poll=null;$('gmailAuth').textContent=''}
      mailItems=await api('/api/gmail/items');
      statementRules=await api('/api/gmail/statement-rules');
      const catalog=await api('/api/gmail/parsers');$('parserCatalog').innerHTML=catalog.parsers.map(p=>`<p><b>${esc(p.name)}</b> · v${esc(p.version)}<br>${esc(p.id)} · ${p.senders.map(esc).join(', ')}</p>`).join('');
      await render();
    }catch(err){message(err.message)}
  }
  async function render(){
    const accounts=(await api('/api/bootstrap')).accounts.filter(a=>!a.archived);
    const choices='<option value="">Select account</option>'+options(accounts);
    fill('statementRuleAccount',choices);fill('statementRulePassword','<option value="">No saved password</option>'+options(accounts));
    $('statementRuleList').innerHTML=statementRules.map(r=>`<article class="history-row"><b>${esc(r.name)}</b><p>${esc(r.sender)}${r.subject_keyword?' · subject contains: '+esc(r.subject_keyword):''}${r.filename_keyword?' · filename contains: '+esc(r.filename_keyword):''}<br>Destination: ${esc(r.account_name)} · Password account: ${esc(r.password_account_name||'None')}</p><button data-rule-edit="${r.id}">Edit</button><button data-rule-delete="${r.id}">Remove</button></article>`).join('')||'<p>No statement rules yet. Use “Create statement rule” on a pending PDF to copy its sender.</p>';
    const filter=$('gmailFilter').value;
    const visible=mailItems.filter(i=>filter==='all'||(filter==='attention'?['pending','needs_review'].includes(i.status):i.status===filter));
    $('gmailItems').innerHTML=visible.map(i=>`<article class="history-row" data-mail="${i.id}"><h3>${esc(i.filename||i.subject||'Email')}</h3><p>${esc(i.sender)} · ${esc(new Date(i.received).toLocaleDateString())} · ${esc(i.status)}</p><p>${esc(i.note)}</p><a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/?authuser=${encodeURIComponent(i.mailbox)}#all/${encodeURIComponent(i.message_id)}">Review original in Gmail</a>
      ${i.filename&&i.status==='pending'?`<label>Fallback destination<select class="mail-account">${choices}</select></label><label>Saved PDF password<select class="mail-password"><option value="">None — unlocked PDF</option>${options(accounts)}</select></label><label class="check"><input type="checkbox" class="mail-override">Use selected destination instead of automatic detection</label><button data-mail-preview="${i.id}">Preview PDF</button><div class="mail-preview" role="status"></div>`:''}
      ${!['imported','dismissed'].includes(i.status)?`<button data-mail-dismiss="${i.id}">Dismiss from Ledger inbox</button>`:''}</article>`).join('')||'<p>No items in this view. Sync after configuring and connecting Gmail.</p>';
    for(const item of visible.filter(i=>!i.filename&&i.status==='needs_review')){
      const card=$('gmailItems').querySelector(`[data-mail="${item.id}"]`);
      card.insertAdjacentHTML('beforeend',`<button data-alert-preview="${item.id}">Preview transaction email</button><div class="mail-preview" role="status"></div>`);
    }
    for(const item of visible.filter(i=>i.filename&&i.status==='pending')){
      const card=$('gmailItems').querySelector(`[data-mail="${item.id}"]`),route=item.routing;
      card.insertAdjacentHTML('afterbegin',`<p>Subject: ${esc(item.subject)}</p>`);
      card.insertAdjacentHTML('beforeend',`<button data-create-statement-rule="${item.id}">Create statement rule</button>`);
      if(route&&!route.ambiguous){card.querySelector('.mail-account').value=route.account_id;card.querySelector('.mail-password').value=route.password_account_id||'';card.insertAdjacentHTML('afterbegin',`<p><b>Matched rule: ${esc(route.name)}</b><br>Suggested account: ${esc(route.account_name)} · Saved password account: ${esc(route.password_account_name||'None')}. Preview to verify the PDF.</p>`)}
      else if(route?.ambiguous)card.insertAdjacentHTML('afterbegin',`<p class="error">${esc(route.note)}</p>`);
    }
  }
  async function previewAlert(card,id,accountId=null){
    const output=card.querySelector('.mail-preview');output.textContent='Reading transaction email and checking matches…';
    const r=await api(`/api/gmail/items/${id}/alert-preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:accountId})});
    const data=await api('/api/bootstrap'),accounts=data.accounts.filter(a=>!a.archived&&a.type===r.account_type);
    output.innerHTML=`<p><b>${fmt(Math.abs(r.amount))} ${r.amount<0?'debit':'credit'} · ${esc(r.date)} ${esc(r.time)}</b></p><p>Account ending ${esc(r.account_last4)} · ${esc(r.parser_id)} v${esc(r.parser_version)}</p><p>${esc(r.note)}</p><p>Confirm the account below; a suggested account is not proof of ownership. Confirmation remembers this account ending for future automatic sync.</p><label>Destination account<select class="alert-account"><option value="">Choose account</option>${options(accounts)}</select></label><label>Description<input class="alert-description" maxlength="1000" value="${esc(r.description)}"></label><label>Category<select class="alert-category">${options(data.categories)}</select></label><label>Transaction type<select class="alert-kind">${(r.amount<0?[['expense','Purchase / fee'],['repayment','Card repayment'],['transfer','Self-transfer']]:[['credit','Unclassified credit'],['income','Income / salary'],['refund','Refund / cashback'],['repayment','Card repayment'],['transfer','Self-transfer']]).map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label><p>${r.matches.length?`<b>${r.matches.length} possible overlap(s)</b> with the same account and amount within three days. Confirmation sends this entry to Review, excluded from totals, until you resolve it.`:'No same-account/same-amount match within three days. This is not a guarantee that the alert is unique.'}</p>${r.matches.map(t=>`<p>Existing: ${esc(t.date)} · ${esc(t.description)} · ${fmt(t.amount)} · ${esc(t.status)}</p>`).join('')}<p>Added email entries are provisional and count in totals if active. They are not verified statement entries. Later statements may require overlap review.</p><button type="button" class="alert-confirm">${r.matches.length?'Confirm to duplicate review':'Confirm and add transaction'}</button>`;
    output.querySelector('.alert-account').value=r.account_id||'';output.querySelector('.alert-category').value=r.category_id;output.querySelector('.alert-kind').value=r.kind;
    const confirm=output.querySelector('.alert-confirm');confirm.disabled=!r.account_id;
    output.querySelector('.alert-account').onchange=e=>{confirm.disabled=true;if(e.target.value)previewAlert(card,id,e.target.value).catch(err=>message(err.message))};
    confirm.onclick=async e=>{e.stopPropagation();confirm.disabled=true;try{const result=await api(`/api/gmail/items/${id}/alert-confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preview_token:r.preview_token,account_id:output.querySelector('.alert-account').value,category_id:output.querySelector('.alert-category').value,description:output.querySelector('.alert-description').value,kind:output.querySelector('.alert-kind').value})});message(result.already_imported?'This email was already added.':result.review?'Added to duplicate Review; it is not counted in totals.':'Added to Transactions as an email/provisional entry. Undo is available in Import history.');await load();await refresh()}catch(err){message(err.message);confirm.disabled=false}};
  }
  $('gmailFilter').onchange=()=>render().catch(e=>message(e.message));
  $('gmailRefresh').onclick=refresh;
  $('gmailSetup').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{
    const file=$('gmailClient').files[0];if(!file||file.size>15000)throw Error('Choose your downloaded Desktop client JSON (under 15 KB).');
    const client=JSON.parse(await file.text());
    await api('/api/gmail/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client,email:$('gmailEmail').value,all_senders:$('gmailAllSenders').checked,start_date:$('gmailAllHistory').checked?'':$('gmailStart').value,senders:$('gmailAllSenders').checked?[]:$('gmailSenders').value.split(/[\n,]+/).map(s=>s.trim()).filter(Boolean)})});
    $('gmailClient').value='';message('Configuration saved in the Windows vault. Connect with Google next.');await refresh();
  }catch(err){message(err.message)}finally{button.disabled=false}};
  $('gmailConnect').onclick=async()=>{try{const r=await api('/api/gmail/connect',{method:'POST'});$('gmailAuth').innerHTML=`<a class="button" href="${esc(r.authorization_url)}" target="_blank" rel="noopener noreferrer">Continue to Google sign-in</a>`;await refresh();if(!poll)poll=setInterval(refresh,5000)}catch(err){message(err.message)}};
  $('gmailDisconnect').onclick=async()=>{if(!confirm('Remove Gmail’s local access token? Imported transactions and review history will remain.'))return;try{const r=await api('/api/gmail/disconnect',{method:'POST'});message(r.note);await refresh()}catch(err){message(err.message)}};
  $('gmailSync').onclick=async()=>{const b=$('gmailSync');b.disabled=true;message('Syncing emails and adding supported alerts. Uncertain entries go to review…');try{const r=await api('/api/gmail/sync',{method:'POST'});message(`${r.added} added · ${r.review} need review · ${r.ignored} ignored · ${r.unsupported} unsupported · ${r.skipped} already processed/skipped · ${r.statements} PDFs awaiting preview.${r.has_more?' More emails remain; click Continue sync.':''}`)}catch(err){message(err.message)}finally{try{await load()}catch(err){message(err.message)}await refresh()}};
  $('gmailItems').addEventListener('change',e=>{const card=e.target.closest('[data-mail]');if(card&&e.target.matches('.mail-account,.mail-password,.mail-override'))card.querySelector('.mail-preview').textContent='Options changed. Preview again before confirming.'});
  $('gmailItems').addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    const card=b.closest('[data-mail]'),id=card.dataset.mail;
    b.disabled=true;
    try{
      if(b.dataset.createStatementRule){const item=mailItems.find(i=>i.id==id),f=$('statementRuleForm').elements;$('statementRuleForm').reset();f.sender.value=item.sender;f.name.value='Monthly statement';f.subject_keyword.value=/statement/i.test(item.subject)?'statement':'';f.account_id.value=card.querySelector('.mail-account').value;f.password_account_id.value=card.querySelector('.mail-password').value;$('statementRuleSettings').open=true;f.name.focus();message('Choose the SBI account and its saved password, then enter a stable subject or filename keyword and save.');return}
      if(b.dataset.mailDismiss){await api(`/api/gmail/items/${id}/dismiss`,{method:'POST'});await refresh();return}
      if(b.dataset.alertPreview){
        await previewAlert(card,id);
        return;
      }
      if(b.dataset.mailPreview){
        const choices={account_id:card.querySelector('.mail-account').value,password_account_id:card.querySelector('.mail-password').value,override:card.querySelector('.mail-override').checked};
        if(!choices.account_id)throw Error('Select a fallback account first.');
        const output=card.querySelector('.mail-preview');output.textContent='Downloading and previewing PDF…';
        const r=await api(`/api/gmail/items/${id}/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(choices)});
        if(r.already_imported){output.textContent='Already imported. Check Import history.';return}
        output.innerHTML=`<p>Destination: <b>${esc(r.account)}</b>${r.detected?' · detected':' · fallback'}</p><p>${r.created} new · ${r.review} possible duplicates · ${r.reconciled||0} email entries to reconcile · ${r.skipped} skipped<br>Debits ${fmt(r.debits)} · Credits ${fmt(r.credits)}</p><details><summary>Inspect ${r.rows.length} entries</summary>${r.rows.map(t=>`<p>${esc(t.date)} · ${esc(t.description)} · ${fmt(t.amount)} · ${esc(t.kind)}</p>`).join('')}</details><button class="button mail-confirm">Confirm import</button>`;
        const route=mailItems.find(i=>i.id==id)?.routing;if(route&&!route.ambiguous&&route.account_name!==r.account)output.insertAdjacentHTML('afterbegin','<p class="error">The PDF destination differs from the email rule. Check the detected account carefully before confirming; the rule has not overridden it.</p>');
        output.querySelector('.mail-confirm').onclick=async event=>{event.stopPropagation();const button=event.target;button.disabled=true;try{const result=await api(`/api/gmail/items/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(choices)});message(result.already_imported?'This attachment was already imported.':`Imported into ${result.account}. Undo is available in Import history.`);await load();await refresh()}catch(err){message(err.message);button.disabled=false}};
      }
    }catch(err){message(err.message);const output=card.querySelector('.mail-preview');if(output)output.textContent=err.message}finally{b.disabled=false}
  });
  refresh();
})();
