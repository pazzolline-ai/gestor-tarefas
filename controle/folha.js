/* ===== Controle: Pró-labore e folha (módulo próprio do Controle, fora do Gestor) ===== */
const FL_PAR_DEF={2026:{fonte:'INSS: Portaria Interministerial MPS/MF nº 13/2026 · IRRF: Receita Federal e Lei 15.270/2025',atualizado:'2026-01-12',
  inss:[[0,.075,0],[1621.01,.09,24.32],[2902.85,.12,111.40],[4354.28,.14,198.49]],teto:8475.55,plAliq:.11,
  irrf:[[0,0,0],[2428.81,.075,182.16],[2826.66,.15,394.16],[3751.06,.225,675.49],[4664.69,.275,908.73]],simpl:607.20,dep:189.59,
  redutor:{ate:5000,lim:7350,a:978.62,b:.133145},fgts:.08}};
const FL={ym:hoje().slice(0,7),f:''};
const flNum=v=>(+v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
const flPct=v=>(Math.round((+v||0)*1000)/10).toLocaleString('pt-BR',{maximumFractionDigits:2})+'%';
const flParse=s=>{s=String(s==null?'':s).trim();if(!s)return NaN;if(/,/.test(s))s=s.replace(/\./g,'').replace(',','.');return parseFloat(s.replace(/[^\d.-]/g,''))};
const flDig=s=>String(s||'').replace(/\D/g,'');
const flCNPJ=s=>{const d=flDig(s);return d.length===14?d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/,'$1.$2.$3/$4-$5'):String(s||'').trim()};
const flYmAdd=(ym,n)=>{const d=new Date(+ym.slice(0,4),+ym.slice(5)-1+n,1);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')};
const flYmLbl=ym=>MESES[+ym.slice(5)-1]+'/'+ym.slice(0,4);
function flLista(){return [...D.folha.entries()].filter(([id])=>id[0]!=='_').map(([id,p])=>Object.assign({id},p))}
function flPar(ano){const c=(D.folha.get('_tabelas')||{}).anos||{};const y=String(ano);if(c[y])return Object.assign({},c[y],{ano:y});if(FL_PAR_DEF[y])return Object.assign({},FL_PAR_DEF[y],{ano:y});
  const ys=Object.keys(Object.assign({},FL_PAR_DEF,c)).filter(k=>+k<=+y).sort();const last=ys[ys.length-1]||'2026';return Object.assign({},c[last]||FL_PAR_DEF[last],{ano:last,faltando:y})}
const flFaixa=(t,v)=>{let r=t[0];for(const f of t)if(v>=f[0])r=f;return r};
function flCalc(p,ym){const P=flPar(ym.slice(0,4));const v=+p.valor||0,dep=+p.dep||0;let inss,inssAl;const b=Math.min(v,P.teto);
  if(p.tipo==='pl'){inss=b*P.plAliq;inssAl=P.plAliq}else{const f=flFaixa(P.inss,b);inss=b*f[1]-f[2];inssAl=b?inss/b:0}
  inss=Math.round(inss*100)/100;const dedLegal=inss+dep*P.dep;const ded=Math.max(dedLegal,P.simpl);const base=Math.max(0,v-ded);const fi=flFaixa(P.irrf,base);const irTab=Math.max(0,base*fi[1]-fi[2]);
  let red=0;if(P.redutor&&v<=P.redutor.ate)red=irTab;else if(P.redutor&&v<=P.redutor.lim)red=Math.min(irTab,Math.max(0,P.redutor.a-P.redutor.b*v));
  const irrf=Math.round(Math.max(0,irTab-red)*100)/100;const fgts=p.tipo==='clt'?Math.round(v*P.fgts*100)/100:0;
  return {P,v,inss,inssAl,ded,usouSimpl:P.simpl>dedLegal,base,irAl:fi[1],irTab:Math.round(irTab*100)/100,red:Math.round(red*100)/100,irrf,fgts,desc:inss+irrf,liq:Math.round((v-inss-irrf)*100)/100}}
function flFiltrada(){let L=flLista().filter(x=>x.ativo!==false);if(FL.f)L=L.filter(x=>x.tipo===FL.f);return L.sort((a,b)=>(a.empresa||'').localeCompare(b.empresa||'','pt')||(a.nome||'').localeCompare(b.nome||'','pt'))}
function vFolha(){
  const ym=FL.ym,P=flPar(ym.slice(0,4)),L=flFiltrada(),R=L.map(p=>({p,c:flCalc(p,ym)})),T=k=>R.reduce((s,r)=>s+r.c[k],0),ges=GT.gestor();
  const ch=(k,t)=>`<button class="btn sm ${FL.f===k?'pri':'ghost'}" data-flf="${k}">${t}</button>`;
  return `<div class="ph" style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px"><button class="btn sm ghost" data-flm="-1" aria-label="Mês anterior">‹</button><b style="min-width:120px;text-align:center;text-transform:capitalize">${flYmLbl(ym)}</b><button class="btn sm ghost" data-flm="1" aria-label="Próximo mês">›</button><span class="sp" style="flex:1"></span>
    ${ges?`<button class="btn sm" data-flimp>Importar planilha</button><button class="btn sm" data-flpar>Tabelas INSS/IRRF</button><button class="btn sm pri" data-flnew>+ Pessoa</button>`:''}</div>
  ${P.faltando?`<div class="reminder"><div style="flex:1">As tabelas de ${P.faltando} ainda não foram cadastradas. O cálculo está usando as de ${P.ano}.</div>${ges?'<button class="btn sm" data-flpar>Atualizar tabelas</button>':''}</div>`:''}
  <div class="pp-k">
    <div class="tile" style="cursor:default"><div class="l">Bruto</div><div class="n">${brl(T('v'))}</div><div class="rl-s">${R.filter(r=>r.p.tipo==='pl').length} pró-labore · ${R.filter(r=>r.p.tipo==='clt').length} CLT</div></div>
    <div class="tile" style="cursor:default"><div class="l">INSS</div><div class="n">${brl(T('inss'))}</div><div class="rl-s">retido dos recibos</div></div>
    <div class="tile" style="cursor:default"><div class="l">IRRF</div><div class="n">${brl(T('irrf'))}</div><div class="rl-s">${brl(T('red'))} de redução (Lei 15.270)</div></div>
    <div class="tile" style="cursor:default"><div class="l">Líquido</div><div class="n">${brl(T('liq'))}</div><div class="rl-s">FGTS ${brl(T('fgts'))}</div></div></div>
  <section class="panel"><div class="ph" style="flex-wrap:wrap;gap:8px"><div style="display:flex;gap:4px;flex-wrap:wrap">${ch('','Todos')}${ch('pl','Pró-labore')}${ch('clt','Colaboradores CLT')}</div><span class="sp"></span>
    ${R.length?`<button class="btn sm" data-flall>Recibos do mês (${R.length})</button><button class="btn sm ghost" data-flxls>Exportar</button>`:''}</div>
  ${R.length?`<div class="tw"><table class="tlist"><thead><tr><th>Pessoa</th><th>Empresa</th><th>Tipo</th><th class="n">Bruto</th><th class="n">INSS</th><th class="n">IRRF</th><th class="n">Líquido</th><th class="n">FGTS</th><th></th></tr></thead><tbody>
    ${R.map(({p,c})=>`<tr><td><a href="#" data-fle="${esc(p.id)}"><b>${esc(p.nome)}</b></a><div style="font-size:.75rem;color:var(--mut)">${esc(p.funcao||'')}</div></td><td>${esc(p.empresa||'')}<div style="font-size:.75rem;color:var(--mut)">${esc(p.cnpj||'')}</div></td>
     <td><span class="flag">${p.tipo==='pl'?'Pró-labore':'CLT'}</span></td><td class="n">${brl(c.v)}</td><td class="n">${brl(c.inss)}<div style="font-size:.72rem;color:var(--mut)">${flPct(c.inssAl)}</div></td>
     <td class="n">${brl(c.irrf)}${c.red?`<div style="font-size:.72rem;color:var(--mut)">−${brl(c.red)} redutor</div>`:''}</td><td class="n"><b>${brl(c.liq)}</b></td><td class="n">${c.fgts?brl(c.fgts):'—'}</td>
     <td><button class="btn sm" data-flr="${esc(p.id)}">Recibo</button></td></tr>`).join('')}</tbody></table></div>`
   :empty(flLista().length?'Ninguém neste filtro.':'Cadastre os sócios (pró-labore) e colaboradores, ou importe a planilha de pró-labore. O cálculo usa as tabelas de INSS e IRRF do ano, com o redutor da Lei 15.270/2025.',ges?'<button class="btn sm pri" data-flnew>+ Pessoa</button>':'')}</section>
  <p style="font-size:.78rem;color:var(--mut);margin:10px 2px">Tabelas ${P.ano}: ${esc(P.fonte||'')}${P.atualizado?' · atualizadas em '+fmt(P.atualizado):''}. Pró-labore: INSS 11% até o teto. CLT: INSS progressivo e FGTS 8%. IRRF com a maior dedução entre INSS (+ dependentes) e o desconto simplificado.</p>`}
function flEditar(id){const ges=GT.gestor();const isNew=!id;const p=Object.assign({tipo:'pl',ativo:true,dep:0},isNew?{}:D.folha.get(id)||{});
  const emps=[];const vistos=new Set();flLista().forEach(x=>{const k=flDig(x.cnpj);if(k&&!vistos.has(k)){vistos.add(k);emps.push({n:x.empresa,c:x.cnpj,e:x.endereco||''})}});
  D.empresas.forEach(e=>{const k=flDig(e.cnpj);if(k.length===14&&!vistos.has(k)){vistos.add(k);emps.push({n:e.razao||e.fantasia||'',c:e.cnpj,e:e.endereco||''})}});
  emps.sort((a,b)=>(a.n||'').localeCompare(b.n||'','pt'));let tipo=p.tipo;
  openModal(`${mh(isNew?'Nova pessoa':esc(p.nome))}<form id="flForm"><div class="mb"><fieldset ${ges?'':'disabled'} style="border:0;padding:0;margin:0"><div class="fg">
    <div class="fd full"><div style="display:flex;gap:4px">${[['pl','Pró-labore (sócio)'],['clt','Colaborador CLT']].map(([k,n])=>`<button type="button" class="btn sm ${tipo===k?'pri':'ghost'}" data-flt="${k}">${n}</button>`).join('')}</div></div>
    ${emps.length?`<div class="fd full"><label for="fl_pick">Puxar empresa cadastrada</label><select class="sel" id="fl_pick"><option value="">Escolher…</option>${emps.map(x=>`<option value="${esc(flDig(x.c))}">${esc(x.n)} · ${esc(x.c)}</option>`).join('')}</select></div>`:''}
    <div class="fd"><label for="fl_emp">Empresa (empregador)</label><input class="inp" id="fl_emp" value="${esc(p.empresa||'')}" required></div>
    <div class="fd"><label for="fl_cnpj">CNPJ</label><input class="inp" id="fl_cnpj" inputmode="numeric" value="${esc(p.cnpj||'')}"></div>
    <div class="fd full"><label for="fl_end">Endereço da empresa</label><input class="inp" id="fl_end" value="${esc(p.endereco||'')}"></div>
    <div class="fd full"><label for="fl_nome">Nome</label><input class="inp" id="fl_nome" value="${esc(p.nome||'')}" required></div>
    <div class="fd"><label for="fl_fun">Função</label><input class="inp" id="fl_fun" value="${esc(p.funcao||'')}" placeholder="Diretor / Sócio administrador"></div>
    <div class="fd"><label for="fl_cbo">CBO</label><input class="inp" id="fl_cbo" value="${esc(p.cbo||'')}"></div>
    <div class="fd"><label for="fl_v" id="fl_vl">${tipo==='pl'?'Valor do pró-labore':'Salário base'} (R$)</label><input class="inp" id="fl_v" inputmode="decimal" value="${p.valor?flNum(p.valor):''}" required></div>
    <div class="fd"><label for="fl_dep">Dependentes para IRRF</label><input class="inp" id="fl_dep" type="number" min="0" value="${+p.dep||0}"></div>
    <div class="fd full"><label class="chk"><input type="checkbox" id="fl_at" ${p.ativo!==false?'checked':''}> Ativo (entra nos recibos do mês)</label></div>
    <div class="fd full" id="fl_prev" style="background:var(--panel2);border:1px solid var(--line);border-radius:var(--r);padding:10px 12px"></div>
  </div></fieldset></div><div class="mf">${!isNew&&ges?'<button type="button" class="btn warn" id="fl_del">Excluir</button><span style="flex:1"></span>':''}<button type="button" class="btn" data-close>${ges?'Cancelar':'Fechar'}</button>${ges?'<button class="btn pri" type="submit">Salvar</button>':''}</div></form>`);
  const prev=()=>{const v=flParse($('#fl_v').value);const el=$('#fl_prev');if(!(v>0)){el.innerHTML='<span style="color:var(--mut)">Informe o valor para ver o cálculo.</span>';return}const c=flCalc({tipo,valor:v,dep:+$('#fl_dep').value||0},FL.ym);
    el.innerHTML=`<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px"><div><small style="color:var(--mut)">INSS</small><div><b>${brl(c.inss)}</b></div></div><div><small style="color:var(--mut)">IRRF</small><div><b>${brl(c.irrf)}</b></div></div><div><small style="color:var(--mut)">Líquido</small><div><b style="color:var(--grn)">${brl(c.liq)}</b></div></div><div><small style="color:var(--mut)">FGTS</small><div><b>${c.fgts?brl(c.fgts):'—'}</b></div></div></div>
     <div style="font-size:.75rem;color:var(--mut);margin-top:6px">Base IRRF ${brl(c.base)} (${c.usouSimpl?'desconto simplificado':'INSS + dependentes'}) · alíquota ${flPct(c.irAl)} · IR pela tabela ${brl(c.irTab)}${c.red?' · redutor '+brl(c.red):''}</div>`};
  prev();$('#fl_v').addEventListener('input',prev);$('#fl_dep').addEventListener('input',prev);
  document.querySelectorAll('[data-flt]').forEach(b=>b.addEventListener('click',()=>{tipo=b.dataset.flt;document.querySelectorAll('[data-flt]').forEach(x=>{x.classList.toggle('pri',x===b);x.classList.toggle('ghost',x!==b)});$('#fl_vl').textContent=(tipo==='pl'?'Valor do pró-labore':'Salário base')+' (R$)';prev()}));
  const pk=$('#fl_pick');if(pk)pk.addEventListener('change',e=>{const x=emps.find(z=>flDig(z.c)===e.target.value);if(x){$('#fl_emp').value=x.n||'';$('#fl_cnpj').value=x.c||'';if(x.e)$('#fl_end').value=x.e}});
  if(!ges)return;
  $('#flForm').addEventListener('submit',ev=>{ev.preventDefault();const v=flParse($('#fl_v').value);if(!(v>0)){toast('Informe o valor');return}
    const body=Object.assign({},p,{tipo,empresa:val('fl_emp').toUpperCase(),cnpj:flCNPJ(val('fl_cnpj')),endereco:val('fl_end'),nome:val('fl_nome').toUpperCase(),funcao:val('fl_fun').toUpperCase(),cbo:val('fl_cbo'),valor:v,dep:+val('fl_dep')||0,ativo:$('#fl_at').checked});delete body.id;
    if(!isNew&&+p.valor!==v)body.hist=(p.hist||[]).slice(-30).concat([{em:agora(),de:+p.valor||0,para:v,por:ME}]);
    put('folha',id||uid(),body);closeModal();toast('Salvo')});
  const dl=$('#fl_del');if(dl)dl.addEventListener('click',()=>confirmBox(`Excluir <b>${esc(p.nome)}</b> da folha?`,'Excluir',()=>{del('folha',id);toast('Excluído')}));
}
function flRecibos(L,ym){const mes=flYmLbl(ym);const pc=flPct,n=flNum;
  const via=(p,c)=>{const pl=p.tipo==='pl';const linhas=[[10023,pl?'PRÓ LABORE':'SALÁRIO BASE','',n(c.v),''],[19998,'INSS',pc(c.inssAl),'',n(c.inss)],[10060,'IRRF',pc(c.irAl),'',n(c.irrf)]];
   return `<div class="via"><div class="mn">
    <div class="hd"><div class="emp"><div class="lb">EMPREGADOR</div><div class="r"><span class="lb">Nome</span><b>${esc(p.empresa||'')}</b></div><div class="r"><span class="lb">Endereço</span><span>${esc(p.endereco||'')}</span></div><div class="r"><span class="lb">CNPJ</span><b>${esc(p.cnpj||'')}</b></div></div>
     <div class="tit"><b class="tt">Recibo de Pagamento de ${pl?'Pró-Labore':'Salário'}</b><span class="lb">Referente ao Mês / Ano</span><b class="mes">${mes}</b></div></div>
    <div class="fn"><div><span class="lb">CÓDIGO</span><b>1</b></div><div><span class="lb">NOME DO FUNCIONÁRIO</span><b>${esc(p.nome||'')}</b></div><div><span class="lb">CBO</span><b>${esc(p.cbo||'')}</b></div><div><span class="lb">FUNÇÃO</span><b>${esc(p.funcao||'')}</b></div></div>
    <div class="it"><div class="ih">Cód.</div><div class="ih">Descrição</div><div class="ih">Referência</div><div class="ih">Proventos</div><div class="ih">Descontos</div>
     <div class="ic">${linhas.map(l=>`<div>${l[0]}</div>`).join('')}</div><div class="ic l">${linhas.map(l=>`<div>${l[1]}</div>`).join('')}</div><div class="ic">${linhas.map(l=>`<div>${l[2]||'&nbsp;'}</div>`).join('')}</div><div class="ic">${linhas.map(l=>`<div>${l[3]||'&nbsp;'}</div>`).join('')}</div><div class="ic">${linhas.map(l=>`<div>${l[4]||'&nbsp;'}</div>`).join('')}</div></div>
    <div class="tot"><div class="msg"><span class="lb">MENSAGENS</span></div><div class="tv"><span class="lb">Total dos Vencimentos</span><span>${n(c.v)}</span></div><div class="tv"><span class="lb">Total dos Descontos</span><span>${n(c.desc)}</span></div>
     <div class="lq"><span class="lb b">Líquido a Receber -&gt;</span></div><div class="lqv"><b>${n(c.liq)}</b></div></div>
    <div class="bs"><div><span class="lb">Salário Base</span><span>${n(c.v)}</span></div><div><span class="lb">Base Cálc. INSS</span><span>${n(Math.min(c.v,c.P.teto))}</span></div><div><span class="lb">Base Cálc. FGTS</span><span>${pl?'0,00':n(c.v)}</span></div><div><span class="lb">FGTS do Mês</span><span>${n(c.fgts)}</span></div><div><span class="lb">Base Cálc. IRRF</span><span>${n(c.base)}</span></div><div><span class="lb">Faixa IRRF</span><span>${pc(c.irAl)}</span></div></div>
   </div><div class="ass"><div class="dc"><span>DECLARO TER RECEBIDO A IMPORTÂNCIA LÍQUIDA DISCRIMINADA NESTE RECIBO.</span></div><div class="as1"><span class="lb">ASSINATURA</span></div><div class="as2"><span class="lb">DATA</span><span class="dt">/&nbsp;&nbsp;&nbsp;&nbsp;/</span></div></div></div>`};
  const css=`@page{size:A4;margin:8mm}*{box-sizing:border-box}body{font:9.5px/1.25 Arial,Helvetica,sans-serif;color:#000;margin:0}
.pg{height:281mm;display:flex;flex-direction:column;justify-content:space-around;page-break-after:always}.pg:last-child{page-break-after:auto}.cut{border-top:1px dashed #888;margin:0 -2mm}
.via{display:flex;gap:2.5mm;height:126mm}.mn{flex:1;border:1px solid #000;display:flex;flex-direction:column;min-width:0}
.lb{font-size:6px;color:#000;margin-right:3px}.lb.b{font-weight:bold;font-size:6.5px}
.hd{display:flex;justify-content:space-between;padding:2mm 2mm 1.5mm;border-bottom:1px solid #000}.emp .r{display:flex;align-items:baseline;gap:2px;margin-top:1px}.emp .r .lb{width:28px;text-align:right}.emp b{font-size:9.5px}
.tit{display:flex;flex-direction:column;align-items:flex-end;text-align:right}.tit .tt{font-size:12.5px;margin-bottom:4px}.tit .mes{font-size:11px;margin-top:3px}
.fn{display:grid;grid-template-columns:12mm 1fr 18mm 50mm;border-bottom:1px solid #000;padding:1mm 2mm 1.5mm}.fn>div{display:flex;flex-direction:column}.fn b{font-size:9.5px;margin-top:1px}
.it{flex:1;display:grid;grid-template-columns:13mm 1fr 18mm 22mm 22mm;grid-template-rows:auto 1fr;border-bottom:1px solid #000}
.ih{border-right:1px solid #000;border-bottom:1px solid #000;text-align:center;padding:1px 2px}.ih:last-of-type{border-right:0}
.ic{border-right:1px solid #000;padding:2px 3px;text-align:right}.ic:last-child{border-right:0}.ic.l{text-align:left}.ic>div{height:12px}
.tot{display:grid;grid-template-columns:1fr 22mm 22mm;grid-template-rows:auto auto}.msg{grid-row:span 2;border-right:1px solid #000;padding:1px 3px}
.tv{display:flex;flex-direction:column;align-items:flex-end;padding:1px 3px;border-right:1px solid #000}.tv:nth-child(3){border-right:0}
.lq{border-top:1px solid #000;border-right:1px solid #000;display:flex;align-items:center;justify-content:flex-end;padding:2px 3px}.lqv{border-top:1px solid #000;text-align:right;padding:2px 3px;font-size:11px}
.bs{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border-top:1px solid #000}.bs>div{display:flex;flex-direction:column;align-items:flex-end;padding:1px 3px}
.dc{position:absolute;left:0;top:0;bottom:0;width:5mm;display:flex;align-items:center;justify-content:center}.dc span{writing-mode:vertical-rl;transform:rotate(180deg);font-size:6.5px;white-space:nowrap}
.ass{width:20mm;border:1px solid #000;display:flex;flex-direction:column;position:relative}.as1{flex:3;position:relative}.as2{flex:1.1;position:relative}
.as1 .lb,.as2 .lb{position:absolute;right:2px;top:50%;writing-mode:vertical-rl;transform:translateY(-50%) rotate(180deg);font-size:6px}
.as1::after{content:"";position:absolute;left:10mm;top:6mm;bottom:6mm;border-left:1px solid #000}.as2::after{content:"";position:absolute;left:10mm;top:3mm;bottom:3mm;border-left:1px solid #000}
.as2 .dt{position:absolute;left:5.5mm;top:50%;transform:translateY(-50%) rotate(-90deg);font-size:9px}
@media screen{body{background:#e9e9e9}.pg{background:#fff;width:210mm;margin:8mm auto;padding:4mm 8mm;box-shadow:0 2px 10px rgba(0,0,0,.15)}}`;
  const html=`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Recibos ${mes}</title><style>${css}</style></head><body>
   ${L.map(p=>{const c=flCalc(p,ym);return `<div class="pg"><div class="cut"></div>${via(p,c)}<div class="cut"></div>${via(p,c)}<div class="cut"></div></div>`}).join('')}<script>setTimeout(()=>print(),500)<\/script></body></html>`;
  const w=window.open('','_blank');if(w){w.document.write(html);w.document.close()}else{flBaixar(new Blob([html],{type:'text/html'}),'recibos-'+ym+'.html');toast('Recibo baixado: abra e imprima em PDF')}}
function flBaixar(blob,nome){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=nome;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},1500)}
function flExportar(){const ym=FL.ym;const rows=[['Competência','Empresa','CNPJ','Nome','Função','Tipo','Bruto','INSS','Base IRRF','IRRF','Redutor','Líquido','FGTS']];
  flFiltrada().forEach(p=>{const c=flCalc(p,ym);rows.push([flYmLbl(ym),p.empresa,p.cnpj,p.nome,p.funcao,p.tipo==='pl'?'Pró-labore':'CLT',c.v,c.inss,c.base,c.irrf,c.red,c.liq,c.fgts])});
  const wb=XLSX.utils.book_new();XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet(rows),'Folha');flBaixar(new Blob([XLSX.write(wb,{type:'array',bookType:'xlsx'})]),'folha-'+ym+'.xlsx')}
function flTabelas(){const ano=FL.ym.slice(0,4);const P=flPar(ano);const y=P.faltando||ano;const T=t=>t.map(f=>f.map(x=>String(x).replace('.',',')).join(' ; ')).join('\n');const vv=x=>String(x==null?'':x).replace('.',',');
  openModal(`${mh('Tabelas INSS e IRRF '+esc(y))}<form id="flTp"><div class="mb"><p style="margin:0 0 10px;font-size:.85rem;color:var(--mut)">Quando sair a tabela nova (normalmente em janeiro), atualize aqui. Cada linha: <b>a partir de ; alíquota ; parcela a deduzir</b>.</p><div class="fg">
    <div class="fd"><label for="tp_inss">INSS empregado (progressivo)</label><textarea class="inp" id="tp_inss" rows="5">${T(P.inss.map(f=>[f[0],f[1]*100,f[2]]))}</textarea></div>
    <div class="fd"><label for="tp_irrf">IRRF mensal</label><textarea class="inp" id="tp_irrf" rows="5">${T(P.irrf.map(f=>[f[0],f[1]*100,f[2]]))}</textarea></div>
    <div class="fd"><label for="tp_teto">Teto INSS</label><input class="inp" id="tp_teto" value="${flNum(P.teto)}"></div><div class="fd"><label for="tp_pl">Pró-labore INSS (%)</label><input class="inp" id="tp_pl" value="${vv(P.plAliq*100)}"></div>
    <div class="fd"><label for="tp_simpl">Desconto simplificado</label><input class="inp" id="tp_simpl" value="${flNum(P.simpl)}"></div><div class="fd"><label for="tp_dep">Dedução por dependente</label><input class="inp" id="tp_dep" value="${flNum(P.dep)}"></div>
    <div class="fd"><label for="tp_ate">Isenção total até (redutor)</label><input class="inp" id="tp_ate" value="${flNum((P.redutor||{}).ate)}"></div><div class="fd"><label for="tp_lim">Redução até</label><input class="inp" id="tp_lim" value="${flNum((P.redutor||{}).lim)}"></div>
    <div class="fd"><label for="tp_a">Redutor: coeficiente fixo</label><input class="inp" id="tp_a" value="${vv((P.redutor||{}).a)}"></div><div class="fd"><label for="tp_b">Redutor: coeficiente da renda</label><input class="inp" id="tp_b" value="${vv((P.redutor||{}).b)}"></div>
    <div class="fd"><label for="tp_fgts">FGTS (%)</label><input class="inp" id="tp_fgts" value="${vv(P.fgts*100)}"></div><div class="fd full"><label for="tp_fonte">Fonte / norma</label><input class="inp" id="tp_fonte" value="${esc(P.fonte||'')}"></div>
  </div></div><div class="mf"><button type="button" class="btn" data-close>Cancelar</button><button class="btn pri" type="submit">Salvar tabelas de ${esc(y)}</button></div></form>`,true);
  $('#flTp').addEventListener('submit',ev=>{ev.preventDefault();const tab=id=>$(id).value.split('\n').map(l=>l.split(';').map(flParse)).filter(r=>r.length>=3&&r.every(z=>!isNaN(z))).map(r=>[r[0],r[1]/100,r[2]]).sort((a,b)=>a[0]-b[0]);
    const par={fonte:val('tp_fonte'),atualizado:hoje(),inss:tab('#tp_inss'),irrf:tab('#tp_irrf'),teto:flParse(val('tp_teto')),plAliq:flParse(val('tp_pl'))/100,simpl:flParse(val('tp_simpl')),dep:flParse(val('tp_dep')),redutor:{ate:flParse(val('tp_ate')),lim:flParse(val('tp_lim')),a:flParse(val('tp_a')),b:flParse(val('tp_b'))},fgts:flParse(val('tp_fgts'))/100};
    if(!par.inss.length||!par.irrf.length||!(par.teto>0)){toast('Confira as tabelas');return}
    const cur=D.folha.get('_tabelas')||{};put('folha','_tabelas',{anos:Object.assign({},cur.anos||{},{[y]:par})});closeModal();toast('Tabelas salvas')})}
function flImportar(){
  openModal(`${mh('Importar planilha de pró-labore')}<div class="mb"><p style="margin:0 0 10px">Use a planilha de pró-labore e colaborador (abas <b>BASE DE CALCULO</b> e <b>BASE COLABORADOR</b>) ou uma lista simples com colunas Empresa, CNPJ, Nome, Função, Tipo (pró-labore/CLT) e Valor.</p><input type="file" id="flF" accept=".xlsx,.xls,.csv"><div id="flR" style="margin-top:12px"></div></div>`);
  const nk=s=>norm(String(s||'')).replace(/[^a-z0-9 -]/g,' ').replace(/\s+/g,' ').trim();
  $('#flF').addEventListener('change',async e=>{const f=e.target.files[0];if(!f)return;const R=$('#flR');R.textContent='Lendo…';
    try{const wb=XLSX.read(await f.arrayBuffer(),{cellDates:true});const out=[];
      const kv=ws=>{const o={};for(const r of XLSX.utils.sheet_to_json(ws,{header:1,defval:''}))if(r[0]!=='')o[nk(r[0])]=r[1];return o};
      const pega=o=>k=>{for(const key in o)if(key.startsWith(k))return o[key];return ''};
      for(const name of wb.SheetNames){const nn=nk(name);const ws=wb.Sheets[name];
        if(nn.startsWith('base de calculo')){const g=pega(kv(ws));const v=+g('pro-labore')||+g('pro labore');if(g('nome do empresario')&&v)out.push({tipo:'pl',empresa:String(g('nome')).trim(),cnpj:String(g('cnpj')).trim(),nome:String(g('nome do empresario')).trim(),funcao:String(g('funcao')).trim(),endereco:String(g('endereco')).trim(),valor:v})}
        else if(nn.startsWith('base colaborador')){const g=pega(kv(ws));const v=+g('salario base');if(g('nome do colaborador')&&v)out.push({tipo:'clt',empresa:String(g('nome')).trim(),cnpj:String(g('cnpj')).trim(),nome:String(g('nome do colaborador')).trim(),funcao:String(g('funcao')).trim(),endereco:String(g('endereco')).trim(),valor:v})}
        else if(!/recibo|pro labore$/.test(nn)){for(const r of XLSX.utils.sheet_to_json(ws,{defval:'',raw:false})){const col=(...ks)=>{for(const k of Object.keys(r)){const n=nk(k);if(ks.some(x=>n.includes(x)))return String(r[k]).trim()}return ''};
          const nome=col('nome','socio','colaborador');const v=flParse(col('valor','salario','pro-labore','pro labore'));if(nome&&v>0)out.push({tipo:/clt|colab|func/i.test(col('tipo'))?'clt':'pl',empresa:col('empresa','empregador','razao'),cnpj:col('cnpj'),nome,funcao:col('funcao','cargo'),valor:v})}}}
      const keyOf=x=>nk(x.nome)+'|'+flDig(x.cnpj);const have=new Map(flLista().map(x=>[keyOf(x),x]));
      R.innerHTML=out.length?`<div class="rows">${out.map(x=>`<div style="display:flex;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)"><div style="flex:1"><b>${esc(x.nome.toUpperCase())}</b><div style="font-size:.76rem;color:var(--mut)">${esc(x.empresa)} · ${esc(x.cnpj)} · ${x.tipo==='pl'?'Pró-labore':'CLT'}</div></div><span>${brl(x.valor)}</span><span class="flag">${have.has(keyOf(x))?'atualizar':'novo'}</span></div>`).join('')}</div><div class="mf" style="padding:12px 0 0"><button class="btn pri" id="flGo">Importar ${out.length}</button></div>`:'<p style="color:var(--red)">Não encontrei dados de pró-labore ou colaborador nessa planilha.</p>';
      const go=$('#flGo');if(go)go.addEventListener('click',()=>{out.forEach(x=>{const ex=have.get(keyOf(x));const body=Object.assign({},ex||{ativo:true,dep:0},x,{empresa:x.empresa.toUpperCase(),nome:x.nome.toUpperCase(),funcao:(x.funcao||'').toUpperCase(),cnpj:flCNPJ(x.cnpj)});const id=ex?ex.id:uid();delete body.id;put('folha',id,body)});closeModal();toast(out.length+' importado(s)')})}
    catch(err){R.innerHTML=`<p style="color:var(--red)">Não consegui ler: ${esc(err.message)}</p>`}})}
document.addEventListener('click',e=>{const t=e.target.closest('[data-flm],[data-flf],[data-fle],[data-flr],[data-flall],[data-flxls],[data-flnew],[data-flpar],[data-flimp]');if(!t||!document.getElementById('view')||!document.getElementById('view').contains(t))return;e.preventDefault();
  const d=t.dataset;if(d.flm){FL.ym=flYmAdd(FL.ym,+d.flm);render()}else if(d.flf!==undefined){FL.f=d.flf;render()}else if(d.fle)flEditar(d.fle);else if(d.flr){const p=flLista().find(x=>x.id===d.flr);if(p)flRecibos([p],FL.ym)}
  else if('flall' in d)flRecibos(flFiltrada(),FL.ym);else if('flxls' in d)flExportar();else if('flnew' in d)flEditar(null);else if('flpar' in d)flTabelas();else if('flimp' in d)flImportar()});
