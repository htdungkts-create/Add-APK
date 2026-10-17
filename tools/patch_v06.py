from pathlib import Path
import runpy

# Build on verified v0.5 geometry discovery.
runpy.run_path('tools/patch_v05.py', run_name='__main__')

p = Path('app/src/main/assets/index.html')
s = p.read_text(encoding='utf-8')


def replace_once(old, new, label):
    global s
    if old not in s:
        raise SystemExit(f'v0.6 patch anchor not found: {label}')
    s = s.replace(old, new, 1)

replace_once('CCL CAD <span class="muted">v0.5</span>', 'CCL CAD <span class="muted">v0.6</span>', 'header version')
replace_once("app:'CCL CAD',version:'0.5.0'", "app:'CCL CAD',version:'0.6.0'", 'evidence version')

# Add a mobile-first grouped candidate summary above the instance-level checkbox list.
old_status = '<div id="worksheetStatus" class="sub" style="margin-top:9px"></div>\n  <div class="scroll">'
new_status = '''<div id="worksheetStatus" class="sub" style="margin-top:9px"></div>
  <div style="margin-top:12px">
    <div class="k">CANDIDATE GROUPS</div>
    <div class="sub">Gom các instance cùng block/entity/layer/area để tránh hiểu nhầm một hình lặp thành nhiều loại exclusion. Hint chỉ hỗ trợ đọc, không tự chọn.</div>
    <div class="scroll" style="margin-top:8px">
      <table>
        <thead><tr><th>Hint</th><th>Nhóm geometry</th><th>N</th><th>A/inst</th><th>ΣA</th></tr></thead>
        <tbody id="groupRows"><tr><td colspan="5" class="muted">Chưa có candidate.</td></tr></tbody>
      </table>
    </div>
  </div>
  <div class="k" style="margin-top:14px">INSTANCE DETAIL</div>
  <div class="sub">Checkbox vẫn ở cấp instance. Không tick theo nhóm nếu chưa xác minh ý nghĩa thiết kế.</div>
  <div class="scroll">'''
replace_once(old_status, new_status, 'group summary html')

# Candidate hinting is deliberately conservative. It never creates exclusion truth.
hint_js = r'''
function normLayerText(x){return String(x||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()}
function semanticCandidateHint(p){
  const x=normLayerText(p?.layer),bn=normLayerText(p?.blockName);
  const possible=['void','shaft','thong tang','lo thang','opening','hole','atrium','exclude','khong tinh','khongtinhs','core'];
  const graphic=['net thay manh','net manh','nét thay mảnh','text','dim','kich thuoc','dimension','grid','truc','axis','annotation','symbol','ky hieu'];
  if(possible.some(k=>x.includes(k)||bn.includes(k)))return'POSSIBLE';
  if(graphic.some(k=>x.includes(normLayerText(k))||bn.includes(normLayerText(k))))return'GRAPHIC-LIKE';
  return'UNKNOWN';
}
function candidateGroupKey(x){
  const p=x.p||x;
  const a=Math.round(Number(x.m2??p.area??0)*10000)/10000;
  return [p.source||'MODEL_SPACE',p.blockName||'',p.blockEntityHandle||p.handle||'',p.layer||'',a].join('|');
}
function buildCandidateGroups(candidates){
  const map=new Map();
  for(const x of candidates){
    const key=candidateGroupKey(x),p=x.p||x;
    let g=map.get(key);
    if(!g){g={key,source:p.source||'MODEL_SPACE',blockName:p.blockName||'',entityHandle:p.blockEntityHandle||p.handle||'',layer:p.layer||'',areaEachM2:x.m2||0,totalAreaM2:0,count:0,hint:semanticCandidateHint(p),insertHandles:[],instancePaths:[]};map.set(key,g)}
    g.count++;g.totalAreaM2+=x.m2||0;
    if(p.insertHandle&&!g.insertHandles.includes(p.insertHandle)&&g.insertHandles.length<12)g.insertHandles.push(p.insertHandle);
    if(p.instancePath&&!g.instancePaths.includes(p.instancePath)&&g.instancePaths.length<8)g.instancePaths.push(p.instancePath);
  }
  const rank={POSSIBLE:0,UNKNOWN:1,'GRAPHIC-LIKE':2};
  return [...map.values()].sort((a,b)=>(rank[a.hint]-rank[b.hint])||(b.totalAreaM2-a.totalAreaM2)||(b.count-a.count));
}
function hintMarkup(h){return h==='POSSIBLE'?'<span class="good"><b>POSSIBLE</b></span>':h==='GRAPHIC-LIKE'?'<span class="warn">GRAPHIC-LIKE</span>':'<span class="muted">UNKNOWN</span>'}
function renderCandidateGroups(groups){
  $('groupRows').innerHTML=groups.length?groups.slice(0,120).map((g,i)=>`<tr><td>${hintMarkup(g.hint)}</td><td><b>${esc(g.layer||'—')}</b><br><span class="muted">${esc(g.source)}${g.blockName?` • ${esc(g.blockName)}`:''} • entity <code>${esc(g.entityHandle||'—')}</code></span></td><td><b>${g.count}</b></td><td>${fmtM2(g.areaEachM2)}</td><td><b>${fmtM2(g.totalAreaM2)}</b></td></tr>`).join(''):'<tr><td colspan="5" class="muted">Không có candidate group.</td></tr>';
}
'''
replace_once('function renderWorksheet(){', hint_js + '\nfunction renderWorksheet(){', 'candidate hint functions')

# Compute and display groups right after geometric containment candidates are produced.
old_valid = 'const validKeys=new Set(candidates.map(x=>x.key));'
new_valid = "const candidateGroups=buildCandidateGroups(candidates);renderCandidateGroups(candidateGroups);const validKeys=new Set(candidates.map(x=>x.key));"
replace_once(old_valid, new_valid, 'group computation')

# Surface group count in the status line.
old_status_line = "let status=`Outer <code>${esc(outer.p.handle||outer.key)}</code> • ${candidates.length} candidate nằm trong outer • ${selected.length} vùng đang được trừ.`;"
new_status_line = "let status=`Outer <code>${esc(outer.p.handle||outer.key)}</code> • ${candidates.length} candidate / ${candidateGroups.length} nhóm geometry • ${selected.length} vùng đang được trừ.`;"
replace_once(old_status_line, new_status_line, 'status group count')

# Make instance detail provenance readable in the existing 'Căn cứ' cell.
old_cause = "${x.likely?'layer hint + ':''}contained${x.p.source&&x.p.source!=='MODEL_SPACE'?` • ${esc(x.p.source)} ${esc(x.p.blockName||'')} @ insert ${esc(x.p.insertHandle||'—')}`:''}${(x.approx||x.p.containmentApprox)?' ≈arc':''}"
new_cause = "${hintMarkup(semanticCandidateHint(x.p))}<br>contained${x.p.source&&x.p.source!=='MODEL_SPACE'?` • ${esc(x.p.source)}<br>block ${esc(x.p.blockName||'—')}<br>insert <code>${esc(x.p.insertHandle||'—')}</code>`:''}${(x.approx||x.p.containmentApprox)?' ≈arc':''}"
replace_once(old_cause, new_cause, 'instance provenance')

# Enrich Evidence JSON with group-level and semantic-hint data.
old_evidence = "candidates:candidates.map(x=>({handle:x.p.handle,layer:x.p.layer,areaM2:x.m2,selected:selectedExclusions.has(x.key),source:x.p.source||'MODEL_SPACE',blockName:x.p.blockName||null,insertHandle:x.p.insertHandle||null,instancePath:x.p.instancePath||null,blockEntityHandle:x.p.blockEntityHandle||null,depth:x.p.depth||0,transformDet:x.p.transformDet??null,containment:(x.approx||x.p.containmentApprox)?'APPROX_VERTEX_WITH_ARC':'VERTEX_POLYGON'})),selectedExclusionTotalM2:exclusionM2"
new_evidence = "candidates:candidates.map(x=>({handle:x.p.handle,layer:x.p.layer,areaM2:x.m2,selected:selectedExclusions.has(x.key),semanticHint:semanticCandidateHint(x.p),groupKey:candidateGroupKey(x),source:x.p.source||'MODEL_SPACE',blockName:x.p.blockName||null,insertHandle:x.p.insertHandle||null,instancePath:x.p.instancePath||null,blockEntityHandle:x.p.blockEntityHandle||null,depth:x.p.depth||0,transformDet:x.p.transformDet??null,containment:(x.approx||x.p.containmentApprox)?'APPROX_VERTEX_WITH_ARC':'VERTEX_POLYGON'})),candidateGroups:candidateGroups.map(g=>({groupKey:g.key,hint:g.hint,source:g.source,blockName:g.blockName,entityHandle:g.entityHandle,layer:g.layer,count:g.count,areaEachM2:g.areaEachM2,totalAreaM2:g.totalAreaM2,insertHandles:g.insertHandles,instancePaths:g.instancePaths})),selectedExclusionTotalM2:exclusionM2"
replace_once(old_evidence, new_evidence, 'evidence groups')

# Reset grouped UI when units are unknown, avoiding stale group rows.
old_units = "if(!u.area){$('worksheetStatus').innerHTML='<span class=\"warn\">Chưa xác định đơn vị diện tích. Chọn drawing units trước.</span>';return}"
new_units = "if(!u.area){$('worksheetStatus').innerHTML='<span class=\"warn\">Chưa xác định đơn vị diện tích. Chọn drawing units trước.</span>';$('groupRows').innerHTML='<tr><td colspan=\"5\" class=\"muted\">Chưa xác định units.</td></tr>';return}"
replace_once(old_units, new_units, 'unknown units group reset')

p.write_text(s, encoding='utf-8')

required = [
    'CANDIDATE GROUPS',
    'semanticCandidateHint',
    'GRAPHIC-LIKE',
    'candidateGroups:candidateGroups.map',
    "version:'0.6.0'",
    'TARGETED_DB_ENTITIES+BLOCK_INSERT'
]
for token in required:
    if token not in s:
        raise SystemExit(f'v0.6 verification token missing: {token}')
print('v0.6 candidate intelligence grouping patch applied')
