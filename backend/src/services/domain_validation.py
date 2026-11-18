import math
from src.config.domain import DOMAIN

INTERVAL_KEY = next((f[0] for f in DOMAIN['fields'] if f[2] == 'interval'), None)


def _validate_interval(value, label):
    if not isinstance(value, dict) or set(value) != {'low', 'high'}:
        raise ValueError(label + '必须录入 low/high 开区间')
    pair = {}
    for key, name in (('low', '下限'), ('high', '上限')):
        v = value[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f'{label}{name}必须是数值')
        v = float(v)
        if not math.isfinite(v) or abs(v) > 1e9:
            raise ValueError(f'{label}{name}必须为有限业务数值')
        if v < 0:
            raise ValueError(f'{label}{name}不得为负')
        pair[key] = v
    if not pair['low'] < pair['high']:
        raise ValueError(label + '开区间要求下限小于上限')
    return pair


def validate_values(values):
    expected = {f[0] for f in DOMAIN['fields']}
    if set(values) != expected:
        raise ValueError('字段必须为 ' + ', '.join(expected))
    out = {}
    for key, label, kind in DOMAIN['fields']:
        v = values[key]
        if kind == 'text':
            if v not in ('A', 'B'):
                raise ValueError('工艺组必须为A或B')
        elif kind == 'interval':
            # Interval studies require an open interval; exact studies may still
            # carry a single measured value (validated as a finite number).
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[key] = float(v)
                continue
            out[key] = _validate_interval(v, label)
        else:
            if isinstance(v, bool):
                raise ValueError(label + '必须是数值')
            v = float(v)
            if not math.isfinite(v) or abs(v) > 1e9:
                raise ValueError(label + '必须为有限业务数值')
            if v < 0:
                raise ValueError(label + '不得为负')
            out[key] = v
    i = DOMAIN['index']
    if i == 0 and any(v > 100 for v in out.values() if isinstance(v, (int, float))):
        raise ValueError('百分比必须在0到100之间')
    if i == 1:
        if any(out[k] != int(out[k]) or out[k] > 100000 for k in ('success', 'failure')):
            raise ValueError('计数必须为0到100000的整数')
        if out['success'] + out['failure'] == 0:
            raise ValueError('组内总数必须大于0')
    if i == 4:
        if not 0 < out['p0'] < 1 or not 0 < out['p1'] < 1 or out['p0'] == out['p1']:
            raise ValueError('两概率须在0和1之间且不同')
        if out['cost_per_contact'] <= 0 or out['budget'] <= 0:
            raise ValueError('成本与预算须为正')
    return out


def _validate_mode(params):
    mode = params.get('mode', DOMAIN.get('default_mode', 'interval'))
    if mode not in [m[0] for m in DOMAIN.get('modes', [['interval', '开区间研究'], ['exact', '精确值研究']])]:
        raise ValueError('未知研究模式')
    return mode


def validate_parameters(params):
    defaults = DOMAIN['defaults']
    interval_defaults = DOMAIN.get('interval_defaults', {})
    if not isinstance(params, dict):
        raise ValueError('分析参数必须是对象')
    mode = _validate_mode(params)
    # Each mode carries its own parameter set; crossing them is rejected so a
    # frozen run never records parameters that its method ignores.
    if mode == 'interval':
        allowed = set(interval_defaults) | {'mode'}
        p = dict(interval_defaults)
    else:
        allowed = set(defaults) | {'mode'}
        p = dict(defaults)
    if set(params) - allowed:
        raise ValueError('存在未知分析参数')
    p.update(params)
    if 'field' in p and p['field'] not in [f[0] for f in DOMAIN['fields']]:
        raise ValueError('未知指标')
    for key in ('resamples', 'simulations'):
        if key in p:
            v = p[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 200 <= v <= 20000:
                raise ValueError('重采样次数必须是200到20000的整数')
            p[key] = int(v)
    for key in ('alpha', 'power'):
        if key in p:
            p[key] = float(p[key])
            if not math.isfinite(p[key]) or not (0.001 <= p[key] <= 0.2 if key == 'alpha' else 0.5 <= p[key] <= 0.99):
                raise ValueError('显著性或功效超出范围')
    if 'overlap_capacity' in p:
        v = p['overlap_capacity']
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 1 <= v <= DOMAIN.get('interval', {}).get('overlap_capacity', 8):
            raise ValueError('重叠容量必须是1到8的整数')
        p['overlap_capacity'] = int(v)
    p['mode'] = mode
    return p
