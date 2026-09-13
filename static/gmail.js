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
    <p>PDFs are staged until you confirm. Transaction alerts and financial emails without PDFs need review and do not affect spending. HDFC bank links remain manual; new PDF layouts may still need support.</p>
    <label>Show<select id="gmailFilter"><option value="attention">Needs attention</option><option value="all">Collected items (up to 500, attention first)</option><option value="ignored">Ignored</option><option value="imported">Imported</option></select></label>
    <div id="gmailItems"></div>
  </div>`);
  let mailItems=[], poll=null;
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
      $('gmailSync').textContent=s.has_more?'Continue sync (next 50 emails)':'Sync and review';
      if(s.configured&&!$('gmailEmail').value){$('gmailEmail').value=s.email;$('gmailStart').value=s.start_date;$('gmailSenders').value=s.senders.join('\n');$('gmailAllSenders').checked=!!s.all_senders;$('gmailAllHistory').checked=!s.start_date;updateScope()}
      if(s.oauth_status!=='waiting'&&poll){clearInterval(poll);poll=null;$('gmailAuth').textContent=''}
      mailItems=await api('/api/gmail/items');
      await render();
    }catch(err){message(err.message)}
  }
  async function render(){
    const accounts=(await api('/api/bootstrap')).accounts.filter(a=>!a.archived);
    const choices='<option value="">Select account</option>'+options(accounts);
    const filter=$('gmailFilter').value;
    const visible=mailItems.filter(i=>filter==='all'||(filter==='attention'?['pending','needs_review'].includes(i.status):i.status===filter));
    $('gmailItems').innerHTML=visible.map(i=>`<article class="history-row" data-mail="${i.id}"><h3>${esc(i.filename||i.subject||'Email')}</h3><p>${esc(i.sender)} · ${esc(new Date(i.received).toLocaleDateString())} · ${esc(i.status)}</p><p>${esc(i.note)}</p><a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/?authuser=${encodeURIComponent(i.mailbox)}#all/${encodeURIComponent(i.message_id)}">Review original in Gmail</a>
      ${i.filename&&i.status==='pending'?`<label>Fallback destination<select class="mail-account">${choices}</select></label><label>Saved PDF password<select class="mail-password"><option value="">None — unlocked PDF</option>${options(accounts)}</select></label><label class="check"><input type="checkbox" class="mail-override">Use selected destination instead of automatic detection</label><button data-mail-preview="${i.id}">Preview PDF</button><div class="mail-preview" role="status"></div>`:''}
      ${!['imported','dismissed'].includes(i.status)?`<button data-mail-dismiss="${i.id}">Dismiss from Ledger inbox</button>`:''}</article>`).join('')||'<p>No items in this view. Sync after configuring and connecting Gmail.</p>';
    for(const item of visible.filter(i=>!i.filename&&i.status==='needs_review')){
      const card=$('gmailItems').querySelector(`[data-mail="${item.id}"]`);
      card.insertAdjacentHTML('beforeend',`<button data-alert-preview="${item.id}">Preview transaction email</button><div class="mail-preview" role="status"></div>`);
    }
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
  $('gmailSync').onclick=async()=>{const b=$('gmailSync');b.disabled=true;message('Collecting up to 50 emails. No transactions are being posted…');try{const r=await api('/api/gmail/sync',{method:'POST'});message(`${r.staged} new inbox items collected.${r.has_more?' More emails remain; click Continue sync.':''}`)}catch(err){message(err.message)}finally{await refresh()}};
  $('gmailItems').addEventListener('change',e=>{const card=e.target.closest('[data-mail]');if(card)card.querySelector('.mail-preview').textContent='Options changed. Preview again before confirming.'});
  $('gmailItems').addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    const card=b.closest('[data-mail]'),id=card.dataset.mail;
    b.disabled=true;
    try{
      if(b.dataset.mailDismiss){await api(`/api/gmail/items/${id}/dismiss`,{method:'POST'});await refresh();return}
      if(b.dataset.alertPreview){
        const output=card.querySelector('.mail-preview');output.textContent='Reading transaction email…';
        const r=await api(`/api/gmail/items/${id}/alert-preview`,{method:'POST'});
        output.innerHTML=`<p><b>${fmt(Math.abs(r.amount))} purchase authorization</b></p><p>${esc(r.date)} at ${esc(r.time)} · IndusInd card ending ${esc(r.card_last4)}</p><p>Account: <b>${esc(r.account_name||'Not yet linked')}</b></p><p>Description: ${esc(r.description)}</p><p>${esc(r.note)}</p><p><b>Preview only — not added to spending.</b> Statement reconciliation is still required before email alerts can be posted.</p>`;
        return;
      }
      if(b.dataset.mailPreview){
        const choices={account_id:card.querySelector('.mail-account').value,password_account_id:card.querySelector('.mail-password').value,override:card.querySelector('.mail-override').checked};
        if(!choices.account_id)throw Error('Select a fallback account first.');
        const output=card.querySelector('.mail-preview');output.textContent='Downloading and previewing PDF…';
        const r=await api(`/api/gmail/items/${id}/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(choices)});
        if(r.already_imported){output.textContent='Already imported. Check Import history.';return}
        output.innerHTML=`<p>Destination: <b>${esc(r.account)}</b>${r.detected?' · detected':' · fallback'}</p><p>${r.created} new · ${r.review} possible duplicates · ${r.skipped} skipped<br>Debits ${fmt(r.debits)} · Credits ${fmt(r.credits)}</p><details><summary>Inspect ${r.rows.length} entries</summary>${r.rows.map(t=>`<p>${esc(t.date)} · ${esc(t.description)} · ${fmt(t.amount)} · ${esc(t.kind)}</p>`).join('')}</details><button class="button mail-confirm">Confirm import</button>`;
        output.querySelector('.mail-confirm').onclick=async event=>{event.stopPropagation();const button=event.target;button.disabled=true;try{const result=await api(`/api/gmail/items/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(choices)});message(result.already_imported?'This attachment was already imported.':`Imported into ${result.account}. Undo is available in Import history.`);await load();await refresh()}catch(err){message(err.message);button.disabled=false}};
      }
    }catch(err){message(err.message);const output=card.querySelector('.mail-preview');if(output)output.textContent=err.message}finally{b.disabled=false}
  });
  refresh();
})();
