const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
const fields=Object.fromEntries(['globalSearch','accountFilter','searchScope','categoryFilter','transactionMonth'].map(id=>[id,{value:'old filter',focus(){this.focused=true}}]));
let rendered=0,view='';
const context={state:{categories:[{id:7,name:'Food'}]},$:id=>fields[id],renderTransactions:()=>rendered++,show:v=>view=v};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function donutSlicePath('),source.indexOf("$('categories').addEventListener('click'")),context);
context.openCategoryTransactions('7','2026-08');
assert.equal(fields.categoryFilter.value,'7');assert.equal(fields.transactionMonth.value,'2026-08');
assert.equal(fields.globalSearch.value,'');assert.equal(fields.accountFilter.value,'');assert.equal(fields.searchScope.value,'current');
assert.equal(rendered,1);assert.equal(view,'transactions');assert.equal(fields.globalSearch.focused,true);
context.openCategoryTransactions('missing','2026-07');assert.equal(rendered,1);
for(const [start,end] of [[0,360],[0,0.01],[180,270]]){
 const path=context.donutSlicePath(start,end);assert.equal((path.match(/ A /g)||[]).length,4);assert.ok(path.endsWith(' Z'));assert.ok(!path.includes('NaN'));
}
console.log('Donut geometry and filtered navigation checks passed.');
