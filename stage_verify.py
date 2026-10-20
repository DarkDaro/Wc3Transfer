# 17.09: Этап verify — верификация после переноса
# 1. Все перенесённые секции (маппинг) есть в приёмнике
# 2. Регистр-конфликтов нет (lowercase уникальны по таблицам)
# 3. Ссылки в abilList/buffList перенесённых секций целы (в приёмнике)
# 4. Ассеты из deps на диске приёмника (или стандартные WC3)
# 5. Баланс скобок в .j приёмника (только перенесённые файлы)
import io, os, sys, json, re

def parse_sections(path):
    # с поддержкой [=[ ]=] блоков (текст внутри — не секции)
    out = set()
    if not os.path.exists(path):
        return out
    s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
    in_block = False
    for l in s.splitlines():
        if not in_block:
            m = re.match(r'^\[([^\]]+)\]', l)
            if m:
                out.add(m.group(1))
        if not in_block and l.rstrip().endswith('[=['):
            in_block = True
        elif in_block and ']=]' in l:
            in_block = False
    return out

def parse_bodies(path):
    # парсер с поддержкой [=[ ]=] блоков (текст описаний — не поля,
    # не секции; кавычки/скобки/слеши внутри игнорируются)
    out = {}
    if not os.path.exists(path):
        return out
    s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
    cur = None
    in_block = False
    for l in s.splitlines():
        if not in_block:
            m = re.match(r'^\[([^\]]+)\]', l)
            if m:
                cur = m.group(1)
                out[cur] = []
                continue
        if cur is not None:
            out[cur].append(l)
        if not in_block and l.rstrip().endswith('[=['):
            in_block = True
        elif in_block and ']=]' in l:
            in_block = False
    return out

def field(lines, key):
    for l in lines:
        m = re.match(r'^' + key + r'\s*=\s*"?([^"\n]*)', l)
        if m:
            return m.group(1)
    return ''

def main():
    cfgp = sys.argv[1]
    # 19.09: --no-map — проверка только приёмника,
    # без секций маппинга (обслуживание карты
    # без донора; маппинг от чужого переноса
    # даёт ложные «нет секций»)
    no_map = '--no-map' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    tgt = cfg['target']

    # 19.09: режим БЕЗ донора (обслуживание карты) —
    # mapping.json может отсутствовать, проверки 1 и 3
    # (по маппингу) пропускаются, остальное работает.
    mp = {}
    mp_p = os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json'))
    if not no_map and os.path.exists(mp_p):
        mp = json.load(io.open(mp_p, 'rb'))
    else:
        print('маппинг не используется — проверяю только приёмник')
    errs = warns = 0

    # prebuilt приёмника (стандартные ID — валидные _parent)
    # 17.09: автопоиск prebuilt рядом с source (lni-структура)
    PB = cfg.get('mapping', {}).get('prebuilt_dir')
    if not PB:
        import glob as _glob
        _srcdir = os.path.dirname(cfg.get('source', ''))
        cand = _glob.glob(os.path.join(_srcdir, '*', 'data', '*', 'prebuilt', 'Custom'))
        if not cand:
            cand = _glob.glob(os.path.join(_srcdir, 'data', '*', 'prebuilt', 'Custom'))
        if not cand:
            # 22.09: fallback на установленный w3x2lni (реальный путь,
            # старый был с двойной вложенностью и не существовал)
            cand = _glob.glob(r'G:\w3x2lni_enUS_v2.7.2\data\*\prebuilt\Custom')
        PB = cand[0] if cand else ''
    pb = {}
    if os.path.isdir(PB):
        for f in os.listdir(PB):
            if f.endswith('.ini'):
                s2 = io.open(os.path.join(PB, f), 'rb').read().decode('utf-8', errors='replace')
                pb[f[:-4]] = set(re.findall(r'^\[([A-Za-z][A-Za-z0-9]{3})\]', s2, re.M))

    # 1+2: секции на месте + lowercase уникальность
    for t in cfg['tables']:
        tp = os.path.join(tgt, 'table', t + '.ini')
        secs = parse_sections(tp)
        miss = [new for k, new in mp.items() if k.startswith(t + ':') and new not in secs]
        if miss:
            print('ОШИБКА %s: нет секций в приёмнике: %s' % (t, miss[:10]))
            errs += len(miss)
        lower = {}
        for sid in secs:
            k = sid.lower()
            if k in lower:
                print('РЕГИСТР-КОНФЛИКТ %s: %s vs %s' % (t, lower[k], sid))
                errs += 1
            lower[k] = sid

    # 3: ссылки в перенесённых секциях
    bodies = {}
    for t in ['unit', 'item', 'ability', 'buff', 'upgrade']:
        for k2, v2 in parse_bodies(os.path.join(tgt, 'table', t + '.ini')).items():
            bodies[k2] = v2
    # 17.09: проверка ПОСЛЕ полной загрузки всех таблиц (была
    # внутри цикла — ability ещё не загружен при проверке unit)
    # стандартные ID WC3 (prebuilt приёмника) — не битые ссылки
    std_ids = set()
    # 22.09: prebuilt-путь дублируется здесь и в блоке PB выше —
    # единый источник теперь cfg, fallback общий. Старый хардкод
    # (двойная вложенность w3x2lni_enUS_v2.7.2\w3x2lni_enUS_v2.7.2)
    # не существовал -> тысячи ложных «БИТЫЙ _PARENT» на стандартные ID.
    PB = cfg.get('mapping', {}).get('prebuilt_dir', '')
    if not PB:
        import glob as _glob
        _srcdir = os.path.dirname(cfg.get('source', ''))
        cand = _glob.glob(os.path.join(_srcdir, '*', 'data', '*', 'prebuilt', 'Custom'))
        if not cand:
            cand = _glob.glob(os.path.join(_srcdir, 'data', '*', 'prebuilt', 'Custom'))
        if not cand:
            cand = _glob.glob(r'G:\w3x2lni_enUS_v2.7.2\data\*\prebuilt\Custom')
        PB = cand[0] if cand else ''
    if os.path.isdir(PB):
        for f in os.listdir(PB):
            if f.endswith('.ini'):
                std_ids |= parse_sections(os.path.join(PB, f))
    for t in ['unit', 'item', 'ability']:
        for k, new in mp.items():
            if not k.startswith(t + ':'):
                continue
            if new not in bodies:
                continue
            lines = bodies[new]
            for key in ('abilList', 'heroAbilList', 'buffList', 'BuffID'):
                v = field(lines, key)
                for tok in re.findall(r"'?[0-9A-Za-z]{4}'?", v):
                    tok = tok.strip("'")
                    if tok and tok not in bodies and tok not in std_ids:
                        print('БИТАЯ ССЫЛКА %s:%s поле %s -> %s' % (t, new, key, tok))
                        errs += 1

    # 4: ассеты
    # 20.09: (а) исключённые exclude_paths — не ошибки (намеренный
    # пропуск импорта); (б) проверять ТОЛЬКО ассеты, на которые
    # реально ссылаются таблицы приёмника (deps тащит и от
    # неперенесённых таблиц — doodad/destructable — ложные «нет ассета»)
    deps_p = os.path.join(here, 'deps_result.json')
    if os.path.exists(deps_p):
        deps = json.load(io.open(deps_p, 'rb'))
        excl = [e.lower().replace('\\', '/') for e in cfg.get('import', {}).get('exclude_paths', [])]
        def is_excluded(pn):
            for e in excl:
                if pn.startswith(e) or ('/' + e) in pn:
                    return True
            return False
        # реальные ссылки: собрать Art/Model-пути из таблиц приёмника
        used_paths = set()
        for t2 in ('unit', 'ability', 'buff', 'item', 'upgrade', 'doodad', 'destructable'):
            tp2 = os.path.join(tgt, 'table', t2 + '.ini')
            if not os.path.exists(tp2):
                continue
            s2 = io.open(tp2, 'rb').read().decode('utf-8', errors='replace')
            for m in re.finditer(r'"([^"]+\.(?:blp|mdx|mdl|mp3|wav))"', s2, re.I):
                used_paths.add(m.group(1).replace('\\', '/').lower())
        for a in deps.get('assets', []):
            al = a.lower().replace('\\', '/')
            if is_excluded(al):
                continue  # намеренно исключён — молчим
            if used_paths and al not in used_paths:
                continue  # таблицы приёмника на него не ссылаются
            p = os.path.join(tgt, 'resource', a.replace('\\', os.sep))
            if not os.path.exists(p):
                # стандартный путь WC3 (mpq) — warning
                if a.startswith('Abilities') or a.startswith('Units') or a.startswith('ReplaceableTextures'):
                    warns += 1
                else:
                    print('НЕТ АССЕТА в приёмнике:', a)
                    errs += 1

    # 5: баланс скобок в ПЕРЕНЕСЁННЫХ .j (не во всех!)
    # 18.09 (v4): подпапки deploy_to лежат в КОРНЕ trigger/.
    # Проверяю только папки-записи FW (only_dirs или все
    # подпапки источника из манифеста), а не родные файлы
    # приёмника — у тех свой мусор, не наша зона.
    deploy_to = cfg['code'].get('deploy_to', 'UFS')
    trig_t = os.path.join(tgt, 'trigger')
    only = [d.strip() for d in cfg['code'].get('only_dirs', []) if d.strip()]
    if only:
        ddirs = [os.path.join(trig_t, d) for d in only]
    else:
        # 18.09: маркер «перенесено» = подпапки ИСТОЧНИКА
        # (родные папки приёмника в источник не входят)
        ddirs = []
        trig_s = os.path.join(cfg.get('source', ''), 'trigger')
        if os.path.isdir(trig_s):
            for nm in os.listdir(trig_s):
                if os.path.isdir(os.path.join(trig_s, nm)) and os.path.isdir(os.path.join(trig_t, nm)):
                    ddirs.append(os.path.join(trig_t, nm))
        if not ddirs:
            ddirs = [os.path.join(trig_t, deploy_to)]
    seen_dirs = set()
    # 22.09: донор и приёмник могут быть КОПИЯМИ одной карты (LOWSKEK->TEST1).
    # Тогда «совпадающие подпапки» = ВЕСЬ trigger приёмника, включая родные
    # файлы с родным мусором. Если файл несбалансирован И В ДОНОРЕ с той же
    # глубиной — это унаследовано 1:1, не порча от переноса: предупреждение.
    def paren_depth(path):
        s = io.open(path, 'rb').read().decode('utf-8', errors='replace')
        depth = 0
        for l in s.splitlines():
            if l.strip().startswith('//'):
                continue
            i2 = l.find('//')
            if i2 >= 0:
                l = l[:i2]
            l2 = re.sub(r'"[^"]*"', '""', l)
            depth += l2.count('(') - l2.count(')')
        return depth
    trig_s = os.path.join(cfg.get('source', ''), 'trigger')
    for ddir in ddirs:
        if not os.path.isdir(ddir) or os.path.abspath(ddir) in seen_dirs:
            continue
        seen_dirs.add(os.path.abspath(ddir))
        for root, dirs, fs in os.walk(ddir):
            for f in fs:
                if not f.endswith('.j'):
                    continue
                rp = os.path.join(root, f)
                depth = paren_depth(rp)
                if depth == 0:
                    continue
                # тот же файл в доноре — сравнить глубину
                rel = os.path.relpath(rp, trig_t)
                sp = os.path.join(trig_s, rel)
                if os.path.exists(sp) and paren_depth(sp) == depth:
                    print('ДИСБАЛАНС СКОБОК (унаследовано из донора, не ошибка):', f, 'глубина', depth)
                    warns += 1
                else:
                    print('ДИСБАЛАНС СКОБОК:', f, 'глубина', depth)
                    errs += 1

    # 6: ЛОМАЕТ СБОРКУ w3x2lni — жёсткие проверки таблиц приёмника
    # 6a: дубли секций в ini (w3x2lni падает или молча теряет объект)
    for t in cfg['tables']:
        tp = os.path.join(tgt, 'table', t + '.ini')
        if not os.path.exists(tp):
            continue
        s = io.open(tp, 'rb').read().decode('utf-8', errors='replace')
        seen = {}
        in_block = False  # внутри [=[ ]=] — не секции
        for l in s.splitlines():
            if not in_block:
                m = re.match(r'^\[([^\]]+)\]', l)
                if m:
                    sid = m.group(1)
                    if sid in seen:
                        print('ДУБЛЬ СЕКЦИИ %s: [%s] (второй раз, строка %d)' % (t, sid, len(seen)))
                        errs += 1
                    seen[sid] = True
            # [=[ ]=] блоки: внутри текст, не секции
            if '[=[' in l:
                in_block = True
            elif ']=]' in l:
                in_block = False
        # 6b: формат ID (4 символа: буква + 3 алфанумерика)
        for sid in seen:
            if not re.match(r'^[A-Za-z][A-Za-z0-9]{3}$', sid):
                print('НЕВЕРНЫЙ ID %s: [%s] (не 4 символа A-Za-z0-9)' % (t, sid))
                errs += 1
        # 6c: _parent существует (в ini ИЛИ в prebuilt — стандарт)
        bodies = parse_bodies(tp)
        pb_t = pb.get(t, set())
        for sid, lines in bodies.items():
            par = field(lines, '_parent')
            if par and par not in bodies and par not in pb_t:
                print('БИТЫЙ _PARENT %s:%s -> %s (нет секции)' % (t, sid, par))
                errs += 1
        # 6d: циклы _parent (A->B->A; self-parent A->A — норма lni)
        for sid in bodies:
            chain = [sid]
            cur = sid
            for _ in range(10):
                par = field(bodies[cur], '_parent')
                if not par or par not in bodies:
                    break
                if par in chain:
                    # цикл только если par не последний self-parent
                    if par != cur:
                        print('ЦИКЛ _PARENT %s: %s' % (t, ' -> '.join(chain + [par])))
                        errs += 1
                    break
                chain.append(par)
                cur = par
        # 6e: незакрытые блоки [=[ ]=]
        for sid, lines in bodies.items():
            body = chr(10).join(lines) if not isinstance(lines, str) else lines
            if body.count('[=[') != body.count(']=]'):
                print('НЕЗАКРЫТЫЙ БЛОК [=[ в %s:%s' % (t, sid))
                errs += 1

    # 7: imp.ini — каждый путь существует на диске приёмника
    imp_p = os.path.join(tgt, 'table', 'imp.ini')
    if os.path.exists(imp_p):
        s = io.open(imp_p, 'rb').read().decode('utf-8', errors='replace')
        res_root = os.path.join(tgt, 'resource')
        snd_root = os.path.join(tgt, 'sound')
        for m in re.finditer(r'"([^"]+)"', s):
            nm = m.group(1)
            if nm == 'import':
                continue
            # 20.09: w3x2lni для записей без пути ищет в war3mapImported\ —
            # иначе 560+ ложных предупреждений на картах с большим импортом
            found = any(os.path.exists(os.path.join(r2, nm.replace('/', os.sep)))
                        for r2 in (res_root, snd_root,
                                   os.path.join(res_root, 'war3mapImported'),
                                   os.path.join(snd_root, 'war3mapImported')))
            if not found:
                print('IMP.INI (предупреждение, файл мог быть удалён ранее):', nm)
                warns += 1

    print('=== ВЕРИФИКАЦИЯ: ошибок %d, предупреждений %d' % (errs, warns))
    sys.exit(1 if errs else 0)

if __name__ == '__main__':
    main()