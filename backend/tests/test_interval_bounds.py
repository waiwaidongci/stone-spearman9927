import itertools,math,random,time
from fractions import Fraction

import pytest

from src.services import interval_bounds as ib


def brute(porosity,low,high):
    n=len(low)
    best=-2.0; worst=2.0
    for perm in itertools.permutations(range(n)):
        ceiling=-math.inf; ok=True
        for j in perm:
            if high[j]<=ceiling: ok=False; break
            ceiling=max(ceiling,low[j])
        if not ok: continue
        y=[0.0]*n
        for position,i in enumerate(perm,start=1): y[i]=position
        rho=ib.spearman(porosity,y)
        best=max(best,rho); worst=min(worst,rho)
    return worst,best


def snapshot(porosity,low,high):
    return [{'source_key':f'S{i:04d}','values':{'porosity':porosity[i],'absorption':{'low':low[i],'high':high[i]}}} for i in range(len(low))]


@pytest.mark.parametrize('seed',[1,2,3])
def test_matches_brute_force_with_ties(seed):
    rng=random.Random(seed); checked=0
    for _ in range(120):
        n=rng.randint(2,7)
        low=[];high=[]
        for _ in range(n):
            a=rng.choice([i*0.5 for i in range(6)])
            low.append(a); high.append(a+rng.choice([0.5,1,1.5,2]))
        porosity=[float(rng.randint(1,4)) for _ in range(n)]
        if len(set(porosity))==1 or ib.max_overlap(low,high)>8: continue
        res=ib.calculate(snapshot(porosity,low,high),{})
        worst,best=brute(porosity,low,high)
        assert res['bounds']['lower']['rho']==pytest.approx(worst,abs=1e-12)
        assert res['bounds']['upper']['rho']==pytest.approx(best,abs=1e-12)
        checked+=1
    assert checked>30


def test_both_endpoints_return_reproducible_values():
    porosity=[9.0,8.0,7.0,6.0,5.0,4.0]
    low=[0.0,1.0,2.0,3.0,4.0,5.0]
    high=[1.0,2.0,3.0,4.0,5.0,6.0]
    res=ib.calculate(snapshot(porosity,low,high),{})
    assert res['bounds']['lower']['rho']==pytest.approx(-1.0)
    assert res['bounds']['upper']['rho']==pytest.approx(-1.0)
    for side in ('lower','upper'):
        item=res['bounds'][side]
        values=[Fraction(v) for v in item['values']]
        assert len(set(values))==len(values)
        assert sorted(range(len(values)),key=lambda i:values[i])==item['order']
        for i,v in enumerate(values):
            assert Fraction(low[i])<v<Fraction(high[i])
        assert ib.spearman(porosity,[float(v) for v in values])==pytest.approx(item['rho'],abs=1e-12)


def test_rejects_batches_over_capacity_before_any_work():
    n=2000
    low=[0.0]*n; high=[1.0]*n
    porosity=[float(i%37) for i in range(n)]
    with pytest.raises(ValueError,match='超过容量'):
        ib.prepare_snapshot(snapshot(porosity,low,high),8)
    start=time.perf_counter()
    with pytest.raises(ValueError,match='超过容量'):
        ib.calculate(snapshot(porosity,low,high),{'overlap_capacity':8})
    assert time.perf_counter()-start<1.0


def _sliding_window(n,width,step=0.001):
    low=[i*step for i in range(n)]
    high=[x+width for x in low]
    return low,high


def test_two_thousand_specimens_eight_overlap_within_deadline():
    n=2000
    low,high=_sliding_window(n,0.007)
    assert ib.max_overlap(low,high)==8
    rng=random.Random(7)
    porosity=[float(rng.uniform(4,28)) for _ in range(n)]
    start=time.perf_counter()
    res=ib.calculate(snapshot(porosity,low,high),{})
    elapsed=time.perf_counter()-start
    assert elapsed<30.0
    assert res['bounds']['max_overlap']<=8
    assert res['bounds']['lower']['rho']<=res['bounds']['upper']['rho']
    for side in ('lower','upper'):
        assert abs(res['bounds'][side]['rho']-res['bounds'][side]['rho_recomputed'])<1e-9


def test_constant_porosity_is_rejected():
    low=[0.0,1.0,2.0];high=[1.0,2.0,3.0]
    with pytest.raises(ValueError,match='常量'):
        ib.calculate(snapshot([5.0,5.0,5.0],low,high),{})


def test_narrow_intervals_use_exact_decimal_fallback():
    n=60
    low=[(i//8)*0.01+(i%8)*0.001 for i in range(n)]
    high=[x+0.007 for x in low]
    rng=random.Random(31)
    porosity=[float(rng.randint(1,3)) for _ in range(n)]
    t0=time.perf_counter()
    res=ib.calculate(snapshot(porosity,low,high),{})
    assert time.perf_counter()-t0<30.0
    representations={res['bounds'][s]['representation'] for s in ('lower','upper')}
    assert 'exact-decimal' in representations
    import decimal
    for side in ('lower','upper'):
        item=res['bounds'][side]
        values=[decimal.Decimal(v) for v in item['values']]
        assert len(set(values))==n
        assert sorted(range(n),key=lambda i:values[i])==item['order']
        for i,v in enumerate(values):
            assert Fraction(low[i])<v<Fraction(high[i])


def test_binary64_values_round_trip_exactly():
    low=[i*1.0 for i in range(8)]
    high=[x+1.0 for x in low]
    porosity=[float(i) for i in range(8)]
    res=ib.calculate(snapshot(porosity,low,high),{})
    for side in ('lower','upper'):
        item=res['bounds'][side]
        assert item['representation']=='binary64'
        floats=item['values_binary64']
        assert [float(v) for v in item['values']]==floats
        assert ib.spearman(porosity,floats)==pytest.approx(item['rho'],abs=1e-9)


def test_endpoint_validation():
    with pytest.raises(ValueError,match='下限小于上限'):
        ib.calculate(snapshot([1.0,2.0],[0.0,2.0],[1.0,2.0]),{})
    bad=[{'source_key':'A','values':{'porosity':1.0,'absorption':{'low':0.0}}},
         {'source_key':'B','values':{'porosity':2.0,'absorption':{'low':1.0,'high':2.0}}}]
    with pytest.raises(ValueError):
        ib.calculate(bad,{})
