// DOM-only readers for use inside the documented Computer Use browser evaluate API.
// These functions do not navigate, click, access cookies, or call private endpoints.
export function readFeeds() {
  return [...document.querySelectorAll('.a11y_feed_card_main')].map(el=>{
    const lines=el.innerText.split('\n').map(v=>v.trim()).filter(Boolean);
    const time=lines.find(v=>/^(\d{1,2}:\d{2}|昨天|前天|\d{1,2}月\d{1,2}日)/.test(v))||'';
    return {name:lines[0]||'',display_time:time,preview:lines.slice(lines.indexOf(time)+1).join('\n'),
            active:el.closest('.a11y_feed_card_item')?.getAttribute('data-feed-active')==='true'};
  }).filter(v=>v.name);
}

export function readMessages(options) {
  const {day,peer,selfName=''}=options;
  const base=new Date(day+'T12:00:00+08:00');
  function stamp(raw) {
    raw=(raw||'').trim();let date=day,time='';
    const hh=raw.match(/(\d{1,2}):(\d{2})/);if(!hh)return null;
    time=hh[1].padStart(2,'0')+':'+hh[2];
    if(raw.includes('昨天'))date=new Date(base.getTime()-86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
    else if(raw.includes('前天'))date=new Date(base.getTime()-2*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
    else{
      const md=raw.match(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日/);
      if(md)date=(md[1]||day.slice(0,4))+'-'+md[2].padStart(2,'0')+'-'+md[3].padStart(2,'0');
    }
    return date+'T'+time+':00+08:00';
  }
  const rows=[...document.querySelectorAll('#messenger .js-message-item')];
  let lastDay=day,lastAuthor=peer;

  return {messages:rows.map(el=>{
    const restricted=!!el.querySelector('[data-im-copy-permission-invalid="true"]');
    const raw=el.querySelector('.message-timestamp')?.textContent||'';
    let timestamp=stamp(raw);
    if(timestamp && /^\d{1,2}:\d{2}$/.test(raw.trim()) && !el.classList.contains('message-item-first'))timestamp=lastDay+timestamp.slice(10);
    if(timestamp)lastDay=timestamp.slice(0,10);
    const content=el.querySelector('.message-content') || el.querySelector('[data-element="message-section-left"]') || el;
    let text=restricted?'[保密消息：未采集正文]':content.innerText.trim();
    if(!text&&el.querySelector('img'))text='[图片消息，未下载图片]';
    const self=el.classList.contains('message-self');
    const author=el.querySelector('.message-info-name,.message-sender-name,.message-user-name,.message-name')?.textContent?.trim()|| (self?selfName:el.classList.contains('message-item-first')?peer:lastAuthor);
    lastAuthor=author;
    return {message_id:el.id,position:el.getAttribute('data-position'),timestamp,display_time:raw,time_precision:'minute',
            sender_name:author,sender:{name:author,sender_type:'user'},text,restricted,
            is_self:self,has_attachment:!!content.querySelector('img,video,audio'),
            has_thread:el.classList.contains('message-thread-container'),reply_count:(el.innerText.match(/(\d+)\s*条回复/)||[])[1]||0};
  }).filter(v=>v.message_id&&v.timestamp),first_display_time:rows[0]?.querySelector('.message-timestamp')?.textContent||'',
  last_display_time:rows.at(-1)?.querySelector('.message-timestamp')?.textContent||'',rendered_count:rows.length};
}

export function readThread(options) {
  const {day,thread}=options, article=document.querySelector('article.chatThreadList');
  if(!article)return {messages:[],boundary:'未打开线程',complete:false};
  const cards=[...article.querySelectorAll('.content-card-wrapper,.message-container')].filter(e=>e.querySelector('.timestamp')&& !e.parentElement.closest('.content-card-wrapper,.message-container'));
  const messages=cards.map(el=>{
    const raw=el.querySelector('.timestamp')?.textContent?.trim()||'';
    const hh=raw.match(/(\d{1,2}):(\d{2})/);if(!hh)return null;
    let date=day;
    if(/昨天|前天/.test(raw))date=new Date(new Date(day+'T12:00:00+08:00').getTime()-(raw.includes('前天')?2:1)*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
    const md=raw.match(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日/);if(md)date=(md[1]||day.slice(0,4))+'-'+md[2].padStart(2,'0')+'-'+md[3].padStart(2,'0');
    const restricted=!!el.querySelector('[data-im-copy-permission-invalid="true"]');
    const text=restricted?'[保密消息：未采集正文]':(el.querySelector('.message-content')?.innerText||'').trim();
    return {thread_id:thread,timestamp:date+'T'+hh[1].padStart(2,'0')+':'+hh[2]+':00+08:00',display_time:raw,time_precision:'minute',sender_name:el.querySelector('.aut')?.textContent?.trim()||'',text,restricted};
  }).filter(Boolean);
  return {messages,first:messages[0]?.display_time,last:messages.at(-1)?.display_time,
    load_more:[...article.querySelectorAll('*')].filter(e=>e.children.length<2&&/加载更多|更早.*回复/.test(e.innerText)).map(e=>e.innerText),
    scrollers:[...article.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+50&&e.clientHeight>100).map(e=>({cls:e.className,top:e.scrollTop,h:e.clientHeight,sh:e.scrollHeight,rect:[e.getBoundingClientRect().x,e.getBoundingClientRect().y,e.getBoundingClientRect().width,e.getBoundingClientRect().height]}))};
}

export function readTopic({day,thread}) {
  const rows=[...document.querySelectorAll('.threadMsgWrap[data-id]')];
  let date=day;
  return {messages:rows.map(el=>{
    const raw=el.querySelector('.groupMsgDate')?.textContent?.trim()||'';
    const hh=raw.match(/(\d{1,2}):(\d{2})/);if(!hh)return null;
    date=day;
    if(/昨天|前天/.test(raw))date=new Date(new Date(day+'T12:00:00+08:00').getTime()-(raw.includes('前天')?2:1)*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
    const md=raw.match(/(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日/);if(md)date=(md[1]||day.slice(0,4))+'-'+md[2].padStart(2,'0')+'-'+md[3].padStart(2,'0');
    const restricted=!!el.querySelector('[data-im-copy-permission-invalid="true"]');
    return {message_id:el.getAttribute('data-id'),position:'thread:'+thread+':'+el.getAttribute('data-position'),thread_id:thread,timestamp:date+'T'+hh[1].padStart(2,'0')+':'+hh[2]+':00+08:00',display_time:raw,time_precision:'minute',sender_name:el.querySelector('.groupMsgHeader_username')?.textContent?.trim()||'',text:restricted?'[保密消息：未采集正文]':(el.querySelector('.groupMsgContent')?.innerText||'').trim(),restricted};
  }).filter(Boolean)};
}
