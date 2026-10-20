# 17.09: Оркестратор переноса объектов между lni-картами (v1)
# Использование:
#   python transfer_run.py --plan            # показать план
#   python transfer_run.py --dry-run         # прогон без записи
#   python transfer_run.py --stage mapping   # один этап
#   python transfer_run.py --all             # весь пайплайн
#   python transfer_run.py --rollback        # откат к последнему успешному этапу
#   python transfer_run.py --status          # состояние (state)
# Этапы: mapping -> registry -> deps -> tables -> import -> code -> geometry -> verify
import io, os, sys, json, hashlib, shutil, time

HERE = os.path.dirname(os.path.abspath(__file__))
# 17.09: конфиг можно указать аргументом (--config X.json) — несколько
# источников сливаются в 1 приёмник ПОСЛЕДОВАТЕЛЬНЫМИ ПРОГОНАМИ,
# каждый со своим конфигом (свой state/mapping, общий приёмник).
CFG_PATH = os.path.join(HERE, 'transfer_config.json')
if '--config' in sys.argv:
    i = sys.argv.index('--config')
    CFG_PATH = os.path.abspath(sys.argv[i + 1])
    del sys.argv[i:i + 2]

STAGES = ['mapping', 'registry', 'deps', 'tables', 'import', 'code', 'code_cut', 'globals', 'geometry', 'testspawn', 'verify']

# профиль -> какие этапы включены
PROFILES = {
    'heroes': ['mapping', 'registry', 'deps', 'tables', 'import', 'code', 'globals', 'testspawn'],
    'objects': ['mapping', 'registry', 'deps', 'tables', 'import', 'code', 'globals'],
    'items': ['mapping', 'registry', 'deps', 'tables', 'import'],
    'full': ['mapping', 'registry', 'deps', 'tables', 'import', 'code', 'globals', 'geometry', 'testspawn'],
    'custom': None,  # по конфигу
}

def load_cfg():
    # 18.09: читаем файл один раз (было двойное чтение)
    # 20.10: дружелюбное сообщение вместо трейсбека на свежем клоне
    if not os.path.exists(CFG_PATH):
        print('ОШИБКА: конфиг не найден: %s' % CFG_PATH)
        print('Запусти GUI (Утилита переноса.bat) — он создаст конфиг по умолчанию.')
        sys.exit(2)
    return json.load(io.open(CFG_PATH, 'rb'))

def cfg_dir():
    # 17.09: рабочие файлы (state/mapping/deps/backup) живут рядом
    # с конфигом — разные конфиги не перекрываются
    return os.path.dirname(os.path.abspath(CFG_PATH))

def load_state(cfg):
    p = os.path.join(cfg_dir(), cfg['safety']['state_file'])
    # 17.09: state привязан к паре карт — смена source/target
    # сбрасывает completed (иначе докатка пропускает этапы
    # от чужого переноса)
    sig = cfg.get('source', '') + '->' + cfg.get('target', '')
    if os.path.exists(p):
        st = json.load(io.open(p, 'rb'))
        if st.get('pair') == sig:
            return st
        return {'completed': [], 'hashes': {}, 'last_ok_stage': None, 'pair': sig}
    return {'completed': [], 'hashes': {}, 'last_ok_stage': None, 'pair': sig}

def save_state(cfg, st):
    # 17.09: пара карт пишется в state
    sig = cfg.get('source', '') + '->' + cfg.get('target', '')
    st['pair'] = sig
    io.open(os.path.join(cfg_dir(), cfg['safety']['state_file']), 'wb').write(
        json.dumps(st, indent=2, ensure_ascii=False).encode('utf-8'))

def log(cfg, msg):
    d = cfg.get('log_dir') or os.path.join(cfg_dir(), 'logs')
    if d and os.path.isdir(d) is False:
        os.makedirs(d, exist_ok=True)
    line = '%s  %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line)
    if d:
        # 20.10: журнал на КОНФИГ (пара карт), а не один общий:
        # разные конфиги не перемешивают сессии друг с другом.
        # Для дефолтного конфига имя прежнее (transfer.log).
        stem = os.path.splitext(os.path.basename(CFG_PATH))[0]
        fname = 'transfer.log' if stem == 'transfer_config' else stem + '.log'
        with io.open(os.path.join(d, fname), 'ab') as f:
            f.write(line.encode('utf-8') + b'\n')

def fhash(p):
    return hashlib.md5(io.open(p, 'rb').read()).hexdigest()

def snapshot(cfg, stage, files):
    """Бэкап файлов перед этапом."""
    bdir = os.path.join(cfg_dir(), cfg['safety']['backup_dir'], stage)
    # 20.10: прошлый бэкап этого этапа удаляем — иначе после двух
    # прогонов в папке смешаны поколения и откат возвращает гибрид.
    if os.path.isdir(bdir):
        shutil.rmtree(bdir)
    os.makedirs(bdir, exist_ok=True)
    n = 0
    for p in files:
        if os.path.exists(p):
            rel = os.path.relpath(p, cfg['target'])
            dst = os.path.join(bdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(p, dst)
            n += 1
    log(cfg, 'снапшот %s: %d файлов' % (stage, n))

def target_files(cfg, stage):
    """Какие файлы приёмника затрагивает этап (для снапшота)."""
    t = cfg['target']
    tb = os.path.join(t, 'table')
    tr = os.path.join(t, 'trigger')
    if stage == 'tables':
        return [os.path.join(tb, n + '.ini') for n in cfg['tables']]
    if stage == 'import':
        return []
    if stage == 'code':
        out = []
        for root, dirs, files in os.walk(os.path.join(t, 'trigger')):
            for f in files:
                if f.endswith('.j') or f == 'catalog.lml':
                    out.append(os.path.join(root, f))
        return out
    if stage == 'geometry':
        return [os.path.join(t, 'map', f) for f in os.listdir(os.path.join(t, 'map'))
                if f.endswith(('.doo', '.w3e'))] if os.path.isdir(os.path.join(t, 'map')) else []
    return []

def run_stage(cfg, stage, dry):
    """Запуск этапа. Скрипты этапов лежат рядом и читают конфиг сами (v2).
    В v1 оркестратор вызывает существующие скрипты-этапы по имени."""
    scripts = {
        'mapping': 'stage_mapping.py',
        'registry': 'stage_registry.py',
        'deps': 'stage_deps.py',
        'tables': 'stage_tables.py',
        'import': 'stage_import.py',
        'code': 'stage_code.py',
        'code_cut': 'stage_code_cut.py',
        'globals': 'stage_globals.py',
        'geometry': 'stage_geometry.py',
        'testspawn': 'stage_testspawn.py',
        'verify': 'stage_verify.py',
    }
    sp = os.path.join(HERE, scripts[stage])
    if not os.path.exists(sp):
        log(cfg, 'ЭТАП %s: скрипт %s ещё не создан — пропуск' % (stage, scripts[stage]))
        return 'skip'
    log(cfg, 'ЭТАП %s: запуск %s%s' % (stage, scripts[stage], ' (DRY-RUN)' if dry else ''))
    import subprocess
    args = [sys.executable, sp, CFG_PATH] + (['--dry-run'] if dry else [])
    # 18.09: --allow-b для этапа code (замена B-литералов-баффов)
    if stage == 'code' and (cfg.get('code', {}).get('allow_b') or '--allow-b' in sys.argv):
        args.append('--allow-b')
    # 20.09: тайминг этапа в лог + защитный timeout (15 мин).
    # Причина: антивирусный stall на спавне python после записи
    # пачки файлов (code_cut no-op висел 8.4 мин) — теперь это
    # видно в логе, а зависший этап не тянет прогон вечно.
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=900)
    except subprocess.TimeoutExpired:
        log(cfg, 'ЭТАП %s: ПРЕВЫШЕН ЛИМИТ 15 мин — убит' % stage)
        return 'fail'
    dt = time.time() - t0
    out = (r.stdout or '') + (r.stderr or '')
    if out.strip():
        # 20.10: при ошибке показываем больше строк — раньше трейсбек
        # обрезался до 30 строк и причина падения терялась.
        tail = 100 if r.returncode != 0 else 30
        for l in out.splitlines()[-tail:]:
            log(cfg, '  | ' + l)
    # 20.09: этап дольше 2 сек — показать время (аномалии сразу видны)
    if dt > 2:
        log(cfg, 'ЭТАП %s: %.1f сек' % (stage, dt))
    if r.returncode != 0:
        log(cfg, 'ЭТАП %s: ОШИБКА (код %d)' % (stage, r.returncode))
        return 'fail'
    return 'ok'

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--stage')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--loop', action='store_true',
                    help='полный перенос с повторами (авто-расширение deps из кода)')
    ap.add_argument('--rollback', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--reset', action='store_true',
                    help='сбросить прогресс (state) для текущей пары карт')
    # 19.09: пересчёт реестра+маппинга под текущую пару карт
    ap.add_argument('--remap', action='store_true',
                    help='пересчитать реестр занятых ID и маппинг (после смены source/target)')
    args = ap.parse_args()

    if args.stage and args.stage not in STAGES:
        print('ОШИБКА: неизвестный этап %r. Доступны: %s'
              % (args.stage, ', '.join(STAGES)))
        sys.exit(2)

    cfg = load_cfg()
    st = load_state(cfg)
    profile = cfg.get('profile', 'custom')
    # 20.10: профиль задаёт базовый набор, галочки stage_enabled его сужают.
    # Раньше stage_enabled писался GUI, но оркестратор его не читал.
    base = PROFILES.get(profile)
    if base is None:
        base = STAGES
    stages = [s for s in base if stage_enabled(cfg, s)]

    if args.status:
        print('Пара:', st.get('pair', '?'))
        print('Пройдено этапов:', st.get('completed', []))
        print('Последний успешный:', st.get('last_ok_stage'))
        return

    if args.reset:
        st = {'completed': [], 'hashes': {}, 'last_ok_stage': None, 'pair': cfg.get('source', '') + '->' + cfg.get('target', '')}
        save_state(cfg, st)
        print('Прогресс сброшен для пары:', st['pair'])
        return

    if args.rollback:
        last = st.get('last_ok_stage')
        if not last:
            print('Нет успешных этапов для отката')
            return
        bdir = os.path.join(cfg_dir(), cfg['safety']['backup_dir'], last)
        if not os.path.isdir(bdir):
            print('Бэкап этапа', last, 'не найден')
            return
        n = 0
        for root, dirs, files in os.walk(bdir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, bdir)
                dst = os.path.join(cfg['target'], rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                n += 1
        print('Откат после этапа', last, ': восстановлено', n, 'файлов')
        print('Файлы, созданные этапом заново, откат не удаляет.')
        st['completed'] = st['completed'][:st['completed'].index(last)] if last in st.get('completed', []) else st.get('completed', [])
        st['last_ok_stage'] = None
        save_state(cfg, st)
        return

    if args.plan:
        print('=== ПЛАН ПЕРЕНОСА:', cfg.get('name'))
        print('Источник:', cfg['source'])
        print('Приёмник:', cfg['target'])
        print('Профиль:', profile, '-> этапы:', ', '.join(stages))
        print('Таблицы:', ', '.join(cfg['tables']))
        print('Пропуск таблиц:', ', '.join(cfg['skip_tables']))
        print('Импорт:', 'вкл' if cfg['import']['enabled'] else 'выкл')
        print('UI:', 'вкл (ОСТОРОЖНО)' if cfg['ui']['enabled'] else 'выкл')
        print('Геометрия:', 'вкл' if cfg['geometry']['enabled'] else 'выкл')
        print('Координаты кода:', cfg['code'].get('shift_coords', {}))
        return

    # 19.09: --remap — пересчёт реестра и маппинга под текущую пару карт.
    # Не трогает state и приёмник: только registry + mapping (рабочие файлы).
    if args.remap:
        log(cfg, '=== ПЕРЕМАППИНГ (реестр + маппинг под текущей пару карт) ===')
        # 20.09: прогресс-бар GUI — общее число этапов
        log(cfg, '=== ЭТАПЫ: 2')
        for s in ('registry', 'mapping'):
            r = run_stage(cfg, s, False)
            if r == 'fail':
                log(cfg, 'ОСТАНОВКА: этап %s упал' % s)
                sys.exit(1)
        log(cfg, 'ПЕРЕМАППИНГ ЗАВЕРШЁН')
        return

    if args.all or args.stage or args.dry_run or args.loop:
        # 17.09: --loop = полный цикл с повторами: deps->mapping->
        # tables->import->code_cut, пока auto_expand добавляет в deps
        # (макс 5 итераций). code_cut сбрасывает completed для повтора.
        if args.loop:
            cfg.setdefault('code_cut', {})['auto_expand'] = True
            # 20.09: БАГ — 'code_cut' if in STAGES else 'code' ЗАМЕНЯЛ code
            # на code_cut (выключен в конфиге -> no-op): триггеры НИКОГДА
            # не переносились в --loop. В цикле обязаны быть code (триггеры)
            # и globals (без них код не скомпилилится). code_cut — опция.
            core = [s for s in ['deps', 'mapping', 'tables', 'import',
                                'code', 'globals', 'code_cut']
                    if s in stages or s == 'code_cut']
            for it in range(1, 6):
                log(cfg, '=== ИТЕРАЦИЯ %d ===' % it)
                # 20.09: прогресс-бар GUI — этапы этой итерации
                # (+registry: реестр должен видеть секции, записанные
                # прошлой итерацией, иначе mapping не знает занятых ID)
                log(cfg, '=== ЭТАПЫ: %d' % (len(core) + 1))
                if it > 1:
                    r0 = run_stage(cfg, 'registry', args.dry_run)
                    if r0 == 'fail':
                        log(cfg, 'ОСТАНОВКА: registry упал')
                        sys.exit(1)
                if not args.dry_run:
                    st['completed'] = [s for s in st.get('completed', []) if s not in core]
                    save_state(cfg, st)
                grew = False
                deps_before = _deps_sig(cfg)
                for s in core:
                    files = target_files(cfg, s)
                    if files and not args.dry_run:
                        snapshot(cfg, s, files)
                    r = run_stage(cfg, s, args.dry_run)
                    if r == 'fail' and cfg['safety']['stop_on_error']:
                        log(cfg, 'ОСТАНОВКА на этапе %s' % s)
                        sys.exit(1)
                    if r == 'ok' and not args.dry_run:
                        st.setdefault('completed', []).append(s)
                        st['last_ok_stage'] = s
                        save_state(cfg, st)
                deps_after = _deps_sig(cfg)
                grew = deps_after != deps_before
                log(cfg, 'итерация %d: deps %s' % (it, 'ИЗМЕНИЛСЯ, повтор' if grew else 'стабилизировался'))
                if not grew:
                    break
            log(cfg, 'ПОЛНЫЙ ЦИКЛ ЗАВЕРШЁН (%d итераций)' % (it))
            return
        # 20.10: --stage вместе с --dry-run больше не запускает ВСЕ этапы
        todo = [args.stage] if args.stage else stages
        # 20.09: прогресс-бар GUI — общее число этапов прогона
        log(cfg, '=== ЭТАПЫ: %d' % len(todo))
        if args.dry_run:
            print('=== DRY-RUN (запись отключена) ===')
        for s in todo:
            # 19.09: verify в dry-run не имеет смысла — приёмник не менялся,
            # проверять нечего (было 498 строк "нет секций" шума)
            if args.dry_run and s == 'verify':
                log(cfg, 'ЭТАП verify: пропущен (dry-run — приёмник не менялся)')
                continue
            if s in st.get('completed', []) and not args.dry_run:
                log(cfg, 'этап %s уже пройден (докатка пропускает)' % s)
                continue
            files = target_files(cfg, s)
            if files and not args.dry_run:
                snapshot(cfg, s, files)
            r = run_stage(cfg, s, args.dry_run)
            if r == 'fail' and cfg['safety']['stop_on_error'] and not args.dry_run:
                log(cfg, 'ОСТАНОВКА на этапе %s. Откат: --rollback' % s)
                sys.exit(1)
            if r == 'ok' and not args.dry_run:
                st.setdefault('completed', []).append(s)
                st['last_ok_stage'] = s
                save_state(cfg, st)
        log(cfg, 'ПРОГОН ЗАВЕРШЁН')

def _deps_sig(cfg):
    # 17.09: сигнатура deps (содержимое, не count) для сравнения итераций
    # 20.10: рабочие файлы живут у конфига, а не у скрипта (мультиконфиг)
    import json
    p = os.path.join(cfg_dir(), 'deps_result.json')
    if not os.path.exists(p):
        return ''
    d = json.load(io.open(p, 'rb'))
    parts = []
    for t in sorted(d.get('objects', {})):
        parts.append(t + ':' + ','.join(sorted(d['objects'][t])))
    return '|'.join(parts)

def stage_enabled(cfg, s):
    # 20.10: галочки этапов из GUI (cfg['stage_enabled']) наконец читаются.
    # Явное значение в конфиге главнее флагов секций.
    se = cfg.get('stage_enabled') or {}
    if s in se:
        return bool(se[s])
    if s == 'geometry':
        return cfg.get('geometry', {}).get('enabled', False)
    if s == 'testspawn':
        return cfg.get('testspawn', {}).get('enabled', False)
    if s == 'import':
        return cfg.get('import', {}).get('enabled', True)
    if s == 'code':
        return cfg.get('code', {}).get('enabled', True)
    return True

if __name__ == '__main__':
    main()