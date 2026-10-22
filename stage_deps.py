# 17.09: Этап deps — граф зависимостей объектов
# Вход: cfg['deps']['roots'] = список ID источника (герои/предметы/способности)
# Собирает замкнутый список: способности юнитов/предметов -> баффы способностей
# -> эффекты/иконки (Art, Model) -> предметы в abilList предметов.
# Выход: отчёт (stdout) + deps_result.json
import io, os, sys, json, re

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

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    src = cfg['source']
    tb = os.path.join(src, 'table')

    roots = list(cfg.get('deps', {}).get('roots', []))
    # 22.10: набор выбора (_JSON): include вливается в roots, голые ID
    # резолвятся по таблицам донора ниже; exclude_objects вычёркиваются
    # из замкнутого списка в конце (с предупреждением в отчёте).
    import transfer_set as tset
    sel = tset.load(cfgp, cfg)
    excl_objs = set(sel.get('exclude_objects', []))
    def norm_id(x):
        """'unit:Hgam' -> 'Hgam'; голый ID остаётся."""
        a, _, b = x.partition(':')
        if b and a in ('unit', 'ability', 'buff', 'item', 'upgrade',
                       'doodad', 'destructable'):
            return b
        return x
    for x in sel.get('include', []):
        nx = norm_id(x)
        if nx not in roots:
            roots.append(nx)
    excl_objs = {norm_id(x) for x in excl_objs}
    if sel.get('include'):
        print('перенос-набор: include %d (влито в корни deps)' % len(sel['include']))
    if not roots:
        # 17.09: пустые roots = ПОЛНЫЙ перенос: все секции всех
        # таблиц + все ассеты resource. wanted=None означает
        # 'вся таблица' в stage_mapping.
        import glob as _glob
        all_objs = {}
        for t in ['unit', 'ability', 'buff', 'item', 'upgrade',
                  'doodad', 'destructable', 'misc']:
            fp = os.path.join(tb, t + '.ini')
            if os.path.exists(fp):
                secs = parse_sections(fp)
                if secs:
                    all_objs[t] = sorted(secs)
        assets = []
        res = os.path.join(src, 'resource')
        for root, dirs, files in os.walk(res):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), res)
                assets.append(rel.replace(os.sep, '\\'))
        outp = os.path.join(os.path.dirname(os.path.abspath(cfgp)), 'deps_result.json')
        io.open(outp, 'wb').write(json.dumps({
            'roots': [],
            'objects': all_objs,
            'assets': sorted(assets),
            'full_transfer': True,
        }, indent=1, ensure_ascii=False).encode('utf-8'))
        print('deps.roots пуст — ПОЛНЫЙ ПЕРЕНОС:')
        for t, ids in sorted(all_objs.items()):
            print('  %s: %d секций' % (t, len(ids)))
        print('  ассетов: %d' % len(assets))
        return

    # загрузить таблицы источника
    tables = {}
    for t in ['unit', 'ability', 'buff', 'item', 'upgrade']:
        tables[t] = parse_sections(os.path.join(tb, t + '.ini'))

    # поля-ссылки: где искать чужие равкоды
    ABIL_KEYS = ['abilList', 'heroAbilList']
    BUFF_KEYS = ['buffList', 'BuffID', 'buffs']
    # 20.10: 'file' — модель юнита/предмета (раньше модели не попадали
    # в deps и не импортировались: собирались только Art-поля).
    ART_KEYS = ['file', 'Art', 'ButtonModel', 'Model', 'TargetArt', 'CasterArt',
                'EffectArt', 'MissileArt', 'SpecialArt']

    keep = set(roots)
    queue = list(roots)
    assets = set()  # пути файлов (иконки/модели)
    missing_assets = []

    def add_ids_from(body, keys, table):
        for k in keys:
            v = field(body, k)
            if not v:
                continue
            for tok in re.findall(r"'?[A-Za-z][0-9A-Za-z]{3}'?", v):
                tok = tok.strip("'")
                if tok in tables[table] and tok not in keep:
                    keep.add(tok)
                    queue.append(tok)

    while queue:
        sid = queue.pop()
        # определить таблицу
        for t in ['unit', 'ability', 'buff', 'item', 'upgrade']:
            if sid in tables[t]:
                body = tables[t][sid]
                if t in ('unit', 'item'):
                    add_ids_from(body, ABIL_KEYS, 'ability')
                if t == 'ability':
                    add_ids_from(body, BUFF_KEYS, 'buff')
                # ассеты
                for k in ART_KEYS:
                    v = field(body, k)
                    if v:
                        for tok in re.findall(r'[\w.\\/-]+\.(?:blp|mdl|mdx|tga)', v):
                            assets.add(tok)
                break

    # 22.10: вычеркнуть явные исключения (exclude_objects) ПОСЛЕ графа:
    # исключённый объект не попадает в перенос и в маппинг, но его
    # ассеты остаются в списке (безвредно: лишние импорты не ломают карту)
    dropped = [k for k in keep if k in excl_objs]
    for k in dropped:
        keep.discard(k)
        if k in queue:
            queue.remove(k)
    if dropped:
        print('перенос-набор: ВЫЧЕРКНУТО (exclude): %d: %s'
              % (len(dropped), ', '.join(sorted(dropped)[:20])))

    # проверка ассетов в источнике
    res_dirs = [os.path.join(src, 'resource'), os.path.join(src, 'sound')]
    for a in sorted(assets):
        found = any(os.path.exists(os.path.join(d, a.replace('\\', os.sep))) for d in res_dirs)
        # также в map/
        if not found and os.path.exists(os.path.join(src, 'map', a)):
            found = True
        if not found:
            missing_assets.append(a)

    print('КОРНИ:', ', '.join(roots))
    print('ЗАТЯНУЛОСЬ ОБЪЕКТОВ:', len(keep))
    _by = {}
    for _k in keep:
        _t, _i = _k.split(':', 1) if ':' in _k else ('?', _k)
        _by.setdefault(_t, []).append(_i)
    for t2 in sorted(_by):
        ids2 = sorted(_by[t2])
        print('  %s (%d): %s%s' % (t2, len(ids2), ', '.join(ids2[:15]), ' ...' if len(ids2) > 15 else ''))
    by_t = {}
    for sid in keep:
        for t in tables:
            if sid in tables[t]:
                by_t.setdefault(t, []).append(sid)
                break
    for t, ids in sorted(by_t.items()):
        print('  %s: %d' % (t, len(ids)))
    # 22.10 (docrутка): молчаливые сценарии deps — корни, НЕ найденные
    # ни в одной таблице донора (стандартные объекты или опечатки,
    # e2e-замер 22.10: 'ability:AHtc' тише исчезал из отчёта), и
    # exclude на объект, которого в замыкании нет. Оба печатаются.
    unknown = sorted(r2 for r2 in roots
                     if not any(r2 in tables[t] for t in tables))
    if unknown:
        print('ВНИМАНИЕ: корней не найдено в таблицах донора '
              '(стандартные или опечатки — перенос не изменится): %d (%s)'
              % (len(unknown), ', '.join(unknown[:10])))
    idle_excl = sorted(e for e in excl_objs
                       if e not in keep and e not in roots)
    if idle_excl:
        print('перенос-набор: exclude на объект, которого нет в '
              'замыкании (ничего не вычеркнуто): %s'
              % ', '.join(idle_excl[:10]))
    print('АССЕТОВ (иконки/модели):', len(assets))
    if missing_assets:
        print('НЕ НАЙДЕНЫ в источнике:', len(missing_assets))
        for a in missing_assets[:15]:
            print('  ', a)

    if not dry:
        outp = os.path.join(os.path.dirname(os.path.abspath(cfgp)), 'deps_result.json')
        # 17.09: сохранить auto_added (добавленные code_cut) —
        # иначе пересчёт от roots их стирает
        prev_auto = {}
        if os.path.exists(outp):
            try:
                prev = json.load(io.open(outp, 'rb'))
                prev_auto = prev.get('auto_added', {})
            except Exception as _e:
                # 22.10: раньше молча теряли auto_added — битый/занятый
                # deps_result.json незаметно менял результат deps
                print('ВНИМАНИЕ: deps_result.json не прочитан (%s) — '
                      'прошлый auto_added не учтён, файл будет перезаписан'
                      % _e)
        merged = {t: ids for t, ids in by_t.items()}
        for t2, ids2 in prev_auto.items():
            lst = merged.setdefault(t2, [])
            for x in ids2:
                if x not in lst:
                    lst.append(x)
        io.open(outp, 'wb').write(json.dumps({
            'roots': roots,
            'objects': merged,
            'assets': sorted(assets),
            'missing_assets': missing_assets,
        }, indent=1, ensure_ascii=False).encode('utf-8'))
        print('результат:', outp)

if __name__ == '__main__':
    main()