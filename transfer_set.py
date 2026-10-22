# 22.10: набор выбора переноса (JSON рядом с конфигом)
# Задача: выборочный перенос объектов (герои/способности/предметы/бафы)
# и явные исключения: какие объекты и ТРИГГЕРЫ пропускаются.
# Файл по умолчанию: <имя конфига>_set.json рядом с конфигом
# (transfer_config.json -> transfer_set.json; мультиконфиг работает так же).
# Формат:
# {
#   "include":          ["Hgam", "unit:Hgam", "ability:A000"],  # что тянуть
#   "exclude_objects":  ["ability:A000"],                        # вычеркнуть после графа
#   "exclude_triggers": ["01-PA1.j", "2-Triggers/03-WillZoero.j", "WillZoero"],  # пропустить триггеры донора
# }
# Голый ID резолвится по таблицам донора (unit/ability/buff/item/upgrade);
# с префиксом типа берётся как есть.

import io
import json
import os


def path_for(cfgp):
    """Путь файла набора по имени конфига (рядом с конфигом)."""
    base = os.path.splitext(os.path.basename(cfgp))[0]
    return os.path.join(os.path.dirname(os.path.abspath(cfgp)),
                        base + '_set.json')


def load(cfgp, cfg=None):
    """Читает набор выбора. Отсутствует или пуст = пустой набор {}.
    Путь переопределяется ключом конфига selection.file."""
    fp = (cfg or {}).get('selection', {}).get('file', '')
    if not fp:
        fp = path_for(cfgp)
    if not os.path.exists(fp):
        return {}
    try:
        d = json.load(io.open(fp, encoding='utf-8'))
    except Exception as ex:
        print('перенос-набор: НЕ ПРОЧИТАН %s (%s) — набор игнорируется' % (fp, ex))
        return {}
    gov = lambda x: [str(t).strip() for t in d.get(x, []) if str(t).strip()]
    return {'include': gov('include'),
            'exclude_objects': gov('exclude_objects'),
            'exclude_triggers': gov('exclude_triggers')}
