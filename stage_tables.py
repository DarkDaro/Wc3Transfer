# 17.09: Этап tables — перенос секций ini по маппингу
# 1. Секция источника -> приёмник под новым ID (или тем же, если нет конфликта)
# 2. _parent: маппится по маппингу; стандартный (не в маппинге) — не трогается
# 3. Ссылки в полях (abilList, buffList, Art-пути не трогаются; равкоды
#    в abilList/buffList заменяются по маппингу)
# Dry-run: только отчёт, без записи.
import io, os, sys, json, re

def parse_sections_raw(path):
    """Секции с сырыми строками (сохранение форматирования)."""
    out = {}
    if not os.path.exists(path):
        return out, []
    s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
    cur = None
    in_block = False
    # 19.09: [=[ ]=] — блоки текста: строки [xxx] внутри — НЕ секции
    order = []
    for l in s.splitlines():
        if not in_block:
            m = re.match(r'^\[([^\]]+)\]', l)
            if m:
                cur = m.group(1)
                out[cur] = []
                order.append(cur)
            elif cur is not None:
                out[cur].append(l)
        else:
            if cur is not None:
                out[cur].append(l)
        if not in_block and l.rstrip().endswith('[=['):
            in_block = True
        elif in_block and ']=]' in l:
            in_block = False
    return out, order

def field(body_lines, key):
    for l in body_lines:
        m = re.match(r'^' + key + r'\s*=\s*"?([^"\n]*)', l)
        if m:
            return m.group(1)
    return ''

def replace_refs_in_body(lines, ref_map):
    """Замена равкодов в полях-списках (abilList, buffList и т.п.)."""
    out = []
    for l in lines:
        m = re.match(r'^(\w+)\s*=', l)
        if m and m.group(1) in ('abilList', 'heroAbilList', 'buffList', 'BuffID', 'buffs', 'ResearchList'):
            for old, new in ref_map.items():
                l = re.sub(r"(?<![0-9A-Za-z])" + re.escape(old) + r"(?![0-9A-Za-z])", new, l)
        out.append(l)
    return out

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    tgt = cfg['target']

    # маппинг
    mp_json = os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json'))
    mp = json.load(io.open(mp_json, 'rb'))
    # ref_map для замен в полях: old -> new (только ability/buff/item/unit)
    ref_map = {}
    for k, new in mp.items():
        t, old = k.split(':', 1)
        if old != new:
            ref_map[old] = new

    total = 0
    for t in cfg['tables']:
        sp = os.path.join(src, 'table', t + '.ini')
        tp = os.path.join(tgt, 'table', t + '.ini')
        secs, order = parse_sections_raw(sp)
        tsecs, torder = parse_sections_raw(tp)
        # какие секции переносим
        tsec_ids = set(tsecs)
        to_move = [(old, mp[t + ':' + old]) for old in order
                   if (t + ':' + old) in mp and mp[t + ':' + old] not in tsec_ids]
        if not to_move:
            print('%s: нечего переносить' % t)
            continue
        # текст секций для вставки
        blocks = []
        for old, new in to_move:
            lines = list(secs[old])
            # _parent: заменить по маппингу, если родитель переносится
            for i, l in enumerate(lines):
                m = re.match(r'^(_parent)\s*=\s*"?([0-9A-Za-z]{4})"?', l)
                if m:
                    par = m.group(2)
                    npar = mp.get(t + ':' + par, par)  # стандарт не трогаем
                    lines[i] = l[:m.start(2)] + npar + l[m.end(2):]
            lines = replace_refs_in_body(lines, ref_map)
            blocks.append('[' + new + ']' + chr(10) + chr(10).join(lines).rstrip() + chr(10))
        if dry:
            print('%s: перенеслось бы %d секций (dry-run)' % (t, len(blocks)))
        else:
            # дописать в хвост приёмника
            cur = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
            add = ''.join(blocks)
            if not cur.endswith(chr(10)):
                add = chr(10) + add
            io.open(tp, 'wb').write((cur + add).encode('utf-8'))
            print('%s: перенесено %d секций' % (t, len(blocks)))
        ids = [b.split(']')[0][1:] for b in blocks[:12]]
        print('  ID:', ', '.join(ids) + (' ...' if len(blocks) > 12 else ''))
        total += len(blocks)

    print('ИТОГО секций:', total, ('(dry-run)' if dry else ''))

if __name__ == '__main__':
    main()