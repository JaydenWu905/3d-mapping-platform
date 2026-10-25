const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const ts = require('typescript');
const cache = new Map();
function loadSource(filename) {
  filename = path.resolve(__dirname, filename);
  if (cache.has(filename)) return cache.get(filename);
  const exports = {}; cache.set(filename, exports);
  const code = ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  new Function('require','exports',code)(specifier => {
    if (specifier.startsWith('.')) {
      const base=path.resolve(path.dirname(filename),specifier);
      for(const extension of ['.ts','.tsx'])if(fs.existsSync(base+extension))return loadSource(base+extension);
    }
    return createRequire(filename)(specifier);
  },exports);
  return exports;
}
module.exports=loadSource;
