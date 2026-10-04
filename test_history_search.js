const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8'),context={};vm.createContext(context);
for(const name of ['transactionDate','matchesImportHistory']){
 const start=source.indexOf('function '+name+'(');vm.runInContext(source.slice(start,source.indexOf('\n',start)),context);
}
assert.equal(context.transactionDate('2026-09-27'),'27 Sep 2026');
assert.equal(context.transactionDate('2026-01-01'),'1 Jan 2026');
assert.equal(context.transactionDate('2024-02-29'),'29 Feb 2024');
assert.equal(context.transactionDate(null),'');assert.equal(context.transactionDate('unknown'),'unknown');
const batch={id:42,filename:'SBI_Statement.xlsx',account:'SimplyClick SBI Card',created_at:'2026-09-27T10:00:00',undone:false};
for(const q of ['','sbi','SBI xlsx','SimplyClick','#42','27 Sep','2026-09-27','active'])assert.equal(context.matchesImportHistory(batch,q),true,q);
for(const q of ['HDFC','undone','SBI pdf'])assert.equal(context.matchesImportHistory(batch,q),false,q);
assert.equal(context.matchesImportHistory({...batch,undone:true},'undone'),true);
console.log('Import-history search and month-name date formatting passed.');
