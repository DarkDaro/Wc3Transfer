# 17.09: Этап registry — реестр занятых ID приёмника + дубли имён
# Выход: target_id_registry.json (все кастомные ID приёмника по таблицам)
# Использование: python stage_registry.py <config.json> [--dry-run]
import io, os, sys, json, re

def parse_ini_sections(path):
    """Секции ini: {ID: body}"""
    out = {}
    if not os.path.exists(path):
        return out
    s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
    cur = None
    in_block = False
    # 19.09: [=[ ]=] — блоки текста: строки [xxx] внутри — НЕ секции
    for l in s.splitlines():
        if not in_block:
            m = re.match(r'^\[([^\]]+)\]', l)
            if m:
                cur = m.group(1)
                out[cur] = []
            elif cur is not None:
                out[cur].append(l)
        else:
            if cur is not None:
                out[cur].append(l)
        if not in_block and l.rstrip().endswith('[=['):
            in_block = True
        elif in_block and ']=]' in l:
            in_block = False
    return {k: chr(10).join(v) for k, v in out.items()}

def field(body, key):
    m = re.search(r'^' + key + r'\s*=\s*"?([^"\n]*)', body, re.M)
    return m.group(1) if m else ''

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    target = cfg['target']
    tb = os.path.join(target, 'table')

    registry = {}
    names = {}  # имя -> [ID] для поиска дублей
    # 20.09: стандартные ID WC3 (std_ids.json, извлечён из template\Melee
    # w3x2lni) — ВСЕГДА заняты. Без этого маппинг считал amrc/anfg/arsh
    # «свободными» и перенос ЗАТИРАЛ стандартные объекты (инцидент 20.09:
    # предметы/баффы записались поверх стандартных).
    std_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'std_ids.json')
    std_ids = {}
    if os.path.exists(std_p):
        std_ids = json.load(io.open(std_p, 'rb'))
    else:
        # 20.09: самовосстановление — извлечь из локальной копии
        # template\Melee (скопирован целиком в утилиту)
        tpl_p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'template', 'Melee')
        if os.path.isdir(tpl_p):
            for t in cfg['tables']:
                tp = os.path.join(tpl_p, t + '.ini')
                if os.path.exists(tp):
                    ts = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
                    std_ids[t] = sorted(set(re.findall(r'^\[([0-9A-Za-z]{4})\]', ts, re.M)))
            if std_ids:
                io.open(std_p, 'wb').write(json.dumps(std_ids, indent=1).encode('utf-8'))
                print('std_ids.json восстановлен из template\\Melee')
        if not std_ids:
            print('ВНИМАНИЕ: std_ids.json и template не найдены — стандартные ID НЕ защищены!')
    for t in cfg['tables']:
        p = os.path.join(tb, t + '.ini')
        secs = parse_ini_sections(p)
        custom = {}
        # 20.09: сначала стандартные ID — базовая защита
        for sid in std_ids.get(t, []):
            custom[sid] = {'parent': None, 'name': '', 'std': True}
        for sid, body in secs.items():
            # кастомный ID = не в prebuilt стандарте: эвристика —
            # секция имеет _parent ИЛИ равкод нестандартного вида.
            # Сохраняем ВСЕ секции с их родителями:
            custom[sid] = {
                'parent': field(body, '_parent'),
                'name': field(body, 'Name').strip(),
            }
            nm = custom[sid]['name']
            if nm:
                names.setdefault(nm, []).append(t + ':' + sid)
        registry[t] = custom
        print('%s: секций %d (стандартных защищено: %d)' % (t, len(custom), len(std_ids.get(t, []))))

    # дубли имён
    dups = {n: ids for n, ids in names.items() if len(ids) > 1}
    if dups:
        print('ДУБЛИ ИМЁН (приёмник):', len(dups))
        for n, ids in list(dups.items())[:10]:
            print('  ', n, '->', ids)

    # lowercase-конфликты (регистр)
    lower = {}
    lc_conflicts = []
    for t, secs in registry.items():
        for sid in secs:
            k = (t, sid.lower())
            if k in lower:
                lc_conflicts.append((sid, lower[k]))
            lower[k] = sid
    if lc_conflicts:
        print('РЕГИСТР-КОНФЛИКТЫ:', len(lc_conflicts))
        for a, b in lc_conflicts[:10]:
            print('  ', a, 'vs', b)

    # 19.09: реестр пишем и в dry-run — это рабочий файл утилиты
    # (не приёмник). Без записи в dry-run маппинг считался по СТАРОМУ
    # реестру от чужой пары карт -> коллизии ID при реальном прогоне.
    out = os.path.join(HERE := os.path.dirname(os.path.abspath(cfgp)),
                       cfg['mapping']['registry'])
    io.open(out, 'wb').write(json.dumps({
        'tables': registry,
        'name_duplicates': dups,
        'case_conflicts': lc_conflicts,
    }, indent=1, ensure_ascii=False).encode('utf-8'))
    print('реестр записан:%s %s' % (' (dry-run, рабочий файл)' if dry else '', out))

if __name__ == '__main__':
    main()