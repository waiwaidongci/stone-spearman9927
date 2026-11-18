import {DOMAIN} from '../constants/domain.js';
import {store,load} from '../stores/research.js';
import {runs} from '../api/research.js';
import {studySelect} from '../components/common/study-select.js';
import {runList} from '../components/common/run-list.js';
import {bindForm} from '../hooks/forms.js';
import {esc} from '../utils/format.js';
const interval=DOMAIN.interval||{};
const capacity=interval.overlap_capacity||8;
const deadline=interval.deadline_seconds||30;
export function render(){const writable=localStorage.getItem('research-role')!=='viewer';return `<div class="eyebrow">02 / METHOD WORKSHEET</div><h1>${DOMAIN.field_label}</h1><p class="lead">${DOMAIN.algorithm}</p><div class="method-note">${DOMAIN.note}</div>${writable?`<form id="run-form" class="worksheet">${studySelect()}<label>本次研究名称<input name="name" required minlength="2" value="${esc(DOMAIN.names[0])} · 核算"></label><div class="inline-form"><label>重叠容量 (1–${capacity})<input name="overlap_capacity" type="number" min="1" max="${capacity}" step="1" value="${capacity}" required></label><label>区间研究<input value="吸水率按开区间、取值互异" disabled></label></div><p>提交时冻结全部观测的区间与孔隙率并生成 SHA256，后台 worker 独立实算。任一点最多 ${capacity} 段重叠；超过容量的批次在排队前被拒绝。结果给出 ρ 的精确上下界，并各附一组可回算的区间内互异取值，${deadline} 秒内完成。</p><button type="submit">冻结输入并排队计算 →</button></form>`:'<p class="method-note">观察员可阅读研究记录，分析师与负责人可以发起计算。</p>'}<h2>计算记录</h2>${runList()}`;}
export function bind(){bindForm('run-form',async data=>{const r=await runs.create({study_id:+data.study_id,name:data.name,parameters:{mode:'interval',overlap_capacity:+data.overlap_capacity}});store.runId=r.id;await load();location.hash='results/'+r.id;});const sel=document.getElementById('study-select');if(sel)sel.onchange=()=>store.studyId=+sel.value;}
