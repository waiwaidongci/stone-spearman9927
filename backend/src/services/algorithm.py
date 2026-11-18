import math
import numpy as np
from scipy import stats

def finite_rows(snapshot,keys):
    if not snapshot: raise ValueError('空批次无法分析')
    result=[]
    for row in snapshot:
        values=row['values']
        if any(k not in values for k in keys): raise ValueError('观测字段不完整')
        x=[float(values[k]) for k in keys]
        if not all(math.isfinite(v) for v in x): raise ValueError('观测必须为有限数值')
        result.append(x)
    return np.asarray(result,dtype=float)

def average_ranks(values):
    x=np.asarray(values,dtype=float);order=np.argsort(x,kind='stable');ranks=np.empty(len(x),dtype=float);i=0
    while i<len(x):
        j=i+1
        while j<len(x) and x[order[j]]==x[order[i]]: j+=1
        ranks[order[i:j]]=(i+1+j)/2;i=j
    return ranks

def spearman(x,y):
    rx,ry=average_ranks(x),average_ranks(y)
    a,b=rx-rx.mean(),ry-ry.mean();den=float(np.linalg.norm(a)*np.linalg.norm(b))
    if den==0: raise ValueError('常量列的秩相关系数未定义')
    return float(np.dot(a,b)/den)

def calculate(snapshot,params):
    x=finite_rows(snapshot,['porosity','absorption'])
    if len(x)<5: raise ValueError('至少5个独立试件')
    rho=spearman(x[:,0],x[:,1]);B=int(params.get('resamples',4999))
    if not 200<=B<=20000: raise ValueError('置换次数超出范围')
    # Permute precomputed centered ranks; ties remain paired to original y values.
    a=average_ranks(x[:,0]);b=average_ranks(x[:,1]);a-=a.mean();b-=b.mean();den=float(np.linalg.norm(a)*np.linalg.norm(b))
    rng=np.random.default_rng(42);count=0
    for _ in range(B):
        rr=float(np.dot(a,rng.permutation(b))/den)
        count+=abs(rr)>=abs(rho)-1e-12
    p=(count+1)/(B+1)
    return {'metrics':{'独立试件数':len(x),'Spearman秩相关ρ':rho,'双侧置换p(加一校正)':p,'置换次数':B,'孔隙率并列数':len(x)-len(np.unique(x[:,0])),'吸水率并列数':len(x)-len(np.unique(x[:,1])),'随机种子':42},'interpretation':f"本批孔隙率与吸水率的Spearman ρ={rho:.4f}，双侧置换p={p:.6g}。{'正' if rho>=0 else '负'}向秩关系只作为后续研究假设。",'caveat':'并列值按平均秩；检验要求独立可交换观测，相关不能推断因果。不能根据p值挑选或删改试件。','columns':['试件','孔隙率(%)','吸水率(%)','孔隙率平均秩','吸水率平均秩'],'rows':[[r['source_key'],*map(float,v),float(rx),float(ry)] for r,v,rx,ry in zip(snapshot,x,average_ranks(x[:,0]),average_ranks(x[:,1]))],'table_title':'逐试件原值与平均秩'}
