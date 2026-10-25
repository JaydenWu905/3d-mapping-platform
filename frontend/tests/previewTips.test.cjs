const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const source=fs.readFileSync(path.join(__dirname,'../src/components/PreviewTips.tsx'),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const exportsForTest={};
new Function('require','exports',compiled)((name)=>{
  if(name==='../utils/jobDisplay')return {STAGE_NAMES:{pose:'位姿估计',surface:'表面重建',distance:'距离场'}};
  if(name==='../hooks/useReducedMotion')return {useReducedMotion:()=>false};
  return require(name);
},exportsForTest);
const {tipsForStage}=exportsForTest;
for(const key of ['pose','surface','distance']){
  const tips=tipsForStage(key);assert.equal(tips[0].kind,'介绍');assert.equal(tips.length,4);
  assert(tips.every(t=>t.text.length>10&&!/马上完成|安全通行|精度已达标/.test(t.text)));
  assert(tips.slice(2).every(t=>t.kind==='操作'&&t.text.startsWith('完成后')));
}
const pose=tipsForStage('pose').map(t=>t.text).join(' ');
const surface=tipsForStage('surface').map(t=>t.text).join(' ');
const distance=tipsForStage('distance').map(t=>t.text).join(' ');
assert.match(pose,/LiDAR.*IMU/);assert.match(surface,/位姿.*点云观测.*融合/);assert.match(distance,/未知.*不能视为已确认安全/);
assert(!/各说各话|排好队|怎么玩/.test(pose+surface+distance));
assert(exportsForTest.TIP_INTERVAL_MS>=12000);
assert.match(pose,/左键.*滚轮.*右键/);assert.match(surface,/原始材质.*法线方向/);
assert.match(distance,/XY、XZ、YZ/);assert.match(distance,/观测掩码.*梯度箭头/);
const trajectory=fs.readFileSync(path.join(__dirname,'../src/viewers/TrajectoryViewer.tsx'),'utf8');
const mesh=fs.readFileSync(path.join(__dirname,'../src/viewers/MeshViewer.tsx'),'utf8');
const esdf=fs.readFileSync(path.join(__dirname,'../src/viewers/EsdfViewer.tsx'),'utf8');
assert.match(trajectory,/OrbitControls/);assert.match(trajectory,/重置视角/);
assert.match(mesh,/OrbitControls/);assert.match(mesh,/option value="original"/);assert.match(mesh,/option value="normal"/);
assert.match(esdf,/观测掩码/);assert.match(esdf,/梯度箭头/);assert.match(esdf,/切片/);
console.log('Preview tips agree with implemented viewers: passed');
