
'use strict';
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const el=(t,c,h)=>{const e=document.createElement(t); if(c)e.className=c;
  if(h!==undefined)e.innerHTML=h; return e;};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=(v,d=3)=>v==null||v!==v?'—':(Math.abs(v)<0.0001&&v!==0?v.toExponential(2):Number(v).toFixed(d));


// ── stains ────────────────────────────────────────────────────────────
// Each family of content is bound to one real histology stain, so a colour
// on screen always means the same kind of thing. Statistics are hematoxylin
// violet; anything eosin pink concerns significance or effect size.
const STAIN={
  'Descriptives':'methylene', 'Assumption checks':'iodine',
  'Two groups':'haem', 'Three or more groups':'haem',
  'Post hoc and multiplicity':'eosin', 'Categorical and proportions':'safranin',
  'Correlation and agreement':'fastgreen', 'Regression':'crystal',
  'Survival':'congo', 'Diagnostic accuracy and prediction':'methylene',
  'Meta-analysis':'trypan', 'Epidemiology and causal':'silver',
  'Power and sample size':'lamp', 'Bench and omics':'lamp',
  'Bayesian and equivalence':'eosin',
  'Group comparison':'haem', 'Distribution':'methylene', 'Relationships':'crystal',
  'Clinical':'congo', 'Bench':'lamp', 'Reporting diagrams':'fastgreen',
  'Literature':'methylene', 'Trial registries':'trypan',
  'Drugs and safety':'safranin', 'Molecular':'pas', 'Population':'silver',
  'Project':'crystal',
  'Workbench':'methylene', 'Evidence':'safranin', 'Output':'fastgreen',
  'Reference':'iodine',
  'Start here':'haem', 'Doing a review':'trypan',
  'Choosing and running a test':'methylene', 'Reading what comes back':'eosin',
  'Producing the output':'fastgreen',
};
const stainOf=g=>STAIN[g]||'silver';

let BOOT=null, STATE={pane:'projects', entry:null, projects:[], activeProject:null, unfiled:{}, newProject:false, dataset:null, dsMeta:null, test:null, plot:null,
  source:'pubmed', result:null, roles:{}, params:{}, plotParams:{}, stage:'title_abstract',
  reviewer:null, reviewers:[], blind:true, instrument:'rob2', form:'rct', queue:[], qi:0, projectFocus:null,
  guideGoal:'compare', guidePrimary:null, guideSecondary:null, guideReq:0, testFromGuide:false,
  preflightToken:null, pendingAttempt:null};

// ── plumbing ──────────────────────────────────────────────────────────
async function api(path, opts={}){
  // Project selection belongs to this browser tab. Every project-owned legacy
  // request carries it explicitly while the v1 screens are introduced.
  const unscoped=['/api/bootstrap','/api/config','/api/projects','/api/reviewers','/api/library'];
  if(STATE.activeProject && path.startsWith('/api/') &&
     !unscoped.some(p=>path===p || path.startsWith(p+'/'))){
    path += (path.includes('?')?'&':'?')+'project='+encodeURIComponent(STATE.activeProject);
  }
  const headers={'Content-Type':'application/json', ...(opts.headers||{})};
  const r=await fetch(path, {...opts, headers});
  let j; try{ j=await r.json(); }catch(e){ throw new Error('Bad response from '+path); }
  if(!r.ok && j.error && typeof j.error==='object') throw new Error(j.error.message||('HTTP '+r.status));
  if(!r.ok && !j.errors && !j.error) throw new Error(j.message||('HTTP '+r.status));
  return j;
}
function toast(msg, kind=''){
  const t=el('div','toast '+kind, esc(msg)); document.body.appendChild(t);
  setTimeout(()=>t.remove(), kind==='err'?7000:3200);
}
function pval(p){ if(p==null)return '—';
  return p<0.001 ? 'p < .001' : 'p = '+p.toFixed(p<0.01?4:3).replace(/^0/,''); }
function starsFor(p){ if(p==null)return '';
  return p<0.001?'***':p<0.01?'**':p<0.05?'*':'ns'; }


// ── hover help ────────────────────────────────────────────────────────
// One floating tip serves every ? on the page, positioned against whichever
// one asked for it and clamped inside the viewport. Long explanations live
// behind the mark so a screen opens with controls, not prose.
function qmark(title, text, cls){
  const b=el('button','qmark'+(cls?' '+cls:''),'?');
  b.type='button';
  b.dataset.tipTitle=title||''; b.dataset.tip=text||'';
  b.setAttribute('aria-label', title?('About '+title):'Help');
  return b;
}
function showTip(src){
  const text=src.dataset.tip; if(!text) return;
  const t=$('#tip'); if(!t) return;
  t.innerHTML=(src.dataset.tipTitle?`<b>${esc(src.dataset.tipTitle)}</b>`:'')+
    esc(text).replace(/`([^`]+)`/g,'<code>$1</code>');
  t.hidden=false;
  const r=src.getBoundingClientRect(), tb=t.getBoundingClientRect();
  let left=r.left, top=r.bottom+7;
  if(left+tb.width>window.innerWidth-10) left=window.innerWidth-tb.width-10;
  if(top+tb.height>window.innerHeight-10) top=Math.max(10, r.top-tb.height-7);
  t.style.left=Math.max(10,left)+'px'; t.style.top=top+'px';
}
function hideTip(){ const t=$('#tip'); if(t) t.hidden=true; }
document.addEventListener('mouseover', e=>{ const q=e.target.closest('.qmark'); if(q) showTip(q); });
document.addEventListener('mouseout', e=>{ if(e.target.closest('.qmark')) hideTip(); });
document.addEventListener('focusin', e=>{ const q=e.target.closest('.qmark'); q?showTip(q):hideTip(); });
window.addEventListener('scroll', hideTip, true);
window.addEventListener('resize', hideTip);

// Anything longer than a glance goes behind the mark; short notes stay inline.
const HINT_THRESHOLD=64;

// Confirmation for anything that removes data. Honest about what goes and
// what survives, and never fires without an explicit yes.
async function confirmDestructive(what, detail){
  if(BOOT && BOOT.config.confirm_destructive===false) return true;
  return window.confirm(what+(detail?('\n\n'+detail):'')+'\n\nThis cannot be undone.');
}

// ── field generation ──────────────────────────────────────────────────
function columnsOfKind(kind){
  if(!STATE.dsMeta) return [];
  const d=STATE.dsMeta.dictionary||{};
  if(kind==='any') return Object.keys(d);
  const want={continuous:['continuous'],categorical:['categorical','binary','ordinal'],
    binary:['binary'],ordinal:['ordinal','binary'],id:['id','categorical','text'],
    time:['time','continuous'],event:['binary','ordinal']}[kind]||[kind];
  return Object.keys(d).filter(c=>want.includes(d[c].kind));
}

function field(p, value, onChange){
  const f=el('div','field'+(p.adv?' adv':''));
  if(p.depends){ f.dataset.dep=p.depends.param; f.dataset.depVal=String(p.depends.equals); }
  const lab=el('label',null, esc(p.label)+(p.unit?` <span class="unit">${esc(p.unit)}</span>`:''));
  f.appendChild(lab);
  let input;
  const set=v=>{ onChange(p.id, v); syncDeps(); };
  switch(p.type){
    case 'bool': {
      f.innerHTML='';
      const w=el('label','check'); const cb=el('input'); cb.type='checkbox';
      cb.checked=!!value; cb.onchange=()=>set(cb.checked);
      w.appendChild(cb); w.appendChild(el('span',null,esc(p.label))); f.appendChild(w);
      break; }
    case 'select': {
      input=el('select');
      (p.choices||[]).forEach(c=>{ const o=el('option',null,esc(c[1])); o.value=c[0];
        if(String(value)===String(c[0]))o.selected=true; input.appendChild(o); });
      input.onchange=()=>set(input.value); f.appendChild(input); break; }
    case 'multiselect': {
      const box=el('div','chips'); const cur=new Set(value||[]);
      (p.choices||[]).forEach(c=>{ const o=el('div','chip'+(cur.has(c[0])?' on':''),esc(c[1]));
        o.onclick=()=>{ cur.has(c[0])?cur.delete(c[0]):cur.add(c[0]);
          o.classList.toggle('on'); set([...cur]); };
        box.appendChild(o); });
      f.appendChild(box); break; }
    case 'column': case 'columns': {
      const cols=STATE.dsMeta?Object.keys(STATE.dsMeta.dictionary||{}):[];
      if(p.type==='column'){
        input=el('select'); input.appendChild(el('option',null,'—'));
        cols.forEach(c=>{ const o=el('option',null,esc(c)); o.value=c;
          if(value===c)o.selected=true; input.appendChild(o); });
        input.onchange=()=>set(input.value||null); f.appendChild(input);
      } else {
        const box=el('div','chips'); const cur=new Set(value||[]);
        cols.forEach(c=>{ const o=el('div','chip'+(cur.has(c)?' on':''),esc(c));
          o.onclick=()=>{ cur.has(c)?cur.delete(c):cur.add(c); o.classList.toggle('on');
            set([...cur]); }; box.appendChild(o); });
        f.appendChild(box);
      } break; }
    case 'textarea': {
      input=el('textarea'); input.value=value==null?'':value;
      if(p.placeholder)input.placeholder=p.placeholder;
      input.oninput=()=>set(input.value); f.appendChild(input); break; }
    default: {
      input=el('input');
      input.type=(p.type==='number'||p.type==='int')?'number':'text';
      if(p.step)input.step=p.step; else if(p.type==='number')input.step='any';
      if(p.min!=null)input.min=p.min; if(p.max!=null)input.max=p.max;
      if(p.placeholder)input.placeholder=p.placeholder;
      input.value=value==null?'':value;
      input.oninput=()=>set(input.value===''?null:
        (p.type==='int'?parseInt(input.value):p.type==='number'?parseFloat(input.value):input.value));
      f.appendChild(input);
    }
  }
  if(p.help){
    if(p.help.length>HINT_THRESHOLD){
      const lab=f.querySelector('label')||f.querySelector('.check');
      if(lab) lab.appendChild(qmark(p.label, p.help));
      else f.appendChild(el('div','help',esc(p.help)));
    } else {
      f.appendChild(el('div','help',esc(p.help)));
    }
  }
  return f;
}

function syncDeps(){
  $$('[data-dep]').forEach(f=>{
    const v=STATE.params[f.dataset.dep];
    f.style.display = String(v)===f.dataset.depVal ? '' : 'none';
  });
}

function roleField(r){
  const f=el('div','field');
  f.appendChild(el('label',null, esc(r.label)+
    ` <span class="unit">${esc(r.kind)}${r.max>1?' ×'+r.max:''}${r.optional?' · optional':''}</span>`));
  const cols=columnsOfKind(r.kind);
  const cur=new Set(STATE.roles[r.id]||[]);
  if(!cols.length){ f.appendChild(el('div','help','No '+esc(r.kind)+
    ' variables in this dataset. Adjust the variable dictionary in the Data pane.')); return f; }
  const box=el('div','chips');
  cols.forEach(c=>{ const o=el('div','chip'+(cur.has(c)?' on':''),esc(c));
    o.onclick=()=>{
      if(cur.has(c)) cur.delete(c);
      else { if(r.max===1) cur.clear(); cur.add(c); }
      STATE.roles[r.id]=[...cur]; renderPane(); preflight();
    }; box.appendChild(o); });
  f.appendChild(box);
  if(r.help){
    const lab=f.querySelector('label');
    if(r.help.length>HINT_THRESHOLD && lab) lab.appendChild(qmark(r.label, r.help));
    else f.appendChild(el('div','help',esc(r.help)));
  }
  return f;
}

function formFor(entry, target){
  (entry.roles||[]).forEach(r=>target.appendChild(roleField(r)));
  const groups={};
  (entry.params||[]).forEach(p=>{ (groups[p.group||'']=groups[p.group||'']||[]).push(p); });
  Object.entries(groups).forEach(([g,ps])=>{
    if(g) target.appendChild(el('div','rail-head',esc(g)));
    ps.forEach(p=>target.appendChild(field(p, STATE.params[p.id],
      (k,v)=>{ STATE.params[k]=v; })));
  });
  syncDeps();
}


// One explanation per screen, behind the ? beside its heading.
const PANE_TIP={
 data:["Data","Everything starts here. The inferred type of each variable decides which tests will accept it, so a 0/1 column read as continuous is the commonest silent error in the whole tool. Correct the dictionary before running anything."],
 analysis:["Analysis","Start with the deterministic analysis guide: it matches the reviewed variable dictionary to the role requirements declared by each method, then lets you configure a structurally compatible analysis. It does not infer scientific intent or choose a test for you. The full method library remains available for expert/manual use. The assumption gate still runs before execution, figures are built from stored results, and every run is written to the ledger."],
 harvest:["Harvest","Each source is a search against a live API. Results land in one shared corpus, deduplicated across sources by DOI and by fuzzy title. Trim the corpus below if a search came back wider than you wanted."],
 screen:["Screening","Keyboard-driven: `i` include, `e` exclude, `m` maybe, `u` undo. Undo genuinely deletes the last judgement rather than just stepping back. Screen under two different reviewer names to get a kappa."],
 synthesis:["Synthesis","Extraction forms, risk of bias, and the conversion from arm-level numbers into effect sizes and standard errors that the meta-analysis expects. Ratio measures come out on the log scale, which is what it wants."],
 report:["Report","The methods paragraph is assembled from the ledger, so it describes what was actually executed rather than what you meant to do. Read it before pasting it: it is a draft, not a fact."],
 runs:["Run ledger","Every test ever executed, with its data hash, spec, seed and package versions. This is what makes the multiplicity audit possible and what stops eight quiet attempts becoming one reported result. Deleting entries is allowed but it is the audit trail you are deleting."],
 projects:["Projects","A project owns its records, datasets, runs and figures, and switching between them changes what every pane shows. Each kind of project has its own line of progression, and every stage on it reports whether it is done by asking the database rather than by being ticked, so the progress line cannot overstate what has actually happened."],
 library:["Handbook","Reference that travels with the tool. The review half explains the order the steps go in and why, and names the pane that handles each one. The statistics half covers choosing a test, what the numbers mean, and the ways results get misread. Links inside an article jump to the pane being described."],
 settings:["Settings","Statistical defaults live here rather than on each test, because an alpha you can change per test after seeing the result is not an alpha. The danger zone at the bottom is the only place that removes whole categories at once."],
};
