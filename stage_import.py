# 17.09: Этап import — копирование ассетов (resource/sound) по deps
# Правила конфликтов (пользователь, 17.09):
# 1. Файла нет в приёмнике -> копировать по пути из Art/Model
# 2. Файл есть и БАЙТ-В-БАЙТ равен -> пропуск (не копировать)
# 3. Файл есть и РАЗНЫЙ -> копировать как <имя>_v2.<ext> рядом +
#    записать замену пути в deps_result.json (assets_renamed),
#    чтобы stage_code/stage_tables могли подменить путь в объектах
# 4. Кастомные пути из Art/Model полей сохраняются как есть
#    (модели со своими путями импорта); стандартные WC3 пути
#    (Abilities/Units/...) — в mpq, не копируются
# Dry-run: только отчёт.
import io, os, sys, json, hashlib

def md5(p):
    return hashlib.md5(io.open(p, 'rb').read()).hexdigest()

def main():
    cfgp = sys.argv[1]
    dry = '--dry-run' in sys.argv
    cfg = json.load(io.open(cfgp, 'rb'))
    here = os.path.dirname(os.path.abspath(cfgp))
    src = cfg['source']
    tgt = cfg['target']

    deps_p = os.path.join(here, 'deps_result.json')
    if not os.path.exists(deps_p):
        print('deps_result.json нет — импорт по списку ассетов невозможен')
        return
    deps = json.load(io.open(deps_p, 'rb'))
    assets = deps.get('assets', [])
    if not assets:
        print('ассетов в deps нет')
        return

    excl = [e.lower().replace('\\', '/') for e in cfg['import'].get('exclude_paths', [])]
    # 20.09: сегментный матчинг исключений — 'UI' = папка UI\...
    # (путь НАЧИНАЕТСЯ с UI/ или содержит /UI/), а не «ui» где
    # угодно (Ruina, Druidic, Liquid — жертвы подстроки)
    def is_excluded(path_norm):
        for e in excl:
            if path_norm.startswith(e) or ('/' + e) in path_norm:
                return True
        return False
    # 20.09: перехват игровых моделей (Abilities/Units/ReplaceableTextures):
    # True = копировать поверх (глобальная замена), False = пропускать
    allow_override = cfg['import'].get('allow_override', True)
    src_dirs = [os.path.join(src, d) for d in cfg['import'].get('copy_dirs', ['resource', 'sound'])]
    # корень импорта приёмника (куда кладём)
    imp_root = os.path.join(tgt, 'resource')

    copied = same = skipped = missing = renamed = 0
    renames = {}  # старый путь -> новый путь (v2)
    for a in assets:
        al = a.lower().replace('\\', '/')
        if is_excluded(al):
            skipped += 1
            continue
        found = None
        for d in src_dirs:
            p = os.path.join(d, a.replace('\\', os.sep))
            if os.path.exists(p):
                found = p
                break
        if not found:
            missing += 1  # стандартный WC3 (mpq)
            continue
        # ПЕРЕКРЫТИЕ игровой модели: стандартный путь, но файл есть
        # в импорте источника — импорт заменит модель ВСЕЙ карты!
        # 20.09: allow_override=False — НЕ перехватывать (пропуск)
        if al.startswith(('abilities/', 'units/', 'replaceabletextures/')):
            if not allow_override:
                skipped += 1
                continue
            print('  ВНИМАНИЕ (перекрытие игровой модели):', a)
            print('    -> импорт заменит модель ГЛОБАЛЬНО для всей карты приёмника')
            print('    источник:', found)
        dst = os.path.join(imp_root, a.replace('\\', os.sep))
        if os.path.exists(dst):
            if md5(dst) == md5(found):
                same += 1  # идентичен — пропуск
                continue
            # разный: <имя>_v2.<ext> (если занято — v3, v4...)
            k = 2
            while True:
                b, e = os.path.splitext(dst)
                cand = '%s_v%d%s' % (b, k, e)
                if not os.path.exists(cand):
                    dst2 = cand
                    break
                k += 1
            if dry:
                print('  КОНФЛИКТ: %s -> %s' % (a, os.path.basename(dst2)))
            else:
                os.makedirs(os.path.dirname(dst2), exist_ok=True)
                io.open(dst2, 'wb').write(io.open(found, 'rb').read())
            # путь в приёмнике: resource/<отн. путь>
            old_rel = a
            new_rel = os.path.relpath(dst2, imp_root)
            renames[old_rel] = new_rel
            renamed += 1
            copied += 1
            continue
        if dry:
            print('  скопировать:', a)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            io.open(dst, 'wb').write(io.open(found, 'rb').read())
        copied += 1

    print('ассетов: %d | копий: %d | идентичных (пропуск): %d | переименовано v2+: %d | исключения: %d | стандартных WC3: %d%s'
          % (len(assets), copied, same, renamed, skipped, missing, ' (dry-run)' if dry else ''))
    if renames:
        print('ЗАМЕНЫ ПУТЕЙ (записать в объекты приёмника):')
        for old, new in renames.items():
            print('  %s -> %s' % (old, new))

    # сохранить renames в deps_result.json (для stage_tables/stage_code)
    if renames and not dry:
        deps['assets_renames'] = renames
        io.open(deps_p, 'wb').write(json.dumps(deps, indent=1, ensure_ascii=False).encode('utf-8'))
        print('renames записаны в deps_result.json')

    # регистрация в table/imp.ini (реестр импорта приёмника)
    if copied and not dry:
        imp_p = os.path.join(tgt, 'table', 'imp.ini')
        if os.path.exists(imp_p):
            cur = io.open(imp_p, 'rb').read().decode('utf-8', errors='replace')
            added = 0
            add_lines = []
            for a in assets:
                al = a.lower().replace('\\', '/')
                if is_excluded(al):
                    continue
                # 20.09: allow_override=False — игровые пути не пишем
                if not allow_override and al.startswith(('abilities/', 'units/', 'replaceabletextures/')):
                    continue
                found = any(os.path.exists(os.path.join(d, a.replace('\\', os.sep))) for d in src_dirs)
                if not found:
                    continue
                # имя в imp.ini: фактический путь (с учётом v2-переименований)
                nm = renames.get(a, a)
                nm = nm.replace('war3mapImported\\', '').replace('war3mapImported/', '')
                # 20.09: imp.ini — Lua-экранирование: одиночный \ ломает
                # парсер w3x2lni («invalid escape sequence near '\C'»).
                # Родной формат — двойной \\.
                nm = nm.replace('\\', '\\\\')
                if ('"%s"' % nm) not in cur:
                    add_lines.append('"%s",' % nm)
                    added += 1
            if added:
                idx = cur.rfind('}')
                cur = cur[:idx] + chr(10).join(add_lines) + chr(10) + cur[idx:]
                io.open(imp_p, 'wb').write(cur.encode('utf-8'))
                print('imp.ini: добавлено %d записей' % added)

if __name__ == '__main__':
    main()