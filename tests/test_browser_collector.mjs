import assert from 'node:assert/strict';
import {readMessages} from '../browser_collector.mjs';
// A compact DOM contract fixture for the date/sender cases observed in Feishu.
function row(id,time,{first=false,self=false,name='',text='消息'}={}) {
  return {id,classList:{contains:c=>c==='message-item-first'?first:c==='message-self'?self:false},
    getAttribute:key=>key==='data-position'?id:null,
    querySelector:sel=>sel==='.message-timestamp'?{textContent:time}:sel==='.message-content'?{innerText:text,querySelector:()=>null}:sel.startsWith('.message-info-name')&&name?{textContent:name}:null,
    innerText:text};
}
globalThis.document={querySelectorAll:()=>[
  row('1','昨天 11:31',{first:true,name:'孙浩'}),
  row('2','11:31'),
  row('3','11:58',{first:true,name:'孙浩'}),
  row('4','16:08',{first:true,self:true}),
  row('5','16:08',{first:true,text:'本机 Codex 已连接'}),
  row('6','16:09'),
  row('7','',{first:true})
]};
const r=readMessages({day:'2026-10-15',peer:'workstation-bot',selfName:'示例用户'});
assert.equal(r.messages.length,6);
assert.equal(r.messages[1].timestamp,'2026-10-14T11:31:00+08:00');
assert.equal(r.messages[2].timestamp,'2026-10-15T11:58:00+08:00');
assert.equal(r.messages[1].sender_name,'孙浩');
assert.equal(r.messages[3].sender_name,'示例用户');
assert.equal(r.messages[4].sender_name,'workstation-bot');
assert.equal(r.messages[5].sender_name,'workstation-bot');
console.log('Browser date inheritance and sender switching: passed');
