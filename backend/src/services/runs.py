import math,os,json,csv,io
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from fastapi import HTTPException
from src.models.run import Run
from src.models.review import Review
from src.services import studies,interval_bounds
from src.services.domain_validation import validate_parameters
from src.services.audits import log
from src.utils.serializers import record,now,checksum


def _preflight(snapshot,params):
    """Reject impossible studies before they can occupy a queue slot."""
    if params.get('mode')=='interval':
        try: interval_bounds.prepare_snapshot(snapshot,params.get('overlap_capacity',interval_bounds.CAPACITY))
        except ValueError as e: raise HTTPException(422,str(e))
        return
    # Exact mode still needs every specimen to carry finite single values.
    if len(snapshot)<5: raise HTTPException(422,'至少5个独立试件')
    for row in snapshot:
        for key in ('porosity','absorption'):
            v=row['values'].get(key)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)):
                raise HTTPException(422,'精确值研究要求孔隙率与吸水率均为有限的实测数值')


def create(db,data,user):
    studies.require(db,data.study_id)
    rows=studies.observations(db,data.study_id)
    if not rows: raise HTTPException(422,'先录入至少一条业务观测')
    try: params=validate_parameters(data.parameters)
    except (ValueError,TypeError) as e: raise HTTPException(422,str(e))
    snapshot=[{'source_key':x['source_key'],'values':x['values']} for x in rows]
    # Oversized interval batches are rejected before a run record or queue
    # entry exists, so they never wait in line only to fail later.
    _preflight(snapshot,params)
    run=Run(study_id=data.study_id,name=data.name,parameters=params,snapshot=snapshot,checksum=checksum(snapshot),created_at=now(),status='queued')
    db.add(run);db.flush();log(db,user,'run.queue',str(run.id));db.commit()
    Redis.from_url(os.environ['REDIS_URL']).rpush('analysis-queue',run.id)
    return record(run)


def _gate(run,item):
    """Withhold interval results unless both bounds and both value sets exist."""
    if run.parameters.get('mode')!='interval' or item['status']!='completed': return item
    try:
        interval_bounds.ensure_present(run.result,len(run.snapshot))
    except (ValueError,TypeError):
        item['status']='failed'
        item['result']=None
        item['error']='区间结果缺少上下界或回算取值，未展示；请重新发起研究。'
    return item


def get(db,id):
    run=db.get(Run,id)
    if not run: raise HTTPException(404,'运行不存在')
    result=_gate(run,record(run))
    review=db.scalar(select(Review).where(Review.run_id==id));result['review']=record(review) if review else None
    return result


def list_runs(db):
    return [get(db,x) for x in db.scalars(select(Run.id).order_by(Run.id.desc()))]


def approve(db,id,data,user):
    run=db.get(Run,id)
    if not run: raise HTTPException(404,'运行不存在')
    if run.status!='completed': raise HTTPException(409,'只能复核已完成运行')
    if run.parameters.get('mode')=='interval':
        try: interval_bounds.ensure_complete(run.result,len(run.snapshot))
        except ValueError: raise HTTPException(409,'区间结果不完整，不能复核')
    if db.scalar(select(Review).where(Review.run_id==id)): raise HTTPException(409,'已复核，记录不可覆盖')
    obj=Review(run_id=id,note=data.note,author=user.email,created_at=now());db.add(obj);log(db,user,'review.approve',f'{id}: {data.note}');db.commit();return record(obj)


def export(db,id,user):
    r=get(db,id)
    if r['status']!='completed': raise HTTPException(409,'尚无完成结果')
    if user.role=='viewer' and not r['review']: raise HTTPException(403,'观察员只能导出已复核结果')
    stream=io.StringIO();w=csv.writer(stream);w.writerow(['运行编号','输入校验SHA256','指标','值'])
    for k,v in r['result']['metrics'].items(): w.writerow([id,r['checksum'],k,json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v])
    w.writerow([id,r['checksum'],'解释',r['result']['interpretation']])
    bounds=r['result'].get('bounds')
    if isinstance(bounds,dict):
        w.writerow([]);w.writerow(['逐试件区间与两端回算取值'])
        w.writerow(bounds['columns'])
        for row in bounds['rows']: w.writerow(row)
    log(db,user,'run.export',id);db.commit()
    return '﻿'+stream.getvalue()
