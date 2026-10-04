const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8'),ctx={esc:s=>String(s).replaceAll('<','&lt;')};vm.createContext(ctx);
for(const name of ['transactionDate','compareTransactionOrder','transactionDateCell']){
 const start=source.indexOf('function '+name+'(');vm.runInContext(source.slice(start,source.indexOf('\n',start)),ctx);
}
const rows=[{id:1,date:'2026-09-01',sort_seconds:500},{id:2,date:'2026-09-01',sort_seconds:100},{id:3,date:'2026-09-01'},{id:4,date:'2026-09-02'}];
assert.deepEqual(rows.sort(ctx.compareTransactionOrder).map(t=>t.id),[4,1,2,3]);
assert.equal(ctx.transactionDateCell({date:'2026-09-01'}),'1 Sep 2026');
assert.ok(ctx.transactionDateCell({date:'2026-09-01',time_label:'≈ 12:30 IST · email received'}).includes('≈ 12:30'));
assert.ok(!ctx.transactionDateCell({date:'2026-09-01',time_label:'<script>'}).includes('<script>'));
assert.ok(ctx.transactionDateCell({date:'2026-09-01',time_label:'≈ 12:30 IST · email received'}).includes('<span>≈ 12:30 IST</span> <span>email received</span>'));
assert.ok(ctx.transactionDateCell({date:'2026-09-01',time_label:'12:30 IST · statement'}).includes('<span>statement</span>'));
console.log('Transaction ordering and time labels passed.');
ctx.transactionBadges=()=>'';
const descriptionStart=source.indexOf('function transactionDescription(');
vm.runInContext(source.slice(descriptionStart,source.indexOf('\n',descriptionStart)),ctx);
const email=ctx.transactionDescription({description:'Shop',source_type:'email'});
assert.ok(email.includes('Email alert*'));
assert.ok(email.includes('title="Not yet matched to a statement"'));
assert.ok(!email.includes('<details'));
assert.ok(!ctx.transactionDescription({description:'Shop',source_type:'statement'}).includes('Email alert*'));
