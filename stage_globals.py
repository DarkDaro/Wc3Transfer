# 18.09: Этап globals — перенос глобальных переменных из map/war3map.j источника
# Вход: cfg['source'], cfg['target'], cfg['code']['deploy_to'], cfg['globals'] (опции).
# Что делает:
#   1. Экстрактит блок globals/endglobals из map/war3map.j источника.
#   2. Собирает имена+типы глобалов приёмника (war3map.j + все .j trigger/).
#   3. Фильтр: gg_* выкидываются (редакторские); конфликты имён — по правилам:
#      имя+тип совпали -> пропуск (безопасно, пишем в отчёт);
#      имя совпало, тип разный -> БЛОКИРОВКА переноса (строгая типизация).
#   4. Пишет <entry>-Globals.j в trigger/ приёмника + дописывает catalog.lml.
# Опции cfg['globals']: enabled (bool), report_conflicts (bool, default True).
# Dry-run: только отчёт, файлы не пишутся.

import io, os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deploy_manifest

def parse_globals_block(text):
    """ВСЕ блоки globals/endglobals в файле -> список строк-объявлений.
    18.09 фикс: раньше брался только первый блок — в .j приёмника
    бывает несколько (vJass библиотеки), глобалы из остальных
    терялись и не попадали в проверку конфликтов."""
    lines = text.splitlines()
    out = []
    a = None
    for i, l in enumerate(lines):
        if l.strip() == 'globals':
            a = i
        elif l.strip() == 'endglobals' and a is not None:
            out.extend(x for x in lines[a + 1:i] if x.strip())
            a = None
    return out

def parse_decl(line):
    """'constant real X = 1.' / 'unit array Y' -> (type, name, is_array) или None.
    18.09: is_array возвращается отдельно — 'real array X' и 'real X'
    это РАЗНЫЕ переменные в JASS, сравнивать надо обе части."""
    m = re.match(r'\s*(?:constant\s+)?(\w+)\s+(array\s+)?(\w+)', line)
    if not m:
        return None
    return (m.group(1), m.group(3), bool(m.group(2)))

def vl_parse(text):
    """variable.lml -> {имя: (тип, array_size)}.
    Формат: 'Имя: тип' + опц. строка '    Array : N' (флаг записи).
    array_size = N при наличии флага, иначе 0.
    21.09 фикс A: флаг читается ТОЛЬКО до следующей записи/непустой
    строки — раньше окно k+1:k+3 приписывало Array-флаг соседней
    переменной. 21.09: N любое (не только 1)."""
    out = {}
    lines = text.splitlines()
    for k, l in enumerate(lines):
        m = re.match(r"(\w+)\s*:\s*(\w+)\s*$", l)
        if not m:
            continue
        arr = 0
        for x in lines[k + 1:]:
            # 'Array : N' (любое число) — флаг массива записи
            m2 = re.match(r"\s*Array\s*:\s*(\d+)\s*$", x)
            if m2:
                arr = int(m2.group(1))
                break
            if not x.strip():
                continue    # пустые строки между записью и флагом
            break    # иная строка (в т.ч. следующая запись) — флага нет
        out[m.group(1)] = (m.group(2), arr)
    return out

def collect_target_globals(tgt, skip_paths=None):
    """Имя -> тип по всем globals приёмника (war3map.j + trigger/**/*.j).
    20.10: skip_paths — не считать собственный прошлый <X>-Globals.j
    (иначе повторный прогон видел конфликт с самим собой)."""
    gm = {}
    skip = set(os.path.normcase(os.path.abspath(x)) for x in (skip_paths or []))
    wj = os.path.join(tgt, 'map', 'war3map.j')
    if os.path.exists(wj):
        for l in parse_globals_block(io.open(wj, 'rb').read().decode('utf-8', errors='replace')):
            d = parse_decl(l)
            if d:
                gm[d[1]] = (d[0], d[2])
    trig = os.path.join(tgt, 'trigger')
    if os.path.isdir(trig):
        for dirpath, dirs, fs in os.walk(trig):
            if '.git' in dirpath:
                dirs[:] = []
                continue
            for f in fs:
                if f.endswith('.j'):
                    p = os.path.join(dirpath, f)
                    if os.path.normcase(os.path.abspath(p)) in skip:
                        continue
                    try:
                        s = io.open(p, 'rb').read().decode('utf-8', errors='replace')
                    except Exception:
                        continue
                    for l in parse_globals_block(s):
                        d = parse_decl(l)
                        if d:
                            gm[d[1]] = (d[0], d[2])
    return gm

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    tgt = cfg['target']
    gopt = cfg.get('globals', {})
    deploy_to = cfg['code'].get('deploy_to', 'UFS')
    report = gopt.get('report_conflicts', True)

    wjs = os.path.join(src, 'map', 'war3map.j')
    if not os.path.exists(wjs):
        print('globals: map/war3map.j источника не найден — пропуск')
        return
    src_decls = parse_globals_block(io.open(wjs, 'rb').read().decode('utf-8', errors='replace'))
    if not src_decls:
        print('globals: блок globals/endglobals в источнике не найден — пропуск')
        return

    # 20.09: purge старого Globals-файла ПО МАНИФЕСТУ — ДО сбора
    # глобалов приёмника. Иначе collect_target_globals считал и
    # старый <X>-Globals.j -> все глобалы 'уже есть' -> keep пуст
    # -> новый файл не писался, старый висел навсегда.
    # Чистим ТОЛЬКО при смене deploy_to (замена одного файла другим).
    trig_tgt = os.path.join(tgt, 'trigger')
    entry_name = deploy_to
    cat_p = os.path.join(trig_tgt, 'catalog.lml')
    if os.path.exists(cat_p):
        cat0 = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')
        m0 = re.search(r"^'?(\d{3}-" + re.escape(deploy_to) + r")'?:", cat0, re.M)
        if m0:
            entry_name = m0.group(1)
    fname = entry_name + '-Globals.j'
    dst = os.path.join(trig_tgt, fname)
    rel_new = os.path.relpath(dst, tgt).replace(os.sep, '/')
    m_old = deploy_manifest.load_manifest(cfgp)
    if m_old and not dry:
        old_g = m_old.get('globals_file')
        old_ge = m_old.get('globals_entry')
        if old_g and old_g != rel_new:
            deploy_manifest.purge_section_files(cfgp, tgt, 'globals_file', {rel_new})
        if old_ge and old_ge != entry_name + '-Globals':
            deploy_manifest.purge_catalog_entry(cfgp, tgt, old_ge)

    skip_g = [dst]
    if m_old and m_old.get('globals_file'):
        skip_g.append(os.path.join(tgt, m_old['globals_file'].replace('/', os.sep)))
    tgt_gm = collect_target_globals(tgt, skip_paths=skip_g)
    print('глобалов в источнике:', len(src_decls), '| в приёмнике:', len(tgt_gm))

    # 21.09 фикс B: udg_ донора, перечисленные в его variable.lml,
    # НЕ переносятся в <X>-Globals.j — редактор генерит их декларации
    # из variable.lml приёмника (синхронизация ниже), дубль в globals-
    # файле = compile error. Работает ТОЛЬКО при живой синхронизации
    # variable.lml (есть оба файла) — иначе udg_ остаются в globals-файле.
    vl_p = os.path.join(trig_tgt, 'variable.lml')
    vl_src_p = os.path.join(src, 'trigger', 'variable.lml')
    vl_sync = os.path.exists(vl_p) and os.path.exists(vl_src_p)
    udg_vl = set()
    if vl_sync:
        udg_vl = set(vl_parse(io.open(vl_src_p, 'rb').read().decode('utf-8', errors='replace')))
    udg_dropped = 0

    keep, skip_same, blocked = [], [], []
    for l in src_decls:
        d = parse_decl(l)
        if not d:
            continue
        typ, name, is_arr = d
        if name.startswith('gg_'):
            continue  # редакторские — редактор создаёт сам
        # 21.09 фикс B: udg_ из variable.lml донора — только в
        # variable.lml приёмника, в globals-файл не пишем
        if vl_sync and name.startswith('udg_') and name[4:] in udg_vl:
            udg_dropped += 1
            continue
        if name in tgt_gm:
            t2, a2 = tgt_gm[name]
            # 18.09: array-модификатор обязателен к сравнению —
            # 'real array X' vs 'real X' несовместимы (индексация!)
            if t2 == typ and a2 == is_arr:
                # в отчёт — обе строки объявления (инициализация
                # может отличаться: донор '= CreateGroup()', приёмник '= null')
                skip_same.append((name, typ, l.strip()))
            else:
                blocked.append((name, typ + (' array' if is_arr else ''), t2 + (' array' if a2 else '')))
            continue
        keep.append(l.rstrip())

    print('переносится:', len(keep), '| пропуск (имя+тип совпали):', len(skip_same), '| БЛОКИРОВАНО (тип разный):', len(blocked))
    if udg_dropped:
        print('udg_ ушли в variable.lml (не в globals-файл):', udg_dropped)
    if report:
        if skip_same:
            print('-- пропуск (переменная уже есть в приёмнике, тип совпал):')
            for n, t, dl in skip_same:
                t2, a2 = tgt_gm[n]
                print('   %s%s : %s' % (t, ' array' if a2 else '', n))
                print('      донор:     %s' % dl)
                print('      приёмник:  %s%s %s' % (t2, ' array' if a2 else '', n))
        if blocked:
            print('-- БЛОКИРОВКА (имя занято другим типом!):')
            for n, t, t2 in blocked:
                print('   %s (донор) vs %s (приёмник) : %s' % (t, t2, n))
        gg = sum(1 for l in src_decls if (parse_decl(l) or ('', '', False))[1].startswith('gg_'))
        print('-- gg_* выкинуто:', gg)

    if blocked and not dry:
        print('globals: есть блокировки — файл НЕ пишется, разбери конфликты')
        return

    # 20.09: синхронизация variable.lml приёмника — редактор видит
    # переменные ТОЛЬКО через variable.lml. Глобалы, перенесённые в
    # <X>-Globals.j, в редакторе/GUI-триггерах были невидимы.
    # Переносим недостающие: имя, тип, Array-флаг. Существующие
    # записи приёмника НЕ трогаем (только добавление).
    # 20.09: стоит ДО ранних return-ов (keep=0 не должен мешать).
    # 21.09: vl_p/vl_src_p/vl_sync определены выше (фикс B).
    if vl_sync:
        vl_dst = vl_parse(io.open(vl_p, 'rb').read().decode('utf-8', errors='replace'))
        vl_src = vl_parse(io.open(vl_src_p, 'rb').read().decode('utf-8', errors='replace'))
        # 22.10: одно имя с другим типом или array флагом донора
        # молча пропускалось (n in vl_dst) и редактор тихо использовал
        # чужой тип. Теперь такой конфликт виден в отчёте.
        # 24.10: конфликтные переменные ДОПИСЫВАЮТСЯ в variable.lml под
        # именем <deploy_to>_<имя> (донорский тип/размер сохраняется);
        # перенесённые lml/.j уже ссылаются на новое имя (stage_code).
        # Раньше донорский GUI-триггер работал с чужим типом/размером:
        # AModInteger integer array(20) против приёмника integervar
        # array(1).
        vl_prefix = (cfg.get('code', {}).get('deploy_to') or 'UFS').strip() + '_'
        vl_conf = []
        for n, (t, a) in vl_src.items():
            if n in vl_dst:
                t2, a2 = vl_dst[n]
                if t2 != t or bool(a) != bool(a2):
                    vl_conf.append((vl_prefix + n, t, a, n))
                    print('ВНИМАНИЕ variable.lml: %s тип донора %s%s vs приёмника %s%s -> дописана под именем %s'
                          % (n, t, ' array(%d)' % a if a else '',
                             t2, ' array(%d)' % a2 if a2 else '', vl_prefix + n))
        vl_add = [(n, t, a) for n, (t, a) in vl_src.items() if n not in vl_dst]
        # 24.10: конфликтные под новыми именами — в ту же дописку
        exist_names = set(vl_dst)
        for nn, t, a, _old in vl_conf:
            if nn not in exist_names:
                vl_add.append((nn, t, a))
        if dry:
            print('variable.lml: не хватает %d из донора (dry-run, не пишу)' % len(vl_add))
        elif vl_add:
            # 21.09: Array-флаг с РЕАЛЬНЫМ размером донора (не всегда 1)
            block = '\n'.join('%s: %s\n%s' % (n, t, ('    Array : %d' % a) if a else '')
                              for n, t, a in vl_add)
            block = block.replace('\n\n', '\n')
            io.open(vl_p, 'ab').write(('\n' + block + '\n').encode('utf-8'))
            print('variable.lml: добавлено %d переменных' % len(vl_add))
            for n, t, a in vl_add:
                print('   %s%s : %s' % (t, (' array(%d)' % a) if a else '', n))
        else:
            print('variable.lml: приёмник уже полный')

    if dry:
        print('(dry-run: файл не пишется)')
        return
    # запись файла (trig_tgt/entry_name/cat_p/fname/dst/rel_new уже
    # определены в purge-блоке в начале main — 20.09)

    if not keep:
        print('globals: переносить нечего')
        return

    # 18.09: чистка старого файла без номера (если первый
    # прогон был до stage_code и записи в каталоге не было,
    # файл назывался '<deploy_to>-Globals.j' без префикса)
    old_alt = os.path.join(trig_tgt, deploy_to + '-Globals.j')
    if entry_name != deploy_to and os.path.exists(old_alt):
        os.remove(old_alt)
        print('удалён старый файл без номера:', old_alt)
    body = '// 18.09: globals донора %s (стейдж globals утилиты переноса)\n' % deploy_to
    body += '// пропущено (уже в приёмнике): %d, блокировано: %d\n' % (len(skip_same), len(blocked))
    body += 'globals\n' + '\n'.join(keep) + '\nendglobals\n'
    io.open(dst, 'wb').write(body.encode('utf-8'))
    print('записан:', dst, '(%d глобалов)' % len(keep))

    # дописка каталога (верхний уровень, в конец)
    if os.path.exists(cat_p):
        cat = io.open(cat_p, 'rb').read().decode('utf-8', errors='replace')
        # 18.09: чистка старой записи каталога без номера
        # (указывает на удалённый файл '<deploy_to>-Globals')
        old_entry = deploy_to + '-Globals'
        if entry_name != deploy_to and re.search(r"^'?" + re.escape(old_entry) + r"'?:", cat, re.M):
            cat = re.sub(r"^'?" + re.escape(old_entry) + r"'?:.*\n?", '', cat, flags=re.M)
            print('удалена старая запись каталога:', old_entry)
        # 18.09 фикс: проверка дубля по ТОЧНОМУ имени записи
        # (раньше только \d{3}-префикс — запись без номера
        # дописывалась повторно, получались дубли)
        if re.search(r"^'?" + re.escape(fname[:-2]) + r"'?:", cat, re.M):
            print('catalog.lml: запись уже есть — не дублирую')
        else:
            esc = lambda x: x.replace(chr(39), chr(39) * 2)
            disp = fname[:-2].split('-', 1)[-1] if '-' in fname[:-2] else fname[:-2]
            entry = "'" + esc(fname[:-2]) + "': '" + esc(disp) + "'"
            io.open(cat_p, 'wb').write((cat.rstrip() + '\n' + entry + '\n').encode('utf-8'))
            print('catalog.lml: запись добавлена')

    # 20.09: своя секция манифеста (merge — чужие секции не трогаю)
    deploy_manifest.merge_section(cfgp, 'globals', {
        'globals_file': rel_new,
        'globals_entry': entry_name + '-Globals',
        'variable_lml': True,
    })
    full = deploy_manifest.load_manifest(cfgp) or {}
    deploy_manifest.record_hashes(cfgp, full, tgt)

if __name__ == '__main__':
    main()