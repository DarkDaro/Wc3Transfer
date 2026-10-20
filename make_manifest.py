# 17.09: manifest — отчёт о переносе в mdlog
# Запуск: python make_manifest.py <config.json>
# Генерирует mdlog/transfer/transfer-manifest-<дата>.md
import io, os, sys, json, time

def main():
    cfgp = sys.argv[1]
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    log_dir = cfg.get('log_dir') or os.path.join(here, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    mp_p = os.path.join(here, cfg['mapping']['pkl'].replace('.pkl', '.json'))
    mp = json.load(io.open(mp_p, 'rb')) if os.path.exists(mp_p) else {}
    deps_p = os.path.join(here, 'deps_result.json')
    deps = json.load(io.open(deps_p, 'rb')) if os.path.exists(deps_p) else {}
    st_p = os.path.join(here, cfg['safety']['state_file'])
    st = json.load(io.open(st_p, 'rb')) if os.path.exists(st_p) else {}

    conflicts = sum(1 for k, v in mp.items() if k.split(':', 1)[1] != v)
    lines = []
    lines.append('---')
    lines.append('description: Манифест переноса %s' % cfg.get('name', ''))
    lines.append('---')
    lines.append('')
    lines.append('# Манифест переноса: %s' % cfg.get('name', ''))
    lines.append('- Дата: %s' % time.strftime('%Y-%m-%d %H:%M'))
    lines.append('- Источник: %s' % cfg['source'])
    lines.append('- Приёмник: %s' % cfg['target'])
    lines.append('- Профиль: %s' % cfg.get('profile'))
    lines.append('- Пройдено этапов: %s' % ', '.join(st.get('completed', [])))
    lines.append('- Объектов в маппинге: %d (из них переименовано: %d)' % (len(mp), conflicts))
    if deps:
        lines.append('- Граф зависимостей: %s' % ', '.join('%s=%d' % (t, len(ids)) for t, ids in deps.get('objects', {}).items()))
        lines.append('- Ассетов: %d (не найдено в источнике: %d)' % (len(deps.get('assets', [])), len(deps.get('missing_assets', []))))
    lines.append('')
    lines.append('## Переименованные ID (конфликты)')
    lines.append('')
    for k, v in sorted(mp.items()):
        if k.split(':', 1)[1] != v:
            lines.append('- %s -> %s' % (k, v))
    out = os.path.join(log_dir, 'transfer-manifest-%s.md' % time.strftime('%Y%m%d-%H%M'))
    io.open(out, 'wb').write(chr(10).join(lines).encode('utf-8'))
    print('манифест:', out)

if __name__ == '__main__':
    main()