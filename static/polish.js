/* Visual enhancements retain the existing elements, IDs, event delegation and data. */
(()=>{
  const theme=document.querySelector('link[href^="/static/polish.css"]');if(theme)document.head.append(theme);
  const icons={dashboard:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',transactions:'M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4',creditCard:'M3 5h18v14H3z M3 10h18 M6 15h4',import:'M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5',review:'M12 3 2 21h20L12 3z M12 9v5m0 3v1',trash:'M4 6h16M9 3h6M6 6l1 15h10l1-15M10 10v7m4-7v7',manage:'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-8 0v6',developer:'m8 6-6 6 6 6m8-12 6 6-6 6M14 3l-4 18'};
  const svg=path=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
  document.querySelector('.brand').insertAdjacentHTML('afterbegin',`<span class="brand-mark">${svg('M5 17V7m7 10V3m7 14v-6M3 21h18')}</span>`);
  document.querySelectorAll('.nav[data-view]').forEach(b=>b.insertAdjacentHTML('afterbegin',svg(icons[b.dataset.view]||icons.dashboard)));
  document.querySelector('aside .nav').insertAdjacentHTML('beforebegin','<div class="nav-section">Workspace</div>');
  $('manageNav').insertAdjacentHTML('beforebegin','<div class="nav-section">Preferences</div>');
  document.querySelector('header').insertAdjacentHTML('beforeend','<span class="local-indicator">Local workspace</span>');
  $('title').insertAdjacentHTML('afterend','<p class="header-note" id="pageDescription"></p>');
  const descriptions={dashboard:'A clear view of your spending, cash flow and the money ahead.',transactions:'Search, organize and make sense of every entry.',creditCard:'Purchases, refunds and repayments. Each in its place.',import:'Bring your statements and email alerts into one ledger.',review:'Compare each pair before deciding what belongs in your ledger.',trash:'Removed entries stay here until you choose to restore them.',manage:'Make the ledger reflect the way you spend.',developer:'Build, test and manage your own extraction rules.'};
  function describe(view){$('pageDescription').textContent=descriptions[view]||'';$('eyebrow').hidden=view!=='dashboard'}
  const oldShow=show;show=function(view){oldShow(view);describe(view)};describe('dashboard');
  // Explain review choices at their point of use without changing actions.
  function polishReview(){
    $('reviewList').querySelectorAll('.list-row').forEach(row=>{
      if(row.dataset.polished)return;row.dataset.polished='true';
      const content=row.firstElementChild,actions=row.lastElementChild;
      content.insertAdjacentHTML('afterbegin','<div class="review-source">Incoming entry · not counted yet</div>');
      content.querySelectorAll('small').forEach(s=>{if(s.textContent.startsWith('Existing:'))s.classList.add('review-comparison')});
      actions.querySelectorAll('[data-reconcile]').forEach(b=>{b.textContent='Merge with existing email';b.title='Use statement details, preserve manual edits, and count this transaction once.'});
      actions.insertAdjacentHTML('beforeend','<p class="review-actions-note">Keep both counts two transactions. Discard keeps the existing entry unchanged.</p>');
    });
  }
  const observer=new MutationObserver(polishReview);observer.observe($('reviewList'),{childList:true});polishReview();
  // Keep disclosure forms readable and preserve their original handlers.
  $('gmailPanel').querySelector('h2').textContent='Your email inbox';
})();
