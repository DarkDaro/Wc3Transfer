# 18.09: GUI для утилиты переноса — CustomTkinter (переписан с transfer_gui.py, поведение 1-в-1)
# Запуск: Утилита переноса.bat (pythonw)
import io, os, sys, json, re, subprocess, threading, queue   # 20.10: +re — был NameError в _load_cfg (geometry глотался молча)
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import time
try:
    import customtkinter as ctk
except ImportError as e:
    # 20.10: машинный интерпретатор по умолчанию может быть не тот (на
    # машине несколько Python) — под pythonw консоли нет и ImportError
    # умирал молча. Диалог + лог.
    _msg = ('customtkinter не установлен в этом Python:\n%s\n\n'
            'Python: %s\n\n'
            'Установка: pip install customtkinter==6.0.0' % (e, sys.executable))
    try:
        _r = tk.Tk()
        _r.withdraw()
        messagebox.showerror('Не хватает зависимости', _msg, parent=_r)
    except Exception:
        pass
    try:
        os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'), exist_ok=True)
        with io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'logs', 'gui_crash.log'), 'ab') as _f:
            _f.write(_msg.encode('utf-8') + b'\n')
    except Exception:
        pass
    sys.exit(1)

import stage_cleanup as sc
import stage_repair as sr

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, 'transfer_config.json')

# 20.10: самодостаточность — свежий клон без конфига работает: GUI
# создаёт каркас по умолчанию (пути карт пусты, добор пребылд-таблиц
# нужно указать вручную — подсказка через планировку полей).
DEFAULT_CFG = {
    '_comment': 'Конфиг переноса объектов между lni-картами. Заполнить под пару карт, затем: python transfer_run.py --plan',
    'source': '',
    'target': '',
    'name': '',
    'tables': ['unit', 'ability', 'buff', 'item', 'upgrade'],
    'skip_tables': ['w3i', 'misc'],
    # 21.10: повторный перенос может обновлять поля уже существующих
    # объектов приёмника (по умолчанию выключено — не затираем правки).
    'tables_update_existing': False,
    'import': {
        'enabled': True,
        'copy_dirs': ['resource', 'sound'],
        'exclude_paths': ['war3mapskin.txt', 'war3mapExtra.txt', 'war3mapMap.blp',
                          'war3mapMap.tga', 'war3mapMap.b00', 'minimap', 'LoadingScreen',
                          'loadingscreen', 'loadbar', 'console', 'war3mapMisc.txt',
                          'war3mapShadow', 'war3mapPreview', 'UI/Console', 'UI/'],
        'check_missing_refs': True,
        'allow_override': True,
    },
    'ui': {'enabled': False, 'mode': 'transfer'},
    'code': {
        'enabled': True, 'folders': 'flat', 'trigger_dirs': [],
        'shift_coords': {'enabled': False, 'dx': 0.0, 'dy': 0.0, 'ufs_range': 4000.0},
        'deploy_to': 'LIA', 'include_monolith': True, 'allow_b': True, 'only_dirs': [],
        'header_mode': 'append', 'func_prefix': 'LIA', 'update_catalog': True,
        'null_broken_gguits': True,
    },
    'geometry': {'enabled': False, 'offset': None, 'recount_z': True},
    'testspawn': {'enabled': False, 'heroes': [], 'items': True, 'rect': 'center'},
    'mapping': {
        'pkl': 'transfer_mapping.pkl', 'registry': 'target_id_registry.json',
        'case_conflict_check': True, 'duplicate_name_check': True, 'mode': 'smart',
        # prebuilt_dir: ОБЯЗАТЕЛЬНО — prebuilt/Custom из w3x2lni своего патча
        'prebuilt_dir': '',
    },
    'profile': 'custom',
    'safety': {'backup_dir': 'transfer_backup', 'state_file': 'transfer_state.json',
               'dry_run_first': True, 'stop_on_error': True,
               'stage_timeout_min': 15},
    'deps': {'roots': []},
    'code_cut': {'enabled': False, 'entries': [], 'output': 'cut_heroes.j', 'auto_expand': True},
    'stage_enabled': {'mapping': True, 'registry': True, 'deps': True, 'tables': True,
                      'import': True, 'code': True, 'code_cut': True, 'geometry': False,
                      'testspawn': False, 'verify': True, 'globals': True},
    # 22.10: toast и звуки событий — по умолчанию включены
    'gui': {'sound_on_done': True, 'autolog': True, 'log_font': 9, 'theme': 'dark',
            'toast': True, 'sounds': True},
}

STAGES = ['mapping', 'registry', 'deps', 'tables', 'import', 'code', 'code_cut', 'globals', 'geometry', 'testspawn', 'verify']
STAGE_LABELS = {
    'mapping': 'Маппинг ID',
    'registry': 'Реестр ID приёмника',
    'deps': 'Граф зависимостей',
    'tables': 'Перенос таблиц (ini)',
    'import': 'Импорт ассетов',
    'code': 'Код (папки триггеров)',
    'code_cut': 'Вырезка из монолита',
    'globals': 'Глобальные переменные',
    'geometry': 'Геометрия (декор/юниты)',
    'testspawn': 'TestSpawn',
    'verify': 'Верификация',
}
STAGE_HINTS = {
    'mapping': 'Сопоставляет ID объектов источника и приёмника. Конфликтные получают новые ID (режим выбирается справа).',
    'registry': 'Собирает все занятые ID приёмника, чтобы новые ID не конфликтовали с существующими.',
    'deps': 'От корней (герои/предметы) тянет всё зависимое: способности, бафы, дамми-юниты, ассеты.',
    'tables': 'Копирует секции [ID] из ini таблиц источника в приёмник с новыми ID.',
    'import': 'Копирует иконки/модели/звуки. Одинаковые файлы пропускает, разные переименовывает v2.',
    'code': 'Переносит папки триггеров с заменой литералов ID и дописывает catalog.lml.',
    'code_cut': 'Вырезает функции героя из монолита war3map.j донора (для карт без исходника).',
    'globals': 'Переносит блок globals из war3map.j источника в отдельный .j файл приёмника. gg_* пропускаются, конфликты имён — в отчёте: имя+тип совпали = пропуск, тип разный = блокировка.',
    'geometry': 'Вставка декора/юнитов в doo. РЕДКО нужно! Риск задвоения при повторном прогоне.',
    'testspawn': 'Генерирует .j для спавна перенесённых героев в игре (проверка что всё живое).',
    'verify': 'Проверяет приёмник: битые ссылки, дубли секций, циклы _parent, imp.ini. Ломает прогон при ошибках.',
}
SHORT = {
    'mapping': 'Маппинг', 'registry': 'Реестр', 'deps': 'Завис.',
    'tables': 'Таблицы', 'import': 'Импорт', 'code': 'Код',
    'code_cut': 'Вырезка', 'globals': 'Глобалы', 'geometry': 'Геометр.',
    'testspawn': 'Спавн', 'verify': 'Вериф.',
}

# 22.10: пресеты настроек. Задача: «сразу понятно, что выбирать и какие
# галочки под какие задачи нажимать». Пресет задаёт этапы, список таблиц
# и hint по корням deps; ID героев пользователь вписывает сам (они
# зависят от карты-донора). Применяется к текущим галочкам GUI,
# Dry-run остаётся как стоит (безопасность не перекрываем).
# stages: {stage: on} само; не указанные этапы выключаются.
# tupd: состояние галочки «Обновлять существующие объекты»
# (22.10: пресет снимает застрявший с прошлого ремонта флаг
# tables_update_existing, чтобы он не тянулся в обычный перенос).
PRESETS = {
    'Полный перенос': {
        'desc': 'Всё: объекты, ассеты, триггеры, глобалы, верификация.\n'
                'Корни deps пустые (полный перенос всех таблиц).\n'
                'Геометрия и спавн не включаются (нужно осознанно).',
        'stages': {'mapping': True, 'registry': True, 'deps': True,
                   'tables': True, 'import': True, 'code': True,
                   'globals': True, 'code_cut': False, 'verify': True},
        'tables': 'unit, ability, buff, item, upgrade, doodad, destructable',
        'roots': '',
        'tupd': False,
    },
    'Только герои и способности': {
        'desc': 'Юниты-герои, их способности, баффы, дамми и ассеты.\n'
                'Впишем ID героев донора в поле «Корни deps»\n'
                '(герои и предметы, через запятую). Таблицы:\n'
                'unit, ability, buff.',
        'stages': {'mapping': True, 'registry': True, 'deps': True,
                   'tables': True, 'import': True, 'code': True,
                   'globals': True, 'code_cut': False, 'verify': True},
        'tables': 'unit, ability, buff',
        'roots': None,   # None = поле не менять, пользователь вписывает ID
        'tupd': False,
    },
    'Только триггеры и код': {
        'desc': 'Переносить только папки триггеров, шапку и globals.\n'
                'Объекты и ассеты не трогаются. Маппинг/реестр\n'
                'пересчитываются (нужны для замены литералов в коде).',
        'stages': {'mapping': True, 'registry': True, 'code': True,
                   'code_cut': False, 'globals': True, 'verify': True},
        'tables': None,
        'roots': None,
        'tupd': False,
    },
    'Синхронизация существующих': {
        # 22.10: отдельный пресет repair-режима: tables обновляет уже
        # перенесённые секции приёмника (правка донора дотягивается в
        # приёмник). Хрупкий режим — пресетом, чтобы не забывать включать.
        'desc': 'Ремонт: tables_update_existing — уже перенесённые\n'
                'секции объектов ДОТЯНУТЬ правки донора в приёмник.\n'
                'Остальные объекты\ассеты не добавляются. Code/globals\n'
                'переписываются штатно (манифест почистит старое).\n'
                'Хрупкий режим: используй осознанно.',
        'stages': {'mapping': True, 'registry': True, 'deps': True,
                   'tables': True, 'code': True, 'code_cut': False,
                   'globals': True, 'verify': True},
        'tables': None,   # не менять список таблиц, ремонт по текущему
        'roots': None,
        'tupd': True,   # единственный пресет, включающий repair-галочку
    },
}


FONT = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 11)
FONT_MICRO = ("Segoe UI", 9)   # 22.10: описания пресетов
FONT_MONO = ("Consolas", 10)

# 20.10: единая палитра акцентов. Целерные литералы разъехались по окнам
# (v7 ab(), trigclean, cleanup, deob, rawconv) — риск расползания оттенков.
ACCENT   = "#3a7bd5"                        # акцент интерфейса (шапка, выделение)
DANGER   = "#c0392b"; DANGER_H = "#96281b"  # боевые операции
OKGREEN  = "#1e8e3e"; OKGREEN_H = "#156a2e" # успешные действия
WARN     = "#b7791f"; WARN_H    = "#9a6a12" # предупреждение / демо-режим

# тема из конфига до создания окна
def _load_theme_name():
    try:
        g = json.load(io.open(CFG, 'rb')).get('gui', {})
        return 'dark' if str(g.get('theme', 'dark')).lower() == 'dark' else 'light'
    except Exception:
        return 'dark'

APPEARANCE = _load_theme_name()
ctk.set_appearance_mode(APPEARANCE)


class Tooltip:
    """Всплывающая подсказка (тёмная/светлая по теме)."""

    def __init__(self, widget, text, wraplength=380):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tip = None
        self._hide_job = None
        # 21.10 (аудит): у CTkFrame события Enter забирают дочерние
        # виджеты. Привязываем подсказку ко всему поддереву.
        self._bind_tree(widget)
        try:
            widget.after_idle(lambda: self._bind_tree(widget))
        except Exception:
            pass

    def _bind_tree(self, w):
        try:
            w.bind("<Enter>", self._show, add="+")
            w.bind("<Leave>", self._leave, add="+")
        except Exception:
            pass
        try:
            kids = w.winfo_children()
        except Exception:
            kids = []
        for c in kids:
            self._bind_tree(c)

    def _show(self, _e=None):
        if self._hide_job:
            try:
                self.widget.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if self.tip:
            return
        mode = ctk.get_appearance_mode()
        bg = "#2b2b2b" if mode == "Dark" else "#1f2937"
        fg = "#f5f5f5" if mode == "Dark" else "#f9fafb"
        x = self.widget.winfo_rootx() + 15
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")

        tk.Label(self.tip, text=self.text, justify="left", bg=bg, fg=fg,
                wraplength=self.wraplength, padx=8, pady=5,
                font=("Segoe UI", 9)).pack()
        self.tip.wm_deiconify()

    def _leave(self, _e=None):
        # 21.10: при переходе между детьми рамки не прячем сразу —
        # даём 120 мс, иначе подсказка мигает.
        if self._hide_job:
            try:
                self.widget.after_cancel(self._hide_job)
            except Exception:
                pass
        try:
            self._hide_job = self.widget.after(120, self._hide)
        except Exception:
            pass

    def _hide(self, _e=None):
        self._hide_job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


def hint(widget, text):
    try:
        Tooltip(widget, text)
    except Exception:
        pass


class App(ctk.CTk):
    # 29.09: авто-подгонка Toplevel-окон под контент (правило: нижние
    # кнопки не должны обрезаться). Окно растёт под содержимое, но не
    # выше 90% экрана; ресайз разрешён.
    def _fit_toplevel(self, win, min_w=None, min_h=None):
        win.update_idletasks()
        req_w = win.winfo_reqwidth()
        req_h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        max_w = int(sw * 0.9)
        max_h = int(sh * 0.9)
        w = max(req_w, min_w or 0)
        h = max(req_h, min_h or 0)
        w = min(w, max_w)
        h = min(h, max_h)
        # центр к главному окну
        try:
            mx = self.winfo_rootx() + (self.winfo_width() - w) // 2
            my = self.winfo_rooty() + (self.winfo_height() - h) // 2
        except Exception:
            mx, my = (sw - w) // 2, (sh - h) // 2
        mx = max(0, min(mx, sw - w))
        my = max(0, min(my, sh - h))
        win.geometry('%dx%d+%d+%d' % (w, h, mx, my))
        win.minsize(min(300, w), min(200, h))

    def __init__(self):
        super().__init__()
        self.title('Утилита переноса объектов между картами (w3x2lni) — v6 CTk')
        # 20.09: контенту нужно ~1130px высоты — окно 860 давило журнал
        # и ленту прогресса. 21.10 (аудит): на 1920x1080 окно 1264x1130
        # уходило нижним краем за экран — статусбар был не виден.
        # Считаем размер от фактического экрана.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w0 = min(1264, sw - 40)
        h0 = min(1130, sh - 90)
        self.geometry('%dx%d' % (w0, h0))
        # 22.10 (UI): с вкладками окно живёт и в малом размере — всё
        # содержимое прокручивается (колонка этапов, настройки, Обслуживание)
        self.minsize(min(1000, w0), min(620, h0))
        self.cfg = {}
        self.stage_vars = {}
        self.q = queue.Queue()
        self.running = False
        self.log_size = 9
        # 20.10 (аудит): рассинхрон окон — галочка защитного списка живёт
        # в окне «Чистка триггеров», а скан окне «Чистка» читает её:
        # дефолт до первого открытия окна (иначе AttributeError)
        self._cleanup_v_prot = tk.BooleanVar(value=True)
        # 20.10 (аудит): разовый перенос выбором (окно «Триггеры...»)
        # сбрасывает only_dirs после прогона — обычный прогон не урезается
        self._clear_only_dirs = False
        self._proc = None

        self._build()
        self._load_cfg()
        # 19.09 (v7-fix): восстановить режим ПОСЛЕ
        # отрисовки окна (configure до первого рендера
        # ломает pack-геометрию главного окна — окно
        # остаётся 200x200, кнопки не нажимаются)
        if self.cfg.get('ui', {}).get('mode') == 'service':
            self.mode_seg.set('Обслуживание')
            self.after(300, self._apply_mode)
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(100, self._poll_log)
        # 22.10 (UI): горячие клавиши — вкладки и сохранение
        for i, tabname in enumerate(('Перенос', 'Обслуживание', 'Геометрия', 'Журнал'), 1):
            self.bind_all('<Control-Key-%d>' % i,
                          lambda e, t=tabname: self._goto_tab(t))
        self.bind_all('<Control-s>', lambda e: self._save_cfg_user())

    # ---------- построение UI ----------

    def _card(self, parent, title):
        """Карточка-секция с заголовком, возвращает inner.
        20.10: мягкий радиус + тонкая рамка — карточки отделяются от фона."""
        f = ctk.CTkFrame(parent, fg_color=("gray96", "gray13"),
                         corner_radius=10, border_width=1,
                         border_color=("gray86", "gray24"))
        ctk.CTkLabel(f, text=title, font=("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        inner = ctk.CTkFrame(f, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return f, inner

    def _refresh_head_status(self):
        # 20.10 (аудит): текст режима в шапке. После прогона «выполняется...»
        # затирал баннер Обслуживания и не восстанавливался — теперь единая
        # точка правды: и _apply_mode, и завершение прогона зовут её.
        serv = self.mode_seg.get() == 'Обслуживание'
        # 22.10: text_color=None крашит CTk — всегда явный цвет
        self.head_status.configure(
            text='РЕЖИМ: ОБСЛУЖИВАНИЕ (только приёмник)' if serv else 'готов',
            text_color=WARN if serv else ("gray35", "gray62"))

    def _stop_run(self):
        # 20.10 (аудит): остановка висящего прогона.
        # terminate() убивал только оркестратор, дочерний stage_*.py
        # продолжал писать в приёмник. На Windows валим дерево целиком.
        p = getattr(self, '_proc', None)
        if p and p.poll() is None:
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)],
                                   capture_output=True,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                else:
                    p.terminate()
                self._log('ОСТАНОВКА по кнопке «Стоп» (включая дочерние этапы)', 'warn')
            except Exception as e:
                self._log('Стоп: не удалось прервать: %s' % e, 'err')
        else:
            self._log('Стоп: активного прогона нет', 'warn')

    def _on_close(self):
        # 20.10 (аудит): закрытие окна во время прогона оставляло
        # оркестратор сиротой — он продолжал писать в приёмник.
        p = getattr(self, '_proc', None)
        if p and p.poll() is None:
            if not messagebox.askyesno(
                    'Идёт прогон',
                    'Прогон ещё выполняется.\nОстановить его и закрыть окно?'):
                return
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)],
                                   capture_output=True,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                else:
                    p.terminate()
            except Exception:
                pass
        self.destroy()

    def _cfg_dir(self):
        return os.path.dirname(os.path.abspath(self._cfg_path()))

    def _run_streamed(self, cmd, prefix='  ', on_line=None):
        """21.10: потоковый запуск инструмента — вывод идёт в журнал
        ПОСТРОЧНО. Раньше подокна собирали вывод subprocess.run до конца:
        GUI молчал минуты на тяжёлом скане. Возвращает (код, текст).
        21.10: on_line(строка) -> True — строка поглощена коллбэком
        (например @@TRIG маркеры), она не идёт в lines и в журнал."""
        env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 encoding='utf-8', errors='replace',
                                 env=env, cwd=HERE, creationflags=flags, bufsize=1)
        except Exception as e:
            return 1, 'ошибка запуска: %s' % e
        self._tool_proc = p
        lines = []
        for ln in p.stdout:
            ln = ln.rstrip()
            if not ln:
                continue
            # 22.10 (аудит): коллбэк-сбой не должен хоронить весь поток —
            # строка просто уходит в журнал, ошибка видна
            try:
                if on_line is not None and on_line(ln):
                    continue
            except Exception:
                self.q.put(('коллбэк потока упал: %s' % sys.exc_info()[1], 'err', None))
            lines.append(ln)
            low = ln.lower()
            tag = 'err' if ('ошибка' in low or 'error' in low) else \
                  ('warn' if ('внимание' in low or 'warning' in low) else None)
            self.q.put((prefix + ln[:160], tag, None))
        p.wait()
        self._tool_proc = None
        return p.returncode, '\n'.join(lines)

    def _win_beat(self, win, lbl, text, stop):
        """21.10: секундный таймер в подокне — «скан идёт: N сек»."""
        t0 = time.time()
        while not stop['f']:
            time.sleep(1)
            self._safe_after(win, lambda s=int(time.time() - t0):
                             lbl.configure(text='%s: %d сек...' % (text, s)))

    def _bg(self, work, done=None):
        """20.10: фоновая задача без заморозки UI. work() -> результат,
        done(результат) выполняется в главном потоке."""
        def run():
            try:
                res = work()
            except Exception as e:
                self._log('ОШИБКА в фоновой задаче: %s' % e, 'err')
                return
            if done is not None:
                try:
                    self.after(0, lambda: done(res))
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True).start()

    def _safe_after(self, win, fn):
        """after() из рабочего потока: окно могло быть закрыто."""
        try:
            win.after(0, fn)
        except Exception:
            pass

    def _goto_tab(self, tabname):
        """22.10 (UI): Ctrl+1/2/3 — открыть вкладку."""
        try:
            self.tabview.set(tabname)
            self._on_tab()
        except Exception:
            pass

    def _on_tab(self):
        """22.10 (UI): выбор вкладки меняет режим (Перенос/Обслуживание).
        Журнал режим не трогает. Защита от взаимного цикла — _tab_guard."""
        if getattr(self, '_tab_guard', False):
            return
        self._tab_guard = True
        try:
            t = self.tabview.get()
            if t in ('Перенос', 'Обслуживание'):
                self.mode_seg.set(t)
                self._apply_mode()
        finally:
            self._tab_guard = False

    def _apply_mode(self):
        """19.09 (v7): режим Перенос/Обслуживание.
        Обслуживание — только приёмник: донор-этапы и
        кнопки переноса disabled, кнопки обслуживания активны.
        22.10 (UI): режим синхронизирован с вкладками."""
        serv = self.mode_seg.get() == 'Обслуживание'
        try:
            if not getattr(self, '_tab_guard', False):
                self._tab_guard = True
                self.tabview.set('Обслуживание' if serv else 'Перенос')
                self._tab_guard = False
        except Exception:
            self._tab_guard = False
        # поля донора
        try:
            self.e_src.configure(state='disabled' if serv else 'normal')
            self.e_name.configure(state='disabled' if serv else 'normal')
        except Exception:
            pass
        # этапы — все disabled в обслуживании (прогон не используется)
        for s, v in self.stage_vars.items():
            for cb in self._stage_cbs.get(s, []):
                cb.configure(state='disabled' if serv else 'normal')
        # 22.10: пресеты — это донорная настройка переноса, в
        # обслуживании недоступны
        try:
            self.preset_box.configure(state='disabled' if serv else 'readonly')
            self.b_preset.configure(state='disabled' if serv else 'normal')
        except Exception:
            pass
        # кнопки переноса: единый список _donor_btns (собирается в _build),
        # донорные под-операции живут на вкладке Перенос и блокируются вместе
        # со всей строкой — донор в Обслуживании не задан
        for b in getattr(self, '_donor_btns', []):
            try:
                b.configure(state='disabled' if serv else 'normal')
            except Exception:
                pass
        # кнопки обслуживания: единый список _svc_btns, активны всегда,
        # в режиме Обслуживание подсвечены рамкой
        for b in getattr(self, '_svc_btns', []):
            try:
                if serv:
                    b.configure(border_width=2, border_color=ACCENT)
                else:
                    b.configure(border_width=0)
            except Exception:
                pass
        # сохранить режим
        self.cfg.setdefault('ui', {})['mode'] = 'service' if serv else 'transfer'
        self._save_cfg()
        # 19.09: индикатор режима в шапке
        self._refresh_head_status()

    def _build(self):
        # --- шапка (20.10: приглушённая подпись + акцентная полоса) ---
        head = ctk.CTkFrame(self, fg_color=("gray82", "gray8"), height=46)
        head.pack(fill="x")
        ctk.CTkFrame(self, height=2, fg_color=ACCENT,
                     corner_radius=0).pack(fill="x")   # 20.10: фирменная полоса
        ctk.CTkLabel(head, text="  Утилита переноса объектов",
                     font=("Segoe UI", 15, "bold")).pack(side="left", padx=8, pady=8)
        ctk.CTkLabel(head, text="w3x2lni", font=FONT_SMALL,
                     text_color=("gray45", "gray60")).pack(side="left", padx=4)
        self.head_status = ctk.CTkLabel(head, text="", font=FONT_SMALL)
        self.head_status.pack(side="right", padx=12)

        # 20.10: подписи тем по-русски (в конфиг пишется light/dark)
        self.THEME_RU = {"Светлая": "light", "Тёмная": "dark"}
        self.theme_seg = ctk.CTkSegmentedButton(
            head, values=list(self.THEME_RU), height=26,
            command=self._toggle_theme)
        self.theme_seg.set({"light": "Светлая", "dark": "Тёмная"}.get(APPEARANCE, "Тёмная"))
        self.theme_seg.pack(side="right", padx=(0, 12))
        for ch in self.theme_seg.winfo_children():
            try:
                Tooltip(ch, "Светлая или тёмная тема. Выбор сохраняется.")
            except Exception:
                pass

        # 19.09 (v7): режим работы — Перенос (донор+приёмник)
        # или Обслуживание карты (только приёмник)
        self.mode_seg = ctk.CTkSegmentedButton(
            head, values=["Перенос", "Обслуживание"], height=26,
            command=lambda v: self._apply_mode())
        self.mode_seg.set("Перенос")
        self.mode_seg.pack(side="right", padx=(0, 16))
        for ch in self.mode_seg.winfo_children():
            try:
                Tooltip(ch, "Перенос — перенос объектов/кода из донора в приёмник.\n"
                        "Обслуживание — работа с одной картой БЕЗ донора:\n"
                        "верификация, чистка объектов, починка таблиц.")
            except Exception:
                pass

        # --- 22.10 (UI): статусбар выше вкладок ---
        # pack отдаёт место в порядке паковки: bottom-виджет пакуется ДО
        # вкладки с expand, иначе вкладка выдавливает его за край (см. 20.09).
        sb = ctk.CTkFrame(self, fg_color="transparent")
        sb.pack(fill="x", side="bottom", padx=10, pady=(0, 6))
        # 20.10 (аудит): Стоп — теряет зависший этап (timeout есть только в CLI)
        self.b_stop = ctk.CTkButton(sb, text='Стоп', width=66, height=26,
                                    font=FONT_SMALL, state='disabled',
                                    command=self._stop_run)
        self.b_stop.pack(side='left', padx=(0, 4))
        self.status = ctk.CTkLabel(sb, text="готов", anchor="w",
                                   font=FONT_SMALL, height=24)
        self.status.pack(side="left", fill="x", expand=True)
        self.pct_lbl = ctk.CTkLabel(sb, text="", width=44, anchor="e",
                                    font=FONT_SMALL)
        self.pct_lbl.pack(side="left", padx=(6, 0))
        self.pbar = ctk.CTkProgressBar(sb, height=8)
        self.pbar.set(0)
        self.pbar.pack(side="left", fill="x", expand=True, padx=(8, 0))
        Tooltip(self.pbar, "Прогресс по этапам переноса.\nПолоска заполняется по мере прохождения этапов.")

        # --- 22.10 (UI): вкладки вместо одной высокой простыни ---
        # «Перенос» (карты, этапы, настройки, кнопки прогона),
        # «Обслуживание» (проверка, чистки, код, отчёты),
        # «Геометрия» (перенос ландшафта: декор и юниты, doo),
        # «Журнал» (прогресс + журнал во всю высоту).
        # Переключатель режима в шапке синхронизирован с вкладкой.
        self._tab_guard = False
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        for tabname in ("Перенос", "Обслуживание", "Геометрия", "Журнал"):
            self.tabview.add(tabname)
        self.tabview.configure(command=lambda _v=None: self._on_tab())
        tab_t = self.tabview.tab("Перенос")
        tab_s = self.tabview.tab("Обслуживание")
        tab_g = self.tabview.tab("Геометрия")
        tab_j = self.tabview.tab("Журнал")

        # содержимое вкладки Обслуживание: прокручиваемые группы операций
        svc_scroll = ctk.CTkScrollableFrame(tab_s, fg_color="transparent")
        svc_scroll.pack(fill="both", expand=True)
        ctk.CTkLabel(svc_scroll, text="Работа с одной картой (без донора).\n"
                     "Карта выбирается в подокне каждой операции; верификация берёт приёмник из поля на вкладке Перенос.",
                     font=FONT_SMALL, justify="left").pack(anchor="w", padx=6, pady=(4, 6))
        svc_rows = {}

        def svc_group(title):
            f = ctk.CTkFrame(svc_scroll, fg_color=("gray96", "gray13"),
                             corner_radius=10, border_width=1,
                             border_color=("gray86", "gray24"))
            f.pack(fill="x", pady=4)
            ctk.CTkLabel(f, text=title, font=("Segoe UI", 12, "bold"),
                         anchor="w").pack(fill="x", padx=12, pady=(6, 2))
            inner = ctk.CTkFrame(f, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=(0, 4))
            svc_rows[title] = inner
            return inner

        svc_chk = svc_group("Проверка и чистка")
        svc_code = svc_group("Триггеры и код")
        svc_misc = svc_group("Отчёты и прочее")
        self._svc_pos = {}

        def ab_svc(group, text, cmd, hint_text=None, color=None):
            parent = svc_rows[group]
            i = self._svc_pos.setdefault(group, 0)
            self._svc_pos[group] = i + 1
            kw = {}
            if color == 'danger':
                kw['fg_color'] = DANGER
                kw['hover_color'] = DANGER_H
            elif color == 'ok':
                kw['fg_color'] = OKGREEN
                kw['hover_color'] = OKGREEN_H
            elif color == 'warn':
                kw['fg_color'] = WARN
                kw['hover_color'] = WARN_H
            b = ctk.CTkButton(parent, text=text, height=34, width=215,
                              font=FONT_SMALL, command=cmd, **kw)
            r, c = divmod(i, 3)
            b.grid(row=r, column=c, padx=6, pady=6, sticky="w")
            if hint_text:
                Tooltip(b, hint_text)
            return b

        # --- вкладка «Геометрия» (22.10): перенос ландшафта одним местом ---
        # stage geometry пишет декор и юниты в doo приёмника; ландшафт w3e
        # не редактируется. Опции, запуск и предостережения в одной вкладке.
        gf1, gi1 = self._card(tab_g, "1. Опции вставки")
        gf1.pack(fill="x", padx=10, pady=(8, 4))
        self.v_geom = tk.BooleanVar(value=False)
        c4 = ctk.CTkCheckBox(gi1, text="Переносить декор и юнитов (этап geometry)",
                             variable=self.v_geom, font=FONT_SMALL,
                             checkbox_width=18, checkbox_height=18)
        c4.pack(anchor="w")
        Tooltip(c4, "Вставка декора/юнитов в doo приёмника со сдвигом offset.\n"
                    "Включай только для переноса ландшафта!\n"
                    "Повторный прогон задвоит декор: защиты нет.")
        self.v_recz = tk.BooleanVar(value=True)
        c4z = ctk.CTkCheckBox(gi1, text="Пересчитывать высоту (z) по рельефу приёмника",
                              variable=self.v_recz, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        c4z.pack(anchor="w", pady=(4, 0))
        Tooltip(c4z, "z берётся из карты приёмника на месте вставки.\n"
                     "Выключи, чтобы сохранить z донора (декор повиснет,\n"
                     "если рельеф различается).")
        # 22.10: разделение категорий — настраивается независимо
        tr_cat = ctk.CTkFrame(gi1, fg_color="transparent")
        tr_cat.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(tr_cat, text="Что переносить:", font=FONT_SMALL).pack(side="left")
        self.v_decor = tk.BooleanVar(value=True)
        c4d = ctk.CTkCheckBox(tr_cat, text="Декорации (war3map.doo)",
                              variable=self.v_decor, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        c4d.pack(side="left", padx=(8, 12))
        Tooltip(c4d, "Деревья, камни и прочие doodad/destructable\n"
                     "из war3map.doo донора.")
        self.v_units = tk.BooleanVar(value=True)
        c4u = ctk.CTkCheckBox(tr_cat, text="Юниты (war3mapUnits.doo)",
                              variable=self.v_units, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        c4u.pack(side="left", padx=4)
        Tooltip(c4u, "Юниты донора из war3mapUnits.doo\n"
                     "(стартовые локации sloc пропускаются).")
        # 22.10: ландшафт (w3e) — по умолчанию выключен (эксперимент)
        self.v_w3e = tk.BooleanVar(value=False)
        c4w = ctk.CTkCheckBox(gi1, text="Ландшафт (w3e): замена клеток перекрытия донором",
                              variable=self.v_w3e, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        c4w.pack(anchor="w", pady=(4, 0))
        Tooltip(c4w, "Клетки рельефа приёмника, попадающие в перекрытие "
                     "с донором (со сдвигом offset), заменяются клетками донора.\n"
                     "За границей донора рельеф приёмника остаётся.\n"
                     "Предохранитель: при разных тайлсетах этап откажется "
                     "(принудительно geometry.w3e.force = true).\n"
                     "Всегда начинай с Dry-run! Повтор безопасен (замена "
                     "идемпотентна).")
        gfr = ctk.CTkFrame(gi1, fg_color="transparent")
        gfr.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(gfr, text="Сдвиг координат offset:", font=FONT_SMALL).pack(side="left")
        ctk.CTkLabel(gfr, text="dx:", font=FONT_SMALL, width=24).pack(side="left", padx=(8, 0))
        self.e_dx = ctk.CTkEntry(gfr, width=90, height=28, font=FONT_MONO)
        self.e_dx.pack(side="left", padx=2)
        ctk.CTkLabel(gfr, text="dy:", font=FONT_SMALL, width=24).pack(side="left")
        self.e_dy = ctk.CTkEntry(gfr, width=90, height=28, font=FONT_MONO)
        self.e_dy.pack(side="left", padx=2)
        Tooltip(gfr, "Сдвиг декора (dx, dy) при вставке в приёмник.\n"
                     "Обычно это разница координат карт (пример: донор у\n"
                     "другого угла приёмника). Пусто = [0, 0].")

        gf2, gi2g = self._card(tab_g, "2. Запуск")
        gf2.pack(fill="x", padx=10, pady=4)
        gbtns = ctk.CTkFrame(gi2g, fg_color="transparent")
        gbtns.pack(fill="x")
        self.b_geom_dry = ctk.CTkButton(gbtns, text="Dry-run геометрии", width=160,
                                        height=32, font=FONT_SMALL,
                                        command=lambda: self._run(['--stage', 'geometry', '--dry-run']))
        self.b_geom_dry.pack(side="left", padx=3)
        self.b_geom = ctk.CTkButton(gbtns, text="Вставить (запись!)", width=160,
                                    height=32, font=FONT_SMALL,
                                    fg_color=DANGER, hover_color=DANGER_H,
                                    command=lambda: self._run(['--stage', 'geometry']))
        self.b_geom.pack(side="left", padx=3)
        Tooltip(self.b_geom_dry, "Прогон этапа geometry БЕЗ записи:\n"
                                 "смотри журнал, что и куда встанет.")
        Tooltip(self.b_geom, "Боевой прогон этапа geometry: декор и юниты\n"
                             "в приёмник со сдвигом offset.\n"
                             "Повторный прогон задвоит вставки.")
        ctk.CTkLabel(gi2g, text="Приёмник берётся из поля «Приёмник» на вкладке\n"
                                "Перенос, состояние этапа видно в Журнале и в\n"
                                "прогрессе этапов.", font=FONT_SMALL,
                     justify="left", anchor="w").pack(fill="x", pady=(6, 0))

        # --- 1. Карты ---
        cf, ci = self._card(tab_t, "1. Карты")
        cf.pack(fill="x", padx=10, pady=(8, 4))
        self.e_src = self._path_row(ci, "Источник (донор):",
            "Папка карты-донора в lni-формате (распакованная w3x2lni).\nНапример: G:\\w3x2lni\\UFS10", key='src')
        self.e_tgt = self._path_row(ci, "Приёмник:",
            "Папка карты, КОТОРУЮ ДОПОЛНЯЕМ.\nСнапшоты изменяемых файлов делаются автоматически.", key='map')
        self.e_name = self._text_row(ci, "Название переноса:",
            "Подпись для плана и манифеста (например \"UFS герои -> LoW\").")

        # --- середина: этапы слева, настройки справа (вкладка Перенос) ---
        mid = ctk.CTkFrame(tab_t, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=10, pady=4)

        # левая колонка: этапы (22.10 (UI): прокручиваемая — при малой
        # высоте окна все этапы и опции доступны, а не обрезаны)
        left = ctk.CTkScrollableFrame(mid, fg_color=("gray96", "gray13"),
                                      corner_radius=10, width=250,
                                      border_width=1, border_color=("gray86", "gray24"))
        left.pack(side="left", fill="y", padx=(0, 6), pady=4)
        ctk.CTkLabel(left, text="2. Этапы", font=("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(8, 2))
        self.stage_vars = {}
        self._stage_cbs = {}
        for s in STAGES:
            v = tk.BooleanVar(value=True)
            cb = ctk.CTkCheckBox(left, text=STAGE_LABELS[s], variable=v,
                                 font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
            cb.pack(anchor="w", padx=12, pady=1)
            Tooltip(cb, STAGE_HINTS[s])
            self.stage_vars[s] = v
            self._stage_cbs[s] = [cb]
        self.stage_vars['geometry'].set(False)
        self.stage_vars['testspawn'].set(False)

        # опции
        ctk.CTkLabel(left, text="Опции", font=("Segoe UI", 12, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        self.v_dry = tk.BooleanVar(value=True)
        c1 = ctk.CTkCheckBox(left, text="Dry-run (без записи)", variable=self.v_dry,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c1.pack(anchor="w", padx=12, pady=2)
        Tooltip(c1, "Прогон всего пайплайна без изменения приёмника.\nВсегда запускай сначала это!")
        self.v_stop = tk.BooleanVar(value=True)
        c2 = ctk.CTkCheckBox(left, text="Стоп при ошибке", variable=self.v_stop,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c2.pack(anchor="w", padx=12, pady=2)
        Tooltip(c2, "Останавливает прогон на первом ошибочном этапе.\nОткат: кнопка «Откат» (снапшоты).")
        self.v_sound = tk.BooleanVar(value=False)
        c6 = ctk.CTkCheckBox(left, text="Звук по завершении", variable=self.v_sound,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c6.pack(anchor="w", padx=12, pady=2)
        Tooltip(c6, "Системный звук, когда прогон завершён (удобно для фоновых прогонов).")
        # 22.10: события для toast и звуков (галочки там же, в «Опциях»)
        self.v_toast = tk.BooleanVar(value=True)
        c8 = ctk.CTkCheckBox(left, text="Всплывающие уведомления (toast)", variable=self.v_toast,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c8.pack(anchor="w", padx=12, pady=2)
        Tooltip(c8, "Компактные уведомления в углу окна: этап упал, прон завершён,\n"
                    "конфиг сохранён. Само исчезает за несколько секунд,\n"
                    "закрывается кликом.")
        self.v_sounds = tk.BooleanVar(value=True)
        c9 = ctk.CTkCheckBox(left, text="Звуки событий", variable=self.v_sounds,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c9.pack(anchor="w", padx=12, pady=2)
        Tooltip(c9, "Системные звуки Windows: упал этап, прогон завершён.\n"
                    "Хранится в конфиге: gui.sounds.")
        self.v_autolog = tk.BooleanVar(value=False)
        c7 = ctk.CTkCheckBox(left, text="Авто-открыть лог после прогона", variable=self.v_autolog,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c7.pack(anchor="w", padx=12, pady=2)
        Tooltip(c7, "После завершения прогона открыть logs/transfer.log.")
        # 21.10: лимит этапа настраивается; 0 = без лимита. Жёсткие
        # 15 минут убивали рабочий этап на больших картах.
        row_tmo = ctk.CTkFrame(left, fg_color="transparent")
        row_tmo.pack(fill="x", padx=12, pady=(2, 0))
        ctk.CTkLabel(row_tmo, text="Лимит этапа, мин:", font=FONT_SMALL).pack(side="left")
        self.e_tmo = ctk.CTkEntry(row_tmo, font=FONT_MONO, width=64, height=26)
        self.e_tmo.pack(side="left", padx=6)
        self.e_tmo.insert(0, "15")
        Tooltip(self.e_tmo, "Сколько минут ждать один этап (например geometry).\n"
                            "0 = ждать сколько нужно (лимита нет).\n"
                            "Хранится в конфиге: safety.stage_timeout_min.")

        # 22.10: пресеты настроек (просто выбор под задачу)
        pres_l = ctk.CTkLabel(left, text="Пресеты", font=("Segoe UI", 12, "bold"),
                              anchor="w")
        pres_l.pack(fill="x", padx=12, pady=(10, 2))
        self.preset_box = ctk.CTkComboBox(left, values=list(PRESETS),
                                          font=FONT_SMALL, height=28,
                                          state="readonly")
        self.preset_box.set(list(PRESETS)[0])
        self.preset_box.pack(fill="x", padx=12, pady=2)
        self.preset_desc = ctk.CTkLabel(left, text=PRESETS['Полный перенос']['desc'],
                                        font=FONT_MICRO, anchor="nw",
                                        justify="left", wraplength=226)
        self.preset_desc.pack(fill="x", padx=12, pady=(2, 4))
        self.b_preset = ctk.CTkButton(left, text="Применить пресет", height=30)
        self.b_preset.pack(fill="x", padx=12, pady=(0, 2))
        self.b_preset.configure(command=self._apply_preset)
        Tooltip(self.b_preset, "Установит этапы/таблицы/галочки под выбранную\n"
                               "задачу. Dry-run и геометрию пресеты не включают.\n"
                               "22.10: пресет также снимает галочку «Обновлять\n"
                               "существующие объекты» (это режим ремонта).\n"
                               "ID героев для пресета «Только герои и способности»\n"
                               "вписываются в «Корни deps». Конфиг записывается\n"
                               "при следующем «Сохранить конфиг» как обычно.")
        self.preset_box.configure(command=self._preset_desc)

        # правая колонка: настройки (скролл)
        right = ctk.CTkScrollableFrame(mid, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, pady=4)

        # 3. Объекты
        rf, ri = self._card(right, "3. Объекты")
        rf.pack(fill="x", pady=4)
        ctk.CTkLabel(ri, text="Режим переноса объектов:", font=FONT_SMALL,
                     anchor="w").pack(fill="x")
        self.mode_var = tk.StringVar(value='smart')
        hints_mode = {
            'smart': 'Конфликтный/изменённый стандарт -> новый ID с наследованием от стандарта. Безопасный дефолт.',
            'replace_std': 'Поля изменённого стандарта ВПИСЫВАЮТСЯ в стандартную секцию приёмника (без нового ID). Как в v6.',
            'custom_only': 'Переносить только кастомные объекты. Стандартные объекты источника не трогаются.',
        }
        for mv, ml in [('smart', 'Умный — новый ID + наследование (рекомендую)'),
                       ('replace_std', 'Заменять стандарт — поля вписать поверх'),
                       ('custom_only', 'Только кастомные — стандарт не трогать')]:
            rb = ctk.CTkRadioButton(ri, text=ml, value=mv, variable=self.mode_var,
                                    font=FONT_SMALL, radiobutton_width=18, radiobutton_height=18)
            rb.pack(anchor="w", pady=1)
            Tooltip(rb, hints_mode[mv])
        ctk.CTkLabel(ri, text="Корни deps (ID героев/предметов, через запятую):",
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(8, 0))
        self.e_roots = ctk.CTkEntry(ri, font=FONT_MONO, height=28)
        self.e_roots.pack(fill="x")
        Tooltip(self.e_roots, "С чего начинать тянуть зависимости.\nНапример: Hgam, Hpal — герои. Пусто = вся таблица.")
        self.v_aexp = tk.BooleanVar(value=False)
        c3 = ctk.CTkCheckBox(ri, text="Авто-расширение deps из кода (дамми и т.д.)",
                             variable=self.v_aexp, font=FONT_SMALL,
                             checkbox_width=18, checkbox_height=18)
        c3.pack(anchor="w", pady=(6, 6))
        Tooltip(c3, "Вырезка кода находит литералы ID, которых нет в deps\n(дамми-способности и т.п.) и добавляет их в перенос.\nРаботает с кнопкой «Полный цикл».")
        # 22.10: набор выбора (JSON): include/exclude_objects/exclude_triggers.
        # По умолчанию файл ищется рядом с конфигом <имя конфига>_set.json;
        # поле задаёт свой путь (пусто = автопуть).
        ctk.CTkLabel(ri, text="Набор выбора (JSON, путь или пусто):",
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(8, 0))
        self.e_setfile = ctk.CTkEntry(ri, font=FONT_MONO, height=28)
        self.e_setfile.pack(fill="x")
        Tooltip(self.e_setfile, "Файл выборочного переноса и исключений:\n"
                                "{ include, exclude_objects, exclude_triggers }.\n"
                                "include вливается в корни deps, exclude_objects\n"
                                "вычёркивается из графа, exclude_triggers\n"
                                "пропускает триггеры/папки донора при переносе кода.\n"
                                "Пусто = <имя конфига>_set.json рядом с конфигом.")
        # 22.10: пресет-сборер — вписал ID героев в «Корни deps», кнопка
        # считает замыкание (stage_deps) и собирает transfer_config_set.json
        self.b_selbuild = ctk.CTkButton(ri, text="Собрать набор из корней deps",
                                        height=28, font=FONT_SMALL,
                                        command=self._build_selection)
        self.b_selbuild.pack(fill="x", pady=(6, 6))
        Tooltip(self.b_selbuild, "stage_deps считает замыкание от ID в поле\n"
                                 "«Корни deps» и записывает набор (на глаз):\n"
                                 "include с типами (unit:X, ability:Y...),\n"
                                 "замыкание по abilList/heroAbilList/buffList.\n"
                                 "Существующие exclude_* сохраняются.")

        # 4. Таблицы
        cf2, ci2 = self._card(right, "4. Таблицы")
        cf2.pack(fill="x", pady=4)
        ctk.CTkLabel(ci2, text="Переносить таблицы (через запятую):",
                     font=FONT_SMALL, anchor="w").pack(fill="x")
        self.e_tables = ctk.CTkEntry(ci2, font=FONT_MONO, height=28)
        self.e_tables.pack(fill="x")
        Tooltip(self.e_tables, "unit, ability, buff, item, upgrade, doodad, destructable")
        ctk.CTkLabel(ci2, text="Пропускать (w3i, misc):",
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(6, 0))
        self.e_skip = ctk.CTkEntry(ci2, font=FONT_MONO, height=28)
        self.e_skip.pack(fill="x", pady=(0, 6))
        Tooltip(self.e_skip, "w3i — настройки карты (слоты, игроки), misc — константы.\nЭти таблицы НЕ переносят (ломают карту).")
        # 21.10 (аудит): повторный перенос по умолчанию не трогает уже
        # существующие секции. Галочка включает синхронизацию полей.
        self.v_tupd = tk.BooleanVar(value=False)
        cb_upd = ctk.CTkCheckBox(
            ci2, text="Обновлять существующие объекты (поля донора поверх приёмника)",
            variable=self.v_tupd, font=FONT_SMALL,
            checkbox_width=18, checkbox_height=18)
        cb_upd.pack(anchor="w", pady=(0, 2))
        Tooltip(cb_upd, "По умолчанию ID, уже существующие в приёмнике, пропускаются.\n"
                        "С галочкой простые поля донора перезаписывают их значения.\n"
                        "Блочные описания [=[ ... ]=] и поля, которых нет у донора, не трогаются.")

        # 5. Импорт ассетов
        imf, imi = self._card(right, "5. Импорт ассетов")
        imf.pack(fill="x", pady=4)
        ctk.CTkLabel(imi, text="НЕ импортировать (по одному в строке, подстрока в пути):",
                     font=FONT_SMALL, anchor="w").pack(fill="x")
        self.t_excl = ctk.CTkTextbox(imi, height=90, font=FONT_MONO)
        self.t_excl.pack(fill="x", pady=(0, 6))
        Tooltip(self.t_excl, "Ассеты с этими сегментами пути не копируются.\n'UI' = папка UI\\... (или \\UI\\ внутри), не «ui» где угодно.\nДефолт уже защищает миникарту, лоадскрин, скин.\nПример: LoadingScreen, minimap, war3mapMap.blp")
        # 20.09: перехват игровых моделей (Abilities/Units/ReplaceableTextures)
        self.v_override = ctk.BooleanVar(value=self.cfg.get('import', {}).get('allow_override', True))
        cb_ovr = ctk.CTkCheckBox(imi, text="Перехват игровых моделей (Abilities/Units/ReplaceableTextures)",
                                 variable=self.v_override, font=FONT_SMALL)
        cb_ovr.pack(anchor="w", pady=(0, 6))
        Tooltip(cb_ovr, "ВКЛ: файлы по стандартным путям WC3 копируются поверх\nи заменяют модель ГЛОБАЛЬНО для всей карты приёмника.\nВЫКЛ: такие ассеты пропускаются (игровые модели приёмника не трогаются).\nПо умолчанию ВКЛ (как раньше).")

        # 6. Код и геометрия
        gf2, gi2 = self._card(right, "6. Код и геометрия")
        gf2.pack(fill="x", pady=(4, 6))
        # 18.09 (v5): шапка донора — режим переноса
        ctk.CTkLabel(gi2, text="Шапка донора (code.j):", font=FONT_SMALL,
                     anchor="w").pack(fill="x")
        self.header_seg = ctk.CTkSegmentedButton(
            gi2, values=["отдельный файл", "в шапку приёмника"], height=28,
            command=lambda v: None)
        self.header_seg.set("отдельный файл")
        self.header_seg.pack(fill="x", pady=(2, 4))
        try:
            Tooltip(self.header_seg, "Куда положить шапку донора (code.j с хелперами).\n"
                    "Отдельный файл — 213-FW-header.j перед папками донора (чище).\n"
                    "В шапку приёмника — дописать в конец твоего code.j с маркерами\n"
                    "(повторный прогон заменяет блок целиком).")
        except Exception:
            pass
        # 18.09 (v5): префикс функций импорта
        pfr = ctk.CTkFrame(gi2, fg_color="transparent")
        pfr.pack(fill="x")
        self.v_prefix = tk.BooleanVar(value=False)
        c9 = ctk.CTkCheckBox(pfr, text="Префикс функций импорта:", variable=self.v_prefix,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c9.pack(side="left")
        Tooltip(c9, "Переименовать функции донора (Sleep -> FW_Sleep).\n"
                "Закрывает конфликты имён с функциями приёмника.\n"
                "Не трогает нативы, глобалы udg_*, строки.")
        self.e_prefix = ctk.CTkEntry(pfr, width=90, height=28, font=FONT_MONO)
        self.e_prefix.pack(side="left", padx=6)
        self.e_prefix.insert(0, "FW_")
        # 19.09 (v6): запись приёмника (deploy_to)
        dfr = ctk.CTkFrame(gi2, fg_color="transparent")
        dfr.pack(fill="x")
        ctk.CTkLabel(dfr, text="Запись приёмника (deploy_to):", font=FONT_SMALL,
                     anchor="w").pack(side="left")
        self.e_deploy = ctk.CTkEntry(dfr, width=110, height=28, font=FONT_MONO)
        self.e_deploy.pack(side="left", padx=6)
        Tooltip(self.e_deploy, "Имя записи каталога приёмника, куда пишется код\n"
                "(папка на диске = имя записи 1:1, как 213-FW).\n"
                "Меняй только для переноса в другую запись!")
        # 20.10: раскладка папок триггеров (редактор не умеет вложенность)
        ctk.CTkLabel(gi2, text="Раскладка папок триггеров:", font=FONT_SMALL,
                     anchor="w").pack(fill="x", pady=(8, 0))
        self.folders_seg = ctk.CTkSegmentedButton(
            gi2, values=["Одна папка", "Папки как у донора"], height=28,
            command=lambda v: None)
        self.folders_seg.set("Одна папка")
        self.folders_seg.pack(fill="x", pady=(2, 4))
        # 20.10 (аудит-фикс): CTk 6 — bind() на SegmentedButton бросает
        # NotImplementedError; у остальных сегментов уже try/except
        try:
            Tooltip(self.folders_seg,
                    "Одна папка — весь импорт в запись deploy_to (213-FW\\),\n"
                    "папка донора = префикс имени файла. Как раньше.\n"
                    "Папки как у донора — каждая папка триггеров донора получает\n"
                    "СВОЮ папку верхнего уровня trigger\\ (имя сохраняется 1:1):\n"
                    "в редакторе видно структуру, а не одна папка-свалка.\n"
                    "Корень донора, code-split и монолит всегда идут в deploy_to.\n"
                    "Смена режима чистит старое по манифесту деплоя.")
        except Exception:
            pass
        # 19.09 (v6): галочки каталога и монолита
        self.v_updcatalog = tk.BooleanVar(value=True)
        c10 = ctk.CTkCheckBox(gi2, text="Обновлять catalog.lml приёмника", variable=self.v_updcatalog,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c10.pack(anchor="w")
        Tooltip(c10, "Добавлять записи в catalog.lml приёмника\n(папка FW, шапка). Выключи, если правишь каталог вручную.")
        self.v_monolith = tk.BooleanVar(value=False)
        c11 = ctk.CTkCheckBox(gi2, text="Переносить монолит (code-split)", variable=self.v_monolith,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c11.pack(anchor="w")
        Tooltip(c11, "Переносить code-split монолит донора (крупный код).\nОбычно выключено — монолит переносится отдельно.")
        # 21.09: null-конверт битых gg_unit (торговцы донора) — ВКЛ по умолчанию
        self.v_ggnul = tk.BooleanVar(value=True)
        c12 = ctk.CTkCheckBox(gi2, text="Битые gg_unit → null (юниты вне карты)", variable=self.v_ggnul,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c12.pack(anchor="w")
        Tooltip(c12, "Ссылки на юнитов, которых нет на карте приёмника\n(торговцы донора) заменяются на null.\nСверка с war3mapUnits.doo приёмника. Выключи, если\nдобавишь юнитов на карту и хочешь живые переменные.")
        # 22.10: блок «Геометрия» (галочка и offset) переехал на ровную
        # вкладку «Геометрия» — перенос ландшафта собран в одном месте
        self.v_allowb = tk.BooleanVar(value=True)
        c8 = ctk.CTkCheckBox(gi2, text="Заменять B-литералы (баффы) в коде", variable=self.v_allowb,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c8.pack(anchor="w", pady=(4, 0))
        Tooltip(c8, "Баффы в JASS-коде вызываются равкодами Bxxx.\nПосле переноса баффы получают новые ID — код надо обновить.\nВыключи, если хочешь заменить их вручную позже.")
        self.v_ts = tk.BooleanVar(value=False)
        c5 = ctk.CTkCheckBox(gi2, text="TestSpawn (спавн героев в игре)", variable=self.v_ts,
                             font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        c5.pack(anchor="w", pady=(4, 0))
        Tooltip(c5, "Генерирует 90-TestSpawn.j: создаёт перенесённых героев для проверки.")
        ctk.CTkLabel(gi2, text="Герои TestSpawn (пусто = все из deps):",
                     font=FONT_SMALL, anchor="w").pack(fill="x", pady=(4, 0))
        self.e_ts = ctk.CTkEntry(gi2, font=FONT_MONO, height=28)
        self.e_ts.pack(fill="x", pady=(0, 6))
        # 22.09: точка спавна (center = 0,0 центр карты)
        ctk.CTkLabel(gi2, text="Точка спавна (center = 0,0 или имя региона):",
                     font=FONT_SMALL, anchor="w").pack(fill="x")
        self.e_tsrect = ctk.CTkEntry(gi2, font=FONT_MONO, height=28)
        self.e_tsrect.pack(fill="x", pady=(0, 6))
        Tooltip(self.e_tsrect, "center или пусто — спавн в центре карты (0, 0).\nИначе — имя региона (gg_rct_team_1_spawn).")

        # 22.10 (перенос): карточка «Пути и лимиты» живёт на вкладке
        # Обслуживание (svc_scroll создан выше, карточка ляжет после
        # групп кнопок): каталоги журналов/бэкапов — настройки именно
        # сервисных операций
        pf7, pi7 = self._card(svc_scroll, "Пути и лимиты (Обслуживание)")
        pf7.pack(fill="x", pady=4)
        ctk.CTkLabel(pi7, text="Пусто = путь по умолчанию (logs/ и transfer_backup/ у конфига).",
                     font=FONT_SMALL, anchor="w").pack(fill="x")
        _prow = {}
        def srv_row(sec, key, label):
            r = ctk.CTkFrame(pi7, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=label, width=132, anchor="w",
                         font=FONT_SMALL).pack(side="left")
            e = ctk.CTkEntry(r, font=FONT_MONO, height=26)
            e.pack(side="left", fill="x", expand=True, padx=4)
            ctk.CTkButton(r, text="...", width=30, height=26,
                          command=lambda: self._pick(e)).pack(side="left")
            Tooltip(e, 'Каталог для журналов/бэкапов, конфиг-ключ '
                       + sec + '.' + key + '.\nПусто = по умолчанию, рядом с конфигом.')
            _prow[(sec, key)] = e
            return e
        self.e_clog = srv_row('cleanup', 'log_dir', 'Чистка, журнал:')
        self.e_cbak = srv_row('cleanup', 'backup_dir', 'Чистка, бэкапы:')
        self.e_tlog = srv_row('trigclean', 'log_dir', 'Тригклин, журнал:')
        self.e_tbak = srv_row('trigclean', 'backup_dir', 'Тригклин, бэкапы:')
        self.e_rlog = srv_row('repair', 'log_dir', 'Починка, журнал:')
        self.e_rbak = srv_row('repair', 'backup_dir', 'Починка, бэкапы:')
        self.e_rvbak = srv_row('rawconv', 'backup_dir', 'Конверт, бэкапы:')

        # 22.10: обе группы кнопок прогона — две ровные строки на вкладке
        # Перенос; донорные под-операции («Триггеры...», TestSpawn) здесь же,
        # они зависят от донора и логически относятся к переносу
        btns = ctk.CTkFrame(tab_t, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=4)

        def ab(parent, text, cmd, hint_text=None, color=None, w=None):
            kw = {}
            w = w or 132    # 22.10 (UI): единая ширина — ровный ряд кнопок
            kw['width'] = w
            if color == 'danger':
                kw['fg_color'] = DANGER
                kw['hover_color'] = DANGER_H
            elif color == 'ok':
                kw['fg_color'] = OKGREEN
                kw['hover_color'] = OKGREEN_H
            elif color == 'warn':
                kw['fg_color'] = WARN
                kw['hover_color'] = WARN_H
            # 19.09 (v7-fix): cmd НЕ привязывался — кнопки
            # были кликабельны визуально, но command=None
            b = ctk.CTkButton(parent, text=text, height=32, font=FONT_SMALL,
                              command=cmd, **kw)
            b.pack(side="left", padx=3)
            if hint_text:
                Tooltip(b, hint_text)
            return b

        ab(btns, "Сохранить конфиг", self._save_cfg_user,
           "Записать все настройки в transfer_config.json")
        self.b_plan = ab(btns, "План", lambda: self._run(['--plan']),
           "Показать что будет делать прогон (без изменений).")
        self.b_dry = ab(btns, "Dry-run всего", lambda: self._run(['--dry-run']),
           "Прогнать ВСЕ этапы без записи. Смотри журнал — что перенесётся.")
        # 19.09: пересчёт маппинга под текущую пару карт
        self.b_remap = ab(btns, "Переписать маппинг", lambda: self._run(['--remap']),
           "Пересчитать реестр занятых ID приёмника и маппинг\nпод ТЕКУЩУЮ пару карт. Запускай после смены\nисточника/приёмника — иначе маппинг останется\nот старой карты (риск коллизий ID).")

        # 22.10 (рефактор A): вторая строка — боевые команды и донорные
        # под-операции («Перенос триггеров», TestSpawn): они берут донора
        # из поля «Карта-донор», потому живут на вкладке Перенос
        btns2 = ctk.CTkFrame(tab_t, fg_color="transparent")
        btns2.pack(fill="x", padx=10, pady=(0, 4))
        self.b_run = ab(btns2, "ЗАПУСК (запись!)", self._run_all,
           "Боевой прогон с записью в приёмник. Снапшоты делаются автоматически,\nоткат — кнопка «Откат».", color='danger', w=170)
        self.b_loop = ab(btns2, "Полный цикл (повторы)", self._run_loop,
           "deps->mapping->tables->import->code_cut повторами, пока код находит\nновые дамми (макс 5 итераций). Для переноса героев из монолита.", color='ok', w=150)
        self.b_status = ab(btns2, "Статус", lambda: self._run(['--status']),
           "Какие этапы уже пройдены (state).")
        self.b_rollback = ab(btns2, "Откат", lambda: self._run(['--rollback']),
           "Восстановить файлы из снапшота последнего этапа.")
        self.b_reset = ab(btns2, "Сброс прогресса", lambda: self._run(['--reset']),
           "Сбросить список пройденных этапов (state).\nНужен после смены пары карт или для повторного прогона.\nState также сбрасывается АВТОМАТИЧЕСКИ при смене source/target.")
        # 22.10 (рефактор A): перенос триггеров и TestSpawn — донорные
        # операции, переехали с вкладки Обслуживание в строку переноса
        self.b_triggers = ab(btns2, "Триггеры...", self._triggers_window,
           "Отдельный перенос триггеров: выбрать подпапки\n(героев/системы) и перенести только их.\nЗапись по правилу v4: папки в корень trigger/.")
        self.b_tspawn = ab(btns2, "TestSpawn .j", lambda: self._run(['--stage', 'testspawn']),
           "Генерирует 90-TestSpawn.j: спавн перенесённых героев\n(точка из поля «Точка спавна», по умолчанию центр карты 0,0).\nВызов в игре: call ExecuteFunc(\"TestSpawn__I\").")

        # 22.10 (рефактор A): вторая строка — боевые команды и донорные
        # под-операции («Перенос триггеров», TestSpawn), они берут донора
        # из поля «Карта-донор» и потому живут на вкладке Перенос
        btns2 = ctk.CTkFrame(tab_t, fg_color="transparent")
        btns2.pack(fill="x", padx=10, pady=(0, 4))
        self.b_manifest = ab_svc('Отчёты и прочее', "Манифест", self._manifest,
           "Отчёт о переносе в mdlog/transfer/ (что перенесено, конфликты ID).")
        self.b_verify = ab_svc('Проверка и чистка', "Верификация", self._verify_only,
           "Только проверка приёмника БЕЗ переноса: битые ссылки,\nдубли секций, циклы _parent, imp.ini, баланс скобок .j.\nБезопасно — ничего не пишет в карту.", color='ok')
        self.b_cleanup = ab_svc('Проверка и чистка', "Чистка объектов...", self._cleanup_window,
           "Чистка карты: неиспользуемые объекты, битые равкоды,\nнеудаляемые способности (по суффиксу/равкоду).\n19.09: расстановка карты (war3map.doo/Units.doo) читается —\nюниты/декорации на карте не удаляются.\nСкан -> список -> подтверждение -> удаление. Никаких молчаливых удалений.")
        self.b_repair = ab_svc('Проверка и чистка', "Починить таблицы", self._repair_main,
           "Починка таблиц ПРИЁМНИКА (table/*.ini): self-parent,\nбитые _parent, дубли секций, разбаланс [=[ ]=],\n19.09: экранирование строк текста с [ вне блока,\nудаление обрывков описаний.\nПервый клик = скан, второй = починка (бэкап + лог).")
        # 22.10 (рефактор A): «Триггеры...» и «TestSpawn .j» переехали
        # в строку кнопок переноса (вкладка Перенос) — они донорные
        self.b_trigclean = ab_svc('Проверка и чистка', "Чистка триггеров...", self._trigclean_window,
           "Чистка триггеров карты: пустые папки, отключённые/\nзакрытые триггеры, неиспользуемые глобалки,\nмёртвые функции. Скан -> список -> подтверждение -> удаление.")
        self.b_rawconv = ab_svc('Триггеры и код', "Конверт равкодов...", self._rawconv_window,
           "Разовый конверт 0xXXXXXXXX -> 'RAWC' (base-256) в скрипте карты.\nВход: файл .j или папка карты (ищет map/war3map.j, war3map.j,\ntrigger/code.j). Скан -> конверт (бэкап + лог замен).")
        self.b_deob = ab_svc('Триггеры и код', "Деобфускация имён...", self._deob_window,
           "Переименование обфусцированных идентификаторов (I/J/1, короткие\nВЕРХНИЕ) в читаемые по типам/семантике + восстановление\nформатирования. VERIFY: OK = токен-эквивалентность.\nВыход: <имя>_deobfuscated.j + rename_map.csv (карта переименований).")
        # 22.10 (рефактор A): TestSpawn переехал в строку кнопок переноса
        ab_svc('Отчёты и прочее', "Открыть папку", lambda: os.startfile(HERE))

        # 22.10 (рефактор A): единые списки кнопок для _apply_mode —
        # добавление новой кнопки не требует правки режима вручную
        self._donor_btns = [self.b_plan, self.b_dry, self.b_remap, self.b_run,
                            self.b_loop, self.b_status, self.b_rollback,
                            self.b_reset, self.b_triggers, self.b_tspawn,
                            self.b_geom, self.b_geom_dry]
        self._svc_btns = [self.b_verify, self.b_cleanup, self.b_repair,
                          self.b_trigclean, self.b_rawconv]

        # --- статусбар ---
        # 22.10 (UI): перенесён выше вкладок (до них по порядку паковки).

        # --- прогресс-лента + журнал: вкладка «Журнал» ---
        # 20.09: до журнала — не выдавливается
        pf, pi = self._card(tab_j, "Прогресс (state)")
        pf.pack(fill="x", padx=10, pady=(4, 4))
        row = ctk.CTkFrame(pi, fg_color="transparent")
        row.pack(fill="x")
        btns2 = ctk.CTkFrame(row, fg_color="transparent")
        btns2.pack(side="right")
        ctk.CTkButton(btns2, text="Обновить", width=80, height=26,
                      command=self._refresh_progress).pack(side="left", padx=1)
        ctk.CTkButton(btns2, text="Сброс", width=60, height=26,
                      command=lambda: self._run(['--reset'])).pack(side="left", padx=1)
        ctk.CTkButton(btns2, text="Журнал", width=70, height=26,
                      command=self._open_log).pack(side="left", padx=1)
        ctk.CTkButton(btns2, text="Манифест", width=80, height=26,
                      command=self._open_manifest).pack(side="left", padx=1)
        self.prog_labels = {}
        for s in STAGES:
            lbl = ctk.CTkLabel(row, text=" " + SHORT.get(s, STAGE_LABELS[s]) + " ",
                               font=("Segoe UI", 10), corner_radius=10,
                               fg_color=("gray88", "gray18"),
                               text_color=("gray35", "gray62"))
            lbl.pack(side="left", padx=1)
            self.prog_labels[s] = lbl
        Tooltip(pf, "Прогресс привязан к паре карт: смена источника/приёмника\nавтоматически сбрасывает список пройденных этапов.\nНесколько конфигов = независимые прогоны (свой state у каждого).")

        # --- журнал (22.10 (UI): вкладка «Журнал» — во всю высоту) ---
        lf, li = self._card(tab_j, "Журнал")
        lf.pack(fill="both", expand=True, padx=10, pady=4)
        lbar = ctk.CTkFrame(li, fg_color="transparent")
        lbar.pack(fill="x")
        ctk.CTkLabel(lbar, text="Поиск:", font=FONT_SMALL).pack(side="left", padx=(0, 2))
        self.e_find = ctk.CTkEntry(lbar, width=220, height=26, font=FONT_SMALL)
        self.e_find.pack(side="left")
        Tooltip(self.e_find, "Подсветить строки журнала (Enter). Esc — сброс.")
        self.e_find.bind("<Return>", self._log_find)
        self.e_find.bind("<Escape>", lambda e: self._log_find_clear())
        ctk.CTkButton(lbar, text="Очистить", width=80, height=26,
                      command=lambda: self.log.delete("1.0", "end")).pack(side="left", padx=4)
        ctk.CTkButton(lbar, text="Копировать всё", width=110, height=26,
                      command=self._log_copy).pack(side="left", padx=2)
        ctk.CTkButton(lbar, text="А-", width=30, height=26,
                      command=lambda: self._log_font(-1)).pack(side="left", padx=(8, 1))
        ctk.CTkButton(lbar, text="А+", width=30, height=26,
                      command=lambda: self._log_font(1)).pack(side="left", padx=1)

        log_wrap = ctk.CTkFrame(li, fg_color="transparent")
        log_wrap.pack(fill="both", expand=True)
        dark = APPEARANCE == 'dark'
        # 22.10 (B): журнал переведён на CTkTextbox — внешний вид в общей
        # теме, встроенный скроллбар, автоскролл с уважением к прокрутке
        self.log = ctk.CTkTextbox(log_wrap, height=9, wrap="word", font=FONT_MONO,
                                  fg_color="#12151a" if dark else "#1e1e1e",
                                  text_color="#c8d0da" if dark else "#d4d4d4",
                                  border_width=0, corner_radius=8)
        self.log.pack(side="left", fill="both", expand=True)
        # делегирование методов tk.Text, которые не обёрнуты в CTkTextbox
        tb = self.log._textbox
        tb.configure(insertbackground="#e8edf4" if dark else "#ffffff",
                     selectbackground=ACCENT, selectforeground="#ffffff")
        self.log.search = tb.search
        self.log.tag_configure = self.log.tag_config
        self.log.tag_configure("err", foreground="#ff6b6b")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("warn", foreground="#e6a23c")
        self.log.tag_configure("found", background="#5a5a2e")
        # 22.10 (B): «следить» = автоскролл, только если пользователь стоит
        # у низа журнала; прокрутил вверх — вывод не уводит просмотр
        self._log_follow = True
        self.log.bind('<Configure>', lambda e: self._log_track_follow())
        self.log._textbox.bind('<MouseWheel>', lambda e: self.after(10, self._log_track_follow), add='+')
        self.log._textbox.bind('<Button-4>', lambda e: self.after(10, self._log_track_follow), add='+')
        self.log._textbox.bind('<Button-5>', lambda e: self.after(10, self._log_track_follow), add='+')
        self.log._textbox.bind('<KeyPress>', lambda e: self.after(10, self._log_track_follow), add='+')

        # --- прогресс-лента ---
        # 20.09: старые статусбар и прогресс-лента отсюда УДАЛЕНЫ —
        # переехали выше (до журнала), см. «статусбар» и «прогресс-лента».

    # --- строки ввода с кнопкой выбора папки ---

    def _hist(self, key):
        """22.10 (UI): история путей из конфига (gui.path_history)."""
        hh = self.cfg.setdefault('gui', {}).setdefault('path_history', {})
        v = hh.get(key)
        return list(v) if isinstance(v, list) else []

    def _bind_cfg_path(self, entry, section, key):
        """22.10: live-синхронизация поля пути подокна с конфигом.
        Фокус уводится / клавиша отпущена / поле стёрто: значение сразу
        в конфиг; пустое поле УДАЛЯЕТ ключ (операция возьмёт дефолт).
        Запись с задержкой (debounce), чтобы не перезаписывать файл
        на каждом нажатии клавиши."""
        def _apply():
            try:
                v = entry.get().strip()
                c = self.cfg.setdefault(section, {})
                if v:
                    if c.get(key) != v:
                        c[key] = v
                        self._save_cfg()
                elif key in c:
                    c.pop(key, None)
                    self._save_cfg()
            except Exception as e:
                # 22.10: раньше проглатывалось молча — правки пути терялись
                self._log('правка пути не сохранена: %s' % e, 'err')
        self._path_save_job = None

        def _sched(event=None):
            if self._path_save_job is not None:
                try:
                    self.after_cancel(self._path_save_job)
                except Exception:
                    pass
            self._path_save_job = self.after(600, _apply)
        entry.bind('<FocusOut>', lambda event=None: _apply())   # уход из поля: сразу
        entry.bind('<KeyRelease>', lambda event=None: _sched()) # набор: с задержкой
        # 22.10: ссылка на обработчик: прямая проверка семантики в тестах
        entry._cfg_path_apply = _apply
        return _apply

    def _remember_path(self, key, value):
        """22.10 (UI): запомнить путь в историю (до 10, свежие сверху).
        Хранится любой существующий путь: папки и файлы (.j у деоба)."""
        value = value.strip()
        if not value or not os.path.exists(value):
            return
        hh = self.cfg.setdefault('gui', {}).setdefault('path_history', {})
        hist = [v for v in (hh.get(key) or [])
                if os.path.normcase(v) != os.path.normcase(value)]
        hist.insert(0, value)
        hh[key] = hist[:10]
        try:
            self._save_cfg()
        except Exception as e:
            # 22.10: история путей важна молча не бывает — сбой сохранения
            # показываем (сам _save_cfg тоже логирует)
            self._log('история путей не сохранена: %s' % e, 'err')

    def _add_hist(self, entry, key):
        """22.10 (UI): кнопка ▾ рядом с полем — выпадающий список последних
        путей. Работает в любом окне: <entry>.get()/insert() не меняются.
        Вкладываем ПОСЛЕ кнопки «...» (pack аддитивный)."""
        b = ctk.CTkButton(entry.master, text='▾', width=30, height=30,
                          font=FONT_SMALL)
        b.pack(side='left', padx=(0, 3))
        def _menu():
            vals = []
            for v in [entry.get().strip()] + self._hist(key):
                v = v.strip()
                if v and os.path.exists(v) and not any(
                        os.path.normcase(v) == os.path.normcase(w) for w in vals):
                    vals.append(v)
            if not vals:
                return
            m = tk.Menu(b, tearoff=0)
            for v in vals:
                def setv(p=v):
                    entry.delete(0, 'end')
                    entry.insert(0, p)
                m.add_command(label=v, command=setv)
            try:
                m.post(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
            except Exception:
                pass
        b.configure(command=_menu)
        return b

    def _path_row(self, parent, label, hint_text, key=None):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=150, anchor="w",
                     font=FONT_SMALL).pack(side="left")
        e = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e.pack(side="left", fill="x", expand=True, padx=6)
        if hint_text:
            Tooltip(e, hint_text)
        ctk.CTkButton(row, text="...", width=36, height=30,
                      command=lambda: self._pick(e, key)).pack(side="left")
        if key:
            self._add_hist(e, key)
        return e

    def _text_row(self, parent, label, hint_text):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=150, anchor="w",
                     font=FONT_SMALL).pack(side="left")
        e = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e.pack(side="left", fill="x", expand=True, padx=6)
        if hint_text:
            Tooltip(e, hint_text)
        return e

    # ---------- тема ----------

    def _toggle_theme(self, value):
        # 20.10: сегмент теперь с русскими подписями — переводим в light/dark
        value = self.THEME_RU.get(value, value)
        global APPEARANCE
        APPEARANCE = value
        ctk.set_appearance_mode(value)
        self.cfg.setdefault('gui', {})['theme'] = value
        try:
            io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        except Exception:
            pass
        self._apply_log_theme()

    def _apply_log_theme(self):
        dark = ctk.get_appearance_mode().lower() == 'dark'
        # 22.10 (B): CTkTextbox — цвета через CTk-атрибуты
        self.log.configure(
            fg_color="#12151a" if dark else "#1e1e1e",
            text_color="#c8d0da" if dark else "#d4d4d4")
        self.log._textbox.configure(
            insertbackground="#e8edf4" if dark else "#ffffff")

    # ---------- прогресс ----------

    def _refresh_progress(self):
        try:
            # 20.10 (аудит): state-файл читаем ИЗ КОНФИГА (safety.state_file)
            # и рядом с конфигом — мультиконфиг и нестандартные имена
            st_name = self.cfg.get('safety', {}).get('state_file', 'transfer_state.json')
            sp = os.path.join(os.path.dirname(self._cfg_path()), st_name)
            done = set()
            if os.path.exists(sp):
                st = json.load(io.open(sp, 'rb'))
                pair = (self.e_src.get().strip() + '->' + self.e_tgt.get().strip())
                if st.get('pair') == pair:
                    done = set(st.get('completed', []))
            dark = ctk.get_appearance_mode().lower() == 'dark'
            for s, lbl in self.prog_labels.items():
                if s in done:
                    lbl.configure(fg_color="#1d3a28" if dark else "#d9f0e2",
                                  text_color="#7ee787" if dark else "#14663a")
                else:
                    lbl.configure(fg_color="gray20" if dark else "gray85",
                                  text_color="gray60" if dark else "gray40")
        except Exception:
            pass

    # ---------- журнал ----------

    def _log_find(self, event=None):
        self._log_find_clear()
        q = self.e_find.get().strip().lower()
        if not q:
            return
        idx = self.log.index('1.0')
        while True:
            pos = self.log.search(q, idx, stopindex='end', nocase=True)
            if not pos:
                break
            end = '%s+%dc' % (pos, len(q))
            self.log.tag_add('found', pos, end)
            idx = end
        self.log.see('1.0')

    def _log_find_clear(self):
        self.log.tag_remove('found', '1.0', 'end')

    def _log_copy(self):
        txt = self.log.get('1.0', 'end').strip()
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.status.configure(text='журнал скопирован в буфер (%d символов)' % len(txt))

    def _log_font(self, delta):
        self.log_size = max(7, min(16, self.log_size + delta))
        self.log.configure(font=('Consolas', self.log_size))

    def _log_path(self):
        # 20.10 (аудит): журнал на конфиг — согласовано с transfer_run.log()
        # (дефолтный конфиг -> transfer.log; остальные -> <имя конфига>.log)
        stem = os.path.splitext(os.path.basename(self._cfg_path()))[0]
        return os.path.join(os.path.dirname(self._cfg_path()), 'logs',
                            'transfer.log' if stem == 'transfer_config' else stem + '.log')

    def _open_log(self):
        p = self._log_path()
        if os.path.exists(p):
            try:
                os.startfile(p)
            except Exception as e:
                # 22.10: сбой startfile под pythonw умирал молча
                self._log('не удалось открыть журнал: %s' % e, 'err')
        else:
            messagebox.showinfo('Журнал', 'Журнала пока нет — запусти прогон.')

    def _open_manifest(self):
        # 20.10 (аудит): манифесты ищем в папке КОНФИГА, не общего HERE
        import glob as _g
        d = os.path.join(os.path.dirname(self._cfg_path()), 'logs')
        fs = sorted(_g.glob(os.path.join(d, 'transfer-manifest-*.md')))
        if fs:
            try:
                os.startfile(fs[-1])
            except Exception as e:
                self._log('не удалось открыть манифест: %s' % e, 'err')
        else:
            messagebox.showinfo('Манифест', 'Манифестов пока нет — запусти перенос.')

    # ---------- логика (1-в-1 со старым GUI) ----------

    def _pick(self, entry, key=None):
        d = filedialog.askdirectory()
        if d:
            entry.delete(0, 'end')
            entry.insert(0, d)
            # 22.10 (UI): выбранный путь попадает в историю
            if key:
                self._remember_path(key, d)

    def _log(self, msg, tag=None, scope=None):
        # 19.09 (вечер): scope='transfer' — сообщения переноса;
        # в режиме Обслуживание они НЕ показываются в журнале
        self.q.put((msg, tag, scope))

    # ---------- 22.10: toast-уведомления и звуки событий ----------

    def _toast(self, text, kind='info'):
        """Компактное уведомление в правом НИЖНЕМ углу главного окна
        (не перекрывает шапку и прогресс вверху). Само исчезает через
        несколько секунд, закрывается кликом. Несколько подряд тостов
        складываются стеком вверх. kind: ok|err|info.
        Thread-safe: вызывать ТОЛЬКО из главного потока — события из
        рабочих потоков идут через очередь маркером '__toast__|kind|text'
        (см. _poll_log, тот же канал, что вывод этапов)."""
        if not getattr(self, 'v_toast', None) or not self.v_toast.get():
            return
        try:
            text = str(text).strip() or '...'
            bg = {'ok': OKGREEN, 'err': DANGER, 'info': "#2b2f36"}.get(kind, "#2b2f36")
            dur = 6.0 if kind == 'err' else 3.5   # ошибки висят дольше
            win = tk.Toplevel(self)
            win.withdraw()
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            fr = tk.Frame(win, bg=bg, padx=12, pady=9)
            fr.pack()
            lbl = tk.Label(fr, text=text, bg=bg, fg="#ffffff",
                           wraplength=280, justify="left",
                           font=("Segoe UI", 10))
            lbl.pack()
            win.update_idletasks()
            w = min(max(win.winfo_reqwidth(), 210), 330)
            h = win.winfo_reqheight()
            x = max(0, self.winfo_rootx() + self.winfo_width() - w - 14)
            # 46 — над строкой статуса/прогресса
            base_y = max(0, self.winfo_rooty() + self.winfo_height() - h - 46)
            toasts = getattr(self, '_toasts', None)
            if toasts is None:
                toasts = self._toasts = []
            y = base_y - len(toasts) * (h + 6)
            win.geometry('%dx%d+%d+%d' % (w, h, x, y))
            win.deiconify()
            # закрытие по клику
            for wdg in (fr, lbl):
                wdg.bind('<Button-1>', lambda e, wn=win: self._toast_close(wn))
            win.bind('<Button-1>', lambda e: self._toast_close(win))
            job = win.after(int(dur * 1000),
                            lambda wn=win: self._toast_close(wn))
            toasts.append({'win': win, 'h': h, 'x': x, 'base_y': base_y})
            self._toast_tracks = getattr(self, '_toast_tracks', {})
            self._toast_tracks[win] = job
        except Exception:
            pass   # сбой тоста не должен трогать mainloop

    def _toast_close(self, win, job=None):
        if job is None:
            job = getattr(self, '_toast_tracks', {}).get(win)
        if win in getattr(self, '_toast_tracks', {}):
            try:
                win.after_cancel(self._toast_tracks[win])
            except Exception:
                pass
            self._toast_tracks.pop(win, None)
        try:
            win.destroy()
        except Exception:
            pass
        if win in [t['win'] for t in getattr(self, '_toasts', [])]:
            self._toasts = [t for t in self._toasts if t['win'] is not win]
            self._toast_restagger()

    def _toast_restagger(self):
        """Позади закрывшегося тоста сдвигаем стек вниз на его место."""
        toasts = getattr(self, '_toasts', [])
        if not toasts:
            return
        off = 0
        for t in toasts:
            try:
                yy = t['base_y'] - off
                t['win'].geometry('+%d+%d' % (t['x'], yy))
                off += t['h'] + 6
            except Exception:
                pass

    def _play_sound(self, kind):
        """Системные звуки Windows без .wav-файлов (MessageBeep — системный
        звук, играется асинхронно, mainloop не блокирует). kind: ok|err|info.
        info не озвучивается (нейтральные тосты тихие)."""
        if not getattr(self, 'v_sounds', None) or not self.v_sounds.get():
            return
        try:
            import winsound
            mb = {'ok': winsound.MB_ICONASTERISK,
                  'err': winsound.MB_ICONHAND}.get(kind)
            if mb is not None:
                winsound.MessageBeep(mb)
        except Exception as e:
            self._log('звук недоступен: %s' % e, 'warn')

    def _save_cfg_user(self):
        """22.10: ЯВНОЕ сохранение (Ctrl+S / кнопка «Сохранить конфиг») —
        с уведомлением. Фоновые _save_cfg (старт прогона, поля путей)
        тостом не спамят: сбой виден в журнале и тостом ошибки."""
        try:
            self._save_cfg()
            self._toast('Настройки сохранены', 'info')
        except Exception as e:
            self._log('Сохранение конфига не удалось: %s' % e, 'err')
            self._toast('Сохранение не удалось: %s' % e, 'err')

    def report_callback_exception(self, exc, val, tb):
        """22.10: НИКАКИХ молчаливых смертей коллбэков tkinter. Прежде
        исключение в GUI-команде уходило в stderr под pythonw (его нет),
        и кнопка «молча» ничего не делала. Теперь сбой попадает в журнал
        и в красный тост."""
        import traceback
        try:
            self._log('ОШИБКА GUI: %s' %
                      ''.join(traceback.format_exception(exc, val, tb))[:600],
                      'err')
            self._toast('Ошибка интерфейса: %s' % val, 'err')
        except Exception:
            pass

    def _poll_log(self):
        while not self.q.empty():
            item = self.q.get()
            # 19.09 (вечер): очередь (msg, tag, scope) —
            # старые 2-элементные записи совместимы
            if len(item) == 3:
                msg, tag, scope = item
            else:
                msg, tag = item
                scope = None
            # 22.10: toast-события из рабочих потоков через ту же очередь
            # (tkinter из потока трогать нельзя) — маркер __toast__|kind|text
            if msg.startswith('__toast__|'):
                try:
                    _, kind, text = msg.split('|', 2)
                except ValueError:
                    kind, text = 'info', msg
                self._toast(text, kind)
                if kind == 'err':
                    self._run_failed = True
                    self._play_sound('err')
                continue
            if msg == '__refresh__':
                # 20.10 (аудит): чипы прогресса — после каждого этапа
                self._refresh_progress()
                continue
            if msg == '__done__':
                self.running = False
                self.b_stop.configure(state='disabled')
                self.status.configure(text='готов')
                self._refresh_head_status()   # 20.10 (аудит): баннер режима восстанавливается
                # 20.09: прогресс-бар — завершение
                self.pbar.set(1)
                self.pct_lbl.configure(text='100%')
                self.after(2500, lambda: (self.pbar.set(0), self.pct_lbl.configure(text='')))
                self._refresh_progress()
                # 22.10: итог прогона — зелёный тост + звук успеха, если
                # ни один этап не упал; звук только у ПОЛНЫХ прогонов
                # (--all/--dry-run/--loop/--stage), одиночные команды
                # (--status/--reset/...) не озвучиваются и не тостят
                run_ok = not getattr(self, '_run_failed', False)
                self._run_failed = False
                if run_ok and getattr(self, '_full_run', False):
                    self._toast('Прогон завершён успешно', 'ok')
                    if self.v_sound.get():
                        self._play_sound('ok')
                if self.v_autolog.get():
                    try:
                        self._open_log()
                    except Exception:
                        pass
                continue
            # 19.09 (вечер): фильтр по режиму —
            # transfer-сообщения не показываются
            # в режиме Обслуживание
            if scope == 'transfer':
                try:
                    if self.mode_seg.get() == 'Обслуживание':
                        continue
                except Exception:
                    pass
            # 21.10 (аудит): машинные маркеры прогресса. Раньше парсились
            # русские строки — любая правка формулировки ломала полоску.
            if msg.startswith('@@'):
                try:
                    if msg.startswith('@@PROGRESS '):
                        self._pb_total = int(msg.split()[1])
                        self._pb_done = 0
                        self.pbar.set(0)
                        self.pct_lbl.configure(text='0%')
                    elif msg.startswith('@@STAGE '):
                        # 21.10: имя текущего этапа — для статуса пульса
                        self._cur_stage = msg.split(' ', 1)[1].strip()
                        if getattr(self, '_pb_total', 0):
                            self._pb_done += 1
                            frac = min(self._pb_done, self._pb_total) / self._pb_total
                            self.pbar.set(frac)
                            self.pct_lbl.configure(text='%d%%' % round(frac * 100))
                    elif msg.startswith('@@TICK '):
                        # 21.10: пульс длинного этапа — полоска не двигается
                        # (этапы считает оркестратор), но в статусе видно,
                        # что прогон жив и сколько уже идёт этап.
                        try:
                            sec = int(msg.split()[1])
                        except (IndexError, ValueError):
                            sec = 0
                        self.status.configure(
                            text='этап %s идёт %d сек...' %
                                 (getattr(self, '_cur_stage', '?'), sec))
                except Exception:
                    pass
                continue
            self.log.insert('end', msg + '\n', tag or ())
            # 22.10 (B): автоскролл — только когда пользователь у низа
            try:
                if self._log_follow:
                    self.log.see('end')
            except Exception:
                pass
        self.after(100, self._poll_log)

    def _log_track_follow(self):
        """22.10 (B): обновить флаг автоскролла: у низа = следим."""
        try:
            self._log_follow = self.log.yview()[1] > 0.998
        except Exception:
            pass

    # 22.10: пресеты настроек
    def _preset_desc(self, name=None):
        """Обновить описание пресета при смене выбора в списке."""
        p = PRESETS.get(self.preset_box.get())
        if p:
            self.preset_desc.configure(text=p['desc'])

    def _apply_preset(self):
        """Пресет: этапы, таблицы, галочки. Dry-run и ID героев
        не трогаются (решения остаются на пользователе)."""
        p = PRESETS.get(self.preset_box.get())
        if not p:
            return
        st = p['stages']
        for s in STAGES:
            self.stage_vars[s].set(bool(st.get(s, False)))
        if p['tables'] is not None:
            self.e_tables.delete(0, 'end')
            self.e_tables.insert(0, p['tables'])
        if p['roots'] is not None:
            self.e_roots.delete(0, 'end')
            if p['roots']:
                self.e_roots.insert(0, p['roots'])
        # 22.10: флаг обновления существующих секций — режим ремонта,
        # пресет снимает его (v_tupd, cfg->tables_update_existing)
        self.v_tupd.set(bool(p.get('tupd', False)))
        self._log('пресет применён: ' + self.preset_box.get(), 'ok')

    def _collect_cfg(self):
        cfg = self.cfg
        # 20.10 (аудит): гарантированные секции — на свежем/старом конфиге
        # без них _collect_cfg падал KeyError до старта любой кнопки
        for k in ('geometry', 'testspawn', 'import', 'code', 'safety', 'gui'):
            cfg.setdefault(k, {})
        cfg['source'] = self.e_src.get().strip()
        cfg['target'] = self.e_tgt.get().strip()
        cfg['name'] = self.e_name.get().strip()
        cfg['tables'] = [t.strip() for t in self.e_tables.get().split(',') if t.strip()]
        cfg['skip_tables'] = [t.strip() for t in self.e_skip.get().split(',') if t.strip()]
        # 21.10: галочка обновления существующих секций
        cfg['tables_update_existing'] = bool(self.v_tupd.get())
        # 21.10: лимит этапа (минуты, 0 = без лимита)
        try:
            cfg.setdefault('safety', {})['stage_timeout_min'] = \
                max(0.0, float(self.e_tmo.get().replace(',', '.') or 15))
        except ValueError:
            pass
        # 21.10: секции import/code больше не расходятся с галочками этапов
        cfg['import']['enabled'] = bool(self.stage_vars['import'].get())
        cfg['code']['enabled'] = bool(self.stage_vars['code'].get())
        cfg.setdefault('deps', {})['roots'] = [t.strip() for t in self.e_roots.get().split(',') if t.strip()]
        cfg.setdefault('mapping', {})['mode'] = self.mode_var.get()
        cfg['geometry']['enabled'] = self.v_geom.get()
        try:
            dx = float(self.e_dx.get() or 0)
            dy = float(self.e_dy.get() or 0)
        except ValueError:
            dx = dy = 0.0
        cfg['geometry']['offset'] = [dx, dy] if (dx or dy) else None
        # 22.10: пересчёт высоты по рельефу приёмника (конфиг↔UI вместе)
        cfg['geometry']['recount_z'] = self.v_recz.get()
        # 22.10: разделение категорий (декор/юниты); обе галочки = секция
        # types не пишем — этап переносит оба типа как раньше
        if self.v_decor.get() and self.v_units.get():
            cfg['geometry'].pop('types', None)
        else:
            cfg['geometry']['types'] = {'decor': self.v_decor.get(),
                                        'units': self.v_units.get()}
        # 22.10: ландшафт (w3e); force в конфиге вручную (предохранитель)
        if self.v_w3e.get():
            cfg['geometry']['w3e'] = {'enabled': True,
                                      'force': bool(self.cfg.get('geometry', {})
                                                    .get('w3e', {}).get('force', False))}
        else:
            cfg['geometry'].pop('w3e', None)
        cfg['testspawn']['enabled'] = self.v_ts.get()
        cfg['testspawn']['heroes'] = [t.strip() for t in self.e_ts.get().split(',') if t.strip()]
        # 22.09: точка спавна — 'center' (0,0) или имя региона; конфиг↔UI вместе
        cfg['testspawn']['rect'] = self.e_tsrect.get().strip() or 'center'
        cfg['import']['exclude_paths'] = [l.strip() for l in self.t_excl.get('1.0', 'end').splitlines() if l.strip()]
        # 20.09: перехват игровых моделей — конфиг↔UI вместе
        cfg['import']['allow_override'] = self.v_override.get()
        cfg.setdefault('code_cut', {})['auto_expand'] = self.v_aexp.get()
        cfg['safety']['stop_on_error'] = self.v_stop.get()
        cfg.setdefault('code', {})['allow_b'] = self.v_allowb.get()
        # 18.09 (v5): шапка донора + префикс функций
        cfg['code']['header_mode'] = 'append' if self.header_seg.get() == 'в шапку приёмника' else 'file'
        cfg['code']['func_prefix'] = self.e_prefix.get().strip() if self.v_prefix.get() else ''
        # 19.09 (v6): deploy_to + каталог + монолит
        dep = self.e_deploy.get().strip()
        if dep:
            cfg['code']['deploy_to'] = dep
        # 22.10: набор выбора (JSON): путь в конфиг либо автопуть
        sf = self.e_setfile.get().strip()
        if sf:
            cfg.setdefault('selection', {})['file'] = sf
        else:
            cfg.get('selection', {}).pop('file', None)
        # 20.10 (аудит): round-trip галочки каталога — писали None (=True
        # по умолчанию), эффекта «выключить и перезапустить» не было
        cfg['code']['update_catalog'] = bool(self.v_updcatalog.get())
        cfg['code']['include_monolith'] = self.v_monolith.get()
        # 20.10: раскладка папок триггеров — конфиг↔UI вместе
        cfg['code']['folders'] = 'folders' if \
            self.folders_seg.get() == 'Папки как у донора' else 'flat'
        # 21.09: null-конверт битых gg_unit — конфиг↔UI вместе
        cfg.setdefault('code', {})['null_broken_gguits'] = self.v_ggnul.get()
        cfg.setdefault('gui', {})['sound_on_done'] = self.v_sound.get()
        # 22.10: toast и звуки событий — конфиг↔UI вместе
        cfg.setdefault('gui', {})['toast'] = bool(self.v_toast.get())
        cfg.setdefault('gui', {})['sounds'] = bool(self.v_sounds.get())
        cfg['gui']['autolog'] = self.v_autolog.get()
        cfg['gui']['log_font'] = self.log_size
        cfg['gui']['theme'] = APPEARANCE
        try:
            cfg['gui']['geometry'] = self.geometry()
        except Exception:
            pass
        se = cfg.setdefault('stage_enabled', {})
        for s in STAGES:
            se[s] = self.stage_vars[s].get()
        # 22.10: пути Обслуживания — пустое поле убирает ключ из конфига
        # (этапы берут дефолт рядом с конфигом)
        _prow = [[('cleanup', 'log_dir'), self.e_clog],
                 [('cleanup', 'backup_dir'), self.e_cbak],
                 [('trigclean', 'log_dir'), self.e_tlog],
                 [('trigclean', 'backup_dir'), self.e_tbak],
                 [('repair', 'log_dir'), self.e_rlog],
                 [('repair', 'backup_dir'), self.e_rbak],
                 [('rawconv', 'backup_dir'), self.e_rvbak]]
        for (sec, key), ent in _prow:
            v = ent.get().strip()
            c = cfg.setdefault(sec, {})
            if v:
                c[key] = v
            else:
                c.pop(key, None)
        return cfg

    def _save_cfg(self):
        self._collect_cfg()
        try:
            io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2,
                                                ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            # 22.10: раньше сбой записи молча ронял вызов (под pythonw без
            # консоли — «кнопка не работает»). Теперь пользователь видит.
            self._log('НЕ УДАЛОСЬ записать конфиг: %s' % e, 'err')
            self._toast('Не удалось записать конфиг: %s' % e, 'err')
            raise
        # 19.09 (вечер): убран _log — «конфиг сохранён» замусоривал
        # журнал при каждом действии (5+ раз за прогон)

    def _load_cfg(self):
        if not os.path.exists(CFG):
            # 20.10 (аудит): самодостаточность — свежий клон без конфига
            # не падает: создаётся каркас по умолчанию, потенциалы пребылд
            # и пути карт пользователь вносит потом
            self.cfg = json.loads(json.dumps(DEFAULT_CFG))    # глубокая копия
            io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2,
                                                ensure_ascii=False).encode('utf-8'))
            self._log('создан конфиг по умолчанию: ' + CFG, 'ok')
        try:
            self.cfg = json.load(io.open(CFG, 'rb'))
        except Exception as e:
            # 22.10: битый JSON раньше умирал молча под pythonw. Теперь —
            # дефолтный каркас + сигнал в журнал.
            self.cfg = json.loads(json.dumps(DEFAULT_CFG))
            self._log('Конфиг не читается (%s) — работа на значениях по умолчанию. '
                      'Правь файл или перенеси его в архив: %s' % (e, CFG), 'err')
        self.e_src.delete(0, 'end'); self.e_src.insert(0, self.cfg.get('source', ''))
        self.e_tgt.delete(0, 'end'); self.e_tgt.insert(0, self.cfg.get('target', ''))
        self.e_name.delete(0, 'end'); self.e_name.insert(0, self.cfg.get('name', ''))
        self.e_tables.delete(0, 'end'); self.e_tables.insert(0, ', '.join(self.cfg.get('tables', [])))
        self.e_skip.delete(0, 'end'); self.e_skip.insert(0, ', '.join(self.cfg.get('skip_tables', [])))
        self.v_tupd.set(bool(self.cfg.get('tables_update_existing', False)))
        self.e_roots.delete(0, 'end'); self.e_roots.insert(0, ', '.join(self.cfg.get('deps', {}).get('roots', [])))
        self.mode_var.set(self.cfg.get('mapping', {}).get('mode', 'smart'))
        self.v_geom.set(self.cfg.get('geometry', {}).get('enabled', False))
        off = self.cfg.get('geometry', {}).get('offset') or [0, 0]
        self.e_dx.delete(0, 'end'); self.e_dx.insert(0, str(off[0]))
        self.e_dy.delete(0, 'end'); self.e_dy.insert(0, str(off[1]))
        # 22.10: пересчёт высоты — восстановление из конфига
        self.v_recz.set(self.cfg.get('geometry', {}).get('recount_z', True))
        # 22.10: категории — восстановление (нет секции = оба типа)
        _gt = self.cfg.get('geometry', {}).get('types', {})
        self.v_decor.set(bool(_gt.get('decor', True)))
        self.v_units.set(bool(_gt.get('units', True)))
        # 22.10: ландшафт w3e — восстановление (нет секции = выкл)
        self.v_w3e.set(bool(self.cfg.get('geometry', {}).get('w3e', {}).get('enabled', False)))
        self.v_ts.set(self.cfg.get('testspawn', {}).get('enabled', False))
        self.e_ts.delete(0, 'end'); self.e_ts.insert(0, ', '.join(self.cfg.get('testspawn', {}).get('heroes', [])))
        # 22.09: точка спавна — восстановление из конфига
        self.e_tsrect.delete(0, 'end')
        self.e_tsrect.insert(0, self.cfg.get('testspawn', {}).get('rect', 'center'))
        self.v_aexp.set(self.cfg.get('code_cut', {}).get('auto_expand', False))
        self.v_allowb.set(self.cfg.get('code', {}).get('allow_b', True))
        # 18.09 (v5): шапка донора + префикс
        hm = self.cfg.get('code', {}).get('header_mode', 'file')
        self.header_seg.set('в шапку приёмника' if hm == 'append' else 'отдельный файл')
        fp = self.cfg.get('code', {}).get('func_prefix', '')
        self.v_prefix.set(bool(fp))
        if fp:
            self.e_prefix.delete(0, 'end')
            self.e_prefix.insert(0, fp)
        # 19.09 (v6): deploy_to + каталог + монолит
        self.e_deploy.delete(0, 'end')
        self.e_deploy.insert(0, self.cfg.get('code', {}).get('deploy_to', ''))
        # 22.10: набор выбора — восстановление пути (нет = автопуть)
        self.e_setfile.delete(0, 'end')
        self.e_setfile.insert(0, self.cfg.get('selection', {}).get('file', ''))
        uc = self.cfg.get('code', {}).get('update_catalog')
        self.v_updcatalog.set(True if uc is None else bool(uc))
        self.v_monolith.set(self.cfg.get('code', {}).get('include_monolith', False))
        # 20.10: раскладка папок триггеров — восстановление из конфига
        self.folders_seg.set('Папки как у донора' if
            self.cfg.get('code', {}).get('folders', 'flat') == 'folders'
            else 'Одна папка')
        # 21.09: null-конверт битых gg_unit — восстановление из конфига
        self.v_ggnul.set(self.cfg.get('code', {}).get('null_broken_gguits', True))
        self.t_excl.delete('1.0', 'end')
        self.t_excl.insert('1.0', chr(10).join(self.cfg.get('import', {}).get('exclude_paths', [])))
        # 20.09: перехват игровых моделей — восстановление из конфига
        self.v_override.set(self.cfg.get('import', {}).get('allow_override', True))
        # 21.10: лимит этапа — восстановление из конфига
        tmo = self.cfg.get('safety', {}).get('stage_timeout_min', 15)
        self.e_tmo.delete(0, 'end')
        self.e_tmo.insert(0, ('%g' % tmo) if isinstance(tmo, (int, float)) else str(tmo))
        # 22.10: пути Обслуживания — восстановление из конфига
        for attr, sec, key in [('e_clog', 'cleanup', 'log_dir'),
                               ('e_cbak', 'cleanup', 'backup_dir'),
                               ('e_tlog', 'trigclean', 'log_dir'),
                               ('e_tbak', 'trigclean', 'backup_dir'),
                               ('e_rlog', 'repair', 'log_dir'),
                               ('e_rbak', 'repair', 'backup_dir'),
                               ('e_rvbak', 'rawconv', 'backup_dir')]:
            e = getattr(self, attr, None)
            if e is not None:
                e.delete(0, 'end')
                e.insert(0, self.cfg.get(sec, {}).get(key, ''))
        g = self.cfg.get('gui', {})
        self.v_sound.set(g.get('sound_on_done', False))
        # 22.10: toast/звуки — восстановление из конфига (по умолчанию ВКЛ)
        self.v_toast.set(bool(g.get('toast', True)))
        self.v_sounds.set(bool(g.get('sounds', True)))
        self.v_autolog.set(g.get('autolog', False))
        self.log_size = g.get('log_font', 9)
        self.log.configure(font=('Consolas', self.log_size))
        geo = g.get('geometry')
        if geo:
            try:
                # 19.09 (v7-fix): игнорировать дефолт CTk
                # 200x200 (окно закрыли до рендера) — иначе
                # замкнутый круг: 200x200 сохраняется и
                # восстанавливается, контент не влезает
                m = re.match(r'^(\d+)x(\d+)', geo)
                if m and int(m.group(1)) > 400 and int(m.group(2)) > 400:
                    # 20.10 (аудит-фикс): координаты клампятся к экрану.
                    # Сохранённое на отключённом втором мониторе окно
                    # открывалось ВНЕ видимой области — процесс работал,
                    # а GUI казался не запущенным
                    mm = re.search(r'([+-]\d+)\s*([+-]\d+)\s*$', geo)
                    if mm:
                        x, y = int(mm.group(1)), int(mm.group(2))
                        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
                        x = max(-40, min(x, sw - 320))
                        y = max(-40, min(y, sh - 320))
                        w2 = min(int(m.group(1)), sw - 40)
                        h2 = min(int(m.group(2)), sh - 90)
                        # 22.10: минимум согласован с вкладками (1000x620),
                        # старые 1180x900 зажимали малое окно
                        self.minsize(min(1000, w2), min(620, h2))
                        self.geometry('%dx%d+%d+%d' % (w2, h2, x, y))
                    else:
                        w2 = min(int(m.group(1)), self.winfo_screenwidth() - 40)
                        h2 = min(int(m.group(2)), self.winfo_screenheight() - 90)
                        self.minsize(min(1000, w2), min(620, h2))
                        self.geometry('%dx%d' % (w2, h2))
            except Exception:
                pass
        # 20.10 (аудит): выбор этапов восстанавливается из конфига —
        # раньше stage_enabled ПИСАЛОСЬ, но не читалось: галочки этапов
        # скидывались к зашитым дефолтам при каждом запуске GUI
        se = self.cfg.get('stage_enabled') or {}
        for s in STAGES:
            self.stage_vars[s].set(bool(se.get(s, s not in ('geometry', 'testspawn'))))
        self._refresh_progress()

    def _cfg_path(self):
        return CFG

    def _log_add(self, msg):
        self._log(msg)

    def _run_all(self):
        self._save_cfg()
        args = ['--all'] if not self.v_dry.get() else ['--dry-run']
        self._run(args)

    def _run_loop(self):
        self._save_cfg()
        # 20.10 (аудит): «Полный цикл» больше не игнорирует Dry-run
        args = ['--loop'] + (['--dry-run'] if self.v_dry.get() else [])
        self._run(args)

    def _verify_only(self):
        if self.running:
            messagebox.showwarning('Занято', 'Прогон уже выполняется — дождись завершения.')
            return
        self._collect_cfg()
        try:
            io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self._log('Прогон не стартовал: конфиг не записан: %s' % e, 'err')
            self._toast('Прогон не стартовал: конфиг не записан', 'err')
            return
        cmd = [sys.executable, '-u', os.path.join(HERE, 'stage_verify.py'), CFG]
        # 19.09: в режиме Обслуживания — без маппинга
        # (маппинг от чужого переноса даёт ложные
        # «нет секций в приёмнике»)
        if self.mode_seg.get() == 'Обслуживание':
            cmd.append('--no-map')
        self._log('>>> Верификация приёмника (без переноса)', 'ok')
        self.running = True
        self._full_run = False
        self._run_failed = False
        self.status.configure(text='верификация...')
        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def _manifest(self):
        self._save_cfg()
        cmd = [sys.executable, os.path.join(HERE, 'make_manifest.py'), CFG]
        self._log('>>> Манифест деплоя', 'ok')

        # 21.10: вывод стримится в журнал построчно (было: capture до
        # конца — GUI молчал, пока манифест не дочитает карту)
        def work():
            return self._run_streamed(cmd)

        def done(res):
            code = res[0] if isinstance(res, tuple) else 1
            self._log('>>> Манифест: код %d' % code, 'ok' if code == 0 else 'err')

        self._bg(work, done)

    # 22.10: пресет-сборер — считать замыкание deps от «Корни deps» и
    # записать transfer_config_set.json (include с типами; существующие
    # exclude_* сохраняются). Работает как обычный фоновый инструмент,
    # thread-safe: поток только в очередь, тосты разбирает _poll_log.
    def _set_path(self):
        fp = (self.cfg.get('selection', {}) or {}).get('file', '')
        if fp:
            return fp if os.path.isabs(fp) else os.path.join(HERE, fp)
        import transfer_set
        return transfer_set.path_for(CFG)

    def _build_selection(self):
        roots = [x.strip() for x in self.e_roots.get().split(',') if x.strip()]
        if not roots:
            self._log('сборер: впишите ID героев/объектов в «Корни deps»', 'warn')
            self._toast('сборер: поле «Корни deps» пустое', 'err')
            return
        if self.running:
            self._log('сборер: пайплайн уже работает', 'err')
            return
        self._save_cfg()
        cmd = [sys.executable, os.path.join(HERE, 'stage_deps.py'), CFG]
        self._log('>>> сборер: считаю замыкание deps (%s)' % ', '.join(roots), 'ok')

        def work():
            return self._run_streamed(cmd)

        def done(res):
            code = res[0] if isinstance(res, tuple) else 1
            if code != 0:
                self._log('сборер: deps упал (код %d) — набор не записан' % code, 'err')
                self._toast('сборер: deps упал, набор не записан', 'err')
                return
            try:
                self._selection_write()
            except Exception as e:
                self._log('сборер: набор не записан: %s' % e, 'err')
                self._toast('сборер: набор не записан: %s' % e, 'err')

        self._bg(work, done)

    def _selection_write(self):
        import transfer_set
        sp = self._set_path()
        old = {}
        if os.path.exists(sp):
            try:
                old = json.load(io.open(sp, encoding='utf-8'))
            except Exception as e:
                self._log('сборер: набор не прочитан (%s) — перезаписан' % e, 'warn')
        dp = os.path.join(HERE, 'deps_result.json')
        deps = json.load(io.open(dp, encoding='utf-8'))
        objs = deps.get('objects', {})
        inc = []
        for t, ids in sorted(objs.items()):
            for iid in sorted(ids):
                inc.append(t + ':' + iid)
        prev_inc = {str(x).strip() for x in old.get('include', []) if str(x).strip()}
        merged = sorted(set(inc) | prev_inc)
        data = {
            'include': merged,
            'exclude_objects': [str(x) for x in old.get('exclude_objects', [])],
            'exclude_triggers': [str(x) for x in old.get('exclude_triggers', [])],
        }
        io.open(sp, 'w', encoding='utf-8').write(
            json.dumps(data, ensure_ascii=False, indent=1))
        n = sum(len(v) for v in objs.values())
        self._log('сборер: %s записан — замыкание %d объектов, include %d '
                  '(исключения сохранены)' % (os.path.basename(sp), n, len(merged)), 'ok')
        self._toast('сборер: %d объектов -> %s' % (n, os.path.basename(sp)), 'ok')

    def _worker(self, cmd, scope=None):
        try:
            cmds = cmd if cmd and isinstance(cmd[0], list) else [cmd]
            for c in cmds:
                self._worker_one(c, scope)
        except Exception as e:
            self.q.put(('ОШИБКА ЗАПУСКА: %s' % e, 'err', None))
        finally:
            self.running = False
            # 20.10 (аудит): разовый перенос выбором (окно «Триггеры...»)
            # снимает only_dirs — иначе обычный прогон тихо урезался
            if self._clear_only_dirs:
                self._clear_only_dirs = False
                self.cfg.get('code', {}).pop('only_dirs', None)
                try:
                    io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2,
                                                        ensure_ascii=False).encode('utf-8'))
                except Exception as e:
                    # 22.10: было молча — сбой в конце прогона не виден
                    self.q.put(('конфиг не записан (only_dirs): %s' % e, 'err', None))
            self._proc = None
            self.q.put(('__done__', None, None))

    def _worker_one(self, cmd, scope=None):
        try:
            # 20.10 (аудит): PYTHONUTF8 — кириллица ребёнка не превращается
            # в 'replace'-мусор при отсутствии штатной переменной; консоль
            # под pythonw не мигает (CREATE_NO_WINDOW)
            env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace',
                                    env=env, creationflags=flags,
                                    cwd=HERE, bufsize=1)
            # 20.10 (аудит): ссылка для кнопки «Стоп»
            self._proc = proc
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                low = line.lower()
                tag = None
                # 20.10 (аудит): убран критерий 'код 1' — ложные покраски
                # обычных строк; код выхода красится своим тегом ниже
                if 'ошибка' in low or 'error' in low:
                    tag = 'err'
                elif 'внимание' in low or 'warning' in low:
                    tag = 'warn'
                self.q.put((line, tag, scope))
            proc.wait()
            self._proc = None
            self.q.put(('--- код выхода: %d ---' % proc.returncode,
                        'ok' if proc.returncode == 0 else 'err', scope))
            # 22.10: этап упал — красный тост + звук ошибки (маркер через
            # очередь: tkinter из рабочего потока не трогаем). Служит и для
            # verify: stage_verify при ошибках выходит не с нулём.
            if proc.returncode != 0:
                self.q.put(('__toast__|err|Этап упал с кодом %d — детали в журнале'
                            % proc.returncode, 'err', None))
            # 20.10 (аудит): чипы прогресса обновляются после КАЖДОГО этапа,
            # не только в конце прогона
            self.q.put(('__refresh__', None, None))
        except Exception as e:
            # 19.09 (вечер): 3-элементная очередь
            self.q.put(('ОШИБКА ЗАПУСКА: %s' % e, 'err', None))

    def _run(self, args):
        if self.running:
            messagebox.showwarning('Занято', 'Прогон уже выполняется — дождись завершения.')
            return
        self._collect_cfg()
        try:
            io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            # 22.10: старт прогона на несохранённом конфиге — без сигнала
            # под pythonw выглядел как «нажал и ничего не происходит»
            self._log('Прогон не стартовал: конфиг не записан: %s' % e, 'err')
            self._toast('Прогон не стартовал: конфиг не записан', 'err')
            return
        if args and isinstance(args[0], list):
            cmds = [[sys.executable, '-u', os.path.join(HERE, 'transfer_run.py')] + a for a in args]
            desc = ' -> '.join(' '.join(a) for a in args)
        else:
            cmds = [[sys.executable, '-u', os.path.join(HERE, 'transfer_run.py')] + args]
            desc = ' '.join(args)
        # 19.09 (вечер): service-команды (обслуживание) не фильтруются
        # в журнале; transfer-этапы скрыты в режиме Обслуживание
        # 20.10 (аудит): БАГ — desc уже строка; join давал ' - - v  e r i f y'
        # и scope всегда 'transfer' (service-вывод глотался в Обслуживании)
        flat = desc
        scope = 'transfer'
        for svc in ('--verify', '--cleanup', '--repair', '--triggers', '--status',
                    '--rollback', '--reset'):
            if svc in flat:
                scope = None
                break
        # 22.10: полный ли это прогон (зелёный тост и звук в конце) —
        # одиночные команды вроде --status не тостят «успех»
        self._full_run = any(k in desc for k in
                             ('--all', '--dry-run', '--loop', '--stage',
                              '--remap', '--plan'))
        self._run_failed = False
        # 20.10 (аудит): новый прогон — чистый журнал (старые сессии
        # не наслаиваются в окне; на диске история остаётся)
        self.log.delete('1.0', 'end')
        self._log('>>> Профиль: %s' % self.cfg.get('name', ''), None, scope)
        self._log('>>> ' + desc, 'ok', scope)
        self.running = True
        # 20.09: прогресс-бар — сброс на старте прогона
        self._pb_total = 0
        self._pb_done = 0
        self.pbar.set(0)
        self.pct_lbl.configure(text='')
        self.status.configure(text='выполняется: ' + desc)
        self.head_status.configure(text='выполняется...')
        self.b_stop.configure(state='normal')
        threading.Thread(target=self._worker, args=(cmds, scope), daemon=True).start()

    # ---------- окно триггеров ----------

    def _trigclean_window(self):
        """19.09: чистка триггеров — пустые папки,
        отключённые/закрытые триггеры, глобалки,
        мёртвые функции. Скан -> список -> подтверждение."""
        win = ctk.CTkToplevel(self)
        win.title('Чистка триггеров')
        # 29.09: авто-подгонка под контент (вместо жёсткой 980x700)
        def _front():
            try:
                win.lift()
                win.focus_force()
            except Exception:
                pass
        win.after(200, _front)

        top, ti = self._card(win, 'Карта')
        top.pack(fill='x', padx=8, pady=6)
        row = ctk.CTkFrame(ti, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text='Папка карты:', font=FONT_SMALL).pack(side='left')
        e_dir = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e_dir.pack(side='left', fill='x', expand=True, padx=6)
        last_dir = self.cfg.get('cleanup', {}).get('last_dir', '')
        e_dir.insert(0, last_dir if last_dir else self.e_tgt.get().strip())
        Tooltip(e_dir, 'Папка карты в lni-формате (trigger/ + catalog.lml).')
        ctk.CTkButton(row, text='...', width=36, height=30,
                      command=lambda: self._cleanup_pick(e_dir)).pack(side='left')
        # 22.10 (конф-синх): история и живой путь в конфиг (единый вид
        # с окном «Чистка карты»: тот же ключ cleanup.last_dir)
        self._add_hist(e_dir, 'map')
        self._bind_cfg_path(e_dir, 'cleanup', 'last_dir')

        opts, oi = self._card(win, 'Что чистим')
        opts.pack(fill='x', padx=8, pady=4)
        # 19.09 (вечер): галочки из конфига (persist cfg['trigclean'])
        tc = self.cfg.get('trigclean', {})
        v_dirs = tk.BooleanVar(value=tc.get('empty_dirs', True))
        v_txt = tk.BooleanVar(value=tc.get('del_empty_txt', True))
        v_dis = tk.BooleanVar(value=tc.get('disabled', True))
        v_clo = tk.BooleanVar(value=tc.get('closed', False))
        v_notes = tk.BooleanVar(value=tc.get('del_notes', False))
        v_glob = tk.BooleanVar(value=tc.get('globals', False))
        v_func = tk.BooleanVar(value=tc.get('dead_funcs', False))
        v_casc = tk.BooleanVar(value=tc.get('cascade', True))
        v_codej = tk.BooleanVar(value=tc.get('include_codej', False))
        v_com = tk.BooleanVar(value=tc.get('comments', False))
        r2b = ctk.CTkFrame(opts, fg_color="transparent"); r2b.pack(fill='x', pady=1)
        cb10 = ctk.CTkCheckBox(r2b, text='Comment-заглушки (разделители, заметки без кода)', variable=v_com,
                               font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb10.pack(side='left')
        Tooltip(cb10, 'Триггеры с флагом Comment БЕЗ .j-кода: разделители\n«--------», заметки-файлы. Триггеры с .j-кодом НЕ трогаются.\nПапки, освободившиеся после удаления, сносятся тем же прогоном.')
        # 19.09 (вечер): исключения — папки, которые не трогать
        er = ctk.CTkFrame(opts, fg_color="transparent"); er.pack(fill='x', pady=1)
        ctk.CTkLabel(er, text='Исключения (папки через запятую):', font=FONT_SMALL).pack(side='left')
        e_excl = ctk.CTkEntry(er, font=FONT_MONO, height=28)
        e_excl.pack(side='left', fill='x', expand=True, padx=(6, 0))
        excl_cfg = self.cfg.get('cleanup', {}).get('exclude_dirs', [])
        e_excl.insert(0, ', '.join(excl_cfg))
        Tooltip(e_excl, 'Имена папок (на любом уровне trigger/), которые\nНЕ трогать: ни папки, ни триггеры, ни функции.\nСохраняется в конфиг (cleanup.exclude_dirs).')
        r1 = ctk.CTkFrame(opts, fg_color="transparent"); r1.pack(fill='x', pady=1)
        cb = ctk.CTkCheckBox(r1, text='Пустые папки', variable=v_dirs, font=FONT_SMALL,
                             checkbox_width=18, checkbox_height=18); cb.pack(side='left')
        Tooltip(cb, 'Папки без файлов и с только пустыми подпапками (рекурсивно).\nЗаписи о них убираются из catalog.lml.')
        cb2 = ctk.CTkCheckBox(r1, text='удалять пустые .txt-заметки (0 байт)', variable=v_txt,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb2.pack(side='left', padx=(16, 0))
        Tooltip(cb2, 'Только ПОЛНОСТЬЮ пустые .txt. Заметки с текстом не трогаются.')
        r2 = ctk.CTkFrame(opts, fg_color="transparent"); r2.pack(fill='x', pady=1)
        cb3 = ctk.CTkCheckBox(r2, text='Отключённые триггеры (Disab)', variable=v_dis, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18); cb3.pack(side='left')
        Tooltip(cb3, 'Триггеры с флагом Disab в catalog.lml.\nТриггер, чьи функции вызываются из живого кода, НЕ удаляется (защита).')
        cb4 = ctk.CTkCheckBox(r2, text='Закрытые (Closed) — ОСТОРОЖНО!', variable=v_clo, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        cb4.pack(side='left', padx=(16, 0))
        Tooltip(cb4, 'ОПАСНО: Closed = «закрыт» в редакторе, НЕ «мёртвый»!\nВ этой карте Closed помечены ЖИВЫЕ триггеры\n(MoveRight, CodeBot и др.). Включай только если\nточно знаешь, что закрытые триггеры не нужны.')
        cb5 = ctk.CTkCheckBox(r2, text='удалять их заметки (.txt с текстом)', variable=v_notes,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb5.pack(side='left', padx=(16, 0))
        Tooltip(cb5, 'По умолчанию заметки отключённых триггеров остаются.')
        r3 = ctk.CTkFrame(opts, fg_color="transparent"); r3.pack(fill='x', pady=1)
        cb6 = ctk.CTkCheckBox(r3, text='Неиспользуемые глобалки (variable.lml)', variable=v_glob,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb6.pack(side='left')
        Tooltip(cb6, 'Переменные редактора без упоминаний udg_Имя в коде.\nvJass-глобалы внутри библиотек не трогаются.')
        r4 = ctk.CTkFrame(opts, fg_color="transparent"); r4.pack(fill='x', pady=1)
        cb7 = ctk.CTkCheckBox(r4, text='Мёртвые функции (trigger/ + корневые .j)', variable=v_func,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb7.pack(side='left')
        Tooltip(cb7, 'Функции без вызовов (включая ExecuteFunc-строки).\nmap/war3map.j (скомпилированный) не трогается.')
        cb8 = ctk.CTkCheckBox(r4, text='каскад', variable=v_casc, font=FONT_SMALL,
                              checkbox_width=18, checkbox_height=18)
        cb8.pack(side='left', padx=(16, 0))
        Tooltip(cb8, 'Функция, вызываемая только из мёртвых, тоже мёртвая.')
        cb9 = ctk.CTkCheckBox(r4, text='включая code.j (кастом-код)', variable=v_codej,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb9.pack(side='left', padx=(16, 0))
        Tooltip(cb9, 'По умолчанию code.j только как источник вызовов,\nсам не чистится.')

        lst, li = self._card(win, 'Скан (выдели строки и подтверди удаление)')
        lst.pack(fill='both', expand=True, padx=8, pady=4)
        dark = APPEARANCE == 'dark'
        style = ttk.Style(win)
        style.configure('TrigClean.Treeview', background="#181b21" if dark else "#ffffff",
                        fieldbackground="#181b21" if dark else "#ffffff",
                        foreground="#e8edf4" if dark else "#1a1a1a",
                        font=('Segoe UI', 10), rowheight=24, borderwidth=0)
        style.map('TrigClean.Treeview', background=[('selected', ACCENT)],
                  foreground=[('selected', '#ffffff')])
        style.configure('TrigClean.Treeview.Heading', font=('Segoe UI', 10, 'bold'),
                        background="#262b33" if dark else "#e3e8ef",
                        foreground="#e8edf4" if dark else "#1a1a1a", padding=(6, 4))
        tree = ttk.Treeview(li, columns=('cat', 'name', 'size', 'why'), show='headings', height=13,
                            selectmode='extended', style='TrigClean.Treeview')
        tree.heading('cat', text='Категория')
        tree.heading('name', text='Имя')
        tree.heading('size', text='Размер')
        tree.heading('why', text='Причина')
        tree.column('cat', width=170)
        tree.column('name', width=280)
        tree.column('size', width=70, anchor='e')
        tree.column('why', width=330)
        tree.pack(side='left', fill='both', expand=True, padx=4, pady=4)
        sb = ctk.CTkScrollbar(li, command=tree.yview)
        sb.pack(side='left', fill='y')
        tree.configure(yscrollcommand=sb.set)
        tree.bind('<Control-a>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])
        tree.bind('<Control-A>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill='x', padx=8, pady=(4, 2))
        btns2 = ctk.CTkFrame(win, fg_color="transparent")
        btns2.pack(fill='x', padx=8, pady=(0, 2))
        lbl = ctk.CTkLabel(btns2, text='', font=FONT_SMALL)
        lbl.pack(side='left', padx=6)
        self._trigclean_state = {'tree': tree, 'win': win, 'lbl': lbl, 'scan': None}

        b_scan = ctk.CTkButton(btns, text='1. СКАН', height=36, font=("Segoe UI", 12, "bold"),
                               command=lambda: self._trigclean_scan(e_dir, win, lbl,
                                   v_dirs, v_txt, v_dis, v_clo, v_notes, v_glob, v_func, v_casc, v_codej, v_com, e_excl))
        b_scan.pack(side='left', padx=(6, 10), pady=2)
        Tooltip(b_scan, 'ШАГ 1. Искать мусор (~1-3 мин на большую карту).\nРезультат появится в списке.')
        b_del = ctk.CTkButton(btns, text='2. УДАЛИТЬ ВЫДЕЛЕННОЕ', height=36,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=OKGREEN, hover_color=OKGREEN_H,
                              command=lambda: self._trigclean_delete(e_dir, lbl))
        b_del.pack(side='left', padx=3, pady=2)
        Tooltip(b_del, 'ШАГ 2. Удалить отмеченные строки.\nПодтверждение + бэкап (включая catalog.lml и variable.lml).')
        # 19.09 (вечер): ДЕМО — что будет удалено, без записи
        b_demo = ctk.CTkButton(btns, text='ДЕМО (без записи)', height=36,
                               font=("Segoe UI", 11),
                               fg_color=WARN, hover_color=WARN_H,
                               command=lambda: self._trigclean_delete(e_dir, lbl, dry=True))
        b_demo.pack(side='left', padx=3, pady=2)
        Tooltip(b_demo, 'ПОКАЗАТЬ что будет удалено — БЕЗ записи в карту\nи без бэкапа. Пишет лог (logs/triggers-дата-demo.md)\nи открывает его. Безопасно.')
        ctk.CTkButton(btns2, text='Выделить всё', height=30,
                      command=lambda: tree.selection_set(tree.get_children())).pack(side='left', padx=(6, 3), pady=2)
        ctk.CTkButton(btns2, text='Открыть лог', height=30,
                      command=self._cleanup_open_log).pack(side='left', padx=3)
        # 19.09: защитный список (cleanup_protect.json) — галочка
        v_prot = ctk.BooleanVar(value=self.cfg.get('cleanup', {}).get('protect', True))
        cb_prot = ctk.CTkCheckBox(btns2, text='Защитный список', variable=v_prot,
                                  font=FONT_SMALL, height=28)
        cb_prot.pack(side='left', padx=(10, 3), pady=2)
        Tooltip(cb_prot, 'НЕ помечать неиспользуемыми объекты из внешнего списка\ncleanup_protect.json (рядом с конфигом): {тип: [равкоды]}\nЖивые дамми-абилки и их баффы, которые сканер может спутать с мусором.\nФормат: {\"buff\": ["B00C", "B023"], "ability": ["A066"]}')
        self._cleanup_v_prot = v_prot
        self._fit_toplevel(win, min_w=980, min_h=700)
        return win

    def _trigclean_scan(self, e_dir, win, lbl, *vars_):
        tgt = e_dir.get().strip()
        if not os.path.isdir(tgt):
            messagebox.showwarning('Путь', 'Укажи папку карты.')
            return
        self._cleanup_remember(tgt)
        v_dirs, v_txt, v_dis, v_clo, v_notes, v_glob, v_func, v_casc, v_codej, v_com, e_excl = vars_
        # 19.09 (вечер): исключения — конфиг↔UI
        excl_raw = e_excl.get().strip()
        excl = [x.strip() for x in excl_raw.split(',') if x.strip()]
        self.cfg.setdefault('cleanup', {})['exclude_dirs'] = excl
        # 19.09 (вечер): галочки — persist в cfg['trigclean']
        self.cfg['trigclean'] = {'empty_dirs': v_dirs.get(),
                                 'del_empty_txt': v_txt.get(),
                                 'disabled': v_dis.get(),
                                 'closed': v_clo.get(),
                                 'del_notes': v_notes.get(),
                                 'globals': v_glob.get(),
                                 'dead_funcs': v_func.get(),
                                 'cascade': v_casc.get(),
                                 'include_codej': v_codej.get(),
                                 'comments': v_com.get()}
        self._save_cfg()
        opts = {'empty_dirs': v_dirs.get(), 'del_empty_txt': v_txt.get(),
                'disabled': v_dis.get() or v_clo.get(), 'closed': v_clo.get(),
                'del_notes': v_notes.get(), 'globals': v_glob.get(),
                'dead_funcs': v_func.get(), 'cascade': v_casc.get(),
                'include_codej': v_codej.get(), 'comments': v_com.get(),
                'exclude_dirs': excl}
        opath = os.path.join(self._cfg_dir(), 'triggers_opts.json')
        io.open(opath, 'wb').write(json.dumps(opts).encode('utf-8'))
        lbl.configure(text='скан идёт (1-3 мин)...')
        self._log('>>> Чистка триггеров: скан %s' % tgt)
        tree = self._trigclean_state['tree']
        tree.delete(*tree.get_children())
        # 21.10: накопитель для маркеров @@TRIG — дерево наполнится
        # по ходу скана, финальный показ вставку не дублирует
        self._trigclean_state['acc'] = {}
        self._trigclean_state['filled'] = False
        # 21.10: секундный таймер — окно показывает «скан идёт: N сек»
        stop_beat = {'f': False}
        threading.Thread(target=self._win_beat, daemon=True,
                         args=(win, lbl, 'скан идёт', stop_beat)).start()

        def work():
            def on_line(ln):
                # 21.10: маркеры @@TRIG вливаются в дерево налету;
                # в журнал их не пропускаем (как @@TICK)
                if not ln.startswith('@@TRIG '):
                    return False
                try:
                    payload = json.loads(ln[7:])
                except Exception:
                    return True
                self._safe_after(win, lambda p=payload: self._trigclean_fill(p))
                return True
            try:
                # 20.10: --dir — чистим именно ту карту, что в поле окна
                # 21.10: стрим — вывод этапа в журнал вживую
                code, out = self._run_streamed(
                    [sys.executable, '-u', os.path.join(HERE, 'stage_triggers.py'),
                     CFG, '--dir', tgt, '--scan', opath],
                    on_line=on_line)
            except Exception as e:
                code, out = 1, str(e)
            finally:
                stop_beat['f'] = True
            self._safe_after(win, lambda: self._trigclean_show(
                code, out, tgt, opts))
        threading.Thread(target=work, daemon=True).start()

    def _trigclean_add(self, tree, res):
        """21.10: вставка строк скана в дерево (общий блок show и филлера
        инкрементального дерева). Возвращает число вставленных строк."""
        n = 0
        for rel in res.get('empty_txt', []):
            # 20.10 (аудит): iid = ПОЛНЫЙ относительный путь — раньше(delete)
            # сопоставлял по basename и при одинаковых именах .txt в разных
            # папках удалял первую попавшуюся
            try:
                tree.insert('', 'end', iid=rel,
                            values=('', os.path.basename(rel), '0', 'пустой .txt'))
            except Exception:
                pass
            n += 1
        for rel in res.get('empty_dirs', []):
            tree.insert('', 'end', values=('', rel, '', 'пустая папка'))
            n += 1
        for tr in res.get('disabled', []):
            why = ','.join(tr.get('flags', []))
            if tr.get('used_by'):
                why += ' | ИСПОЛЬЗУЕТСЯ: ' + ', '.join(tr['used_by'][:3])
            if tr.get('note'):
                why += ' | ' + tr['note']
            tree.insert('', 'end', values=(tr.get('cat_disk', ''), tr.get('disk', ''),
                                           tr.get('size', 0), why))
            n += 1
        for g in res.get('globals_unused', []):
            tree.insert('', 'end', values=('глобалка', g, '', 'не упоминается в коде'))
            n += 1
        for name, rels in sorted(res.get('dead_funcs', {}).items()):
            tree.insert('', 'end', values=(os.path.dirname(rels[0]) if rels else '', name,
                                           '', 'мёртвая функция: ' + (', '.join(os.path.basename(r) for r in rels[:2]))))
            n += 1
        return n

    def _trigclean_fill(self, payload):
        """21.10: вливание куска результата скана (@@TRIG маркер) в дерево
        по ходу — строки появляются сразу, а не разом в конце."""
        st = getattr(self, '_trigclean_state', None)
        if not st:
            return
        tree = st.get('tree')
        if tree is None:
            return
        try:
            if not tree.winfo_exists():
                return
        except Exception:
            return
        acc = st.setdefault('acc', {})
        st['filled'] = True
        # dead_funcs приходят кусками — сливаем в накопитель, в дерево
        # вставляем только этот кусок (сортировку общего списка делает show
        # при unfilled-пути; инкрементально строки идут в порядке кусков)
        for k, v in payload.items():
            if k == 'dead_funcs':
                acc.setdefault('dead_funcs', {}).update(v)
            else:
                acc[k] = v
        self._trigclean_add(tree, payload)

    def _trigclean_show(self, code, out, tgt, opts):
        st = getattr(self, '_trigclean_state', None)
        if not st:
            return
        lbl = st.get('lbl')
        tree = st.get('tree')
        try:
            if lbl is None or tree is None or not tree.winfo_exists():
                return
        except Exception:
            return
        # 21.10: строки уже ушли в журнал стримом (_run_streamed) —
        # в журнал дублируем только при провале запуска
        if code != 0 and out and not out.startswith('ошибка запуска'):
            pass
        if code != 0:
            if out:
                self._log(out, 'err')
            lbl.configure(text='скан не удался')
            self._log('>>> Скан триггеров: ОШИБКА', 'err')
            return
        try:
            res = json.load(io.open(os.path.join(self._cfg_dir(), 'triggers_scan.json'), 'rb'))
        except Exception as e:
            lbl.configure(text='нет результатов')
            self._log('>>> Скан триггеров: не прочитан результат: %s' % e, 'err')
            return
        self._trigclean_state['dir'] = tgt
        if st.get('filled'):
            # 21.10: дерево уже наполнено по ходу скана (маркеры @@TRIG,
            # филлер _trigclean_fill). Вставку не дублируем: сводим итог
            # из накомленных кусков и ставим счётчик.
            res = st.get('acc') or res
            self._trigclean_state['scan'] = res
            n = (len(res.get('empty_txt', [])) + len(res.get('empty_dirs', []))
                 + len(res.get('disabled', [])) + len(res.get('globals_unused', []))
                 + len(res.get('dead_funcs', {})))
        else:
            self._trigclean_state['scan'] = res
            n = self._trigclean_add(tree, res)
        lbl.configure(text='найдено: %d' % n)
        self._log('>>> Чистка триггеров: скан %s — найдено %d' % (tgt, n), 'ok')

    def _trigclean_delete(self, e_dir, lbl, dry=False):
        st = getattr(self, '_trigclean_state', None)
        if not st or not st.get('scan'):
            messagebox.showwarning('Скан', 'Сначала запусти Скан.')
            return
        tree = st['tree']
        sel = tree.selection()
        if not sel:
            messagebox.showwarning('Выбор', 'Выдели строки для удаления.')
            return
        # 20.10: удаляем в той карте, по которой сделан скан
        tgt = st.get('dir') or e_dir.get().strip()
        # 19.09 (вечер): ДЕМО — без подтверждения и записи
        if dry:
            pass
        elif not messagebox.askyesno('Подтверждение', 'Удалить %d записей?\nКарта: %s\nПеред удалением будет бэкап (включая catalog.lml и variable.lml).' % (len(sel), tgt)):
            return
        # собираю delete-JSON по категориям
        d = {'empty_dirs': [], 'empty_txt': [], 'disabled': [], 'globals': [], 'dead_funcs': {},
             'del_notes': bool(self.cfg.get('trigclean', {}).get('del_notes', False))}
        scan = st['scan']
        for item in sel:
            vals = tree.item(item, 'values')
            cat, name, size, why = vals[0], vals[1], vals[2], vals[3]
            if why.startswith('пустая папка'):
                d['empty_dirs'].append(name)
            elif why.startswith('пустой .txt'):
                # 20.10 (аудит): iid строки = полный rel из скана — совпадение
                # по basename выдавало первую попавшуюся при дубликатах имён
                if item in [r for r in scan.get('empty_txt', [])]:
                    d['empty_txt'].append(item)
            elif why.startswith('Disab') or why.startswith('Closed') or 'Disab' in why or 'Closed' in why:
                for tr in scan.get('disabled', []):
                    if tr.get('disk') == name and tr.get('cat_disk') == cat:
                        d['disabled'].append(tr)
                        break
            elif cat == 'глобалка':
                d['globals'].append(name)
            elif why.startswith('мёртвая функция'):
                if name in scan.get('dead_funcs', {}):
                    d['dead_funcs'][name] = scan['dead_funcs'][name]
        jp = os.path.join(self._cfg_dir(), 'triggers_delete.json')
        io.open(jp, 'wb').write(json.dumps(d, ensure_ascii=False, indent=1).encode('utf-8'))
        lbl.configure(text='демо...' if dry else 'удаление...')
        win_d = st['win']
        stop_beat = {'f': False}
        threading.Thread(target=self._win_beat, daemon=True,
                         args=(win_d, lbl, 'демо идёт' if dry else 'удаление идёт',
                               stop_beat)).start()

        def work():
            try:
                cmd = [sys.executable, '-u', os.path.join(HERE, 'stage_triggers.py'),
                       CFG, '--dir', tgt, '--delete', jp]
                # 19.09 (вечер): ДЕМО — флаг --dry, без записи
                if dry:
                    cmd.append('--dry')
                # 21.10: стрим — вывод в журнал вживую
                code, out = self._run_streamed(cmd)
            except Exception as e:
                code, out = 1, str(e)
            finally:
                stop_beat['f'] = True
            if dry:
                # открыть демо-лог (строка ЛОГ: путь)
                for l in out.splitlines():
                    if l.startswith('ЛОГ: '):
                        try:
                            os.startfile(l[5:].strip())
                        except Exception:
                            pass
                        break
                self._safe_after(win_d, lambda: self._trigclean_deleted(code, out, len(sel), lbl, tree, [], dry=True))
            else:
                self._safe_after(win_d, lambda: self._trigclean_deleted(code, out, len(sel), lbl, tree, sel, dry=dry))
        threading.Thread(target=work, daemon=True).start()

    def _trigclean_deleted(self, code, out, n, lbl, tree, sel, dry=False):
        try:
            if tree is None or not tree.winfo_exists():
                return
        except Exception:
            return
        # 21.10: строки уже ушли в журнал стримом — дубли не в журнал
        if code == 0:
            self._log('>>> ДЕМО завершено: ничего не записано, лог открыт' if dry
                      else '>>> Чистка триггеров завершена, лог в logs/', 'ok')
            for item in sel:
                tree.delete(item)
            lbl.configure(text=('демо: %d будет удалено' if dry else 'удалено: %d') % n)
        else:
            lbl.configure(text='ошибка удаления')
            self._log('>>> Чистка триггеров: ОШИБКА', 'err')

    def _triggers_window(self):
        win = ctk.CTkToplevel(self)
        win.title('Перенос триггеров')
        # 29.09: авто-подгонка под контент (вместо жёсткой 760x560)
        # 19.09: CTk-баг — Toplevel рождается позади
        def _front():
            try:
                win.lift()
                win.focus_force()
            except Exception:
                pass
        win.after(200, _front)

        src = self.e_src.get().strip()
        trig = os.path.join(src, 'trigger')
        top, ti = self._card(win, 'Подпапки триггеров источника')
        top.pack(fill="both", expand=True, padx=8, pady=6)
        ctk.CTkLabel(ti, text=src, font=FONT_SMALL, anchor="w").pack(fill="x", pady=2)

        lb = tk.Listbox(ti, selectmode='extended', exportselection=False,
                        font=('Consolas', 11), activestyle='none',
                        bg="#181b21" if APPEARANCE == 'dark' else "#ffffff",
                        fg="#e8edf4" if APPEARANCE == 'dark' else "#1a1a1a",
                        selectbackground=ACCENT, selectforeground="#ffffff",
                        borderwidth=0, highlightthickness=0)
        sb = ctk.CTkScrollbar(ti, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        Tooltip(lb, 'Выдели подпапки для переноса (Ctrl/Shift — как в проводнике).\nПусто = перенести ВСЁ.')

        subs = []
        if os.path.isdir(trig):
            for x in sorted(os.listdir(trig)):
                if os.path.isdir(os.path.join(trig, x)):
                    n = sum(1 for f in os.listdir(os.path.join(trig, x)) if f.endswith('.j'))
                    subs.append((x, n))
        for x, n in subs:
            lb.insert('end', '%s  (%d .j)' % (x, n))

        info = ctk.CTkLabel(ti, text='', font=FONT_SMALL, anchor="w")
        info.pack(fill="x", pady=4)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(btns, text='Выделить всё', height=30,
                      command=lambda: lb.select_set(0, 'end')).pack(side='left', padx=3)
        ctk.CTkButton(btns, text='Снять выделение', height=30,
                      command=lambda: lb.select_clear(0, 'end')).pack(side='left', padx=3)

        def do_transfer():
            sel = [lb.get(i).rsplit('  (', 1)[0] for i in lb.curselection()]
            # 20.10 (аудит): правим ЖИВОЙ конфиг инстанса и сохраняем.
            # Раньше правили файл на диске, но _save_cfg перезаписывал
            # его из памяти — only_dirs молча терялся, переносилось ВСЁ.
            self.cfg.setdefault('code', {})['only_dirs'] = sel
            # 20.10 (аудит): after прогона only_dirs снимается (см. _worker) —
            # иначе следующий обычный прогон был бы урезанным
            self._clear_only_dirs = True
            self._save_cfg()
            self._log('Перенос триггеров: %s -> %s' % (len(sel) if sel else 'ВСЁ', ', '.join(sel[:8]) + ('...' if len(sel) > 8 else '')))
            win.destroy()
            self._run([['--stage', 'code'], ['--stage', 'verify']])

        ctk.CTkButton(btns, text='ПЕРЕНЕСТИ ВЫБРАННЫЕ', height=36,
                      fg_color=OKGREEN, hover_color=OKGREEN_H,
                      command=do_transfer).pack(side='left', padx=8)
        ctk.CTkButton(btns, text='Закрыть', height=30,
                      command=win.destroy).pack(side='right', padx=3)

        def upd_info(e=None):
            n = len(lb.curselection())
            files = 0
            for i in lb.curselection():
                files += subs[i][1]
            info.configure(text='Выбрано: %d папок, %d файлов .j' % (n, files) if n else 'Не выбрано — перенесётся ВСЁ (%d файлов)' % sum(x[1] for x in subs))
        lb.bind('<<ListboxSelect>>', upd_info)
        upd_info()
        self._fit_toplevel(win, min_w=760, min_h=560)
        return win

    # ---------- окно чистки ----------

    def _cleanup_window(self):
        win = ctk.CTkToplevel(self)
        win.title('Чистка карты')
        # 29.09: авто-подгонка под контент (вместо жёсткой 980x640)
        # 19.09: CTk-баг — Toplevel рождается позади
        # главного окна, кажется что кнопка не нажалась
        def _front():
            try:
                win.lift()
                win.focus_force()
            except Exception:
                pass
        win.after(200, _front)

        top, ti = self._card(win, 'Карта')
        top.pack(fill='x', padx=8, pady=6)
        row = ctk.CTkFrame(ti, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text='Папка карты:', font=FONT_SMALL).pack(side='left')
        e_dir = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e_dir.pack(side='left', fill='x', expand=True, padx=6)
        # 19.09: восстановить последнюю карту чистки из конфига
        last_dir = self.cfg.get('cleanup', {}).get('last_dir', '')
        e_dir.insert(0, last_dir if last_dir else self.e_tgt.get().strip())
        Tooltip(e_dir, 'Папка карты в lni-формате (table/*.ini + trigger/).')
        ctk.CTkButton(row, text='...', width=36, height=30,
                      command=lambda: self._cleanup_pick(e_dir)).pack(side='left')
        # 22.10 (UI): история путей карты рядом с полем
        self._add_hist(e_dir, 'map')
        # 22.10 (конф-синх): путь живёт в конфиге и при стирании поля
        self._bind_cfg_path(e_dir, 'cleanup', 'last_dir')

        opts, oi = self._card(win, 'Что чистим')
        opts.pack(fill='x', padx=8, pady=4)
        v_unused = tk.BooleanVar(value=False)
        v_bad = tk.BooleanVar(value=False)
        v_suf = tk.BooleanVar(value=False)
        v_casc = tk.BooleanVar(value=True)
        cb1 = ctk.CTkCheckBox(oi, text='Неиспользуемые объекты', variable=v_unused,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb1.pack(anchor='w', pady=2)
        Tooltip(cb1, 'Объекты без ссылок из кода и других объектов.\nСтандартные WC3 и mustuse (Avul, Amov...) не трогаются.')
        cb2 = ctk.CTkCheckBox(oi, text='Битые равкоды', variable=v_bad,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb2.pack(anchor='w', pady=2)
        Tooltip(cb2, 'Равкод не 4 символа или неверный префикс типа\n(юнит E/H/N/O/U, способность A, бафф B/X, предмет I, улучшение R).')
        cb3 = ctk.CTkCheckBox(oi, text='По суффиксу редактора', variable=v_suf,
                              font=FONT_SMALL, checkbox_width=18, checkbox_height=18)
        cb3.pack(anchor='w', pady=2)
        Tooltip(cb3, 'Способности с суффиксом (убрано)/(Убрано)/не используется\n+ ручной список равкодов в конфиге (cleanup.manual_ids).')
        # 19.09 (вечер): редактируемый список суффиксов (конфиг↔UI)
        sr = ctk.CTkFrame(oi, fg_color="transparent")
        sr.pack(fill="x", pady=2)
        ctk.CTkLabel(sr, text='Суффиксы (через запятую):', font=FONT_SMALL).pack(side='left', padx=(0, 6))
        e_suf = ctk.CTkEntry(sr, font=FONT_MONO, height=28)
        e_suf.pack(side='left', fill='x', expand=True)
        suf_cfg = self.cfg.get('cleanup', {}).get('suffix_patterns', sc.DEFAULT_SUFFIX_PATTERNS)
        e_suf.insert(0, ', '.join(suf_cfg))
        Tooltip(e_suf, 'Подстроки в названии объекта, по которым он считается\n«убранным» (например: (убрано), не используется, Копировать).\nСохраняется в конфиг (cleanup.suffix_patterns).')
        cr = ctk.CTkFrame(oi, fg_color="transparent")
        cr.pack(fill="x", pady=2)
        ctk.CTkLabel(cr, text='Каскад:', font=FONT_SMALL).pack(side='left', padx=(0, 6))
        ctk.CTkCheckBox(cr, text='удалять и то, что держалось только на мёртвых (волнами, видно до подтверждения)',
                        variable=v_casc, font=FONT_SMALL,
                        checkbox_width=18, checkbox_height=18).pack(side='left')
        tr = ctk.CTkFrame(oi, fg_color="transparent")
        tr.pack(fill="x", pady=2)
        ctk.CTkLabel(tr, text='Типы:', font=FONT_SMALL).pack(side='left', padx=(0, 6))
        self._type_vars = {}
        for tid, tname in [('unit', 'Юниты'), ('ability', 'Способности'), ('item', 'Предметы'),
                           ('buff', 'Баффы'), ('upgrade', 'Улучшения'), ('doodad', 'Декорации'),
                           ('destructable', 'Разрушаемые')]:
            v = tk.BooleanVar(value=True)
            cb = ctk.CTkCheckBox(tr, text=tname, variable=v, font=FONT_SMALL,
                                 checkbox_width=18, checkbox_height=18)
            cb.pack(side='left', padx=4)
            self._type_vars[tid] = v
        Tooltip(tr, 'Фильтр скана: показывать и удалять только отмеченные типы.')

        # список (Treeview — ttk, стилизованный под тему)
        lst, li = self._card(win, 'Скан (выдели строки и подтверди удаление)')
        lst.pack(fill='both', expand=True, padx=8, pady=4)
        dark = APPEARANCE == 'dark'
        style = ttk.Style(win)
        style.configure('Clean.Treeview', background="#181b21" if dark else "#ffffff",
                        fieldbackground="#181b21" if dark else "#ffffff",
                        foreground="#e8edf4" if dark else "#1a1a1a",
                        font=('Segoe UI', 10), rowheight=24, borderwidth=0)
        style.map('Clean.Treeview', background=[('selected', ACCENT)],
                  foreground=[('selected', '#ffffff')])
        style.configure('Clean.Treeview.Heading', font=('Segoe UI', 10, 'bold'),
                        background="#262b33" if dark else "#e3e8ef",
                        foreground="#e8edf4" if dark else "#1a1a1a", padding=(6, 4))
        tree = ttk.Treeview(li, columns=('id', 'type', 'name'), show='headings', height=14,
                            selectmode='extended', style='Clean.Treeview')
        tree.heading('id', text='Равкод')
        tree.heading('type', text='Тип')
        tree.heading('name', text='Имя / причина')
        tree.column('id', width=90)
        tree.column('type', width=100)
        tree.column('name', width=560)
        tree.pack(side='left', fill='both', expand=True, padx=4, pady=4)
        sb = ctk.CTkScrollbar(li, command=tree.yview)
        sb.pack(side='left', fill='y')
        tree.configure(yscrollcommand=sb.set)
        tree.bind('<Control-a>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])
        tree.bind('<Control-A>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])

        # панель кнопок — 19.09: два ряда, чтобы влезали
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill='x', padx=8, pady=(4, 2))
        btns2 = ctk.CTkFrame(win, fg_color="transparent")
        btns2.pack(fill='x', padx=8, pady=(0, 2))
        self._cleanup_state = {'scan': None, 'tree': tree, 'win': win}
        # 20.10 (аудит): iid-кэш фильтра сбрасывается при открытии окна —
        # оставался от прошлого скана другой карты и молча не работал
        self._cleanup_all_iids = None

        b_scan = ctk.CTkButton(btns, text='1. СКАН', height=36, font=("Segoe UI", 12, "bold"),
                               command=lambda: self._cleanup_scan(e_dir, v_unused, v_bad, v_suf, v_casc, e_suf))
        b_scan.pack(side='left', padx=(6, 10), pady=2)
        Tooltip(b_scan, 'ШАГ 1. Искать мусор в карте.\nРезультат появится в списке ниже.')
        b_del = ctk.CTkButton(btns, text='2. УДАЛИТЬ ВЫДЕЛЕННОЕ', height=36,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=OKGREEN, hover_color=OKGREEN_H,
                              command=lambda: self._cleanup_delete(e_dir))
        b_del.pack(side='left', padx=3, pady=2)
        Tooltip(b_del, 'ШАГ 2. Удалить отмеченные в списке строки.\nСпросит подтверждение, сделает бэкап.')
        # 19.09 (вечер): ДЕМО — что будет удалено, без записи
        b_demo = ctk.CTkButton(btns, text='ДЕМО (без записи)', height=36,
                               font=("Segoe UI", 11),
                               fg_color=WARN, hover_color=WARN_H,
                               command=lambda: self._cleanup_delete(e_dir, dry=True))
        b_demo.pack(side='left', padx=3, pady=2)
        Tooltip(b_demo, 'ПОКАЗАТЬ какие объекты будут удалены —\nБЕЗ записи в таблицы и без бэкапа.\nПишет лог (logs/cleanup-дата-demo.md) и открывает его.')
        b_rep = ctk.CTkButton(btns, text='ПОЧИНИТЬ ТАБЛИЦЫ', height=36,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=WARN, hover_color=WARN_H,
                              command=lambda: self._repair_tables(e_dir))
        b_rep.pack(side='left', padx=(10, 3), pady=2)
        Tooltip(b_rep, 'Авто-починка table/*.ini: self-parent (родитель = сам себе),\nбитые _parent -> дефолт типа, дубли секций, разбаланс [=[ ]=].\nПервый запуск = скан, повторный = починка (бэкап + лог).')
        # 19.09: второй ряд — мелкие кнопки
        ctk.CTkButton(btns2, text='Выделить всё', height=30,
                      command=lambda: self._cleanup_select_all(tree)).pack(side='left', padx=(6, 3), pady=2)
        ctk.CTkLabel(btns2, text='Фильтр:', font=FONT_SMALL).pack(side='left', padx=(10, 2))
        e_f = ctk.CTkEntry(btns2, width=140, height=28, font=FONT_SMALL)
        e_f.pack(side='left')
        Tooltip(e_f, 'Показать в списке только строки с этим текстом\n(имя, тип или причина). Очисти поле и Enter — сброс.')
        e_f.bind('<Return>', lambda e: self._cleanup_filter(tree, e_f.get().strip()))
        ctk.CTkButton(btns2, text='Открыть лог', height=30,
                      command=self._cleanup_open_log).pack(side='left', padx=3)
        lbl = ctk.CTkLabel(btns2, text='', font=FONT_SMALL)
        lbl.pack(side='left', padx=10)
        self._cleanup_lbl = lbl
        self._fit_toplevel(win, min_w=980, min_h=640)
        return win

    def _cleanup_pick(self, entry):
        # 19.09: выбор карты чистки + сохранение в конфиг
        d = filedialog.askdirectory()
        if d:
            entry.delete(0, 'end')
            entry.insert(0, d)
            self.cfg.setdefault('cleanup', {})['last_dir'] = d
            # 22.10 (UI): путь карты попадает в историю
            self._remember_path('map', d)
            self._save_cfg()

    def _cleanup_remember(self, tgt):
        # 19.09: запомнить карту чистки (скан/удаление/починка)
        self.cfg.setdefault('cleanup', {})['last_dir'] = tgt
        self._save_cfg()

    def _cleanup_scan(self, e_dir, v_unused, v_bad, v_suf, v_casc, e_suf=None):
        tgt = e_dir.get().strip()
        if not os.path.isdir(tgt):
            messagebox.showwarning('Путь', 'Укажи папку карты.')
            return
        self._cleanup_remember(tgt)
        # 19.09 (вечер): суффиксы — конфиг↔UI (поле в окне)
        if e_suf is not None:
            suf = [x.strip() for x in e_suf.get().split(',') if x.strip()]
            self.cfg.setdefault('cleanup', {})['suffix_patterns'] = suf
            self._save_cfg()
        patterns = self.cfg.get('cleanup', {}).get('suffix_patterns', sc.DEFAULT_SUFFIX_PATTERNS)
        manual = self.cfg.get('cleanup', {}).get('manual_ids', {})
        # 19.09: защитный список — если галочка стоит
        protect = {}
        if self._cleanup_v_prot.get():
            self.cfg.setdefault('cleanup', {})['protect'] = True
            pp = os.path.join(self._cfg_dir(), 'cleanup_protect.json')
            if os.path.exists(pp):
                protect = json.load(io.open(pp, 'rb'))
        else:
            self.cfg.setdefault('cleanup', {})['protect'] = False
        self._save_cfg()
        # 20.10 (аудит): скан большой карты больше не морозит окно.
        # Значения Tk-переменных снимаем в главном потоке.
        show_suf = bool(v_suf.get())
        show_bad = bool(v_bad.get())
        show_unused = bool(v_unused.get())
        casc = bool(v_casc.get())
        allowed = {tid for tid, v in getattr(self, '_type_vars', {}).items() if v.get()} or set(sc.TYPES)
        self._cleanup_lbl.configure(text='скан...')
        self._log('>>> Чистка: скан %s ...' % tgt)

        def work():
            # 21.10: шаги скана видны в окне («проход 1: ability...»)
            lbl_p = self._cleanup_lbl

            def prog(msg):
                self._safe_after(lbl_p, lambda: lbl_p.configure(text=msg))

            return sc.scan(tgt, patterns, manual, protect,
                           cfgp=self._cfg_path(), progress=prog)

        def done(res):
            self._cleanup_render(res, tgt, casc, allowed, show_unused, show_bad, show_suf)

        self._bg(work, done)

    def _cleanup_render(self, res, tgt, casc, allowed, show_unused, show_bad, show_suf):
        st = getattr(self, '_cleanup_state', None)
        if not st or not st.get('tree'):
            return
        tree = st['tree']
        self._cleanup_state = {'scan': res, 'dir': tgt, 'casc': casc,
                               'tree': tree, 'win': st.get('win')}
        tree.delete(*tree.get_children())
        self._cleanup_all_iids = None
        n = 0
        for t, d in res['suffix'].items():
            if t not in allowed or not show_suf:
                continue
            for sid, v in d.items():
                tree.insert('', 'end', values=(sid, t, (v['name'] or '') + '  [суффикс: ' + v['pattern'] + ']'))
                n += 1
        for t, d in res['badcode'].items():
            if t not in allowed or not show_bad:
                continue
            for sid, v in d.items():
                tree.insert('', 'end', values=(sid, t, (v['name'] or '') + '  [битый равкод]'))
                n += 1
        for t, d in res['unused'].items():
            if t not in allowed or not show_unused:
                continue
            for sid, v in d.items():
                tree.insert('', 'end', values=(sid, t, (v['name'] or '') + '  [не используется]'))
                n += 1
        for i, w in enumerate(res['waves']):
            if i == 0 or not show_unused:
                continue
            for sid, v in w.items():
                if v['type'] not in allowed:
                    continue
                tree.insert('', 'end', values=(sid, v['type'], (v['name'] or '') + '  [каскад, волна %d <- %s]' % (i, ', '.join(v['owners'][:3]))))
                n += 1
        self._cleanup_lbl.configure(text='найдено: %d' % n)
        self._log('>>> Чистка: скан %s — найдено %d' % (tgt, n), 'ok')

    def _cleanup_delete(self, e_dir, dry=False):
        st = getattr(self, '_cleanup_state', None)
        if not st or not st.get('scan'):
            messagebox.showwarning('Скан', 'Сначала запусти Скан.')
            return
        self._cleanup_remember(e_dir.get().strip())
        tree = st['tree']
        sel = tree.selection()
        if not sel:
            messagebox.showwarning('Выбор', 'Выдели строки для удаления (Ctrl/Shift для группы).')
            return
        # 19.09 (вечер): ДЕМО — без подтверждения и записи
        if dry:
            pass
        elif not messagebox.askyesno('Подтверждение', 'Удалить %d объектов?\nПеред удалением будет бэкап.' % len(sel)):
            return
        del_list = {}
        for item in sel:
            sid, t = tree.item(item, 'values')[0], tree.item(item, 'values')[1]
            del_list.setdefault(t, []).append(sid)
        tgt = st['dir']
        # 21.10: пути чистки настраиваемые (cleanup.log_dir/backup_dir),
        # дефолт прежний: logs/ и transfer_backup/cleanup у конфига
        ccfg = self.cfg.get('cleanup', {})
        sbd = self.cfg.get('safety', {}).get('backup_dir', 'transfer_backup')
        log_dir = ccfg.get('log_dir') or os.path.join(self._cfg_dir(), 'logs')
        bdir = ccfg.get('backup_dir') or os.path.join(self._cfg_dir(), sbd, 'cleanup')
        self._log('>>> Чистка: %s %d объектов ...' % ('демо' if dry else 'удаление', len(sel)))

        def work():
            lb = getattr(self, '_cleanup_lbl', None)

            def prog(msg):
                if lb is not None:
                    self._safe_after(lb, lambda: lb.configure(text=msg))

            return sc.delete(tgt, del_list, log_dir, bdir, dry=dry, progress=prog)

        def done(lines):
            for l in lines:
                self._log('  ' + l)
            # 19.09 (вечер): ДЕМО — открыть лог, ничего не удалять из списка
            if dry:
                for l in lines:
                    if l.startswith('ЛОГ: '):
                        try:
                            os.startfile(l[5:].strip())
                        except Exception:
                            pass
                        break
                self._log('>>> ДЕМО завершено: ничего не записано, лог открыт', 'ok')
                self._cleanup_lbl.configure(text='демо: %d будет удалено' % len(sel))
                return
            self._log('>>> Чистка завершена, лог в logs/', 'ok')
            for item in sel:
                try:
                    tree.delete(item)
                except Exception:
                    pass
            self._cleanup_lbl.configure(text='удалено: %d' % len(sel))

        self._bg(work, done)

    def _repair_tables(self, e_dir):
        tgt = e_dir.get().strip()
        if not os.path.isdir(tgt):
            messagebox.showwarning('Путь', 'Укажи папку карты.')
            return
        self._cleanup_remember(tgt)
        first = not getattr(self, '_repair_ran', False) or getattr(self, '_repair_tgt', '') != tgt
        self._repair_tgt = tgt
        if not first and not messagebox.askyesno('Починка', 'Применить правки к таблицам?\nПеред записью будет бэкап.'):
            return
        # 20.10 (аудит): починка большого набора таблиц в фоне (UI не морозим)
        self._log('>>> Починка: %s ...' % ('скан' if first else 'применение'))
        cfgp = self._cfg_path()
        # 21.10: пути починки настраиваемые (repair.backup_dir/log_dir)
        rcfg = self.cfg.get('repair', {})
        sbd = self.cfg.get('safety', {}).get('backup_dir', 'transfer_backup')
        bdir = rcfg.get('backup_dir') or os.path.join(self._cfg_dir(), sbd, 'repair')

        def work():
            lb = getattr(self, '_cleanup_lbl', None)

            def prog(msg):
                if lb is not None:
                    self._safe_after(lb, lambda: lb.configure(text=msg))

            return sr.repair(tgt, None, bdir, do=not first, cfgp=cfgp, progress=prog)

        def done(res):
            lines, total = res
            for l in lines:
                self._log('  ' + l)
            if total:
                if first:
                    self._repair_ran = True
                    self._log('>>> Починка: скан — найдено %d проблем. Запусти ещё раз для применения (бэкап + лог).' % total, 'warn')
                else:
                    ldir = rcfg.get('log_dir') or os.path.join(self._cfg_dir(), 'logs')
                    os.makedirs(ldir, exist_ok=True)
                    lp = os.path.join(ldir, 'repair-%s.md' % time.strftime('%Y-%m-%d'))
                    io.open(lp, 'ab').write((chr(10).join(lines) + chr(10) + chr(10)).encode('utf-8'))
                    self._log('>>> Починка применена: %d правок, лог %s' % (total, lp), 'ok')
            else:
                self._log('>>> Починка: проблем не найдено', 'ok')

        self._bg(work, done)

    # 29.09: деобфускация имён (deob.py, сторонний скрипт юзера) — режим Обслуживания

    def _deob_window(self):
        """29.09: деобфускатор имён deob.py. Вход: файл .j.
        СКАН = прогон во временную папку (вход не трогается) + парсинг отчёта.
        ПРИМЕНИТЬ = выход <имя>_deobfuscated.j + rename_map.csv рядом с входом.
        VERIFY-отчёт в журнал GUI."""
        win = ctk.CTkToplevel(self)
        win.title('Деобфускация имён')
        def _front():
            try:
                win.lift(); win.focus_force()
            except Exception:
                pass
        win.after(200, _front)

        top, ti = self._card(win, 'Скрипт карты')
        top.pack(fill='x', padx=8, pady=6)
        row = ctk.CTkFrame(ti, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text='Файл .j:', font=FONT_SMALL).pack(side='left')
        e_file = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e_file.pack(side='left', fill='x', expand=True, padx=6)
        last = self.cfg.get('deob', {}).get('last_path', '')
        e_file.insert(0, self._deob_default_path(last))
        Tooltip(e_file, 'Обычный JASS-скрипт (war3map.j / code.j).\nvJass-директивы //! сохраняются, но не разворачиваются.')
        ctk.CTkButton(row, text='...', width=36, height=30,
                      command=lambda: self._deob_pick(e_file)).pack(side='left')
        # 22.10 (UI): история файлов .j рядом с полем
        self._add_hist(e_file, 'j')
        # 22.10 (конф-синх): путь живёт в конфиге и при стирании поля
        self._bind_cfg_path(e_file, 'deob', 'last_path')

        info, ii = self._card(win, 'Отчёт')
        info.pack(fill='x', padx=8, pady=4)
        lbl = ctk.CTkLabel(ii, text='нет данных', font=FONT_SMALL, anchor='w',
                           justify='left')
        lbl.pack(fill='x', pady=2)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill='x', padx=8, pady=6)
        b_scan = ctk.CTkButton(btns, text='1. СКАН (пробный прогон)', height=36,
                                font=("Segoe UI", 12, "bold"),
                                command=lambda: self._deob_scan(e_file, lbl))
        b_scan.pack(side='left', padx=(6, 10), pady=2)
        Tooltip(b_scan, 'Прогон deob.py во временную папку — вход НЕ трогается.\nПоказывает: число функций/глобалов, переименований, VERIFY-статус.')
        b_run = ctk.CTkButton(btns, text='2. ПРИМЕНИТЬ', height=36,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=OKGREEN, hover_color=OKGREEN_H,
                              command=lambda: self._deob_apply(e_file, lbl))
        b_run.pack(side='left', padx=3, pady=2)
        Tooltip(b_run, "Деобфускация: выход <имя>_deobfuscated.j + rename_map.csv\nрядом с входом. Вход не изменяется.\nVERIFY: OK = токен-эквивалентность гарантирована.")

        self._fit_toplevel(win, min_w=760, min_h=360)
        return win

    def _deob_pick(self, entry):
        p = filedialog.askopenfilename(filetypes=[('JASS', '*.j'), ('Все файлы', '*.*')])
        if p:
            entry.delete(0, 'end'); entry.insert(0, p)
            # 22.10 (UI): файл попадает в историю
            self._remember_path('j', p)
            # 22.10 (конф-синх): выбор файла сразу в конфиг (не только
            # после СКАНа как раньше)
            self.cfg.setdefault('deob', {})['last_path'] = p
            self._save_cfg()

    def _deob_run(self, src, out_dir):
        """Прогон deob.py: src -> out_dir/<имя>_deobfuscated.j + rename_map.csv.
        Возвращает (ok, текст отчёта)."""
        import subprocess
        base = os.path.splitext(os.path.basename(src))[0]
        out = os.path.join(out_dir, base + '_deobfuscated.j')
        mapf = os.path.join(out_dir, 'rename_map.csv')
        cmd = [sys.executable, os.path.join(HERE, 'deob2.py'), src,
               '-o', out, '-m', mapf]
        try:
            # 21.10: стрим — прогресс deob2.py виден в журнале вживую
            code, text = self._run_streamed(cmd)
            return code == 0, text
        except Exception as ex:
            return False, 'ошибка запуска deob2.py: %s' % ex

    def _deob_default_path(self, last):
        # 20.10 (аудит): дефолт был папкой приёмника — первый СКАН всегда
        # ловил «укажи файл .j». Папку карты превращаем в её монолит.
        p = last or self.e_tgt.get().strip()
        if p and os.path.isdir(p):
            for cand in (os.path.join(p, 'map', 'war3map.j'),
                         os.path.join(p, 'war3map.j'),
                         os.path.join(p, 'trigger', 'code.j')):
                if os.path.exists(cand):
                    return cand
        return p

    def _deob_scan(self, e_file, lbl):
        p = e_file.get().strip()
        if not p or not os.path.isfile(p):
            messagebox.showwarning('Путь', 'Укажи файл .j.')
            return
        self.cfg.setdefault('deob', {})['last_path'] = p
        # 22.10 (UI): файл .j попадает в историю и скана
        self._remember_path('j', p)
        self._save_cfg()
        lbl.configure(text='сканирую...')
        def work():
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                ok, rep = self._deob_run(p, td)
            def upd():
                lbl.configure(text=rep.replace('\n', ' | ')[:400])
                self._log('>>> Деобфускация, СКАН (%s):' % ('ok' if ok else 'FAIL'))
                for l in rep.splitlines():
                    if l.strip():
                        self._log('  ' + l)
            try:
                self.after(0, upd)
            except Exception:
                pass
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _deob_apply(self, e_file, lbl):
        p = e_file.get().strip()
        if not p or not os.path.isfile(p):
            messagebox.showwarning('Путь', 'Укажи файл .j.')
            return
        if not messagebox.askyesno('Деобфускация',
                'Запустить деобфускацию?\nВход не изменяется; рядом появятся\n<имя>_deobfuscated.j и rename_map.csv'):
            return
        def work():
            out_dir = os.path.dirname(p) or '.'
            ok, rep = self._deob_run(p, out_dir)
            def upd():
                lbl.configure(text=rep.replace('\n', ' | ')[:400])
                self._log('>>> Деобфускация (%s):' % ('ГОТОВО' if ok else 'FAIL'),
                          'ok' if ok else 'err')
                for l in rep.splitlines():
                    if l.strip():
                        self._log('  ' + l)
            try:
                self.after(0, upd)
            except Exception:
                pass
        import threading
        threading.Thread(target=work, daemon=True).start()

    # 21.09: конверт равкодов (0xXXXXXXXX -> 'RAWC') — режим Обслуживания

    def _rawconv_window(self):
        """21.09: конвертер равкодов — разовая операция. Вход: файл или
        папка карты (auto: map/war3map.j, war3map.j, trigger/code.j).
        Скан -> применение с бэкапом. Лог замен рядом с файлом."""
        win = ctk.CTkToplevel(self)
        win.title('Конверт равкодов')
        # 29.09: авто-подгонка под контент (вместо жёсткой 760x420)
        def _front():
            try:
                win.lift()
                win.focus_force()
            except Exception:
                pass
        win.after(200, _front)

        import stage_rawconv as rc

        top, ti = self._card(win, 'Скрипт карты')
        top.pack(fill='x', padx=8, pady=6)
        row = ctk.CTkFrame(ti, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text='Файл или папка:', font=FONT_SMALL).pack(side='left')
        e_dir = ctk.CTkEntry(row, font=FONT_MONO, height=30)
        e_dir.pack(side='left', fill='x', expand=True, padx=6)
        last = self.cfg.get('rawconv', {}).get('last_path', '')
        e_dir.insert(0, last if last else self.e_tgt.get().strip())
        Tooltip(e_dir, 'Файл .j ИЛИ папка карты (lni) — при папке ищутся\nmap/war3map.j, war3map.j, trigger/code.j автоматически.')
        ctk.CTkButton(row, text='...', width=36, height=30,
                      command=lambda: self._rawconv_pick(e_dir)).pack(side='left')
        # 22.10 (UI): история путей карты рядом с полем
        self._add_hist(e_dir, 'map')
        # 22.10 (конф-синх): путь живёт в конфиге и при стирании поля
        self._bind_cfg_path(e_dir, 'rawconv', 'last_path')

        # 29.09: направление конверта — туда/обратно
        dirc, dirci = self._card(win, 'Направление')
        dirc.pack(fill='x', padx=8, pady=4)
        v_dir = ctk.StringVar(value=self.cfg.get('rawconv', {}).get('last_dir', 'to'))
        # 22.10 (конф-синх): радиокнопка со сменой направления сразу в конфиг
        def _dir_save(_v=None):
            self.cfg.setdefault('rawconv', {})['last_dir'] = v_dir.get()
            self._save_cfg()
        for val, txt, tip in (
            ('to', 'туда (деобфускация)', "'Amrf' <- 0x/dec/$ (читаемый вид)"),
            ('from', 'обратно (обфускация)', "'Amrf' -> 0x/dec/$ (скрытый вид)"),
        ):
            rb = ctk.CTkRadioButton(dirci, text=txt, variable=v_dir, value=val,
                                    font=FONT_SMALL, command=_dir_save)
            rb.pack(side='left', padx=(6, 10))
            Tooltip(rb, tip)

        # 29.09: целевая форма для обратного направления
        tofc, tofci = self._card(win, 'Целевая форма (обратно)')
        tofc.pack(fill='x', padx=8, pady=4)
        v_to = ctk.StringVar(value=self.cfg.get('rawconv', {}).get('last_to', 'hex'))
        # 22.10 (конф-синх): целевая форма сразу в конфиг
        def _to_save(_v=None):
            self.cfg.setdefault('rawconv', {})['last_to'] = v_to.get()
            self._save_cfg()
        for val, txt, tip in (
            ('hex', '0x...', "'Amrf' -> 0x416D7266"),
            ('dec', 'dec', "'Amrf' -> 1097691750 (десятичное число)"),
            ('jhex', '$...', "'Amrf' -> $416D7266 ($-hex JASS)"),
        ):
            rb = ctk.CTkRadioButton(tofci, text=txt, variable=v_to, value=val,
                                    font=FONT_SMALL, command=_to_save)
            rb.pack(side='left', padx=(6, 10))
            Tooltip(rb, tip)

        # 29.09: выбор режима конверта — hex / dec / оба
        rmode, rmi = self._card(win, 'Режим')
        rmode.pack(fill='x', padx=8, pady=4)
        # 20.10 (аудит): last_mode раньше сохранялся как rawc_hex —
        # при следующем открытии ни одна радиокнопка не выбиралась.
        _rm = self.cfg.get('rawconv', {}).get('last_mode', 'both')
        if _rm.startswith('rawc_'):
            _rm = _rm[5:]
        if _rm not in ('both', 'hex', 'dec', 'jhex'):
            _rm = 'both'
        v_mode = ctk.StringVar(value=_rm)
        # 22.10 (конф-синх): режим сразу в конфиг (базовый, без rawc_)
        def _mode_save(_v=None):
            self.cfg.setdefault('rawconv', {})['last_mode'] = v_mode.get()
            self._save_cfg()
        for val, txt, tip in (
            ('both', 'оба', 'hex-литералы (0x416D7266) и десятичные (1097691750).\nСначала hex, потом dec.'),
            ('hex', 'hex', "только 0xXXXXXXXX -> 'RAWC'"),
            ('dec', 'dec', "только десятичные обфусцированные равкоды:\nUnitRemoveAbility(u, 1097691750) -> 'Amrf'.\nКонвертируются только числа, чьи 4 байта — печатаемые ASCII;\nобычные константы (2000000000) пропускаются."),
            ('jhex', '$hex', "только $-литералы JASS (все длины):\n$D000F -> 851983, $A -> 10, $96 -> 150,\n$416D7266 -> 'Amrf' (если байты печатаемые).\nСемантика не меняется."),
        ):
            rb = ctk.CTkRadioButton(rmi, text=txt, variable=v_mode, value=val,
                                    font=FONT_SMALL, command=_mode_save)
            rb.pack(side='left', padx=(6, 10))
            Tooltip(rb, tip)

        info, ii = self._card(win, 'Скан')
        info.pack(fill='x', padx=8, pady=4)
        lbl = ctk.CTkLabel(ii, text='нет данных', font=FONT_SMALL, anchor='w')
        lbl.pack(fill='x', pady=2)

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill='x', padx=8, pady=6)
        b_scan = ctk.CTkButton(btns, text='1. СКАН', height=36, font=("Segoe UI", 12, "bold"),
                               command=lambda: self._rawconv_scan(e_dir, lbl, rc, v_mode, v_dir, v_to))
        b_scan.pack(side='left', padx=(6, 10), pady=2)
        Tooltip(b_scan, 'Найти скрипт(ы) и посчитать литералы выбранного режима. Без записи.')
        b_run = ctk.CTkButton(btns, text='2. КОНВЕРТИРОВАТЬ', height=36,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=OKGREEN, hover_color=OKGREEN_H,
                              command=lambda: self._rawconv_apply(e_dir, lbl, rc, v_mode, v_dir, v_to))
        b_run.pack(side='left', padx=3, pady=2)
        Tooltip(b_run, 'Заменить литералы выбранного режима на \'RAWC\' (base-256).\nПеред записью — бэкап, лог замен рядом с файлом.')

        # 29.09: авто-подгонка под контент (нижние кнопки не обрезаются)
        self._fit_toplevel(win, min_w=760, min_h=420)
        # журнал — тот же лог главного окна
        return win

    def _rawconv_pick(self, entry):
        # 21.09: выбор файла ИЛИ папки — два диалога через меню выбора
        q = tk.Toplevel(self)
        q.title('Выбор'); q.geometry('280x120')
        q.transient(self)
        ctk.CTkLabel(q, text='Что выбираем?', font=FONT_SMALL).pack(pady=10)
        def pick_file():
            q.destroy()
            p = filedialog.askopenfilename(filetypes=[('JASS', '*.j'), ('Все файлы', '*.*')])
            if p:
                entry.delete(0, 'end'); entry.insert(0, p)
                # 22.10 (UI): путь в историю (это может быть и карта-папка)
                self._remember_path('j' if p.lower().endswith('.j') else 'map', p)
        def pick_dir():
            q.destroy()
            p = filedialog.askdirectory()
            if p:
                entry.delete(0, 'end'); entry.insert(0, p)
                self._remember_path('map', p)
        fr = ctk.CTkFrame(q, fg_color='transparent'); fr.pack(pady=6)
        ctk.CTkButton(fr, text='Файл', width=100, command=pick_file).pack(side='left', padx=6)
        ctk.CTkButton(fr, text='Папка', width=100, command=pick_dir).pack(side='left', padx=6)

    def _rawconv_scan(self, e_dir, lbl, rc, v_mode=None, v_dir=None, v_to=None):
        p = e_dir.get().strip()
        if not p:
            messagebox.showwarning('Путь', 'Укажи файл или папку карты.')
            return
        self.cfg.setdefault('rawconv', {})['last_path'] = p
        base_mode = v_mode.get() if v_mode else 'both'
        mode = base_mode
        direction = v_dir.get() if v_dir else 'to'
        to_form = v_to.get() if v_to else 'hex'
        if direction == 'from':
            mode = 'rawc_' + to_form
        self.cfg.setdefault('rawconv', {})['last_dir'] = direction
        self.cfg['rawconv']['last_to'] = to_form
        # 20.10: храним базовый режим, а не вычисленный rawc_*
        self.cfg['rawconv']['last_mode'] = base_mode
        self._save_cfg()

        def work():
            try:
                res = rc.scan(p, mode)
                return '\n'.join('%s: %d литералов' % (fp, n) for fp, n in res) if res \
                    else 'скрипт карты не найден'
            except Exception as ex:
                return 'ошибка скана: %s' % ex

        def done(win_txt):
            try:
                lbl.configure(text=win_txt)
                self._log('>>> Конверт равкодов, скан: ' + win_txt.replace('\n', ' | '))
            except Exception:
                pass

        self._bg(work, done)

    def _rawconv_apply(self, e_dir, lbl, rc, v_mode=None, v_dir=None, v_to=None):
        p = e_dir.get().strip()
        if not p:
            messagebox.showwarning('Путь', 'Укажи файл или папку карты.')
            return
        base_mode = v_mode.get() if v_mode else 'both'
        mode = base_mode
        direction = v_dir.get() if v_dir else 'to'
        to_form = v_to.get() if v_to else 'hex'
        if direction == 'from':
            mode = 'rawc_' + to_form
        dir_txt = 'туда' if direction == 'to' else 'обратно (%s)' % to_form
        if not messagebox.askyesno('Конверт', 'Заменить литералы (%s)?\nНаправление: %s\nПеред записью — бэкап, лог замен рядом с файлом.' % (mode, dir_txt)):
            return
        self.cfg.setdefault('rawconv', {})['last_path'] = p
        self.cfg['rawconv']['last_dir'] = direction
        self.cfg['rawconv']['last_to'] = to_form
        # 20.10: базовый режим (hex/dec/both/jhex) без префикса rawc_
        self.cfg['rawconv']['last_mode'] = base_mode
        self._save_cfg()
        bdir = self.cfg.get('rawconv', {}).get('backup_dir') or \
            os.path.join(self._cfg_dir(), 'transfer_backup', 'rawconv')

        def work():
            # 20.10: lines инициализируется ВСЕГДА — раньше при исключении
            # upd() падал с NameError и ошибка не доходила до журнала.
            lines = []
            try:
                lines = rc.run(p, bdir, apply=True, mode=mode)
                txt = '\n'.join(lines)
                ok = not any('не найден' in l for l in lines)
            except Exception as ex:
                txt, ok = 'ошибка: %s' % ex, False
                lines = [txt]
            return lines, txt, ok

        def done(res):
            lines, txt, ok = res
            try:
                lbl.configure(text=txt.replace('\n', ' | '))
                for l in lines:
                    self._log('  ' + l)
                self._log('>>> Конверт равкодов: ' + ('готово' if ok else 'НЕ УДАЛОСЬ'),
                          'ok' if ok else 'err')
            except Exception:
                pass

        self._bg(work, done)

    def _cleanup_select_all(self, tree):
        tree.selection_set(tree.get_children())

    def _cleanup_filter(self, tree, q):
        q = (q or '').strip().lower()
        all_iids = getattr(self, '_cleanup_all_iids', None)
        if all_iids is None:
            all_iids = tree.get_children()
            self._cleanup_all_iids = list(all_iids)
        for iid in self._cleanup_all_iids:
            if not tree.exists(iid):
                continue
            vals = tree.item(iid, 'values')
            text = ' '.join(str(v) for v in vals).lower()
            if q and q not in text:
                tree.detach(iid)
            else:
                tree.reattach(iid, '', 'end')

    def _repair_main(self):
        self._repair_tables(self.e_tgt)

    def _cleanup_open_log(self):
        p = os.path.join(self._cfg_dir(), 'logs')
        if os.path.isdir(p):
            fs = sorted([f for f in os.listdir(p) if f.startswith('cleanup-')])
            if fs:
                os.startfile(os.path.join(p, fs[-1]))
            else:
                messagebox.showinfo('Лог', 'Логов чистки пока нет.')
        else:
            messagebox.showinfo('Лог', 'Папки logs ещё нет.')


if __name__ == '__main__':
    try:
        app = App()
        app.mainloop()
    except Exception:
        # 20.10 (аудит-фикс): под pythonw консоли нет — любая ошибка
        # старта умирала молча («батник не запускает»). Пишем
        # logs/gui_crash.log и показываем диалог с трейсбеком.
        import traceback
        tb = traceback.format_exc()
        try:
            os.makedirs(os.path.join(HERE, 'logs'), exist_ok=True)
            with io.open(os.path.join(HERE, 'logs', 'gui_crash.log'), 'wb') as f:
                f.write(tb.encode('utf-8'))
        except Exception:
            pass
        try:
            messagebox.showerror('Ошибка запуска GUI', tb[-1500:])
        except Exception:
            pass
        raise
