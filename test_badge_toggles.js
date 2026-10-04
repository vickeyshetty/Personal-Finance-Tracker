const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function badgeToggleOverrides('),source.indexOf('function readEditBadges(')),ctx);
const run=(base,choices)=>JSON.parse(JSON.stringify(ctx.badgeToggleOverrides(base,choices)));
assert.deepEqual(run({},[{id:'1',initial:true,selected:false}]),{'1':false});
assert.deepEqual(run({},[{id:'2',initial:false,selected:true}]),{'2':true});
assert.deepEqual(run({'1':true,'2':false},[{id:'1',initial:true,selected:true},{id:'2',initial:false,selected:false}]),{'1':true,'2':false});
assert.deepEqual(run({},[{id:'1',initial:true,selected:true}]),{}); // untouched / toggled back retains keyword matching
assert.deepEqual(run({'2':false},[{id:'2',initial:false,selected:true}]),{'2':true});
console.log('Badge toggles preserve untouched overrides and support adding/removing automatic and manual badges.');
