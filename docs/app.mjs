import config from './config.mjs';
import {parseAnswerFile,summarize,sha256} from './scoring.mjs';
import {referenceLevels} from './reference.mjs';
const $=id=>document.getElementById(id);
let selected=null,report=null;
const baseline=config.historical_baseline;
if(baseline){
 const rate=(v)=>`${(v*100).toFixed(1)}%`;
 $('baseline-accuracy').textContent=`${rate(baseline.accuracy)} · ${Math.round(baseline.accuracy*baseline.n)}/${baseline.n}`;
 $('baseline-within').textContent=`${rate(baseline.within_one_level)} · ${Math.round(baseline.within_one_level*baseline.n)}/${baseline.n}`;
 $('baseline-rho').textContent=baseline.spearman_rho.toFixed(4);
}
const save=(text,name,type='application/json')=>{const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
function reset(){report=null;for(const id of ['accuracy','within-one','rho'])$(id).textContent='—';$('coverage').textContent='等待完整答案';$('exact-count').textContent='预测档位与参考档位相同';$('within-count').textContent='包括完全命中及相邻档位';$('rho-note').textContent='使用并列平均秩计算排序相关性';$('download-report').hidden=true;}
function fail(error){$('error').textContent=error instanceof Error?error.message:String(error);$('error').hidden=false;}
$('answers').addEventListener('change',async()=>{
 const file=$('answers').files?.[0];selected=null;$('score').disabled=true;$('error').hidden=true;reset();
 if(!file){$('filename').textContent='尚未选择 · 最大 4 MB';return;}
 $('filename').textContent=file.name;
 try{
  if(!file.name.toLowerCase().endsWith('.jsonl'))throw Error('请选择 .jsonl 答案文件。');
  if(file.size>4*1024*1024)throw Error('答案文件不能超过 4 MB。');
  const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
  // Ignore a read that completed after the user already selected another file.
  if($('answers').files?.[0]!==file)return;
  const rows=parseAnswerFile(text,config.ids);selected={text,name:file.name,rows};
  $('filename').textContent=`${file.name} · 已校验 ${rows.length}/87 题`;$('score').disabled=false;
 }catch(error){if($('answers').files?.[0]===file)fail(error);}
});
document.querySelector('form').addEventListener('submit',async event=>{
 event.preventDefault();if(!selected)return;const source=selected;$('score').disabled=true;$('error').hidden=true;
 try{
  const truth=referenceLevels();if(truth.length!==config.ids.length)throw Error('参考数据不完整。');
  const metrics=summarize(truth,source.rows.map(r=>r.level));
  const digest=await sha256(source.text);if(selected!==source)return;
  report={report_version:2,dataset_id:config.dataset_id,dataset_version:config.dataset_version,bundle_fingerprint:config.bundle_fingerprint,required_generation_protocol_id:config.protocol_id,required_prompt_set_sha256:config.prompt_set_sha256,protocol_id:'web-file-v1',execution:'browser-local',model_identity_independently_verified:false,generation_protocol_independently_verified:false,graded_at_utc:new Date().toISOString(),prediction_sha256:digest,submission_name:source.name,primary_metrics:['accuracy','within_one_level','spearman_rho'],metric_targets:{accuracy:'maximize',within_one_level:1,spearman_rho:1},rationale_quality_scored:false,metrics};
  const pct=x=>`${(100*x).toFixed(1)}%`;
  $('accuracy').textContent=pct(metrics.accuracy);$('within-one').textContent=pct(metrics.within_one_level);$('rho').textContent=metrics.spearman_rho===null?'未定义':metrics.spearman_rho.toFixed(4);
  $('coverage').textContent=`${metrics.n}/87 题 · 计算完成`;$('exact-count').textContent=`${metrics.exact_matches}/87 题完全一致`;$('within-count').textContent=`${metrics.within_one_count}/87 题 · ${metrics.n-metrics.within_one_count} 题偏差超过一档`;
  $('rho-note').textContent=metrics.spearman_rho===null?'常数预测的相关系数未定义':'相关系数与命中率分别计算';$('download-report').hidden=false;
 }catch(error){fail(error);}finally{$('score').disabled=!selected;}
});
$('template').onclick=()=>save(config.ids.map(id=>JSON.stringify({id,level:null})).join('\n')+'\n','answers-template.jsonl','application/x-ndjson');
$('download-report').onclick=()=>{if(report)save(JSON.stringify(report,null,2)+'\n','luogubench-result.json');};
