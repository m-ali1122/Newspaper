/* The Morning Paper — vanilla JS frontend */
(() => {
'use strict';
const SECTIONS = ['world','pakistan','politics','business','technology','science','health','climate','sports','culture'];
const EMOJI = {world:'🌍',pakistan:'🇵🇰',politics:'🏛️',business:'💼',technology:'💻',science:'🔬',health:'🩺',climate:'🌦️',sports:'🏏',culture:'🎭'};
const $ = (s, r=document) => r.querySelector(s);
const app = $('#app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cap = s => String(s||'').replace(/^./, c => c.toUpperCase());

let uid = null, curEdition = null, observers = [], lastTranscriptForRebuild = false;
try { uid = localStorage.getItem('mp_uid'); } catch(e){}
function setUid(u){ uid = u; try { localStorage.setItem('mp_uid', u); } catch(e){} }
// ?user=<id> opens a given reader's paper (demo links)
{ const q = new URLSearchParams(location.search).get('user'); if (q) setUid(q); }

/* ---------- utils ---------- */
function toast(msg, err=false, ms=3800){
  const t = document.createElement('div'); t.className = 'toast' + (err?' err':''); t.textContent = msg;
  $('#toasts').appendChild(t); setTimeout(() => t.remove(), ms);
}
async function api(path, opts={}){
  const o = {method: opts.method || 'GET', headers: {}};
  if (opts.body !== undefined){ o.body = JSON.stringify(opts.body); o.headers['Content-Type'] = 'application/json'; if(!opts.method) o.method='POST'; }
  const r = await fetch(path, o);
  if (!r.ok){ let d=''; try{ d = (await r.json()).detail || ''; }catch(e){} throw new Error(`${r.status} ${typeof d==='string'?d:JSON.stringify(d)}`.trim()); }
  return r.json();
}
function fmtDate(d){ try { return new Date(d.length<=10 ? d+'T12:00:00' : d).toLocaleDateString(undefined,{weekday:'long',year:'numeric',month:'long',day:'numeric'}); } catch(e){ return d||''; } }
function pressLoader(msg){
  app.innerHTML = `<div class="press"><div class="type">${'PRESS'.split('').map(c=>`<span>${c}</span>`).join('')}</div><h2>Setting the type…</h2><p>${esc(msg||'Gathering stories, ranking, laying out columns')}</p></div>`;
}
function cleanup(){ observers.forEach(o => o.disconnect()); observers = []; if(simRAF) cancelAnimationFrame(simRAF); simRAF = 0; }

/* ---------- router ---------- */
async function route(){
  cleanup();
  const h = location.hash || '';
  const parts = h.replace(/^#\/?/, '').split('/');
  const view = parts[0] || (uid ? 'paper' : 'welcome');
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.dataset.r === view));
  const needUser = view !== 'welcome';
  $('#nav').hidden = view === 'welcome';
  $('#voice-fab').hidden = !(view === 'paper' && uid);
  if (view !== 'paper') { $('#voice-panel').hidden = true; }
  window.scrollTo(0,0);
  if (needUser && !uid){ location.hash = '#/welcome'; return; }
  try {
    if (view === 'welcome') viewWelcome();
    else if (view === 'archive') await viewArchive();
    else if (view === 'insights') await viewInsights();
    else await viewPaper((parts[1] || 'today').split('?')[0], /force/.test(h));
  } catch(e){
    app.innerHTML = `<div class="empty">Stop the presses — ${esc(e.message)}<br><br><button class="btn" onclick="location.reload()">Try again</button></div>`;
    toast(e.message, true);
  }
}
window.addEventListener('hashchange', route);

/* ---------- onboarding ---------- */
function viewWelcome(){
  const S = {step:0, name:'', city:'', sections:new Set(), keywords:[], avoid:[], free:'', minutes:10, tone:'balanced'};
  const total = 4;
  let rec = null;
  function render(){
    const dots = Array.from({length:total},(_,i)=>`<i class="${i<=S.step?'on':''}"></i>`).join('');
    let body = '';
    if (S.step===0) body = `<h2>First, who's reading?</h2><p class="lede">Every paper needs a masthead. Yours carries your name.</p>
      <label class="field"><span>Your name</span><input type="text" id="f-name" value="${esc(S.name)}" placeholder="e.g. Ali" autofocus></label>
      <label class="field"><span>Your city</span><input type="text" id="f-city" value="${esc(S.city)}" placeholder="e.g. Lahore"></label>`;
    if (S.step===1) body = `<h2>What belongs on your front page?</h2><p class="lede">Tap the sections you care about. Pick as many as you like.</p>
      <div class="sgrid">${SECTIONS.map(s=>`<div class="scard ${S.sections.has(s)?'on':''}" data-s="${s}" role="button" tabindex="0"><span class="e">${EMOJI[s]}</span>${s}</div>`).join('')}</div>`;
    if (S.step===2) body = `<h2>Tell us in your own words</h2><p class="lede">Speak or type — “I follow AI startups and Pakistani cricket, not celebrity gossip.”</p>
      <div class="say"><textarea id="f-free" placeholder="What do you want to read about?">${esc(S.free)}</textarea><button class="mic" id="f-mic" type="button" aria-label="Dictate">🎤</button></div>
      <div class="interim" id="f-interim"></div>
      <label class="field"><span>Keywords you follow</span><div class="chips" id="c-kw"></div></label>
      <label class="field"><span>Topics to avoid</span><div class="chips" id="c-av"></div></label>`;
    if (S.step===3) body = `<h2>How much time have you got?</h2><p class="lede">We'll size the paper to fit your coffee.</p>
      <div class="big"><span id="mins">${S.minutes}</span> <small style="font-size:18px">minutes</small></div>
      <input type="range" id="f-min" min="5" max="20" step="5" value="${S.minutes}">
      <div class="legend"><span>5 · quick glance</span><span>10 · usual</span><span>20 · deep read</span></div>
      <label class="field"><span>Tone</span></label>
      <div class="opts">${['balanced','upbeat','serious'].map(t=>`<div class="opt ${S.tone===t?'on':''}" data-t="${t}" role="button" tabindex="0">${t}</div>`).join('')}</div>`;
    app.innerHTML = `<div class="onb"><div class="brand">The Morning Paper</div><div class="tag">A daily edition of one — written for you, and it learns.</div>
      <div class="steps">${dots}</div><div class="step">${body}</div>
      <div class="navrow">${S.step>0?'<button class="btn ghost" id="back">Back</button>':'<span></span>'}
      <button class="btn" id="next">${S.step===total-1?'Print my paper':'Continue'}</button></div>
      ${S.step===0?'<div class="demo">Just browsing? <button class="btn ghost small" id="demo">Try demo reader</button></div>':''}</div>`;
    bind();
  }
  function chipField(id, arr, cls){
    const box = $(id); if(!box) return;
    const draw = () => { box.innerHTML = arr.map((k,i)=>`<span class="chip ${cls}">${esc(k)}<button data-i="${i}" aria-label="remove">×</button></span>`).join('') + `<input type="text" placeholder="type, press Enter">`;
      box.querySelectorAll('button').forEach(b=>b.onclick=()=>{arr.splice(+b.dataset.i,1);draw();});
      const inp = $('input',box);
      const add = () => { inp.value.split(',').map(x=>x.trim()).filter(Boolean).forEach(x=>{ if(!arr.includes(x)) arr.push(x);}); draw(); $('input',box).focus(); };
      inp.onkeydown = e => { if(e.key==='Enter'||e.key===','){ e.preventDefault(); add(); } else if(e.key==='Backspace'&&!inp.value&&arr.length){ arr.pop(); draw(); $('input',box).focus(); } };
      inp.onblur = () => { if(inp.value.trim()) add(); };
    };
    draw();
  }
  function bind(){
    const keep = () => { const n=$('#f-name'); if(n) S.name=n.value; const c=$('#f-city'); if(c) S.city=c.value; const f=$('#f-free'); if(f) S.free=f.value; };
    $('#next').onclick = () => { keep(); if(S.step===0 && !S.name.trim()){ toast('Please tell us your name.',true); return; } if(S.step<total-1){ stopRec(); S.step++; render(); } else submit(); };
    const b=$('#back'); if(b) b.onclick=()=>{ keep(); stopRec(); S.step--; render(); };
    document.querySelectorAll('.scard').forEach(c=>{ const t=()=>{ const s=c.dataset.s; S.sections.has(s)?S.sections.delete(s):S.sections.add(s); c.classList.toggle('on'); }; c.onclick=t; c.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();t();}}; });
    document.querySelectorAll('.opt').forEach(o=>o.onclick=()=>{ S.tone=o.dataset.t; document.querySelectorAll('.opt').forEach(x=>x.classList.toggle('on',x===o)); });
    const r=$('#f-min'); if(r) r.oninput=()=>{ S.minutes=+r.value; $('#mins').textContent=r.value; };
    chipField('#c-kw', S.keywords, ''); chipField('#c-av', S.avoid, 'av');
    const mic=$('#f-mic'); if(mic) mic.onclick=()=>toggleRec(mic);
    const d=$('#demo'); if(d) d.onclick=async()=>{ d.disabled=true; pressLoader('Seeding a demo reader and printing the first edition'); try{ const r=await api('/api/demo/seed',{method:'POST',body:{}}); const u=r.user_id||(r.profile&&r.profile.user_id)||r.uid; if(!u) throw new Error('Demo seed returned no user id'); setUid(u); location.hash='#/paper/today'; }catch(e){ toast(e.message,true); render(); } };
  }
  function stopRec(){ if(rec){ try{rec.stop();}catch(e){} rec=null; } }
  function toggleRec(mic){
    if(rec){ stopRec(); mic.classList.remove('rec'); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SR){ toast('Speech input is not supported in this browser — please type instead.',true); return; }
    const ta=$('#f-free'), base=ta.value ? ta.value.replace(/\s*$/,' ') : '';
    rec = new SR(); rec.continuous=true; rec.interimResults=true; rec.lang='en-US';
    let fin='';
    rec.onresult = e => { let it=''; for(let i=e.resultIndex;i<e.results.length;i++){ const r=e.results[i]; if(r.isFinal) fin+=r[0].transcript+' '; else it+=r[0].transcript; } ta.value=base+fin; S.free=ta.value; $('#f-interim').textContent=it; };
    rec.onend = () => { mic.classList.remove('rec'); rec=null; const i=$('#f-interim'); if(i) i.textContent=''; };
    rec.onerror = e => { toast('Mic: '+e.error,true); };
    rec.start(); mic.classList.add('rec');
  }
  async function submit(){
    const fr=$('#f-free'); if(fr) S.free=fr.value;
    pressLoader('Interviewing the editor, then printing your first edition. This can take up to half a minute.');
    try{
      const p = await api('/api/users',{body:{name:S.name.trim(),city:S.city.trim(),sections:[...S.sections],keywords:S.keywords,avoid:S.avoid,free_text:S.free,tone:S.tone,reading_minutes:S.minutes}});
      setUid(p.user_id);
      await api(`/api/users/${uid}/editions/today`,{method:'POST',body:{}});
      location.hash='#/paper/today';
    }catch(e){ toast(e.message,true); render(); }
  }
  render();
}

/* ---------- paper ---------- */
async function viewPaper(eid, force){
  pressLoader();
  let ed;
  if (eid === 'today') ed = await api(`/api/users/${uid}/editions/today${force?'?force=1':''}`,{method:'POST',body:{}});
  else ed = await api(`/api/editions/${encodeURIComponent(eid)}`);
  curEdition = ed;
  renderEdition(ed);
}
function readTime(a){ return a.read_minutes ? `${a.read_minutes} min read` : ''; }
function card(a, opts={}){
  const {big=false, img=true} = opts;
  const reasons = (a.reasons||[]);
  const t = `<article class="card" data-aid="${esc(a.id)}">
    ${img && a.image ? `<img loading="lazy" src="${esc(a.image)}" alt="" onerror="this.remove()">` : ''}
    <div class="meta"><span class="sec">${esc(a.section)}</span> · ${esc(a.source||'')} ${a.read_minutes?`· ${esc(readTime(a))}`:''}</div>
    ${big ? `<h2><a class="hl" target="_blank" rel="noopener" href="/r/${encodeURIComponent(curEdition.id)}/${encodeURIComponent(a.id)}">${esc(a.title)}</a></h2>`
          : `<h3><a class="hl" target="_blank" rel="noopener" href="/r/${encodeURIComponent(curEdition.id)}/${encodeURIComponent(a.id)}">${esc(a.title)}</a></h3>`}
    ${opts.noSummary ? '' : `<p class="sum">${esc(a.summary||'')}</p>`}
    <div class="acts"><button data-a="like" title="More like this">👍 Like</button><button data-a="dislike" title="Less like this">👎 Less</button><button data-a="skip" title="Skip">✕ Skip</button>
      <button class="why" data-a="why">Why this?</button></div>
    <div class="reasons"><ul>${reasons.length?reasons.map(r=>`<li>${esc(r)}</li>`).join(''):'<li>Matched your general profile.</li>'}</ul></div>
  </article>`;
  return t;
}
function deltaText(d){
  if(!d) return '';
  const out=[];
  const walk = (o) => {
    if (Array.isArray(o)) { o.forEach(x => { if (Array.isArray(x) && x.length>=2 && typeof x[1]==='number') out.push((x[1]>=0?'+':'-')+x[0]); else if (typeof x==='string') out.push(x); else walk(x); }); }
    else if (o && typeof o==='object') for (const [k,v] of Object.entries(o)) { if (typeof v==='number') out.push((v>=0?'+':'-')+k); else walk(v); }
  };
  walk(d); return [...new Set(out)].slice(0,6).join(', ');
}
async function sendEvent(aid, action, value){
  try{
    const r = await api('/api/events',{body:{user_id:uid,article_id:aid,action,value}});
    return r;
  }catch(e){ toast(e.message,true); return null; }
}
function renderEdition(ed){
  const d = ed.mood||{}; const tot = (d.positive||0)+(d.neutral||0)+(d.negative||0) || 1;
  const secs = (ed.sections||[]).filter(s => (s.articles||[]).length);
  const lead = ed.lead;
  const html = `
  <header class="masthead">
    <div class="mast-top"><span>${esc(fmtDate(ed.date))}</span><span>Edition No. ${esc(ed.edition_no)}</span><span>${ed.stats?esc(ed.stats.candidates)+' stories considered':''}</span></div>
    <div class="mast-title">${esc(ed.title||'The Morning Paper')}</div>
    <div class="mast-bar"><span class="greeting">${esc(ed.greeting||'')}</span>
      <span class="tools"><a class="btn small ghost" href="/api/editions/${encodeURIComponent(ed.id)}/pdf" download>⬇ Download PDF</a><button class="btn small ghost" id="refresh">↻ Refresh edition</button></span></div>
  </header>
  ${lead ? `<section class="lead"><div class="card-wrap">${lead.image?`<img src="${esc(lead.image)}" alt="" style="width:100%;aspect-ratio:3/2;object-fit:cover;filter:grayscale(.2) sepia(.15)" onerror="this.remove()">`:''}</div>
     <div class="body-col dropcap">${card(lead,{big:true,img:false})}</div></section>` : ''}
  ${secs.map(s=>`<section class="section-block"><h4>${esc(s.name)}</h4><div class="cols">${s.articles.map((a,i)=>card(a,{img:i===0})).join('')}</div></section>`).join('')}
  ${(ed.serendipity||[]).length ? `<section class="serendipity"><div class="grid">${ed.serendipity.map(a=>card(a)).join('')}</div></section>` : ''}
  <div class="lower">
    <div class="threads"><div class="side-h">Following the story</div>
      ${(ed.threads||[]).length ? ed.threads.map(t=>`<div class="th"><b>${esc(t.entity)}</b><ul class="tl">${t.articles.map(x=>`<li><a href="${esc(x.url||'#')}" target="_blank" rel="noopener">${esc(x.title)}</a><small>${esc((x.date||'').slice(0,10))}</small></li>`).join('')}</ul></div>`).join('') : '<p class="empty">No developing stories to trace today.</p>'}
    </div>
    <aside>
      <div class="side-h">In Brief</div>
      ${(ed.briefs||[]).length ? ed.briefs.map(a=>`<div class="brief">${card(a,{img:false,noSummary:true})}</div>`).join('') : '<p class="empty">Nothing brief today.</p>'}
      <div class="side-h" style="margin-top:24px">Mood of the day</div>
      <div class="mood"><i style="width:${(d.positive||0)/tot*100}%;background:#3d7a4a"></i><i style="width:${(d.neutral||0)/tot*100}%;background:#b9ae93"></i><i style="width:${(d.negative||0)/tot*100}%;background:var(--red)"></i></div>
      <div class="legend"><span>${d.positive||0} upbeat</span><span>${d.neutral||0} neutral</span><span>${d.negative||0} grave</span></div>
    </aside>
  </div>
  <section class="kgwrap"><div class="cap"><span>Your Knowledge Map</span><span>Highlighted = what you like · tap a node to ask for more</span></div><svg id="kg" viewBox="0 0 900 460" preserveAspectRatio="xMidYMid meet"></svg></section>
  <div class="colophon">Printed for ${esc(ed.title||'you')} · ${ed.stats?esc(ed.stats.events_learned)+' signals learned so far':''} · <a href="#/insights">See how it learned</a></div>`;
  app.innerHTML = html;
  $('#refresh').onclick = () => { pressLoader('Re-setting the type with your latest taste'); viewPaper('today', true).catch(e=>toast(e.message,true)); };
  bindCards();
  drawKG(ed.kg);
}
function bindCards(){
  const io = new IntersectionObserver(entries => {
    entries.forEach(en => {
      const el = en.target;
      if (en.isIntersecting && en.intersectionRatio>=0.5 && !el._read && !el._timer){
        el._t0 = Date.now();
        el._timer = setTimeout(() => { el._read = true; el._timer=null; sendEvent(el.dataset.aid,'read',Math.round((Date.now()-el._t0)/1000)); }, 8000);
      } else if (!en.isIntersecting && el._timer){ clearTimeout(el._timer); el._timer=null; }
    });
  }, {threshold:[0,.5]});
  observers.push(io);
  document.querySelectorAll('.card').forEach(el => {
    io.observe(el);
    el.addEventListener('click', async ev => {
      const b = ev.target.closest('button[data-a]'); if(!b) return;
      const a = b.dataset.a;
      if (a==='why'){ $('.reasons',el).classList.toggle('open'); return; }
      const act = a;
      const r = await sendEvent(el.dataset.aid, act);
      if (!r) return;
      const dt = deltaText(r.profile_delta);
      toast(dt ? 'Learning: '+dt : (act==='like'?'Noted — more like this.':act==='dislike'?'Noted — less like this.':'Skipped.'));
      if (act==='skip' || act==='dislike'){ el.classList.add('gone'); setTimeout(()=>{ el.style.display='none'; }, 550); }
      else { document.querySelectorAll(`.card[data-aid="${CSS.escape(el.dataset.aid)}"] [data-a=like]`).forEach(x=>x.classList.add('on')); }
    });
  });
}

/* ---------- knowledge map (tiny force sim) ---------- */
let simRAF = 0;
function drawKG(kg){
  const svg = $('#kg'); if(!svg) return;
  if(!kg || !(kg.nodes||[]).length){ svg.outerHTML = '<p class="empty">The knowledge map fills in as more stories arrive.</p>'; return; }
  const W=900,H=460;
  const maxW = Math.max(...kg.nodes.map(n=>n.weight||0),1e-9);
  const nodes = kg.nodes.map((n,i)=>({...n, r: 5+ 15*Math.sqrt((n.weight||0)/maxW), x: W/2+Math.cos(i*2.4)*(60+i*6), y: H/2+Math.sin(i*2.4)*(40+i*4), vx:0, vy:0}));
  const idx = new Map(nodes.map(n=>[n.id,n]));
  const edges = (kg.edges||[]).map(e=>({s:idx.get(e.source&&e.source.id||e.source),t:idx.get(e.target&&e.target.id||e.target),w:e.weight||1})).filter(e=>e.s&&e.t);
  const maxE = Math.max(...edges.map(e=>e.w),1);
  const typeCol = {PERSON:'#1f4e79',ORG:'#7a4a1f',GPE:'#3d7a4a',LOC:'#3d7a4a',EVENT:'#6a3d7a'};
  svg.innerHTML = `<g id="kg-e"></g><g id="kg-n"></g>`;
  const ge = $('#kg-e'), gn = $('#kg-n');
  const lines = edges.map(e => { const l=document.createElementNS('http://www.w3.org/2000/svg','line'); l.setAttribute('stroke','#8a7f66'); l.setAttribute('stroke-opacity',.25+.5*e.w/maxE); l.setAttribute('stroke-width',.6+2*e.w/maxE); ge.appendChild(l); return l; });
  const gs = nodes.map(n => {
    const g = document.createElementNS('http://www.w3.org/2000/svg','g'); g.setAttribute('class','kgnode');
    const col = n.liked ? '#b3261e' : (typeCol[n.type]||'#3a352c');
    g.innerHTML = `<title>${esc(n.label)} (${esc(n.type||'')})</title><circle r="${n.r}" fill="${col}" fill-opacity="${n.liked?.95:.55}" stroke="${n.liked?'#17140f':'#fbf7ea'}" stroke-width="${n.liked?2.5:1.2}"></circle>${n.liked?`<circle r="${n.r+5}" fill="none" stroke="#b3261e" stroke-opacity=".4"></circle>`:''}<text y="${-n.r-4}" text-anchor="middle" fill="#17140f">${esc(n.label)}</text>`;
    g.onclick = () => { openVoice(); voiceSend(`more about ${n.label}`); };
    gn.appendChild(g); return g;
  });
  let alpha = 1, ticks = 0;
  function step(){
    for (let i=0;i<nodes.length;i++){ const a=nodes[i];
      for (let j=i+1;j<nodes.length;j++){ const b=nodes[j]; let dx=b.x-a.x, dy=b.y-a.y, d2=dx*dx+dy*dy+.01, d=Math.sqrt(d2); const f=(2600/d2) * alpha; dx/=d; dy/=d; a.vx-=dx*f; a.vy-=dy*f; b.vx+=dx*f; b.vy+=dy*f;
        const mind=a.r+b.r+22; if(d<mind){ const p=(mind-d)*.05; a.vx-=dx*p; a.vy-=dy*p; b.vx+=dx*p; b.vy+=dy*p; } } }
    edges.forEach(e => { let dx=e.t.x-e.s.x, dy=e.t.y-e.s.y, d=Math.sqrt(dx*dx+dy*dy)||1; const k=(d-90)*.012*alpha; dx/=d; dy/=d; e.s.vx+=dx*k; e.s.vy+=dy*k; e.t.vx-=dx*k; e.t.vy-=dy*k; });
    nodes.forEach(n => { n.vx += (W/2-n.x)*.004*alpha*2; n.vy += (H/2-n.y)*.007*alpha*2; n.vx*=.82; n.vy*=.82; n.x+=n.vx; n.y+=n.vy; n.x=Math.max(n.r+20,Math.min(W-n.r-20,n.x)); n.y=Math.max(n.r+16,Math.min(H-n.r-8,n.y)); });
    alpha = Math.max(.02, alpha*.992);
  }
  function paint(){ lines.forEach((l,i)=>{ const e=edges[i]; l.setAttribute('x1',e.s.x); l.setAttribute('y1',e.s.y); l.setAttribute('x2',e.t.x); l.setAttribute('y2',e.t.y); }); gs.forEach((g,i)=>g.setAttribute('transform',`translate(${nodes[i].x.toFixed(1)},${nodes[i].y.toFixed(1)})`)); }
  (function loop(){ step(); step(); paint(); if(++ticks<260 && document.body.contains(svg)) simRAF=requestAnimationFrame(loop); })();
}

/* ---------- archive ---------- */
async function viewArchive(){
  pressLoader('Fetching the back issues');
  const list = await api(`/api/users/${uid}/editions`);
  app.innerHTML = `<h1 class="page-h">The Archive</h1>` + (list.length ? `<div class="agrid">${list.map(e=>`<a class="thumb" href="#/paper/${encodeURIComponent(e.id)}"><div class="tt">${esc(e.title)}</div><div class="ln h"></div><div class="ln"></div><div class="ln"></div><div class="ln" style="width:60%"></div><div class="ln h" style="margin-top:16px;width:55%"></div><div class="ln"></div><div class="ln"></div><div class="ln" style="width:70%"></div><div class="dt"><span>${esc(e.date)}</span><span>No. ${esc(e.edition_no)}</span></div><div class="dt"><span>${esc(e.count)} stories</span></div></a>`).join('')}</div>` : `<div class="empty">No back issues yet. <a href="#/paper/today">Print today's paper.</a></div>`);
}

/* ---------- insights ---------- */
function bars(pairs, cls=''){
  if(!pairs.length) return '<p class="empty">Nothing learned yet — like, skip or ask your editor.</p>';
  const m = Math.max(...pairs.map(p=>Math.abs(p[1])),1e-9);
  return pairs.map(([k,v])=>`<div class="bar ${cls}"><span>${esc(k)}</span><span class="t"><i style="width:${Math.max(2,Math.abs(v)/m*100)}%"></i></span><span>${(+v).toFixed(2)}</span></div>`).join('');
}
const toPairs = x => Array.isArray(x) ? x.map(e => Array.isArray(e) ? e : (typeof e==='object' ? [e.name||e.label||e.section||e.keyword||'?', e.weight??e.value??e.score??0] : [e,1])) : Object.entries(x||{});
async function viewInsights(){
  pressLoader('Reading the editor\'s notebook');
  const ins = await api(`/api/users/${uid}/insights`);
  const ec = ins.event_counts||{};
  const ecKeys = Object.keys(ec);
  const bandit = Object.entries(ins.bandit||{}).map(([s,v]) => { let m = v; if (v && typeof v==='object') m = (v.mean!=null)? v.mean : (v.a!=null ? v.a/((v.a+v.b)||1) : 0); return [s, m]; }).sort((a,b)=>b[1]-a[1]);
  app.innerHTML = `<h1 class="page-h">How your paper learned</h1>
   <div class="panel"><h3>Signals received</h3><div class="stats">${ecKeys.length?ecKeys.map(k=>`<div class="stat"><b>${esc(ec[k])}</b><span>${esc(k)}</span></div>`).join(''):'<p class="empty">No signals yet.</p>'}</div></div>
   <div class="igrid"><div class="panel"><h3>Favourite sections</h3>${bars(toPairs(ins.top_sections).slice(0,10))}</div>
   <div class="panel"><h3>Top keywords</h3>${bars(toPairs(ins.top_keywords).slice(0,12),'r')}</div></div>
   <div class="panel"><h3>How your interests shifted</h3>${historyChart(ins.history||[])}</div>
   <div class="panel"><h3>The editor's bandit — expected hit rate per section</h3>${bars(bandit)}<p style="font-size:13px;color:var(--ink2)">Thompson sampling: the editor mostly serves sections you engage with, while still exploring others.</p></div>`;
}
function historyChart(hist){
  if(hist.length<1) return '<p class="empty">The timeline appears after your first learning updates.</p>';
  const freq = {}; hist.forEach(h => (h.top||[]).forEach(([n,w]) => freq[n]=(freq[n]||0)+w));
  const names = Object.entries(freq).sort((a,b)=>b[1]-a[1]).slice(0,5).map(x=>x[0]);
  const W=800,H=240,pl=30,pb=24;
  const series = names.map(n => hist.map(h => { const f=(h.top||[]).find(t=>t[0]===n); return f?f[1]:0; }));
  const mx = Math.max(...series.flat(),1e-9);
  const X = i => pl + (hist.length>1 ? i/(hist.length-1) : .5)*(W-pl-10), Y = v => H-pb - v/mx*(H-pb-14);
  const cols = ['#b3261e','#17140f','#9a7b2f','#1f4e79','#3d7a4a'];
  const lines = series.map((s,k)=>`<polyline fill="none" stroke="${cols[k]}" stroke-width="2.2" points="${s.map((v,i)=>X(i)+','+Y(v)).join(' ')}"/>${s.map((v,i)=>`<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${cols[k]}"/>`).join('')}`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%"><line x1="${pl}" y1="${H-pb}" x2="${W-10}" y2="${H-pb}" stroke="#2b2620"/><line x1="${pl}" y1="8" x2="${pl}" y2="${H-pb}" stroke="#2b2620"/>${lines}<text x="${pl}" y="${H-6}" font-size="11" font-family="sans-serif" fill="#4a443a">update 1</text><text x="${W-10}" y="${H-6}" text-anchor="end" font-size="11" font-family="sans-serif" fill="#4a443a">update ${hist.length}</text></svg>
   <div class="legend" style="flex-wrap:wrap;gap:12px;justify-content:flex-start">${names.map((n,k)=>`<span><b style="color:${cols[k]}">━</b> ${esc(n)}</span>`).join('')}</div>`;
}

/* ---------- voice harness ---------- */
let vrec = null, speaking = false;
function openVoice(){ $('#voice-panel').hidden = false; }
function vlog(cls, text){ const p=document.createElement('div'); p.className=cls; p.textContent=text; const l=$('#vp-log'); const h=$('.vp-hint',l); if(h) h.remove(); l.appendChild(p); l.scrollTop=l.scrollHeight; }
function speak(text, cb){
  if(!('speechSynthesis' in window) || !text){ cb&&cb(); return; }
  const u = new SpeechSynthesisUtterance(text); u.rate = 1.02; u.onend = () => cb&&cb(); u.onerror = () => cb&&cb();
  window.speechSynthesis.speak(u);
}
function speakList(items, i=0){ if(i>=items.length || !speaking) { speaking=false; return; } speak(`${i+1}. ${items[i]}`, () => speakList(items, i+1)); }
async function voiceSend(text){
  text = (text||'').trim(); if(!text) return;
  vlog('u', '“'+text+'”');
  try{
    const r = await api('/api/voice',{body:{user_id:uid,text}});
    vlog('a', r.reply || '(no reply)');
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    const heads = (r.headlines||[]).map(h => typeof h==='string'?h:(h.title||'')).filter(Boolean);
    speaking = true;
    speak(r.reply, () => { if (heads.length) speakList(heads); else speaking=false; });
    if (heads.length) heads.forEach((h,i)=>vlog('a', `${i+1}. ${h}`));
    const acts = $('#vp-actions'); acts.innerHTML='';
    const changed = r.changes && (Array.isArray(r.changes) ? r.changes.length : Object.keys(r.changes).length);
    if (changed || /more|less|avoid|follow|add|remove|mute/i.test(r.intent||'')){
      const b=document.createElement('button'); b.className='btn small'; b.textContent='Rebuild my paper'; b.style.margin='6px 0';
      b.onclick = () => { speaking=false; window.speechSynthesis&&window.speechSynthesis.cancel(); $('#voice-panel').hidden=true; if(location.hash.startsWith('#/paper/today')){ pressLoader('Re-setting the type with your latest taste'); viewPaper('today',true).catch(e=>toast(e.message,true)); } else location.hash='#/paper/today?force'; };
      acts.appendChild(b);
    }
  }catch(e){ vlog('a','Sorry — '+e.message); toast(e.message,true); }
}
function initVoice(){
  $('#voice-fab').onclick = () => { const p=$('#voice-panel'); p.hidden=!p.hidden; if(!p.hidden) $('#vp-input').focus(); };
  $('#vp-close').onclick = () => { $('#voice-panel').hidden=true; speaking=false; window.speechSynthesis&&window.speechSynthesis.cancel(); };
  $('#vp-form').onsubmit = e => { e.preventDefault(); const i=$('#vp-input'); const t=i.value; i.value=''; voiceSend(t); };
  const mic = $('#vp-mic'); const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ mic.title='Speech recognition unavailable here — type instead'; mic.style.opacity=.4; }
  mic.onclick = () => {
    if(!SR){ toast('Speech recognition not supported in this browser — type your command.',true); return; }
    if(vrec){ try{vrec.stop();}catch(e){} return; }
    if (window.speechSynthesis) window.speechSynthesis.cancel(); speaking=false;
    vrec = new SR(); vrec.lang='en-US'; vrec.interimResults=true; vrec.continuous=false;
    let fin='';
    vrec.onresult = e => { let t=''; for(let i=0;i<e.results.length;i++){ t+=e.results[i][0].transcript; if(e.results[i].isFinal) fin=t; } $('#vp-input').value=t; };
    vrec.onend = () => { mic.classList.remove('rec'); vrec=null; const t=$('#vp-input').value; if(t.trim()){ $('#vp-input').value=''; voiceSend(t); } };
    vrec.onerror = e => toast('Mic: '+e.error,true);
    vrec.start(); mic.classList.add('rec');
  };
}

initVoice();
route();
})();
