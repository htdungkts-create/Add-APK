from pathlib import Path

p = Path('app/src/main/assets/index.html')
s = p.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'patch anchor not found: {label}')
    s = s.replace(old, new, 1)

# Keep the proven v0.3 LWPOLYLINE semantics and polish the front-stage branding.
old_closed = "function closed(o,pts){for(const k of ['closed','isClosed','is_closed']){if(o?.[k]===true||o?.[k]===1)return true}for(const k of ['flag','flags']){if(Number.isFinite(+o?.[k])&&((+o[k])&1))return true}if(pts?.length>2){const a=pts[0],b=pts[pts.length-1];if(Math.hypot(a.x-b.x,a.y-b.y)<1e-7)return true}return false}"
new_closed = "function closed(o,pts){for(const k of ['closed','isClosed','is_closed']){if(o?.[k]===true||o?.[k]===1)return true}const typ=String(o?.type??o?.dxfName??'').toUpperCase();for(const k of ['flag','flags']){if(Number.isFinite(+o?.[k])){const f=+o[k];if(typ==='LWPOLYLINE'){if((f&512)!==0)return true}else if((f&1)!==0)return true}}if(pts?.length>2){const a=pts[0],b=pts[pts.length-1];if(Math.hypot(a.x-b.x,a.y-b.y)<1e-7)return true}return false}"
replace_once(old_closed, new_closed, 'closed flag semantics')
replace_once('<title>CCL CAD POCKET</title>', '<title>CCL CAD</title>', 'title')
replace_once('header{padding:18px 16px 14px;', 'header{padding:calc(18px + env(safe-area-inset-top, 0px)) 16px 14px;', 'safe area')
replace_once('CCL CAD POCKET <span class="muted">APK v0.2</span>', 'CCL CAD <span class="muted">v0.4</span>', 'header branding')
replace_once('DWG geometry review • phone-first • local-only', 'Pocket Review • DWG geometry • local-only', 'subtitle')

# AREA WORKSHEET needs the actual polygon vertices, not just the measured area.
old_push = "polys.push({type:typ||'POLYLINE?',layer,handle:handleOf(e),vertices:m.pts.length,area:m.area,perimeter:m.perimeter,hasBulge:m.hasBulge,isInPaperSpace:!!e.isInPaperSpace,ownerBlockRecordSoftId:String(e.ownerBlockRecordSoftId??'')})"
new_push = "polys.push({type:typ||'POLYLINE?',layer,handle:handleOf(e),vertices:m.pts.length,points:m.pts.map(q=>({x:q.x,y:q.y,bulge:q.bulge||0})),area:m.area,perimeter:m.perimeter,hasBulge:m.hasBulge,isInPaperSpace:!!e.isInPaperSpace,ownerBlockRecordSoftId:String(e.ownerBlockRecordSoftId??'')})"
replace_once(old_push, new_push, 'polyline points')

# Worksheet state is reset whenever a new drawing is opened.
replace_once('let engine=null,evidence=null;', "let engine=null,evidence=null,outerKey='',selectedExclusions=new Set();", 'worksheet state')
replace_once("async function parseNative(name,size){$('fileName').textContent=name;", "async function parseNative(name,size){outerKey='';selectedExclusions.clear();$('fileName').textContent=name;", 'new-file reset')
replace_once("app:'CCL CAD POCKET',version:'apk-0.2'", "app:'CCL CAD',version:'0.4.0'", 'evidence identity')

worksheet_html = '''
<section class="card" id="areaWorksheet">
  <div class="k">AREA WORKSHEET</div>
  <div class="sub">Outer boundary → exclusion được chọn rõ ràng → NET CAD. Candidate chỉ dựa trên containment hình học, không tự coi là phần được trừ.</div>
  <div class="row" style="margin-top:10px">
    <div class="grow"><div class="k">OUTER BOUNDARY</div><select id="outerSelect"><option value="">Chưa có dữ liệu</option></select></div>
    <div class="grow"><div class="k">TV / EXCEL CLAIM (m²)</div><input id="tvClaim" inputmode="decimal" placeholder="VD: 4662.600"></div>
  </div>
  <div class="kpis">
    <div><div class="k">OUTER</div><div id="outerM2" class="v">—</div></div>
    <div><div class="k">EXCLUSIONS</div><div id="exclM2" class="v">0 m²</div></div>
    <div><div class="k">NET CAD</div><div id="netM2" class="v">—</div></div>
    <div><div class="k">DELTA vs TV</div><div id="deltaM2" class="v">—</div></div>
  </div>
  <div id="worksheetStatus" class="sub" style="margin-top:9px"></div>
  <div class="scroll">
    <table>
      <thead><tr><th>Trừ</th><th>Layer</th><th>Handle</th><th>Area</th><th>Căn cứ</th></tr></thead>
      <tbody id="exclRows"><tr><td colspan="5" class="muted">Chọn DWG để tìm candidate exclusion.</td></tr></tbody>
    </table>
  </div>
</section>
'''
replace_once('<section class="card"><div class="k">DIAGNOSTIC</div>', worksheet_html + '<section class="card"><div class="k">DIAGNOSTIC</div>', 'worksheet html')

worksheet_js = r'''
function worksheetKey(p,i){return String(p?.handle||`idx-${i}`)}
function parseAreaClaim(v){const t=String(v??'').trim().replace(/\s+/g,'').replace(',','.');const n=Number(t);return Number.isFinite(n)?n:null}
function pointOnSegment(p,a,b){const cross=(p.x-a.x)*(b.y-a.y)-(p.y-a.y)*(b.x-a.x);if(Math.abs(cross)>1e-7)return false;const dot=(p.x-a.x)*(p.x-b.x)+(p.y-a.y)*(p.y-b.y);return dot<=1e-7}
function pointInPolygon(p,poly){let inside=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[j],b=poly[i];if(pointOnSegment(p,a,b))return true;const hit=((b.y>p.y)!==(a.y>p.y))&&(p.x<(a.x-b.x)*(p.y-b.y)/((a.y-b.y)||1e-20)+b.x);if(hit)inside=!inside}return inside}
function polygonContained(inner,outer){if(!Array.isArray(inner?.points)||!Array.isArray(outer?.points)||inner.points.length<3||outer.points.length<3)return false;return inner.points.every(pt=>pointInPolygon(pt,outer.points))}
function likelyExclusionLayer(layer){const x=String(layer||'').toLowerCase();return ['void','shaft','thong tang','thông tầng','lo thang','lỗ','hole','core','exclude','opening','open to below'].some(k=>x.includes(k))}
function fmtM2(n){return Number.isFinite(n)?n.toLocaleString('vi-VN',{minimumFractionDigits:3,maximumFractionDigits:6})+' m²':'—'}
function renderWorksheet(){
  if(!evidence)return;
  const u=units(evidence.scan.unitCode,$('unit').value),polys=evidence.scan.polylines||[];
  if(!u.area){$('worksheetStatus').innerHTML='<span class="warn">Chưa xác định đơn vị diện tích. Chọn drawing units trước.</span>';return}
  const keyed=polys.map((p,i)=>({p,key:worksheetKey(p,i),m2:p.area*u.area}));
  if(!outerKey||!keyed.some(x=>x.key===outerKey)){
    const golden=keyed.find(x=>String(x.p.handle)==='3790'&&(x.p.layer||'').toLowerCase()==='sa_dien tich san xd'&&Math.abs(x.m2-4835.997173)<=.1);
    const fallback=[...keyed].sort((a,b)=>b.p.area-a.p.area)[0];
    outerKey=(golden||fallback)?.key||'';
    selectedExclusions.clear();
  }
  const sorted=[...keyed].sort((a,b)=>b.p.area-a.p.area);
  $('outerSelect').innerHTML=sorted.length?sorted.map(x=>`<option value="${esc(x.key)}" ${x.key===outerKey?'selected':''}>${esc(x.p.layer||'—')} • ${esc(x.p.handle||x.key)} • ${fmtM2(x.m2)}</option>`).join(''):'<option value="">Không có closed polyline</option>';
  const outer=keyed.find(x=>x.key===outerKey);
  if(!outer){$('worksheetStatus').textContent='Không xác định được outer boundary.';return}
  const candidates=keyed.filter(x=>x.key!==outer.key&&x.p.handle&&x.p.area>0&&x.p.area<outer.p.area*.98&&polygonContained(x.p,outer.p)).map(x=>({...x,likely:likelyExclusionLayer(x.p.layer),approx:!!(x.p.hasBulge||outer.p.hasBulge)})).sort((a,b)=>(b.likely-a.likely)||(b.p.area-a.p.area));
  const validKeys=new Set(candidates.map(x=>x.key));
  for(const k of [...selectedExclusions])if(!validKeys.has(k))selectedExclusions.delete(k);
  const selected=candidates.filter(x=>selectedExclusions.has(x.key));
  const exclusionM2=selected.reduce((sum,x)=>sum+x.m2,0),net=outer.m2-exclusionM2,claim=parseAreaClaim($('tvClaim').value),delta=claim===null?null:net-claim;
  $('outerM2').textContent=fmtM2(outer.m2);$('exclM2').textContent=fmtM2(exclusionM2);$('netM2').textContent=fmtM2(net);$('deltaM2').textContent=delta===null?'—':`${delta>=0?'+':''}${delta.toLocaleString('vi-VN',{minimumFractionDigits:3,maximumFractionDigits:6})} m²`;
  let status=`Outer <code>${esc(outer.p.handle||outer.key)}</code> • ${candidates.length} candidate nằm trong outer • ${selected.length} vùng đang được trừ.`;
  if(claim!==null&&selected.length===0)status+=` <span class="warn">RAW DELTA outer−TV = ${(outer.m2-claim).toLocaleString('vi-VN',{maximumFractionDigits:6})} m², chưa phải exclusion.</span>`;
  if(claim!==null&&selected.length>0)status+=Math.abs(delta)<=.01?` <span class="good"><b>NET MATCH TV ✓</b></span>`:` <span class="warn">NET chưa khớp TV.</span>`;
  if(!candidates.length)status+=` <span class="warn">Không thấy candidate direct Model Space. Exclusion có thể nằm trong block/XREF/hatch hoặc chưa phải closed polyline.</span>`;
  $('worksheetStatus').innerHTML=status;
  $('exclRows').innerHTML=candidates.length?candidates.slice(0,200).map(x=>`<tr><td><input class="exclCheck" style="width:auto" type="checkbox" data-key="${esc(x.key)}" ${selectedExclusions.has(x.key)?'checked':''}></td><td>${esc(x.p.layer||'—')}</td><td><code>${esc(x.p.handle||'—')}</code></td><td><b>${fmtM2(x.m2)}</b></td><td>${x.likely?'layer hint + ':''}contained${x.approx?' ≈arc':''}</td></tr>`).join(''):'<tr><td colspan="5" class="muted">Không có candidate exclusion direct Model Space.</td></tr>';
  document.querySelectorAll('.exclCheck').forEach(el=>el.onchange=()=>{const k=el.dataset.key;if(el.checked)selectedExclusions.add(k);else selectedExclusions.delete(k);renderWorksheet()});
  evidence.areaWorksheet={semantics:'OUTER minus explicitly selected geometrically-contained candidates; candidates are never auto-excluded',containmentMode:'VERTEX_RAYCAST',outer:{handle:outer.p.handle,layer:outer.p.layer,areaM2:outer.m2,hasBulge:!!outer.p.hasBulge},candidates:candidates.map(x=>({handle:x.p.handle,layer:x.p.layer,areaM2:x.m2,selected:selectedExclusions.has(x.key),containment:x.approx?'APPROX_VERTEX_WITH_ARC':'VERTEX_POLYGON'})),selectedExclusionTotalM2:exclusionM2,netCadM2:net,consultantClaimM2:claim,deltaM2:delta};
}
'''
replace_once('async function parseNative(name,size){', worksheet_js + '\nasync function parseNative(name,size){', 'worksheet js')

# Existing area render now also refreshes the worksheet.
old_render_tail = ":'<div class=\"muted\">Golden B chưa kích hoạt.</div>'; }"
if old_render_tail in s:
    s = s.replace(old_render_tail, ":'<div class=\"muted\">Golden B chưa kích hoạt.</div>';renderWorksheet();}", 1)
else:
    old_render_tail2 = ":'<div class=\"muted\">Golden B chưa kích hoạt.</div>';}"
    replace_once(old_render_tail2, ":'<div class=\"muted\">Golden B chưa kích hoạt.</div>';renderWorksheet();}", 'render worksheet hook')

old_handlers = "$('openBtn').onclick=()=>Android.pickDwg();$('filter').oninput=render;$('unit').onchange=render;$('exportBtn').onclick=()=>{if(!evidence)return;"
new_handlers = "$('openBtn').onclick=()=>Android.pickDwg();$('filter').oninput=render;$('unit').onchange=render;$('tvClaim').oninput=renderWorksheet;$('outerSelect').onchange=()=>{outerKey=$('outerSelect').value;selectedExclusions.clear();renderWorksheet()};$('exportBtn').onclick=()=>{if(!evidence)return;renderWorksheet();"
replace_once(old_handlers, new_handlers, 'worksheet event handlers')

p.write_text(s, encoding='utf-8')

required = ['AREA WORKSHEET', 'selectedExclusions', 'pointInPolygon', 'areaWorksheet', 'f&512', "version:'0.4.0'"]
for token in required:
    if token not in s:
        raise SystemExit(f'v0.4 verification token missing: {token}')
print('v0.4 AREA WORKSHEET patch applied')
