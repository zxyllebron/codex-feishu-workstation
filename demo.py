"""Fictional, disposable UI data. Does not import or connect to any account."""
import storage as db
from datetime import date,timedelta

def seed():
    cfg=db.get('settings');cfg.update(name='朋友',schedule_enabled=False,notify_feishu=False);db.put('settings',cfg)
    db.put('feishu_connection',{'ready':True,'mode':'user','phase':'ready','message':'演示账户 · 虚构数据，不连接飞书'})
    db.put('feishu_self',{'name':'示例用户','open_id':'ou_demo'})
    db.put('feishu_crawl',{'status':'complete','mode':'user','chats_done':2,'chats_total':2,'messages':2,'errors':[],'pending_work':[]})
    for id,title,text in [('thread:demo','整理产品设计说明','已梳理页面结构，下一步补齐验收清单。'),('feishu:demo','示例项目群','@示例用户 请在明天讨论前核对演示材料。')]:
        db.save_record({'id':id,'kind':'codex' if id.startswith('thread') else 'feishu','day':db.today(),'updated':db.now(),
            'title':title,'text':text,'has_result':True,'sender_name':'示例同事','chat_type':'group','mentions':[{'id':'ou_demo'}]})
    for id,title,origin in [('todo:demo','核对明天演示的材料','user'),('intent:demo','补齐产品设计的验收清单','codex')]:
        db.save_task({'id':id,'day':db.today(),'created':db.now(),'title':title,'summary':'演示数据，可尝试勾选、编辑、回退或删除。','status':'todo','origin':origin,
            'role':'todo' if origin=='user' else 'intention','evidence_ids':['thread:demo']})
    plan={'day':db.today(),'generated_at':db.now(),
        'night_recommendations':[{'title':'整理明天演示的检查清单','content':'汇总已有材料中的缺口，形成一页核对清单。','prompt':'请只依据我提供的设计材料，列出已确认的验收条件和需要补充的内容，不执行外部操作。','evidence_ids':['thread:demo']}],
        'risks':[{'title':'验收条件未确认，可能影响明天的讨论','reason':'已有设计说明尚未包含验收条件。','preparation':'讨论前核对参与者需要确认的事项。','confidence':'medium','evidence_ids':['thread:demo']}]}
    db.put('plan:'+db.today(),plan)
    for kind,key in [('night','night_recommendations'),('risk','risks')]:db.save_planning_batch(kind,plan[key])
    old=(date.fromisoformat(db.today())-timedelta(days=6)).isoformat()
    db.save_record({'id':'memory:demo-old','kind':'memory','day':old,'updated':old+'T12:00:00+08:00','title':'历史示例','text':'此内容仅在 Markdown 归档保留。'})
    # Entirely fictional, with no applicant IDs or real institutions.
    items=[]
    for number,(school,program,stage,summary) in enumerate([
        ('示例大学 A','Robotics MSc','draft','材料已保存，尚未提交。'),
        ('示例大学 A','Computer Science MSc','preparing','正在准备个人陈述。'),
        ('示例大学 B','Design MA','submitted','虚构邮件确认已收到申请；门户仍待本人核验。')]):
        ref='gmail:demo-application-'+str(number)
        db.save_record({'id':ref,'kind':'gmail','day':db.today(),'updated':db.now(),
            'title':'虚构申请状态示例','text':summary,'coverage':'仅用于演示，不对应真实学校或申请。'})
        items.append({'id':'application:demo-'+str(number),'institution':school,'program':program,'cycle':'示例入学季',
            'application_id':'','stage':stage,'summary':summary,'next_action':'核对所需材料与当前状态。','deadline':'',
            'portal_url':'','portal_checked_at':None,'portal_state':'needs_verification','updated':db.now(),'evidence_ids':[ref]})
    db.put('applications',{'items':items,'contacts':[],'generated_at':db.now(),
        'coverage':'全部为虚构演示项目；展开学校查看项目及来源。'})
    import archives
    archives.write_days()
