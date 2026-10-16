from pathlib import Path
import runpy
import re

# Build on the verified v0.4 worksheet rather than rewriting the proven geometry engine.
runpy.run_path('tools/patch_v04.py', run_name='__main__')

p = Path('app/src/main/assets/index.html')
s = p.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'v0.5 patch anchor not found: {label}')
    s = s.replace(old, new, 1)

replace_once('CCL CAD <span class="muted">v0.4</span>', 'CCL CAD <span class="muted">v0.5</span>', 'header version')
replace_once("app:'CCL CAD',version:'0.4.0'", "app:'CCL CAD',version:'0.5.0'", 'evidence version')
replace_once("function worksheetKey(p,i){return String(p?.handle||`idx-${i}`)}", "function worksheetKey(p,i){return String(p?.instanceKey||p?.handle||`idx-${i}`)}", 'worksheet unique key')

nested_js = r'''
function matIdentity(){return{a:1,b:0,c:0,d:1,tx:0,ty:0}}
function matMul(A,B){return{a:A.a*B.a+A.c*B.b,b:A.b*B.a+A.d*B.b,c:A.a*B.c+A.c*B.d,d:A.b*B.c+A.d*B.d,tx:A.a*B.tx+A.c*B.ty+A.tx,ty:A.b*B.tx+A.d*B.ty+A.ty}}
function matPoint(M,p){return{x:M.a*p.x+M.c*p.y+M.tx,y:M.b*p.x+M.d*p.y+M.ty,bulge:p.bulge||0}}
function matDet(M){return M.a*M.d-M.b*M.c}
function insertMatrix(ins,block,col=0,row=0){
  const ip=ins?.insertionPoint||{x:0,y:0},bp=block?.basePoint||{x:0,y:0};
  const sx=Number.isFinite(+ins?.xScale)?+ins.xScale:1,sy=Number.isFinite(+ins?.yScale)?+ins.yScale:1,ang=Number.isFinite(+ins?.rotation)?+ins.rotation:0;
  const cs=Math.cos(ang),sn=Math.sin(ang),a=cs*sx,b=sn*sx,c=-sn*sy,d=cs*sy;
  const ox=-Number(bp.x||0)+col*Number(ins?.columnSpacing||0),oy=-Number(bp.y||0)+row*Number(ins?.rowSpacing||0);
  return{a,b,c,d,tx:Number(ip.x||0)+a*ox+c*oy,ty:Number(ip.y||0)+b*ox+d*oy};
}
function approxPolylinePerimeter(pts){let p=0;for(let i=0;i<pts.length;i++){const a=pts[i],b=pts[(i+1)%pts.length];p+=Math.hypot(b.x-a.x,b.y-a.y)}return p}
function scanNestedBlockPolylines(db){
  const entries=Array.isArray(db?.tables?.BLOCK_RECORD?.entries)?db.tables.BLOCK_RECORD.entries:[];
  const blockMap=new Map(entries.map(b=>[String(b?.name||''),b]));
  const out=[],stats={modelSpaceInserts:0,expandedInsertInstances:0,nestedPolylineCount:0,maxDepthSeen:0,cycleSkips:0,missingBlockDefs:0,capped:false,xrefBlockHits:0};
  const MAX_DEPTH=7,MAX_INSTANCES=5000,MAX_POLYS=20000,MAX_ARRAY_CELLS=256;
  let instances=0;
  function visitInsert(ins,parentM,pathNames,pathLabel,depth){
    if(!ins||depth>MAX_DEPTH||instances>=MAX_INSTANCES||out.length>=MAX_POLYS){stats.capped=true;return}
    const blockName=String(ins.name||'');
    const block=blockMap.get(blockName);
    if(!block){stats.missingBlockDefs++;return}
    if(pathNames.includes(blockName)){stats.cycleSkips++;return}
    const cols=Math.max(1,Math.min(Number(ins.columnCount)||1,MAX_ARRAY_CELLS)),rows=Math.max(1,Math.min(Number(ins.rowCount)||1,MAX_ARRAY_CELLS));
    const total=Math.min(cols*rows,MAX_ARRAY_CELLS);
    let cell=0;
    for(let r=0;r<rows&&cell<total;r++)for(let c=0;c<cols&&cell<total;c++,cell++){
      if(instances>=MAX_INSTANCES||out.length>=MAX_POLYS){stats.capped=true;return}
      instances++;stats.expandedInsertInstances++;stats.maxDepthSeen=Math.max(stats.maxDepthSeen,depth);
      const local=insertMatrix(ins,block,c,r),M=matMul(parentM,local),det=Math.abs(matDet(M));
      const insertHandle=handleOf(ins)||'?';
      const path=`${pathLabel}${pathLabel?' > ':''}${blockName}@${insertHandle}${total>1?`[${r},${c}]`:''}`;
      const isXref=!!((Number(block.flags)||0)&(4|8));if(isXref)stats.xrefBlockHits++;
      for(const e of (Array.isArray(block.entities)?block.entities:[])){
        if(!e||typeof e!=='object')continue;
        const typ=String(e.type??e.dxfName??e.typeName??'').toUpperCase();
        if(typ==='INSERT'){
          visitInsert(e,M,[...pathNames,blockName],path,depth+1);continue;
        }
        const verts=e.vertices??e.vertexes??e.points;
        if(Array.isArray(verts)&&verts.length>=3&&/POLYLINE/i.test(typ)){
          const m=metrics(verts);if(!m||!closed(e,m.pts))continue;
          const worldPts=m.pts.map(q=>matPoint(M,q));
          const area=m.area*det;
          const blockEntityHandle=handleOf(e);
          const instanceKey=`BLOCK:${path}:${blockEntityHandle||'nohandle'}`;
          out.push({type:typ||'POLYLINE?',layer:layerOf(e)||layerOf(ins)||'',handle:blockEntityHandle,instanceKey,vertices:worldPts.length,points:worldPts,area,perimeter:approxPolylinePerimeter(worldPts),hasBulge:m.hasBulge,isInPaperSpace:false,ownerBlockRecordSoftId:String(e.ownerBlockRecordSoftId??''),source:isXref?'BLOCK_XREF':'BLOCK',blockName,blockFlags:Number(block.flags)||0,blockEntityHandle,insertHandle,instancePath:path,depth,transformDet:det,transformMode:'BLOCK_BASEPOINT→SCALE_XY→ROTATE→TRANSLATE',containmentApprox:!!m.hasBulge});
          stats.nestedPolylineCount++;
          if(out.length>=MAX_POLYS){stats.capped=true;return}
        }
      }
    }
  }
  const roots=Array.isArray(db?.entities)?db.entities.filter(e=>String(e?.type||'').toUpperCase()==='INSERT'):[];
  stats.modelSpaceInserts=roots.length;
  for(const ins of roots)visitInsert(ins,matIdentity(),[],'',1);
  return{polylines:out,stats};
}
'''
replace_once('function targetedScan(db){', nested_js + '\nfunction targetedScan(db){', 'nested block functions')

# Replace the compact targeted scanner with the same direct scan plus nested BLOCK/INSERT expansion.
pattern = re.compile(r"function targetedScan\(db\)\{.*?\}\nfunction units\(code,forced\)", re.S)
m = pattern.search(s)
if not m:
    raise SystemExit('v0.5 targetedScan function span not found')
new_targeted = r'''function targetedScan(db){const entities=Array.isArray(db?.entities)?db.entities:[];const layers=tableLayerNames(db),polys=[],types=new Map();let processed=0;for(const e of entities){if(!e||typeof e!=='object')continue;processed++;const typ=String(e.type??e.dxfName??e.typeName??'');types.set(typ||'UNKNOWN',(types.get(typ||'UNKNOWN')||0)+1);const layer=layerOf(e);if(layer)layers.add(layer);const verts=e.vertices??e.vertexes??e.points;if(Array.isArray(verts)&&verts.length>=3&&/POLYLINE/i.test(typ)){const m=metrics(verts);if(m&&closed(e,m.pts))polys.push({type:typ||'POLYLINE?',layer,handle:handleOf(e),vertices:m.pts.length,points:m.pts.map(q=>({x:q.x,y:q.y,bulge:q.bulge||0})),area:m.area,perimeter:m.perimeter,hasBulge:m.hasBulge,isInPaperSpace:!!e.isInPaperSpace,ownerBlockRecordSoftId:String(e.ownerBlockRecordSoftId??''),source:'MODEL_SPACE',instanceKey:`MS:${handleOf(e)||processed}`,containmentApprox:!!m.hasBulge})}}const nested=scanNestedBlockPolylines(db);for(const p of nested.polylines){polys.push(p);if(p.layer)layers.add(p.layer)}return{nodes:processed,entities:entities.length,unitCode:headerUnitCode(db?.header),layers:[...layers].filter(Boolean).sort(),polylines:polys,typeCounts:[...types.entries()].sort((a,b)=>b[1]-a[1]),truncated:false,scanMode:'TARGETED_DB_ENTITIES+BLOCK_INSERT',nestedStats:nested.stats}}
function units(code,forced)'''
s = s[:m.start()] + new_targeted + s[m.end():]

# Upgrade worksheet provenance without changing explicit-selection semantics.
replace_once("${x.likely?'layer hint + ':''}contained${x.approx?' ≈arc':''}", "${x.likely?'layer hint + ':''}contained${x.p.source&&x.p.source!=='MODEL_SPACE'?` • ${esc(x.p.source)} ${esc(x.p.blockName||'')} @ insert ${esc(x.p.insertHandle||'—')}`:''}${(x.approx||x.p.containmentApprox)?' ≈arc':''}", 'candidate provenance UI')
replace_once("candidates:candidates.map(x=>({handle:x.p.handle,layer:x.p.layer,areaM2:x.m2,selected:selectedExclusions.has(x.key),containment:x.approx?'APPROX_VERTEX_WITH_ARC':'VERTEX_POLYGON'}))", "candidates:candidates.map(x=>({handle:x.p.handle,layer:x.p.layer,areaM2:x.m2,selected:selectedExclusions.has(x.key),source:x.p.source||'MODEL_SPACE',blockName:x.p.blockName||null,insertHandle:x.p.insertHandle||null,instancePath:x.p.instancePath||null,blockEntityHandle:x.p.blockEntityHandle||null,depth:x.p.depth||0,transformDet:x.p.transformDet??null,containment:(x.approx||x.p.containmentApprox)?'APPROX_VERTEX_WITH_ARC':'VERTEX_POLYGON'}))", 'candidate provenance evidence')
replace_once("if(!candidates.length)status+=` <span class=\"warn\">Không thấy candidate direct Model Space. Exclusion có thể nằm trong block/XREF/hatch hoặc chưa phải closed polyline.</span>`;", "if(!candidates.length)status+=` <span class=\"warn\">Không thấy candidate sau direct Model Space + BLOCK/INSERT transform. Cửa tiếp theo: HATCH loops / unresolved XREF / non-closed geometry.</span>`;", 'no-candidate status')
replace_once("containmentMode:'VERTEX_RAYCAST'", "containmentMode:'VERTEX_RAYCAST_WITH_BLOCK_INSERT_AFFINE'", 'containment mode')

p.write_text(s, encoding='utf-8')

required = [
    'TARGETED_DB_ENTITIES+BLOCK_INSERT',
    'scanNestedBlockPolylines',
    'BLOCK_BASEPOINT→SCALE_XY→ROTATE→TRANSLATE',
    'insertHandle',
    "version:'0.5.0'",
    'f&512'
]
for token in required:
    if token not in s:
        raise SystemExit(f'v0.5 verification token missing: {token}')
print('v0.5 nested BLOCK/INSERT geometry patch applied')
