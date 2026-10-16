const fs=require('node:fs');const vm=require('node:vm');const assert=require('node:assert/strict');const path=require('node:path');
const context=vm.createContext({window:{},console,Uint8ClampedArray,Uint8Array,Float32Array,Math});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ForFilm/js/convert.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'avatar-editor.js'),'utf8'),context);
const editor=context.window.PassportAvatarEditor;
assert.equal(editor.defaults.dither,true);assert.equal(editor.defaults.algorithm,'floydSteinberg');
const valid=editor.validateEdit({source:'data:image/png;base64,AA==',options:{zoom:2,turns:1}});
assert.equal(valid.options.zoom,2);assert.equal(valid.options.turns,1);
assert.throws(()=>editor.validateEdit({source:valid.source,options:{algorithm:'colorQual'}}));
assert.throws(()=>editor.validateEdit({source:valid.source,options:{zoom:NaN}}));
// Exercise the exact Film algorithms the editor uses on a skin-tone field.
const pixels=()=>({width:128,height:160,data:Uint8ClampedArray.from({length:128*160*4},(_,i)=>[213,165,140,255][i%4])});
for(const algorithm of ['floydSteinberg','atkinson','bayer']){
  const p=pixels();context.applyDitherByType(p,algorithm,1);
  const colors=new Set();for(let i=0;i<p.data.length;i+=4)colors.add([...p.data.slice(i,i+3)].join(','));
  assert.ok(colors.size>1,algorithm+' retains tonal detail via spatial dithering');
}
console.log('Avatar source/options validation and Film dithering passed');
