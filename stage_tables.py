# 17.09: Этап tables — перенос секций ini по маппингу
# 1. Секция источника -> приёмник под новым ID (или тем же, если нет конфликта)
# 2. _parent: маппится по маппингу; стандартный (не в маппинге) — не трогается
# 3. Ссылки в полях (abilList, buffList, Art-пути не трогаются; равкоды
#    в abilList/buffList заменяются по маппингу)
# 20.10: режим replace_std применяется здесь (replace_std.json), пути
# переименованных ассетов (assets_renames) подставляются в секции.
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

def replace_asset_paths(lines, renames):
    """20.10: пути из deps_result.assets_renames (конфликт -> _v2).
    В ini/lml слеши удвоены, поэтому проверяем оба написания.
    24.10: sibling-расширения — донорские объекты ссылаются на путь
    с «движковым» расширением (unit Art: 'X.mdl', импортировался
    'X.mdx'): замена 'X.mdx'->'X_v2.mdx' не подменяла поле 'X.mdl',
    и объект оставался на РОДНОЙ модели приёмника. Теперь каждая пара
    old->new замещает и родственные расширения (mdl/mdx, blp/tga,
    mp3/wav игнорируем: звук путём ссылается точно)."""
    if not renames:
        return lines
    SIB = {'mdx': ('mdl', 'mdx'), 'mdl': ('mdl', 'mdx'),
           'blp': ('blp', 'tga'), 'tga': ('blp', 'tga')}
    pairs = []
    for old, new in renames.items():
        new_s = new.replace('\\', '\\\\')
        pairs.append((old, new_s))
        pairs.append((old.replace('\\', '\\\\'), new_s))
        pairs.append((old.replace('/', '\\\\'), new_s))
        # 24.10: sibling-расширение обеих сторон
        ob, oe = os.path.splitext(old)
        nb, ne = os.path.splitext(new)
        oe_l = oe.lower().lstrip('.')
        if oe_l in SIB:
            for sib in SIB[oe_l]:
                if sib == oe_l:
                    continue
                o2 = ob + '.' + sib
                pairs.append((o2, nb + '.' + ne))
                pairs.append((o2.replace('\\', '\\\\'), nb.replace('\\', '\\\\') + '.' + ne))
    out = []
    for l in lines:
        for old, new in pairs:
            if old and old in l:
                l = l.replace(old, new)
        out.append(l)
    return out

def prepare_fields(lines, table, mp, ref_map, renames):
    """21.10: простые поля секции донора для обновления существующей
    секции приёмника. Блочные значения [=[ ... ]=] не переносим:
    вставка многострочного текста в одну строку ломает ini."""
    fields = {}
    in_block = False
    for l in lines:
        if in_block:
            if ']=]' in l:
                in_block = False
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', l)
        if not m:
            if l.rstrip().endswith('[=['):
                in_block = True
            continue
        k, v = m.group(1), m.group(2).strip()
        if '[=[' in l:
            in_block = True
            continue
        fields[k] = v
    if '_parent' in fields:
        # 23.10: значение часто в кавычках ("Udre") — без снятия кавычек
        # ключ маппинга не находился, и update-ветка возвращала секции
        # донорского родителя (у перенесённых юнитов пропадали иконки:
        # наследование шло на перекрытие донора, которого в приёмнике нет)
        _pv = fields['_parent']
        _q = _pv.startswith('"')
        _pk = _pv.strip('"')
        _pn = mp.get(table + ':' + _pk, _pk)
        fields['_parent'] = '"%s"' % _pn if _q else _pn
    keys = list(fields)
    pseudo = ['%s = %s' % (k, fields[k]) for k in keys]
    pseudo = replace_refs_in_body(pseudo, ref_map)
    pseudo = replace_asset_paths(pseudo, renames)
    for k, l in zip(keys, pseudo):
        fields[k] = l.split('=', 1)[1].strip()
    return fields


def apply_std_fields(text, sid, fields):
    """20.10: вписать поля в существующую секцию [sid] (режим replace_std).
    Возвращает (новый текст, сколько полей применено, менялось ли).
    24.10 (О1): поле переписывается ТОЛЬКО если значение реально
    отличается — повторные update-прогоны не переписывают файл заново
    (идемпотентность: md5 приёмника сохраняется, когда донор не менялся)."""
    lines = text.split('\n')
    start = None
    end = len(lines)
    for i, l in enumerate(lines):
        m = re.match(r'^\[([^\]]+)\]', l)
        if not m:
            continue
        if start is not None:
            end = i
            break
        if m.group(1) == sid:
            start = i
    if start is None:
        return text, 0, False
    applied = set()
    changed = False
    in_block = False
    for i in range(start + 1, end):
        l = lines[i]
        if not in_block:
            mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', l)
            if mm and mm.group(1) in fields:
                new_line = '%s = %s' % (mm.group(1), fields[mm.group(1)])
                applied.add(mm.group(1))
                if lines[i] != new_line:
                    lines[i] = new_line
                    changed = True
        if not in_block and l.rstrip().endswith('[=['):
            in_block = True
        elif in_block and ']=]' in l:
            in_block = False
    missing = [k for k in fields if k not in applied]
    if missing:
        changed = True
        pos = end
        while pos > start + 1 and lines[pos - 1].strip() == '':
            pos -= 1
        lines[pos:pos] = ['%s = %s' % (k, fields[k]) for k in missing]
    return '\n'.join(lines), len(applied) + len(missing), changed

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
    # 22.10: ремап ссылок только для id, СУЩЕСТВУЮЩИХ в доноре.
    # Записи маппинга для стандартных id (AHtc -> A9K0 и т.п.) соседних
    # прогонов превращали корректные ссылки приёмника в несуществующие
    # id (70 «БИТАЯ ССЫЛКА» verify).
    donor_ids = set()
    for t in cfg['tables']:
        sp2 = os.path.join(src, 'table', t + '.ini')
        secs2, _ = parse_sections_raw(sp2)
        donor_ids.update(secs2.keys())
    ref_map = {o: n for o, n in ref_map.items() if o in donor_ids}

    # 20.10: переименованные при импорте ассеты и поля replace_std
    renames = {}
    deps_p = os.path.join(here, 'deps_result.json')
    if os.path.exists(deps_p):
        try:
            renames = json.load(io.open(deps_p, 'rb')).get('assets_renames') or {}
        except ValueError:
            renames = {}
    std_p = os.path.join(here, 'replace_std.json')
    std_all = {}
    if os.path.exists(std_p):
        try:
            std_all = json.load(io.open(std_p, 'rb'))
        except ValueError:
            std_all = {}

    total = 0
    applied_std = 0
    updated_secs = 0
    updated_fields = 0
    errors = 0
    # 24.10 (О2/О3): ключ идемпотентности update-ветки. Обновление
    # переписывает ~25 тыс. полей (~6 мин). Если донор-таблицы, маппинг
    # и renames не изменились с прошлого успешного update — повторять
    # бессмысленно: тот же донор даёт те же поля (а О1 пишет только
    # реально отличающиеся). Ключ хранится рядом с конфигом; при смене
    # пары карт (source/target) ключ сбрасывается сам.
    # Пропуск не влияет на перенос НОВЫХ секций (that's to_move).
    import hashlib
    _key_parts = []
    for t in cfg['tables']:
        fp = os.path.join(src, 'table', t + '.ini')
        _key_parts.append('%s:%s' % (t, hashlib.md5(io.open(fp, 'rb').read()).hexdigest()
                                     if os.path.exists(fp) else 'none'))
    _key_parts.append('mp:%s' % (hashlib.md5(io.open(mp_json, 'rb').read()).hexdigest()
                                 if os.path.exists(mp_json) else 'none'))
    _key_parts.append('renames:' + json.dumps(renames, sort_keys=True, ensure_ascii=False))
    # 24.10: приёмник в ключе — смена target сбрасывает пропуски
    _key_parts.append('tgt:' + tgt)
    _upd_key = hashlib.md5('|'.join(_key_parts).encode('utf-8')).hexdigest()
    _key_p = os.path.join(here, 'tables_upd_key.json')
    _prev_key = None
    if os.path.exists(_key_p):
        try:
            _prev_key = json.load(io.open(_key_p, 'rb')).get('key')
        except Exception:
            _prev_key = None
    update_skip = (cfg.get('tables_update_existing')
                   and _prev_key == _upd_key)
    if cfg.get('tables_update_existing') and update_skip:
        print('обновление существующих секций: ПРОПУСК (донор/маппинг/renames '
              'не менялись с прошлого update, ключ tables_upd_key.json)')
    for t in cfg['tables']:
        sp = os.path.join(src, 'table', t + '.ini')
        tp = os.path.join(tgt, 'table', t + '.ini')
        if not os.path.exists(tp):
            # 20.10: раньше здесь был трейсбек FileNotFoundError
            print('%s: ОШИБКА — нет файла приёмника %s' % (t, tp))
            errors += 1
            continue
        secs, order = parse_sections_raw(sp)
        tsecs, torder = parse_sections_raw(tp)
        # какие секции переносим
        tsec_ids = set(tsecs)
        to_move = [(old, mp[t + ':' + old]) for old in order
                   if (t + ':' + old) in mp and mp[t + ':' + old] not in tsec_ids]
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
            lines = replace_asset_paths(lines, renames)
            blocks.append('[' + new + ']' + chr(10) + chr(10).join(lines).rstrip() + chr(10))
        if dry:
            if blocks:
                print('%s: перенеслось бы %d секций (dry-run)' % (t, len(blocks)))
        elif blocks:
            # дописать в хвост приёмника
            cur = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
            add = ''.join(blocks)
            if not cur.endswith(chr(10)):
                add = chr(10) + add
            io.open(tp, 'wb').write((cur + add).encode('utf-8'))
            print('%s: перенесено %d секций' % (t, len(blocks)))
        elif not to_move:
            print('%s: нечего переносить' % t)

        # 21.10 (аудит): повторный перенос. Существующие секции раньше
        # просто пропускались, и правки донора не доезжали. Опция
        # tables_update_existing переносит простые поля поверх приёмника,
        # не трогая блочные [=[ ... ]=] и отсутствующие в доноре поля.
        # 24.10 (О3): при неизменившихся доноре/маппинге/renames
        # повторный update пропускается (ключ tables_upd_key.json) —
        # ~6 минут регулярного цикла не тратятся зря.
        if cfg.get('tables_update_existing') and not update_skip:
            upd_text = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
            n_sec = n_fld = 0
            for old in order:
                key = t + ':' + old
                if key not in mp:
                    continue
                new = mp[key]
                if new not in tsec_ids:
                    continue
                fields = prepare_fields(secs[old], t, mp, ref_map, renames)
                if not fields:
                    continue
                upd_text, nf, _ch = apply_std_fields(upd_text, new, fields)
                if nf:
                    n_sec += 1
                    n_fld += nf
            if n_fld:
                if not dry:
                    io.open(tp, 'wb').write(upd_text.encode('utf-8'))
                print('%s: обновлено существующих секций: %d, полей: %d%s'
                      % (t, n_sec, n_fld, ' (dry-run)' if dry else ''))
                updated_secs += n_sec
                updated_fields += n_fld

        # 20.10: replace_std — поля поверх стандартных секций приёмника
        repl = {}
        for k, v in std_all.items():
            kt, sid = k.split(':', 1)
            if kt == t:
                repl[sid] = v
        if repl:
            text = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
            n_std = 0
            for sid, fields in sorted(repl.items()):
                # 21.10: пути переименованных ассетов подставляем и в
                # поля replace_std, иначе иконка/модель остаётся старой.
                keys = list(fields)
                vals = replace_asset_paths(
                    ['%s = %s' % (k, fields[k]) for k in keys], renames)
                f2 = {}
                for k, l in zip(keys, vals):
                    f2[k] = l.split('=', 1)[1].strip()
                text, nf = apply_std_fields(text, sid, f2)[:2]
                if nf:
                    n_std += nf
                else:
                    print('  replace_std: секции %s нет в приёмнике — пропуск' % sid)
            if n_std and not dry:
                io.open(tp, 'wb').write(text.encode('utf-8'))
            if n_std:
                print('%s: replace_std применено полей: %d%s'
                      % (t, n_std, ' (dry-run)' if dry else ''))
                applied_std += n_std

        if blocks:
            ids = [b.split(']')[0][1:] for b in blocks[:12]]
            print('  ID:', ', '.join(ids) + (' ...' if len(blocks) > 12 else ''))
            total += len(blocks)

    print('ИТОГО секций:', total, '| replace_std полей:', applied_std,
          '| обновлено секций:', updated_secs, 'полей:', updated_fields,
          ('(dry-run)' if dry else ''))
    # 24.10 (О3): ключ сохраняется только при успешном боевом update —
    # следующий прогон с неизменным донором пропустит обновление
    if (cfg.get('tables_update_existing') and not update_skip
            and not dry and not errors):
        io.open(_key_p, 'wb').write(json.dumps({'key': _upd_key}, indent=1).encode('utf-8'))
        print('ключ обновления сохранён (tables_upd_key.json)')
    if errors:
        sys.exit(1)

if __name__ == '__main__':
    main()
