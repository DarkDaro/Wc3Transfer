# 17.09: Этап mapping — маппинг ID источник -> приёмник (v2, режимы объектов)
# Режимы (cfg['mapping']['mode']):
#   'smart' (default): конфликт/изменённый стандарт -> новый ID + parent=стандарт
#   'replace_std': изменённые стандарты -> поля ВПИСАТЬ в стандартную секцию
#                  приёмника (без нового ID); кастомные -> как есть/новый ID
#   'custom_only': переносить ТОЛЬКО кастомные объекты (не стандарт источника)
# Классификация: prebuilt приёмника (Custom/*.ini) = множество стандартных ID.
# Выход: transfer_mapping.json + .pkl + mapping_report.txt (решения по объектам)
import io, os, sys, json, re, pickle, shutil, time

def parse_sections(path):
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

def gen_id(prefix, used_lower, counter):
    chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    while True:
        n = counter[0]
        counter[0] += 1
        c3 = chars[n % 62] + chars[(n // 62) % 62] + chars[(n // 3844) % 62]
        nid = prefix + c3
        if nid.lower() not in used_lower:
            used_lower.add(nid.lower())
            return nid

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    mode = cfg.get('mapping', {}).get('mode', 'smart')

    # prebuilt приёмника (стандартные ID)
    PB = cfg.get('mapping', {}).get('prebuilt_dir')
    if not PB:
        # 17.09: автопоиск prebuilt рядом с source (lni-структура)
        import glob as _glob
        cand = _glob.glob(os.path.join(os.path.dirname(src), '*', 'data', '*', 'prebuilt', 'Custom'))
        if not cand:
            cand = _glob.glob(os.path.join(os.path.dirname(src), 'data', '*', 'prebuilt', 'Custom'))
        PB = cand[0] if cand else ''
    pb = {}
    if os.path.isdir(PB):
        for f in os.listdir(PB):
            if f.endswith('.ini'):
                s2 = io.open(os.path.join(PB, f), 'rb').read().decode('utf-8', errors='replace')
                pb[f[:-4]] = set(re.findall(r'^\[([A-Za-z][A-Za-z0-9]{3})\]', s2, re.M))
    else:
        print('ВНИМАНИЕ: prebuilt не найден:', PB, '— классификация стандарт/кастом ограничена')

    deps_p = os.path.join(here, 'deps_result.json')
    wanted = None
    if os.path.exists(deps_p):
        deps = json.load(io.open(deps_p, 'rb'))
        wanted = {t: set(ids) for t, ids in deps['objects'].items()}

    reg_p = os.path.join(here, cfg['mapping']['registry'])
    reg = json.load(io.open(reg_p, 'rb'))
    used_lower = set()
    for t, secs in reg['tables'].items():
        for sid in secs:
            used_lower.add(sid.lower())

    stb = os.path.join(src, 'table')
    mapping = {}
    replace_std = {}   # (table, std_id) -> {поле: значение} (режим replace_std)
    report = []
    # 20.09: ИНКРЕМЕНТАЛЬНОСТЬ — прежние назначения неприкосновенны.
    # Без этого --loop сдвигал ID между итерациями (deps растёт ->
    # сортировка меняется -> gen_id выдаёт ДРУГОЙ объекту ID, занятый
    # прошлой итерацией -> tables писал юнита ПОВТОРНО -> 3 копии героев).
    # 21.10 (аудит): KEEP привязан к паре карт. Раньше после смены
    # донора/приёмника подхватывались старые назначения — объекты
    # получали ID от прошлой карты. --remap теперь ещё и --fresh.
    fresh = '--fresh' in sys.argv
    pair_p = os.path.join(here, 'mapping_pair.json')
    pair_now = [os.path.normcase(os.path.abspath(src)),
                os.path.normcase(os.path.abspath(cfg['target']))]
    pair_old = None
    if os.path.exists(pair_p):
        try:
            pair_old = json.load(io.open(pair_p, 'rb'))
        except ValueError:
            pair_old = None
    same_pair = pair_old is None or pair_old == pair_now
    prev_p = os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json'))
    prev = {}
    if os.path.exists(prev_p) and same_pair and not fresh:
        prev = json.load(io.open(prev_p, 'rb'))
        kept = 0
        for k, v in prev.items():
            t, old = k.split(':', 1)
            mapping[(t, old)] = v
            used_lower.add(v.lower())  # выданные ранее ID заняты навсегда
            kept += 1
        if kept:
            report.append('KEEP: %d прежних назначений сохранено (инкрементально)' % kept)
    elif pair_old is not None and not same_pair:
        report.append('ПАРА КАРТ ИЗМЕНИЛАСЬ — прежний маппинг не используется')
        print('маппинг: пара карт изменилась — прежние назначения не беру')
    elif fresh:
        report.append('--remap: маппинг пересобран с нуля')
        print('маппинг: --remap — прежние назначения не беру')

    counter = [0]
    for t in cfg['tables']:
        secs = parse_sections(os.path.join(stb, t + '.ini'))
        if wanted is not None:
            # deps есть: переносить ТОЛЬКО затянутое (пусто = ничего)
            ids = sorted(wanted.get(t, []))
        else:
            ids = sorted(secs)
        pb_t = pb.get(t, set())
        for sid in ids:
            if sid not in secs:
                continue
            # 20.09: инкрементальность — назначение уже есть, не трогаем
            if (t, sid) in mapping:
                continue
            body = secs[sid]
            par = field(body, '_parent')
            is_std_src = sid in pb_t or (par == sid)  # self-parent = изменённый стандарт
            is_std_id_taken = sid.lower() in used_lower

            if mode == 'custom_only' and is_std_src:
                report_line = 'SKIP (стандарт источника): %s:%s' % (t, sid)
                report.append(report_line)
                continue

            if mode == 'replace_std' and is_std_src:
                # вписать поля в стандартную секцию приёмника
                fields = {}
                for l in secs[sid].splitlines():
                    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', l)
                    if m and m.group(1) != '_parent' and m.group(2).strip() != '[=[':
                        fields[m.group(1)] = m.group(2)
                replace_std[(t, sid)] = fields
                report_line = 'REPLACE-STD: %s:%s (вписать %d полей в стандарт)' % (t, sid, len(fields))
                report.append(report_line)
                continue

            # smart / кастомные
            if is_std_id_taken:
                nid = gen_id(sid[0], used_lower, counter)
                mapping[(t, sid)] = nid
                report_line = 'NEW-ID: %s:%s -> %s (конфликт/изменённый стандарт)' % (t, sid, nid)
            else:
                mapping[(t, sid)] = sid
                report_line = 'AS-IS: %s:%s' % (t, sid)
            report.append(report_line)

    # сохранить (17.09: пишем и в dry-run — маппинг это рабочая
    # папка утилиты, не приёмник; без записи tables в dry-run
    # берёт СТАРЫЙ маппинг и показывает мусор)
    mp_json = os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json'))
    # 21.10: при смене пары/--remap старые рабочие файлы не затираем
    # молча — складываем в архив рядом с бэкапами.
    if fresh or (pair_old is not None and not same_pair):
        adir = os.path.join(here, cfg.get('safety', {}).get(
                            'backup_dir', 'transfer_backup'),
                            'mapping_%s_%d' % (
                                time.strftime('%Y%m%d-%H%M%S'), time.time_ns()))
        os.makedirs(adir, exist_ok=True)
        for p in (mp_json, os.path.join(here, cfg['mapping']['pkl']),
                  os.path.join(here, 'replace_std.json')):
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(adir, os.path.basename(p)))
        print('старый маппинг сохранён в архив:', adir)
    io.open(mp_json, 'wb').write(json.dumps(
        {'%s:%s' % k: v for k, v in mapping.items()},
        indent=1, ensure_ascii=False).encode('utf-8'))
    with open(os.path.join(here, cfg['mapping']['pkl']), 'wb') as pf:
        pickle.dump({'table': dict(mapping)}, pf)
    # 21.10: replace_std перезаписываем ВСЕГДА (пустой тоже), иначе
    # после смены донора применялись поля прошлой карты.
    io.open(os.path.join(here, 'replace_std.json'), 'wb').write(json.dumps(
        {'%s:%s' % k: v for k, v in replace_std.items()},
        indent=1, ensure_ascii=False).encode('utf-8'))
    io.open(pair_p, 'wb').write(json.dumps(pair_now, ensure_ascii=False).encode('utf-8'))
    io.open(os.path.join(here, 'mapping_report.txt'), 'wb').write(
        chr(10).join(report).encode('utf-8'))
    print('маппинг: %d записей, replace_std: %d, отчёт: mapping_report.txt' % (len(mapping), len(replace_std)))

if __name__ == '__main__':
    main()