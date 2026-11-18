"""Exact Spearman bounds when absorption is known only as an open interval.

Each specimen contributes an exact porosity value and an absorption interval
``(low, high)``: the true absorption is strictly inside it and all specimen
absorptions are distinct.  A specimen order is realisable exactly when it is a
linear extension of the interval order

    i must precede j   <=>   high_i <= low_j,

so the set of possible rank vectors is the set of linear extensions of an
interval order.  Sweeping the interval endpoints keeps a frontier of at most
``overlap`` specimens (the maximum number of intervals covering one point), so
with a capacity of 8 each gap needs at most 2**8 frontier states.  Maximising
and minimising the integer objective ``sum(d_i * position_i)`` over that
frontier therefore gives the exact Spearman bounds in O(n * 2**capacity).

``d_i = 2 * (average porosity rank_i - (n + 1) / 2)`` is an integer even when
porosity ties are present.  The absorption denominator only depends on n and is
identical for every assignment, so it cancels out of the optimisation.

For each bound a concrete strictly increasing assignment inside the open
intervals is reconstructed and independently re-scored, so both endpoint
results are reproducible from the returned values.
"""
import decimal
import math
from bisect import bisect_right
from fractions import Fraction

from src.config.domain import DOMAIN

CAPACITY = int(DOMAIN.get('interval', {}).get('overlap_capacity', 8))
MIN_SPECIMENS = int(DOMAIN.get('interval', {}).get('min_specimens', 2))

_POP_ORDER = {}
_BITS = {}


def _prepare_masks(a):
    if a not in _POP_ORDER:
        size = 1 << a
        _POP_ORDER[a] = sorted(range(size), key=lambda m: -m.bit_count())
        _BITS[a] = [tuple(b for b in range(a) if (m >> b) & 1) for m in range(size)]
    return _POP_ORDER[a], _BITS[a]


def doubled_centered_ranks(values):
    """Twice the average rank minus (n+1); always an integer."""
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    out = [0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        # Average rank of positions i+1 .. j is (i+1+j)/2.
        c = (i + 1) + j - (n + 1)
        for k in range(i, j):
            out[order[k]] = c
        i = j
    return out


def average_ranks(values):
    n = len(values)
    order = sorted(range(n), key=lambda i: (values[i], i))
    out = [0.0] * n
    i = 0
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            out[order[k]] = rank
        i = j
    return out


def spearman(x, y):
    """Average-rank Spearman, matching the exact-value research method."""
    rx = average_ranks(x)
    ry = average_ranks(y)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    ax = [v - mx for v in rx]
    ay = [v - my for v in ry]
    den = math.sqrt(sum(v * v for v in ax)) * math.sqrt(sum(v * v for v in ay))
    if den == 0:
        raise ValueError('常量列的秩相关系数未定义')
    return sum(a * b for a, b in zip(ax, ay)) / den


def build_phases(low, high):
    """Gaps between consecutive endpoints and the intervals active in them.

    ``acts[p]`` contains the specimens with low <= coords[p] < high, i.e. the
    ones that may receive a value inside gap (coords[p], coords[p+1]);
    ``expired[p]`` counts specimens with high <= coords[p], which therefore
    must already hold a value in an earlier gap.
    """
    n = len(low)
    coords = sorted(set(low) | set(high))
    by_low = {}
    by_high = {}
    for i in range(n):
        by_low.setdefault(low[i], []).append(i)
        by_high.setdefault(high[i], []).append(i)
    sorted_high = sorted(high)
    active = set()
    acts = []
    expired = []
    for c in coords[:-1]:
        for i in by_high.get(c, ()):
            active.discard(i)
        for i in by_low.get(c, ()):
            active.add(i)
        acts.append(sorted(active))
        expired.append(bisect_right(sorted_high, c))
    return coords, acts, expired


def max_overlap(low, high):
    _, acts, _ = build_phases(low, high)
    return max((len(a) for a in acts), default=0)


def _optimise(d, acts, expired, coords, high, sign):
    """Maximise sign * sum(d_i * position_i); return (value, order, tables)."""
    tables = []
    cur = None
    for p, act in enumerate(acts):
        a = len(act)
        if p == 0:
            cur = {(1 << a) - 1: 0}
        else:
            old_act = acts[p - 1]
            old_a = len(old_act)
            expiring = 0
            target = [-1] * old_a
            new_pos = {it: b for b, it in enumerate(act)}
            for b, it in enumerate(old_act):
                if high[it] == coords[p]:
                    expiring |= 1 << b
                else:
                    target[b] = new_pos[it]
            new_items = 0
            old_set = set(old_act)
            for b, it in enumerate(act):
                if it not in old_set:
                    new_items |= 1 << b
            mapping = [0] * (1 << old_a)
            mapping[0] = new_items
            for m in range(1, 1 << old_a):
                low_bit = m & -m
                b = low_bit.bit_length() - 1
                t = target[b]
                mapping[m] = mapping[m ^ low_bit] | ((1 << t) if t >= 0 else 0)
            nxt = {}
            for om, value in cur.items():
                if om & expiring:
                    continue
                nm = mapping[om]
                if value > nxt.get(nm, -(2 ** 300)):
                    nxt[nm] = value
            cur = nxt
        ep = expired[p]
        pop_order, bits = _prepare_masks(a)
        for m in pop_order:
            value = cur.get(m)
            if value is None:
                continue
            pos = ep + a - m.bit_count() + 1
            for b in bits[m]:
                nm = m ^ (1 << b)
                nv = value + sign * d[act[b]] * pos
                if nv > cur.get(nm, -(2 ** 300)):
                    cur[nm] = nv
        tables.append(cur)
    final = cur.get(0)
    if final is None:
        raise ValueError('区间约束不存在可行的吸水率顺序')
    final *= sign

    seq = []
    p = len(acts) - 1
    m = 0
    while True:
        table = tables[p]
        a = len(acts[p])
        if p == 0 and m == (1 << a) - 1:
            break
        value = table[m]
        ep = expired[p]
        found = False
        for b in range(a):
            if (m >> b) & 1:
                continue
            m2 = m | (1 << b)
            v2 = table.get(m2)
            if v2 is None:
                continue
            pos = ep + a - m2.bit_count() + 1
            if v2 + sign * d[acts[p][b]] * pos == value:
                seq.append((pos, acts[p][b]))
                m = m2
                found = True
                break
        if found:
            continue
        if p == 0:
            raise RuntimeError('区间最优顺序回溯失败（初始状态）')
        old_act = acts[p - 1]
        cur_bit = {it: b for b, it in enumerate(acts[p])}
        pm = 0
        for ob, it in enumerate(old_act):
            if high[it] == coords[p]:
                continue
            if (m >> cur_bit[it]) & 1:
                pm |= 1 << ob
        prev = tables[p - 1].get(pm)
        if prev is not None and prev == value:
            p -= 1
            m = pm
            continue
        raise RuntimeError('区间最优顺序回溯失败（阶段衔接）')
    seq.sort()
    order = [it for _, it in seq]
    if len(order) != len(set(order)):
        raise RuntimeError('区间最优顺序回溯失败（顺序重复）')
    return final, order, tables


def _exact_decimal_text(value, precision=60):
    context = decimal.Context(prec=precision)
    text = format(context.divide(decimal.Decimal(value.numerator), decimal.Decimal(value.denominator)), 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def _float_texts(values, low, high):
    """Round-trip texts that are exactly inside the open intervals, else None."""
    texts = [repr(v) for v in values]
    for i, text in enumerate(texts):
        exact = Fraction(text)
        if not (Fraction(low[i]) < exact < Fraction(high[i])):
            return None
    if len(set(texts)) != len(texts):
        return None
    return texts


def _decimal_witness(order, low, high):
    """Fallback: exact rational midpoints when floats cannot separate values."""
    n = len(order)
    caps = [None] * n
    cap = None
    for k in range(n - 1, -1, -1):
        h = Fraction(high[order[k]])
        cap = h if cap is None or h < cap else cap
        caps[k] = cap
    exact = [None] * n
    prev = None
    for k, i in enumerate(order):
        lo = Fraction(low[i])
        if prev is not None and prev > lo:
            lo = prev
        hi = caps[k]
        if not lo < hi:
            raise ValueError('区间端点精度不足，无法构造严格互异的取值')
        value = (lo + hi) / 2
        exact[i] = value
        prev = value
    if len(set(exact)) != n:
        raise ValueError('区间端点精度不足，无法构造严格互异的取值')
    texts = [_exact_decimal_text(v) for v in exact]
    return exact, texts


def witness_values(order, low, high):
    """Return (values, decimal texts, representation).

    Values are placed at the midpoint of the exact feasible bracket for their
    position, so they sit well inside the open intervals instead of hugging an
    endpoint.  The bracket uses a backward pass over the upper endpoints and a
    forward pass over already chosen values; feasibility is checked with exact
    rationals, not with rounded floats.  When double precision cannot separate
    the bracket (intervals narrower than an ulp), the values fall back to exact
    rational midpoints rendered as exact decimals.
    """
    n = len(order)
    caps = [None] * n
    cap = None
    for k in range(n - 1, -1, -1):
        h = Fraction(high[order[k]])
        cap = h if cap is None or h < cap else cap
        caps[k] = cap
    floats = [0.0] * n
    prev = None
    ok = True
    for k, i in enumerate(order):
        lo = Fraction(low[i])
        if prev is not None and prev > lo:
            lo = prev
        hi = caps[k]
        if not lo < hi:
            raise ValueError('区间端点精度不足，无法构造严格互异的取值')
        candidate = float((lo + hi) / 2)
        if not (lo < Fraction(candidate) < hi):
            candidate = math.nextafter(float(lo), math.inf)
        if not (lo < Fraction(candidate) < hi):
            ok = False
            break
        floats[i] = candidate
        prev = candidate
    if ok:
        texts = _float_texts(floats, low, high)
        if texts is not None:
            return floats, texts, 'binary64'
        # Values are fine as floats; only the shortest round-trip text is not
        # strictly inside.  Emit the exact decimal expansion of each float.
        texts = [format(decimal.Decimal(v), 'f') for v in floats]
        return floats, texts, 'binary64-exact-decimal'
    exact, texts = _decimal_witness(order, low, high)
    return None, texts, 'exact-decimal'


def _rank_positions_from_decimals(porosity, texts):
    """Independent recomputation: ranks come only from the decimal values."""
    values = [decimal.Decimal(t) for t in texts]
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    positions = [0] * len(values)
    for rank, i in enumerate(order, start=1):
        positions[i] = rank
    return positions


def exact_rho(d, positions):
    """Recompute rho from porosity ranks and absorption positions."""
    n = len(d)
    num = sum(d[i] * positions[i] for i in range(n))
    den_x2 = sum(x * x for x in d)
    if den_x2 == 0:
        raise ValueError('孔隙率为常量，秩相关系数未定义')
    return num / math.sqrt(den_x2 * n * (n * n - 1) / 12.0)


def prepare_snapshot(snapshot, capacity=CAPACITY):
    """Validate an interval snapshot and return arrays plus its max overlap.

    This runs before a job is queued.  In particular, batches whose intervals
    overlap at any point more than ``capacity`` ways are rejected here, before
    any queue entry or run record exists.
    """
    if not snapshot:
        raise ValueError('空批次无法分析')
    porosity = []
    low = []
    high = []
    for row in snapshot:
        values = row.get('values') if isinstance(row, dict) else None
        if not isinstance(values, dict):
            raise ValueError('观测记录格式不完整')
        if 'porosity' not in values or 'absorption' not in values:
            raise ValueError('观测字段不完整')
        p = values['porosity']
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError('孔隙率必须是数值')
        p = float(p)
        if not math.isfinite(p):
            raise ValueError('孔隙率必须为有限数值')
        a = values['absorption']
        if not isinstance(a, dict):
            raise ValueError('区间研究要求吸水率以 low/high 开区间录入')
        if set(a) != {'low', 'high'}:
            raise ValueError('吸水率开区间必须只包含 low 和 high')
        pair = {}
        for key in ('low', 'high'):
            v = a[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError('吸水率区间端点必须是数值')
            v = float(v)
            if not math.isfinite(v) or abs(v) > 1e9:
                raise ValueError('吸水率区间端点必须为有限业务数值')
            if v < 0:
                raise ValueError('吸水率区间端点不得为负')
            pair[key] = v
        if not pair['low'] < pair['high']:
            raise ValueError('吸水率开区间要求下限小于上限')
        porosity.append(p)
        low.append(pair['low'])
        high.append(pair['high'])
    n = len(porosity)
    if n < MIN_SPECIMENS:
        raise ValueError(f'区间研究至少需要{MIN_SPECIMENS}个独立试件')
    if all(x == 0 for x in doubled_centered_ranks(porosity)):
        raise ValueError('孔隙率为常量，秩相关系数未定义')
    overlap = max_overlap(low, high)
    if overlap > capacity:
        raise ValueError(
            f'吸水率区间最大重叠 {overlap} 段，超过容量 {capacity} 段；'
            '请在来源页收窄或拆分区间后再发起研究'
        )
    return porosity, low, high, overlap


def ensure_present(result, specimen_count):
    """Cheap structural check used whenever a stored result is read.

    The full check (including exact decimal parsing and distinctness) runs once
    in the worker before a run may be marked completed; every read path only
    needs to confirm that both bounds and both value sets are actually there.
    """
    if not isinstance(result, dict) or result.get('mode') != 'interval':
        raise ValueError('区间研究结果格式不完整')
    bounds = result.get('bounds')
    if not isinstance(bounds, dict):
        raise ValueError('区间研究结果缺少上下界')
    previous = None
    for side in ('lower', 'upper'):
        item = bounds.get(side)
        if not isinstance(item, dict):
            raise ValueError(f'区间研究结果缺少{side}端')
        for key in ('rho', 'rho_recomputed'):
            value = item.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'区间研究{side}端 {key} 缺失')
        if abs(item['rho'] - item['rho_recomputed']) > 1e-7:
            raise ValueError(f'区间研究{side}端回算不一致')
        values = item.get('values')
        positions = item.get('positions')
        if not isinstance(values, list) or len(values) != specimen_count:
            raise ValueError(f'区间研究{side}端取值不齐全')
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f'区间研究{side}端取值缺失')
        if not isinstance(positions, list) or sorted(positions) != list(range(1, specimen_count + 1)):
            raise ValueError(f'区间研究{side}端位次不齐全')
        if previous is not None and item['rho'] < previous - 1e-12:
            raise ValueError('区间研究上下界顺序异常')
        previous = item['rho']
    if bounds.get('max_overlap') is None or bounds.get('capacity') is None:
        raise ValueError('区间研究结果缺少重叠容量信息')


def ensure_complete(result, specimen_count):
    """Full check: both bounds plus two verified, distinct, in-interval value sets."""
    ensure_present(result, specimen_count)
    bounds = result['bounds']
    for side in ('lower', 'upper'):
        item = bounds[side]
        try:
            parsed = [decimal.Decimal(v) for v in item['values']]
        except decimal.InvalidOperation:
            raise ValueError(f'区间研究{side}端取值不是合法十进制数')
        if not all(v.is_finite() for v in parsed):
            raise ValueError(f'区间研究{side}端取值非有限数')
        if len(set(parsed)) != specimen_count:
            raise ValueError(f'区间研究{side}端取值不互异')
        positions = sorted(range(specimen_count), key=lambda i: (parsed[i], i))
        expected = [0] * specimen_count
        for rank, i in enumerate(positions, start=1):
            expected[i] = rank
        if expected != item['positions']:
            raise ValueError(f'区间研究{side}端位次与取值不一致')


def calculate(snapshot, params):
    capacity = int(params.get('overlap_capacity', CAPACITY))
    porosity, low, high, overlap = prepare_snapshot(snapshot, capacity)
    n = len(porosity)
    d = doubled_centered_ranks(porosity)
    coords, acts, expired = build_phases(low, high)

    upper_value, upper_order, _ = _optimise(d, acts, expired, coords, high, 1)
    lower_value, lower_order, _ = _optimise(d, acts, expired, coords, high, -1)
    if lower_value > upper_value:
        raise RuntimeError('区间上下界顺序异常')

    side_data = {}
    for name, value, order in (('lower', lower_value, lower_order),
                               ('upper', upper_value, upper_order)):
        positions = [0] * n
        for rank, i in enumerate(order, start=1):
            positions[i] = rank
        if sum(d[i] * positions[i] for i in range(n)) != value:
            raise RuntimeError('区间最优顺序目标值不一致')
        floats, texts, representation = witness_values(order, low, high)
        # Recompute ranks from the returned decimal values alone.
        rebuilt_positions = _rank_positions_from_decimals(porosity, texts)
        if rebuilt_positions != positions:
            raise RuntimeError('区间回算取值的秩与最优顺序不一致')
        for i, text in enumerate(texts):
            if not (Fraction(low[i]) < Fraction(text) < Fraction(high[i])):
                raise RuntimeError('区间回算取值越界')
        rho = round(exact_rho(d, positions), 12)
        side_data[name] = {
            'rho': rho,
            'rho_recomputed': round(exact_rho(d, rebuilt_positions), 12),
            'values': texts,
            'values_binary64': floats,
            'representation': representation,
            'positions': positions,
            'order': order,
        }

    representations = {side_data['lower']['representation'], side_data['upper']['representation']}
    if representations == {'binary64'}:
        representation_note = '两端取值均为双精度可表示值。'
    else:
        representation_note = '部分区间窄于双精度可分辨范围，端点取值以精确十进制给出，需用十进制或有理数回算。'

    tie_count = n - len(set(porosity))
    lower_rho = side_data['lower']['rho']
    upper_rho = side_data['upper']['rho']
    if lower_rho == upper_rho:
        lead = f'吸水率在各自开区间内取互异值时，Spearman ρ 被唯一确定，精确值 {lower_rho:.6f}。'
    else:
        lead = (f'吸水率在各自开区间内取互异值时，Spearman ρ 的精确下界为 '
                f'{lower_rho:.6f}、上界为 {upper_rho:.6f}。')
    rows = []
    for i, row in enumerate(snapshot):
        rows.append([
            row.get('source_key'),
            porosity[i],
            low[i],
            high[i],
            side_data['lower']['values'][i],
            side_data['upper']['values'][i],
            side_data['lower']['positions'][i],
            side_data['upper']['positions'][i],
        ])
    result = {
        'mode': 'interval',
        'metrics': {
            '独立试件数': n,
            'Spearman ρ 下界': lower_rho,
            'Spearman ρ 上界': upper_rho,
            '区间最大重叠': overlap,
            '重叠容量': capacity,
            '孔隙率并列数': tie_count,
            '吸水率取值': '互异（由构造保证）',
            '方法': '开区间线性扩展精确包络',
            '取值表示': '；'.join(sorted(representations)),
        },
        'bounds': {
            'lower': side_data['lower'],
            'upper': side_data['upper'],
            'max_overlap': overlap,
            'capacity': capacity,
            'columns': ['试件', '孔隙率(%)', '吸水率下限(%)', '吸水率上限(%)',
                        '下界取值', '上界取值', '下界秩', '上界秩'],
            'rows': rows,
        },
        'interpretation': (
            lead + '两端各附一组位于开区间内、彼此互异的取值，按该组取值回算可得到相应端点。'
            '上下界只反映区间与互异约束，不含测量误差分布或抽样不确定性。' + representation_note
        ),
        'caveat': '开区间端点均不含；上下界来自全部可行取值顺序，不是置信区间，也不意味着因果。',
        'columns': ['试件', '孔隙率(%)', '吸水率下限(%)', '吸水率上限(%)',
                    '下界取值', '上界取值', '下界秩', '上界秩'],
        'rows': rows,
        'table_title': '逐试件开区间与两端回算取值',
    }
    ensure_complete(result, n)
    return result
