# 17.09: GUI для утилиты переноса (tkinter) — v2: визуал + подсказки
# Запуск: python transfer_gui.py (или двойной клик по Утилита переноса.bat)
import io, os, sys, json, subprocess, threading, queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import time
import stage_cleanup as sc
import stage_repair as sr

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, 'transfer_config.json')

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

# палитра (v5): две темы — светлая и тёмная
THEMES = {
    'light': {
        'bg': '#eef1f5', 'panel': '#ffffff', 'head': '#2b3440',
        'accent': '#2d6cdf', 'danger': '#c0392b', 'ok': '#1e8e3e',
        'warn': '#b7791f', 'log_bg': '#1e1e1e', 'log_fg': '#d4d4d4',
        'zebra': '#f4f7fb', 'border': '#d5dbe3',
        'label': '#3a4654', 'muted': '#8a94a3', 'entry_bg': '#ffffff',
        'entry_fg': '#1a1a1a', 'head_fg': '#ffffff', 'head_sub': '#8fa4bd',
        'status_bg': '#e3e8ef', 'status_fg': '#555555',
        'sel_bg': '#cfe0f7', 'sel_fg': '#1a1a1a',
        'heading_bg': '#e3e8ef', 'btnbar': '#dde3ec',
        'prog_done_bg': '#d9f0e2', 'prog_done_fg': '#14663a',
        'prog_bg': '#eef1f5', 'hint_bg': '#fffde7', 'hint_fg': '#333333',
        'found_bg': '#5a5a2e', 'title': '#2b3440',
    },
    'dark': {
        'bg': '#1e2229', 'panel': '#262b33', 'head': '#12151a',
        'accent': '#4d8df0', 'danger': '#e05545', 'ok': '#3ecf6e',
        'warn': '#e6a23c', 'log_bg': '#12151a', 'log_fg': '#c8d0da',
        'zebra': '#232830', 'border': '#3a4150',
        'label': '#d5dce6', 'muted': '#7a8494', 'entry_bg': '#181b21',
        'entry_fg': '#e8edf4', 'head_fg': '#ffffff', 'head_sub': '#7d90a8',
        'status_bg': '#161a20', 'status_fg': '#9aa5b1',
        'sel_bg': '#2d5aa8', 'sel_fg': '#ffffff',
        'heading_bg': '#2a303a', 'btnbar': '#262b33',
        'prog_done_bg': '#1d3a28', 'prog_done_fg': '#7ee787',
        'prog_bg': '#1e2229', 'hint_bg': '#3a3625', 'hint_fg': '#e8e2c8',
        'found_bg': '#6b6b1e', 'title': '#4d8df0',
    },
}
# активная тема (глобальная ссылка — читается из конфига)
THEME_NAME = 'light'
T = THEMES[THEME_NAME]

# короткие алиасы (совместимость со старым кодом)
def _sync_aliases():
    global C_BG, C_PANEL, C_HEAD, C_ACCENT, C_DANGER, C_OK, C_WARN
    global C_LOG_BG, C_LOG_FG, C_ZEBRA, C_BORDER
    C_BG = T['bg']; C_PANEL = T['panel']; C_HEAD = T['head']
    C_ACCENT = T['accent']; C_DANGER = T['danger']; C_OK = T['ok']
    C_WARN = T['warn']; C_LOG_BG = T['log_bg']; C_LOG_FG = T['log_fg']
    C_ZEBRA = T['zebra']; C_BORDER = T['border']
_sync_aliases()

def hint(widget, text):
    tt = tk.Toplevel(widget)
    tt.withdraw()
    tt.overrideredirect(True)
    lbl = tk.Label(tt, text=text, justify='left', wraplength=380,
                   bg=T['hint_bg'], fg=T['hint_fg'], relief='solid', borderwidth=1,
                   font=('Segoe UI', 9), padx=6, pady=4)
    lbl.pack()
    def enter(e):
        tt.deiconify()
        x = widget.winfo_rootx() + 15
        y = widget.winfo_rooty() + widget.winfo_height() + 5
        tt.geometry('+%d+%d' % (x, y))
    def leave(e):
        tt.withdraw()
    widget.bind('<Enter>', enter)
    widget.bind('<Leave>', leave)

class App:
    def __init__(self, root):
        self.root = root
        root.title('Утилита переноса объектов между картами (w3x2lni) — v5')
        root.geometry('1180x820')
        root.configure(bg=C_BG)
        self.cfg = {}
        self.stage_vars = {}
        self.q = queue.Queue()
        self.running = False
        open('M_init.txt', 'a').write('style;')
        self._style()
        open('M_init.txt', 'a').write('build;')
        self._build()
        open('M_init.txt', 'a').write('load;')
        self._load_cfg()
        open('M_init.txt', 'a').write('after;')
        self.root.after(100, self._poll_log)

    def _style(self):
        # 18.09 (v5): все цвета из активной темы T
        st = ttk.Style()
        st.theme_use('clam')
        st.configure('TLabelframe', background=T['panel'], borderwidth=1,
                     relief='solid', bordercolor=T['border'])
        st.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground=T['label'])
        st.configure('TFrame', background=T['panel'])
        st.configure('BtnBar.TFrame', background=T['btnbar'])
        st.configure('TLabel', background=T['panel'], font=('Segoe UI', 10), foreground=T['label'])
        st.configure('TCheckbutton', background=T['panel'], font=('Segoe UI', 10))
        st.map('TCheckbutton', foreground=[('active', T['accent'])])
        st.configure('TRadiobutton', background=T['panel'], font=('Segoe UI', 10))
        st.map('TRadiobutton', foreground=[('active', T['accent'])])
        st.configure('TButton', font=('Segoe UI', 10), padding=(10, 5))
        st.map('TButton', background=[('active', T['btnbar'])])
        st.configure('TEntry', padding=3, fieldbackground=T['entry_bg'],
                     foreground=T['entry_fg'], insertcolor=T['entry_fg'])
        # зебра для Treeview
        st.configure('Treeview', background=T['panel'], fieldbackground=T['panel'],
                     foreground=T['entry_fg'], font=('Segoe UI', 10), rowheight=26,
                     bordercolor=T['border'])
        st.map('Treeview', background=[('selected', T['sel_bg'])],
               foreground=[('selected', T['sel_fg'])])
        st.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'),
                     background=T['heading_bg'], foreground=T['label'], padding=(6, 5))
        st.map('Treeview.Heading', background=[('active', T['border'])])
        # кнопки: крупнее (v5)
        st.configure('Accent.TButton', font=('Segoe UI', 10, 'bold'), foreground='white', padding=(14, 7))
        st.map('Accent.TButton', background=[('active', '#1d5bc4'), ('!active', T['accent'])])
        st.configure('Big.TButton', font=('Segoe UI', 11, 'bold'), foreground='white', padding=(20, 9))
        st.map('Big.TButton', background=[('active', '#1d5bc4'), ('!active', T['accent'])])
        st.configure('BigOk.TButton', font=('Segoe UI', 11, 'bold'), foreground='white', padding=(20, 9))
        st.map('BigOk.TButton', background=[('active', '#156a2e'), ('!active', T['ok'])])
        st.configure('BigWarn.TButton', font=('Segoe UI', 11, 'bold'), foreground='white', padding=(20, 9))
        st.map('BigWarn.TButton', background=[('active', '#9a6a12'), ('!active', T['warn'])])
        st.configure('Danger.TButton', font=('Segoe UI', 11, 'bold'), foreground='white', padding=(14, 7))
        st.map('Danger.TButton', background=[('active', '#96281b'), ('!active', T['danger'])])
        st.configure('Loop.TButton', font=('Segoe UI', 11, 'bold'), foreground='white', padding=(14, 7))
        st.map('Loop.TButton', background=[('active', '#166b2f'), ('!active', T['ok'])])
        st.configure('Theme.TButton', font=('Segoe UI', 9, 'bold'), padding=(8, 4))

    def _apply_theme(self, name):
        # 18.09 (v5): переключение светлой/тёмной темы на лету
        global THEME_NAME, T, C_BG, C_PANEL, C_HEAD, C_ACCENT, C_DANGER
        global C_OK, C_WARN, C_LOG_BG, C_LOG_FG, C_ZEBRA, C_BORDER
        THEME_NAME = name
        T = THEMES[name]
        C_BG = T['bg']; C_PANEL = T['panel']; C_HEAD = T['head']
        C_ACCENT = T['accent']; C_DANGER = T['danger']; C_OK = T['ok']
        C_WARN = T['warn']; C_LOG_BG = T['log_bg']; C_LOG_FG = T['log_fg']
        C_ZEBRA = T['zebra']; C_BORDER = T['border']
        self._style()
        self.root.configure(bg=C_BG)
        # перекрасить существующие виджеты
        try:
            self._retheme()
        except Exception:
            pass

    def _build(self):
        # 18.09: тёмная шапка с названием и статусом
        head = tk.Frame(self.root, bg=C_HEAD, height=44)
        head.pack(fill='x')
        head.pack_propagate(False)
        tk.Label(head, text='  Утилита переноса объектов', bg=C_HEAD, fg=T['head_fg'],
                 font=('Segoe UI', 13, 'bold')).pack(side='left', padx=8)
        self.lbl_sub = tk.Label(head, text='w3x2lni', bg=C_HEAD, fg=T['head_sub'],
                 font=('Segoe UI', 10))
        self.lbl_sub.pack(side='left', padx=4)
        self.head_status = tk.Label(head, text='', bg=C_HEAD, fg=T['ok'],
                                    font=('Segoe UI', 10))
        self.head_status.pack(side='right', padx=12)
        # 18.09 (v5): переключатель темы
        self.head = head
        self.b_theme = tk.Label(head, text='Тема: светлая', bg=C_HEAD, fg=T['head_sub'],
                                font=('Segoe UI', 9, 'underline'), cursor='hand2')
        self.b_theme.pack(side='right', padx=(0, 12))
        self.b_theme.bind('<Button-1>', self._toggle_theme)


        # верх: пути
        top = ttk.Labelframe(self.root, text=' 1. Карты ')
        top.pack(fill='x', padx=10, pady=(8, 4))
        top.configure(style='TLabelframe')
        ttk.Label(top, text='Источник (донор):').grid(row=0, column=0, sticky='w', padx=6, pady=3)
        self.e_src = ttk.Entry(top, width=62)
        self.e_src.grid(row=0, column=1, padx=4, pady=3)
        hint(self.e_src, 'Папка карты-донора в lni-формате (распакованная w3x2lni).\nНапример: G:\\w3x2lni\\UFS10')
        ttk.Button(top, text='...', width=3, command=lambda: self._pick(self.e_src)).grid(row=0, column=2)
        ttk.Label(top, text='Приёмник:').grid(row=1, column=0, sticky='w', padx=6, pady=3)
        self.e_tgt = ttk.Entry(top, width=62)
        self.e_tgt.grid(row=1, column=1, padx=4, pady=3)
        hint(self.e_tgt, 'Папка карты, КОТОРУЮ ДОПОЛНЯЕМ.\nСнапшоты изменяемых файлов делаются автоматически.')
        ttk.Button(top, text='...', width=3, command=lambda: self._pick(self.e_tgt)).grid(row=1, column=2)
        ttk.Label(top, text='Название переноса:').grid(row=2, column=0, sticky='w', padx=6, pady=3)
        self.e_name = ttk.Entry(top, width=62)
        self.e_name.grid(row=2, column=1, padx=4, pady=3)
        hint(self.e_name, 'Подпись для плана и манифеста (например "UFS герои -> LoW").')
        # середина
        mid = ttk.Frame(self.root)
        mid.pack(fill='both', expand=True, padx=10, pady=4)
        mid.configure(style='TFrame')

        # левая колонка: этапы
        left = ttk.Labelframe(mid, text=' 2. Этапы ')
        left.pack(side='left', fill='y', padx=(0, 6), pady=4)
        self.stage_vars = {}
        for i, s in enumerate(STAGES):
            v = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(left, text=STAGE_LABELS[s], variable=v)
            cb.grid(row=i, column=0, sticky='w', padx=6, pady=1)
            hint(cb, STAGE_HINTS[s])
            self.stage_vars[s] = v
        self.stage_vars['geometry'].set(False)
        self.stage_vars['testspawn'].set(False)

        opt = ttk.Labelframe(left, text=' Опции ')
        opt.grid(row=len(STAGES), column=0, sticky='we', padx=4, pady=8)
        self.v_dry = tk.BooleanVar(value=True)
        c1 = ttk.Checkbutton(opt, text='Dry-run (без записи)', variable=self.v_dry)
        c1.pack(anchor='w', padx=6, pady=2)
        hint(c1, 'Прогон всего пайплайна без изменения приёмника.\nВсегда запускай сначала это!')
        self.v_stop = tk.BooleanVar(value=True)
        c2 = ttk.Checkbutton(opt, text='Стоп при ошибке', variable=self.v_stop)
        c2.pack(anchor='w', padx=6, pady=2)
        hint(c2, 'Останавливает прогон на первом ошибочном этапе.\nОткат: кнопка «Откат» (снапшоты).')
        # 18.09: новые настройки
        self.v_sound = tk.BooleanVar(value=False)
        c6 = ttk.Checkbutton(opt, text='Звук по завершении', variable=self.v_sound)
        c6.pack(anchor='w', padx=6, pady=2)
        hint(c6, 'Системный звук, когда прогон завершён (удобно для фоновых прогонов).')
        self.v_autolog = tk.BooleanVar(value=False)
        c7 = ttk.Checkbutton(opt, text='Авто-открыть лог после прогона', variable=self.v_autolog)
        c7.pack(anchor='w', padx=6, pady=2)
        hint(c7, 'После завершения прогона открыть logs/transfer.log.')

        # правая колонка: настройки (скролл)
        right_wrap = ttk.Frame(mid)
        right_wrap.pack(side='left', fill='both', expand=True, pady=4)
        canvas = tk.Canvas(right_wrap, bg=C_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(right_wrap, orient='vertical', command=canvas.yview)
        right = ttk.Frame(canvas)
        right.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=right, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        right.columnconfigure(0, weight=1)

        rf = ttk.Labelframe(right, text=' 3. Объекты ')
        rf.pack(fill='x', padx=6, pady=4)
        ttk.Label(rf, text='Режим переноса объектов:').pack(anchor='w', padx=6, pady=(6, 0))
        self.mode_var = tk.StringVar(value='smart')
        hints_mode = {
            'smart': 'Конфликтный/изменённый стандарт -> новый ID с наследованием от стандарта. Безопасный дефолт.',
            'replace_std': 'Поля изменённого стандарта ВПИСЫВАЮТСЯ в стандартную секцию приёмника (без нового ID). Как в v6.',
            'custom_only': 'Переносить только кастомные объекты. Стандартные объекты источника не трогаются.',
        }
        for mv, ml in [('smart', 'Умный — новый ID + наследование (рекомендую)'),
                       ('replace_std', 'Заменять стандарт — поля вписать поверх'),
                       ('custom_only', 'Только кастомные — стандарт не трогать')]:
            rb = ttk.Radiobutton(rf, text=ml, value=mv, variable=self.mode_var)
            rb.pack(anchor='w', padx=6)
            hint(rb, hints_mode[mv])
        ttk.Label(rf, text='Корни deps (ID героев/предметов, через запятую):').pack(anchor='w', padx=6, pady=(8, 0))
        self.e_roots = ttk.Entry(rf, width=55)
        self.e_roots.pack(fill='x', padx=6)
        hint(self.e_roots, 'С чего начинать тянуть зависимости.\nНапример: Hgam, Hpal — герои. Пусто = вся таблица.')
        self.v_aexp = tk.BooleanVar(value=False)
        c3 = ttk.Checkbutton(rf, text='Авто-расширение deps из кода (дамми и т.д.)', variable=self.v_aexp)
        c3.pack(anchor='w', padx=6, pady=(6, 6))
        hint(c3, 'Вырезка кода находит литералы ID, которых нет в deps\n(дамми-способности и т.п.) и добавляет их в перенос.\nРаботает с кнопкой «Полный цикл».')

        cf = ttk.Labelframe(right, text=' 4. Таблицы ')
        cf.pack(fill='x', padx=6, pady=4)
        ttk.Label(cf, text='Переносить таблицы (через запятую):').pack(anchor='w', padx=6, pady=(6, 0))
        self.e_tables = ttk.Entry(cf, width=55)
        self.e_tables.pack(fill='x', padx=6)
        hint(self.e_tables, 'unit, ability, buff, item, upgrade, doodad, destructable')
        ttk.Label(cf, text='Пропускать (w3i, misc):').pack(anchor='w', padx=6, pady=(6, 0))
        self.e_skip = ttk.Entry(cf, width=55)
        self.e_skip.pack(fill='x', padx=6, pady=(0, 6))
        hint(self.e_skip, 'w3i — настройки карты (слоты, игроки), misc — константы.\nЭти таблицы НЕ переносят (ломают карту).')

        imf = ttk.Labelframe(right, text=' 5. Импорт ассетов ')
        imf.pack(fill='x', padx=6, pady=4)
        ttk.Label(imf, text='НЕ импортировать (по одному в строке, подстрока в пути):').pack(anchor='w', padx=6, pady=(6, 0))
        self.t_excl = tk.Text(imf, height=5, font=('Consolas', 9),
                              bg=T['entry_bg'], fg=T['entry_fg'],
                              insertbackground=T['entry_fg'])
        self.t_excl.pack(fill='x', padx=6, pady=(0, 6))
        hint(self.t_excl, 'Ассеты с этими словами в пути не копируются.\nДефолт уже защищает миникарту, лоадскрин, скин.\nПример: LoadingScreen, minimap, war3mapMap.blp')

        gf2 = ttk.Labelframe(right, text=' 6. Код и геометрия ')
        gf2.pack(fill='x', padx=6, pady=(4, 6))
        self.v_geom = tk.BooleanVar(value=False)
        c4 = ttk.Checkbutton(gf2, text='Геометрия (декор/юниты — РЕДКО!)', variable=self.v_geom)
        c4.pack(anchor='w', padx=6, pady=(6, 0))
        hint(c4, 'Вставка декора/юнитов в doo приёмника со сдвигом offset.\nВключай только для переноса ландшафта! Повторный прогон задвоит декор.')
        gfr = ttk.Frame(gf2)
        gfr.pack(fill='x', padx=12)
        ttk.Label(gfr, text='offset dx:').pack(side='left')
        self.e_dx = ttk.Entry(gfr, width=9)
        self.e_dx.pack(side='left', padx=2)
        ttk.Label(gfr, text='dy:').pack(side='left')
        self.e_dy = ttk.Entry(gfr, width=9)
        self.e_dy.pack(side='left', padx=4)
        hint(gfr, 'Сдвиг координат декора (dx, dy) при вставке в приёмник.')
        self.v_ts = tk.BooleanVar(value=False)
        # 18.09: B-литералы (баффы) — замена в коде
        self.v_allowb = tk.BooleanVar(value=True)
        c8 = ttk.Checkbutton(gf2, text='Заменять B-литералы (баффы) в коде', variable=self.v_allowb)
        c8.pack(anchor='w', padx=6, pady=(4, 0))
        hint(c8, 'Баффы в JASS-коде вызываются равкодами Bxxx.\nПосле переноса баффы получают новые ID — код надо обновить.\nВыключи, если хочешь заменить их вручную позже.')
        c5 = ttk.Checkbutton(gf2, text='TestSpawn (спавн героев в игре)', variable=self.v_ts)
        c5.pack(anchor='w', padx=6, pady=(4, 0))
        hint(c5, 'Генерирует 90-TestSpawn.j: создаёт перенесённых героев в регионе спавна для проверки.')
        ttk.Label(gf2, text='Герои TestSpawn (пусто = все из deps):').pack(anchor='w', padx=6, pady=(4, 0))
        self.e_ts = ttk.Entry(gf2, width=55)
        self.e_ts.pack(fill='x', padx=6, pady=(0, 6))

        # кнопки (v5: ДВА РЯДА — иначе обрезаются за краем)
        btns = ttk.Frame(self.root, style='TFrame')
        btns.pack(fill='x', padx=10, pady=4)
        btns2r = ttk.Frame(self.root, style='TFrame')
        btns2r.pack(fill='x', padx=10, pady=(0, 4))
        def sep():
            tk.Frame(btns, width=1, bg=C_BORDER).pack(side='left', fill='y', padx=5, pady=2)
        def sep2():
            tk.Frame(btns2r, width=1, bg=C_BORDER).pack(side='left', fill='y', padx=5, pady=2)
        b1 = ttk.Button(btns, text='Сохранить конфиг', command=self._save_cfg)
        b1.pack(side='left', padx=3)
        hint(b1, 'Записать все настройки в transfer_config.json')
        sep()
        b2 = ttk.Button(btns, text='План', command=lambda: self._run(['--plan']))
        b2.pack(side='left', padx=3)
        hint(b2, 'Показать что будет делать прогон (без изменений).')
        b3 = ttk.Button(btns, text='Dry-run всего', command=lambda: self._run(['--dry-run']))
        b3.pack(side='left', padx=3)
        hint(b3, 'Прогнать ВСЕ этапы без записи. Смотри журнал — что перенесётся.')
        b4 = ttk.Button(btns, text='ЗАПУСК (запись!)', style='Danger.TButton', command=self._run_all)
        b4.pack(side='left', padx=3)
        hint(b4, 'Боевой прогон с записью в приёмник. Снапшоты делаются автоматически,\nоткат — кнопка «Откат».')
        b5 = ttk.Button(btns, text='Полный цикл (повторы)', style='Loop.TButton', command=self._run_loop)
        sep()
        b5.pack(side='left', padx=3)
        hint(b5, 'deps->mapping->tables->import->code_cut повторами, пока код находит\nновые дамми (макс 5 итераций). Для переноса героев из монолита.')
        b6 = ttk.Button(btns, text='Статус', command=lambda: self._run(['--status']))
        b6.pack(side='left', padx=3)
        hint(b6, 'Какие этапы уже пройдены (state).')
        b7 = ttk.Button(btns, text='Откат', command=lambda: self._run(['--rollback']))
        b7.pack(side='left', padx=3)
        hint(b7, 'Восстановить файлы из снапшота последнего этапа.')
        b7b = ttk.Button(btns, text='Сброс прогресса', command=lambda: self._run(['--reset']))
        b7b.pack(side='left', padx=3)
        hint(b7b, 'Сбросить список пройденных этапов (state).\nНужен после смены пары карт или для повторного прогона.\nState также сбрасывается АВТОМАТИЧЕСКИ при смене source/target.')
        sep()
        b8 = ttk.Button(btns2r, text='Манифест', command=self._manifest)
        b8.pack(side='left', padx=3)
        hint(b8, 'Отчёт о переносе в mdlog/transfer/ (что перенесено, конфликты ID).')
        b8b = ttk.Button(btns2r, text='Верификация', command=self._verify_only)
        b8b.pack(side='left', padx=3)
        hint(b8b, 'Только проверка приёмника БЕЗ переноса: битые ссылки,\nдубли секций, циклы _parent, imp.ini, баланс скобок .j.\nБезопасно — ничего не пишет в карту.')
        b8c = ttk.Button(btns2r, text='Чистка...', command=self._cleanup_window)
        b8c.pack(side='left', padx=3)
        b8d = ttk.Button(btns2r, text='Починить таблицы', command=self._repair_main)
        b8e = ttk.Button(btns2r, text='Триггеры...', command=self._triggers_window)
        b8e.pack(side='left', padx=3)
        hint(b8e, 'Отдельный перенос триггеров: выбрать подпапки\n(героев/системы) и перенести только их.\nЗапись по правилу v4: папки в корень trigger/.')
        b8d.pack(side='left', padx=3)
        hint(b8d, 'Починка таблиц ПРИЁМНИКА (table/*.ini): self-parent,\nбитые _parent, дубли секций, разбаланс [=[ ]=].\nПервый клик = скан, второй = починка (бэкап + лог).')
        hint(b8c, 'Чистка карты: неиспользуемые объекты, битые равкоды,\nнеудаляемые способности (по суффиксу/равкоду).\nСкан -> список -> подтверждение -> удаление. Никаких молчаливых удалений.')
        sep()
        sep2()
        b9 = ttk.Button(btns2r, text='Открыть папку', command=lambda: os.startfile(HERE))
        b9.pack(side='left', padx=3)

        # лог (v3: панель инструментов + поиск)
        lf = ttk.Labelframe(self.root, text=' Журнал ')
        lf.pack(fill='both', expand=True, padx=10, pady=(4, 4))
        lbar = ttk.Frame(lf)
        lbar.pack(fill='x', padx=2, pady=(2, 0))
        ttk.Label(lbar, text='Поиск:').pack(side='left', padx=(4, 2))
        self.e_find = ttk.Entry(lbar, width=28)
        self.e_find.pack(side='left')
        hint(self.e_find, 'Подсветить строки журнала (Enter). Esc — сброс.')
        self.e_find.bind('<Return>', self._log_find)
        self.e_find.bind('<Escape>', lambda e: self._log_find_clear())
        ttk.Button(lbar, text='Очистить', width=9, command=lambda: self.log.delete('1.0', 'end')).pack(side='left', padx=4)
        ttk.Button(lbar, text='Копировать всё', width=13, command=self._log_copy).pack(side='left', padx=2)
        ttk.Button(lbar, text='А-', width=3, command=lambda: self._log_font(-1)).pack(side='left', padx=(8, 1))
        ttk.Button(lbar, text='А+', width=3, command=lambda: self._log_font(1)).pack(side='left', padx=1)
        self.log_size = 9
        self.log = scrolledtext.ScrolledText(lf, height=9, font=('Consolas', 9),
                                             bg=C_LOG_BG, fg=C_LOG_FG, insertbackground='white')
        self.log.pack(fill='both', expand=True, padx=2, pady=2)
        self.log.tag_configure('err', foreground='#ff6b6b')
        self.log.tag_configure('ok', foreground='#7ee787')
        self.log.tag_configure('warn', foreground=T['warn'])
        self.log.tag_configure('found', background=T['found_bg'])
        # 18.09 (v5): выделение текста в журнале
        self.log.configure(selectbackground=T['sel_bg'], selectforeground=T['sel_fg'],
                           spacing1=2, spacing3=2)
        self._progress_panel(self.root)

        # статусбар
        self.status = tk.Label(self.root, text='готов', anchor='w', bg=T['status_bg'], fg=T['status_fg'],
                               font=('Segoe UI', 9), padx=8, pady=3)
        self.status.pack(fill='x', side='bottom')

    def _toggle_theme(self, e=None):
        # 18.09 (v5): светлая <-> тёмная
        self._apply_theme('dark' if THEME_NAME == 'light' else 'light')
        self.b_theme.config(text='Тема: ' + ('тёмная' if THEME_NAME == 'dark' else 'светлая'))
        self.cfg.setdefault('gui', {})['theme'] = THEME_NAME
        io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))


    def _retheme(self):
        # 18.09 (v5): перекраска виджетов после смены темы
        self.root.configure(bg=C_BG)
        self.head.configure(bg=C_HEAD)
        for w in self.head.winfo_children():
            if w is not self.b_theme:
                w.configure(bg=C_HEAD)
        try:
            self.lbl_sub.configure(fg=T['head_sub'])
        except Exception:
            pass
        self.head_status.configure(fg=T['ok'])
        self.b_theme.configure(bg=C_HEAD,
                               fg='#8fa4bd' if THEME_NAME == 'light' else '#6f8fb8')
        self.b_theme.config(text='Тема: ' + ('светлая' if THEME_NAME == 'light' else 'тёмная'))
        # лог
        self.log.configure(bg=C_LOG_BG, fg=C_LOG_FG, insertbackground=T['entry_fg'])
        # прогресс-панель
        # 18.09: помечаю done-метки флагом, чтобы не сравнивать цвета
        for s2, lbl in self.prog_labels.items():
            done_now = str(lbl.cget('foreground')) == str(self._last_done_fg) if getattr(self, '_last_done_fg', None) else False
            if done_now:
                lbl.configure(bg=T['prog_done_bg'], fg=T['prog_done_fg'])
            else:
                lbl.configure(bg=T['prog_bg'], fg=T['muted'])
        self._last_done_fg = T['prog_done_fg']
        # статусбар
        self.status.configure(bg=T['status_bg'], fg=T['status_fg'])

    def _progress_panel(self, parent):
        # 17.09: панель прогресса — чеклист этапов из state
        pf = ttk.Labelframe(parent, text=' Прогресс (state) ')
        pf.pack(fill='x', padx=10, pady=(4, 0))
        row = ttk.Frame(pf)
        row.pack(fill='x', padx=6, pady=4)
        self.prog_labels = {}
        # 18.09 (v6): компактный дизайн — короткие метки
        # стейджей в ОДИН ряд, кнопки справа в той же строке
        SHORT = {
            'mapping': 'Маппинг', 'registry': 'Реестр', 'deps': 'Завис.',
            'tables': 'Таблицы', 'import': 'Импорт', 'code': 'Код',
            'code_cut': 'Вырезка', 'globals': 'Глобалы', 'geometry': 'Геометр.',
            'testspawn': 'Спавн', 'verify': 'Вериф.',
        }
        btns2 = ttk.Frame(row)
        btns2.pack(side='right')
        ttk.Button(btns2, text='Обновить', width=9, command=self._refresh_progress).pack(side='left', padx=1)
        ttk.Button(btns2, text='Сброс', width=7, command=lambda: self._run(['--reset'])).pack(side='left', padx=1)
        ttk.Button(btns2, text='Журнал', width=8, command=self._open_log).pack(side='left', padx=1)
        ttk.Button(btns2, text='Манифест', width=9, command=self._open_manifest).pack(side='left', padx=1)
        for i, s in enumerate(STAGES):
            lbl = tk.Label(row, text=' ' + SHORT.get(s, STAGE_LABELS[s]) + ' ', fg=T['muted'], bg=T['prog_bg'],
                           font=('Segoe UI', 8))
            lbl.pack(side='left', padx=1)
            self.prog_labels[s] = lbl
        hint(pf, 'Прогресс привязан к паре карт: смена источника/приёмника\nавтоматически сбрасывает список пройденных этапов.\nНесколько конфигов = независимые прогоны (свой state у каждого).')

    def _refresh_progress(self):
        # читает state рядом с конфигом
        import json as _json
        try:
            sp = os.path.join(HERE, 'transfer_state.json')
            if not os.path.exists(sp):
                for lbl in self.prog_labels.values():
                    lbl.config(fg=T['muted'])
                return
            st = _json.load(io.open(sp, 'rb'))
            pair = (self.e_src.get().strip() + '->' + self.e_tgt.get().strip())
            done = set(st.get('completed', [])) if st.get('pair') == pair else set()
            for s, lbl in self.prog_labels.items():
                if s in done:
                    lbl.config(bg=T['prog_done_bg'], fg=T['prog_done_fg'])
                else:
                    lbl.config(bg=T['prog_bg'], fg=T['muted'])
        except Exception:
            pass

    def _log_find(self, event=None):
        # 18.09: подсветка строк журнала по подстроке
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
        self.root.clipboard_clear()
        self.root.clipboard_append(txt)
        self.status.config(text='журнал скопирован в буфер (%d символов)' % len(txt))

    def _apply_log_font(self):
        # 18.09: применить размер шрифта журнала
        self.log.configure(font=('Consolas', self.log_size))

    def _log_font(self, delta):
        # 18.09: А+/А- — размер шрифта журнала
        self.log_size = max(7, min(16, self.log_size + delta))
        self._apply_log_font()

    def _open_log(self):
        p = os.path.join(HERE, 'logs', 'transfer.log')
        if os.path.exists(p):
            os.startfile(p)
        else:
            messagebox.showinfo('Журнал', 'Журнала пока нет — запусти прогон.')

    def _open_manifest(self):
        import glob as _g
        d = os.path.join(HERE, 'logs')
        fs = sorted(_g.glob(os.path.join(d, 'transfer-manifest-*.md')))
        if fs:
            os.startfile(fs[-1])
        else:
            messagebox.showinfo('Манифест', 'Манифестов пока нет — запусти перенос.')

    # ---------- логика ----------
    def _pick(self, entry):
        d = filedialog.askdirectory()
        if d:
            entry.delete(0, 'end')
            entry.insert(0, d)

    def _log(self, msg, tag=None):
        self.q.put((msg, tag))

    def _poll_log(self):
        while not self.q.empty():
            msg, tag = self.q.get()
            if msg == '__done__':
                self.running = False
                self.status.config(text='готов')
                self.head_status.config(text='готов', fg=T['ok'])
                self._refresh_progress()
                # 18.09: звук + автолог
                if self.v_sound.get():
                    try:
                        import winsound
                        winsound.MessageBeep(winsound.MB_OK)
                    except Exception:
                        pass
                if self.v_autolog.get():
                    try:
                        self._open_log()
                    except Exception:
                        pass
                continue
            self.log.insert('end', msg + '\n', tag or ())
            self.log.see('end')
        self.root.after(100, self._poll_log)

    def _collect_cfg(self):
        cfg = self.cfg
        cfg['source'] = self.e_src.get().strip()
        cfg['target'] = self.e_tgt.get().strip()
        cfg['name'] = self.e_name.get().strip()
        cfg['tables'] = [t.strip() for t in self.e_tables.get().split(',') if t.strip()]
        cfg['skip_tables'] = [t.strip() for t in self.e_skip.get().split(',') if t.strip()]
        cfg.setdefault('deps', {})['roots'] = [t.strip() for t in self.e_roots.get().split(',') if t.strip()]
        cfg.setdefault('mapping', {})['mode'] = self.mode_var.get()
        cfg['geometry']['enabled'] = self.v_geom.get()
        try:
            dx = float(self.e_dx.get() or 0)
            dy = float(self.e_dy.get() or 0)
        except ValueError:
            dx = dy = 0.0
        cfg['geometry']['offset'] = [dx, dy] if (dx or dy) else None
        cfg['testspawn']['enabled'] = self.v_ts.get()
        cfg['testspawn']['heroes'] = [t.strip() for t in self.e_ts.get().split(',') if t.strip()]
        cfg['import']['exclude_paths'] = [l.strip() for l in self.t_excl.get('1.0', 'end').splitlines() if l.strip()]
        cfg.setdefault('code_cut', {})['auto_expand'] = self.v_aexp.get()
        cfg['safety']['stop_on_error'] = self.v_stop.get()
        cfg.setdefault('code', {})['allow_b'] = self.v_allowb.get()
        # 18.09: настройки GUI
        cfg.setdefault('gui', {})['sound_on_done'] = self.v_sound.get()
        cfg['gui']['autolog'] = self.v_autolog.get()
        cfg['gui']['log_font'] = self.log_size
        try:
            cfg['gui']['geometry'] = self.root.geometry()
        except Exception:
            pass
        # 17.09: этапы из чекбоксов -> отдельный словарь stage_enabled
        # (ключ 'tables' конфликтовал со списком таблиц!)
        se = cfg.setdefault('stage_enabled', {})
        for s in STAGES:
            se[s] = self.stage_vars[s].get()
        return cfg

    def _save_cfg(self):
        self._collect_cfg()
        io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        self._log('конфиг сохранён: ' + CFG, 'ok')

    def _load_cfg(self):
        if not os.path.exists(CFG):
            return
        self.cfg = json.load(io.open(CFG, 'rb'))
        self.e_src.delete(0, 'end'); self.e_src.insert(0, self.cfg.get('source', ''))
        self.e_tgt.delete(0, 'end'); self.e_tgt.insert(0, self.cfg.get('target', ''))
        self.e_name.delete(0, 'end'); self.e_name.insert(0, self.cfg.get('name', ''))
        self.e_tables.delete(0, 'end'); self.e_tables.insert(0, ', '.join(self.cfg.get('tables', [])))
        self.e_skip.delete(0, 'end'); self.e_skip.insert(0, ', '.join(self.cfg.get('skip_tables', [])))
        self.e_roots.delete(0, 'end'); self.e_roots.insert(0, ', '.join(self.cfg.get('deps', {}).get('roots', [])))
        self.mode_var.set(self.cfg.get('mapping', {}).get('mode', 'smart'))
        self.v_geom.set(self.cfg.get('geometry', {}).get('enabled', False))
        off = self.cfg.get('geometry', {}).get('offset') or [0, 0]
        self.e_dx.delete(0, 'end'); self.e_dx.insert(0, str(off[0]))
        self.e_dy.delete(0, 'end'); self.e_dy.insert(0, str(off[1]))
        self.v_ts.set(self.cfg.get('testspawn', {}).get('enabled', False))
        self.e_ts.delete(0, 'end'); self.e_ts.insert(0, ', '.join(self.cfg.get('testspawn', {}).get('heroes', [])))
        self.v_aexp.set(self.cfg.get('code_cut', {}).get('auto_expand', False))
        self.v_allowb.set(self.cfg.get('code', {}).get('allow_b', True))
        self.t_excl.delete('1.0', 'end')
        self.t_excl.insert('1.0', chr(10).join(self.cfg.get('import', {}).get('exclude_paths', [])))
        # 18.09: настройки GUI
        g = self.cfg.get('gui', {})
        self.v_sound.set(g.get('sound_on_done', False))
        self.v_autolog.set(g.get('autolog', False))
        self.log_size = g.get('log_font', 9)
        self._apply_log_font()
        # 18.09 (v5): тема из конфига
        th = g.get('theme', 'light')
        if th in THEMES and th != THEME_NAME:
            self._apply_theme(th)
            self.b_theme.config(text='Тема: ' + ('тёмная' if THEME_NAME == 'dark' else 'светлая'))
        geo = g.get('geometry')
        if geo:
            try:
                self.root.geometry(geo)
            except Exception:
                pass

    def _load_cfg_btn(self):
        self._load_cfg()
        self._log('конфиг загружен', 'ok')

    def _run_all(self):
        self._save_cfg()
        args = ['--all'] if not self.v_dry.get() else ['--dry-run']
        self._run(args)

    def _run_loop(self):
        self._save_cfg()
        self._run(['--loop'])

    def _verify_only(self):
        # 17.09: верификация приёмника без переноса — прямой вызов
        # stage_verify.py (не этап, отдельный запуск)
        if self.running:
            messagebox.showwarning('Занято', 'Прогон уже выполняется — дождись завершения.')
            return
        self._collect_cfg()
        io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        cmd = [sys.executable, '-u', os.path.join(HERE, 'stage_verify.py'), CFG]
        self._log('>>> Верификация приёмника (без переноса)', 'ok')
        self.running = True
        self.status.config(text='верификация...')
        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def _triggers_window(self):
        # 18.09: отдельный перенос триггеров — выбор подпапок
        win = tk.Toplevel(self.root)
        win.title('Перенос триггеров')
        win.geometry('760x560')
        win.configure(bg=C_BG)

        src = self.e_src.get().strip()
        trig = os.path.join(src, 'trigger')
        top = ttk.Labelframe(win, text=' Подпапки триггеров источника ')
        top.pack(fill='both', expand=True, padx=8, pady=6)
        ttk.Label(top, text=src).pack(anchor='w', padx=6, pady=2)

        mid = ttk.Frame(top)
        mid.pack(fill='both', expand=True, padx=4, pady=4)
        lb = tk.Listbox(mid, selectmode='extended', exportselection=False,
                        font=('Consolas', 11), bg=T['entry_bg'], fg=T['entry_fg'],
                        selectbackground=T['sel_bg'], selectforeground=T['sel_fg'],
                        activestyle='none')
        sb = ttk.Scrollbar(mid, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        subs = []
        if os.path.isdir(trig):
            for x in sorted(os.listdir(trig)):
                if os.path.isdir(os.path.join(trig, x)):
                    n = sum(1 for f in os.listdir(os.path.join(trig, x)) if f.endswith('.j'))
                    subs.append((x, n))
        for x, n in subs:
            lb.insert('end', '%s  (%d .j)' % (x, n))
        hint(lb, 'Выдели подпапки для переноса (Ctrl/Shift — как в проводнике).\nПусто = перенести ВСЁ.')

        info = ttk.Label(top, text='')
        info.pack(anchor='w', padx=6)

        btns = ttk.Frame(win)
        btns.pack(fill='x', padx=8, pady=6)
        ttk.Button(btns, text='Выделить всё', command=lambda: lb.select_set(0, 'end')).pack(side='left', padx=3)
        ttk.Button(btns, text='Снять выделение', command=lambda: lb.select_clear(0, 'end')).pack(side='left', padx=3)

        def do_transfer():
            sel = [lb.get(i).rsplit('  (', 1)[0] for i in lb.curselection()]
            cfgp = self._cfg_path()
            cfg = json.load(io.open(cfgp, 'rb'))
            cfg.setdefault('code', {})['only_dirs'] = sel
            io.open(cfgp, 'wb').write(json.dumps(cfg, indent=2, ensure_ascii=False).encode('utf-8'))
            self._log_add('Перенос триггеров: %d подпапок -> %s' % (len(sel) if sel else 'ВСЁ', ', '.join(sel[:8]) + ('...' if len(sel) > 8 else '')))
            win.destroy()
            # 18.09: цепочка code -> verify (один воркер, без 'Занято')
            self._run([['--stage', 'code'], ['--stage', 'verify']])

        ttk.Button(btns, text='ПЕРЕНЕСТИ ВЫБРАННЫЕ', style='BigOk.TButton', command=do_transfer).pack(side='left', padx=8)
        ttk.Button(btns, text='Закрыть', command=win.destroy).pack(side='right', padx=3)

        def upd_info(e=None):
            n = len(lb.curselection())
            files = 0
            for i in lb.curselection():
                files += subs[i][1]
            info.configure(text='Выбрано: %d папок, %d файлов .j' % (n, files) if n else 'Не выбрано — перенесётся ВСЁ (%d файлов)' % sum(x[1] for x in subs))
        lb.bind('<<ListboxSelect>>', upd_info)
        upd_info()

    def _cleanup_window(self):
        # 17.09: окно чистки карты
        win = tk.Toplevel(self.root)
        win.title('Чистка карты')
        win.geometry('980x640')
        win.configure(bg=C_BG)

        top = ttk.Labelframe(win, text=' Карта ')
        top.pack(fill='x', padx=8, pady=6)
        ttk.Label(top, text='Папка карты:').grid(row=0, column=0, sticky='w', padx=6, pady=3)
        e_dir = ttk.Entry(top, width=60)
        e_dir.grid(row=0, column=1, padx=4, pady=3)
        e_dir.insert(0, self.e_tgt.get().strip())
        hint(e_dir, 'Папка карты в lni-формате (table/*.ini + trigger/).')
        ttk.Button(top, text='...', width=3, command=lambda: self._pick(e_dir)).grid(row=0, column=2)

        opts = ttk.Labelframe(win, text=' Что чистим ')
        opts.pack(fill='x', padx=8, pady=4)
        v_unused = tk.BooleanVar(value=False)
        v_bad = tk.BooleanVar(value=False)
        v_suf = tk.BooleanVar(value=False)
        v_casc = tk.BooleanVar(value=True)
        cb1 = ttk.Checkbutton(opts, text='Неиспользуемые объекты', variable=v_unused)
        cb1.grid(row=0, column=0, sticky='w', padx=6, pady=2)
        hint(cb1, 'Объекты без ссылок из кода и других объектов.\nСтандартные WC3 и mustuse (Avul, Amov...) не трогаются.')
        cb2 = ttk.Checkbutton(opts, text='Битые равкоды', variable=v_bad)
        cb2.grid(row=1, column=0, sticky='w', padx=6, pady=2)
        hint(cb2, 'Равкод не 4 символа или неверный префикс типа\n(юнит E/H/N/O/U, способность A, бафф B/X, предмет I, улучшение R).')
        cb3 = ttk.Checkbutton(opts, text='По суффиксу редактора', variable=v_suf)
        cb3.grid(row=2, column=0, sticky='w', padx=6, pady=2)
        hint(cb3, 'Способности с суффиксом (убрано)/(Убрано)/не используется\n+ ручной список равкодов в конфиге (cleanup.manual_ids).')
        ttk.Label(opts, text='Каскад:').grid(row=0, column=1, sticky='e', padx=(20, 4))
        ttk.Checkbutton(opts, text='удалять и то, что держалось только на мёртвых (волнами, видно до подтверждения)', variable=v_casc).grid(row=0, column=2, columnspan=2, sticky='w')
        # 18.09: галочки по типам объектов
        ttk.Label(opts, text='Типы:').grid(row=3, column=0, sticky='e', padx=(20, 4))
        tf = ttk.Frame(opts)
        tf.grid(row=3, column=1, columnspan=3, sticky='w')
        self._type_vars = {}
        for i, (tid, tname) in enumerate([('unit', 'Юниты'), ('ability', 'Способности'), ('item', 'Предметы'),
                                          ('buff', 'Баффы'), ('upgrade', 'Улучшения'), ('doodad', 'Декорации'),
                                          ('destructable', 'Разрушаемые')]):
            v = tk.BooleanVar(value=True)
            cb = ttk.Checkbutton(tf, text=tname, variable=v)
            cb.grid(row=0, column=i, padx=3, sticky='w')
            self._type_vars[tid] = v
        hint(tf, 'Фильтр скана: показывать и удалять только отмеченные типы.')

        lst = ttk.Labelframe(win, text=' Скан (выдели строки и подтверди удаление) ')
        lst.pack(fill='both', expand=True, padx=8, pady=4)
        tree = ttk.Treeview(lst, columns=('id', 'type', 'name'), show='headings', height=14,
                            selectmode='extended')
        tree.heading('id', text='Равкод')
        tree.heading('type', text='Тип')
        tree.heading('name', text='Имя / причина')
        tree.column('id', width=90)
        tree.column('type', width=100)
        tree.column('name', width=560)
        tree.pack(side='left', fill='both', expand=True, padx=4, pady=4)
        sb = ttk.Scrollbar(lst, command=tree.yview)
        sb.pack(side='left', fill='y')
        tree.configure(yscrollcommand=sb.set)
        tree.bind('<Control-a>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])
        tree.bind('<Control-A>', lambda e: (tree.selection_set(tree.get_children()), 'break')[1])

        # 18.09: панель кнопок СВЕРХУ (между настройками и списком)
        btns = ttk.Frame(win, style='BtnBar.TFrame', padding=6)
        btns.pack(fill='x', padx=8, pady=(4, 2))
        self._cleanup_state = {'scan': None, 'tree': tree, 'win': win}

        b_scan = ttk.Button(btns, text='1. СКАН', style='Big.TButton',
                            command=lambda: self._cleanup_scan(e_dir, v_unused, v_bad, v_suf, v_casc))
        b_scan.pack(side='left', padx=(6, 10), pady=2)
        hint(b_scan, 'ШАГ 1. Искать мусор в карте.\nРезультат появится в списке ниже.')
        b_del = ttk.Button(btns, text='2. УДАЛИТЬ ВЫДЕЛЕННОЕ', style='BigOk.TButton',
                           command=lambda: self._cleanup_delete(e_dir))
        b_del.pack(side='left', padx=3, pady=2)
        hint(b_del, 'ШАГ 2. Удалить отмеченные в списке строки.\nСпросит подтверждение, сделает бэкап.')
        b_rep = ttk.Button(btns, text='ПОЧИНИТЬ ТАБЛИЦЫ', style='BigWarn.TButton',
                           command=lambda: self._repair_tables(e_dir))
        b_rep.pack(side='left', padx=(10, 3), pady=2)
        hint(b_rep, 'Авто-починка table/*.ini: self-parent (родитель = сам себе),\nбитые _parent -> дефолт типа, дубли секций, разбаланс [=[ ]=].\nПервый запуск = скан, повторный = починка (бэкап + лог).')
        ttk.Button(btns, text='Выделить всё', command=lambda: self._cleanup_select_all(tree)).pack(side='left', padx=3, pady=2)
        ttk.Label(btns, text='Фильтр:').pack(side='left', padx=(10, 2))
        e_f = ttk.Entry(btns, width=18)
        e_f.pack(side='left')
        hint(e_f, 'Показать в списке только строки с этим текстом\n(имя, тип или причина). Очисти поле и Enter — сброс.')
        e_f.bind('<Return>', lambda e: self._cleanup_filter(tree, e_f.get().strip()))
        ttk.Button(btns, text='Открыть лог', command=self._cleanup_open_log).pack(side='left', padx=3)
        lbl = ttk.Label(btns, text='')
        lbl.pack(side='left', padx=10)
        self._cleanup_lbl = lbl

    def _cleanup_scan(self, e_dir, v_unused, v_bad, v_suf, v_casc):
        tgt = e_dir.get().strip()
        if not os.path.isdir(tgt):
            messagebox.showwarning('Путь', 'Укажи папку карты.')
            return
        patterns = self.cfg.get('cleanup', {}).get('suffix_patterns', sc.DEFAULT_SUFFIX_PATTERNS)
        manual = self.cfg.get('cleanup', {}).get('manual_ids', {})
        res = sc.scan(tgt, patterns, manual)
        self._cleanup_state = {'scan': res, 'dir': tgt, 'casc': v_casc.get(),
                               'filters': {'unused': v_unused.get(), 'bad': v_bad.get(), 'suf': v_suf.get()},
                               'tree': self._cleanup_state['tree'], 'win': self._cleanup_state['win']}
        tree = self._cleanup_state['tree']
        tree.delete(*tree.get_children())
        self._cleanup_all_iids = None
        # фильтр по типам (галочки)
        allowed = {tid for tid, v in getattr(self, '_type_vars', {}).items() if v.get()} or set(sc.TYPES)
        # 18.09: галочки 'что чистим' фильтруют категории
        show_suf = v_suf.get()
        show_bad = v_bad.get()
        show_unused = v_unused.get()
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
        self._cleanup_lbl.config(text='найдено: %d' % n)
        self._log('>>> Чистка: скан %s — найдено %d' % (tgt, n), 'ok')

    def _cleanup_delete(self, e_dir):
        st = getattr(self, '_cleanup_state', None)
        if not st or not st.get('scan'):
            messagebox.showwarning('Скан', 'Сначала запусти Скан.')
            return
        tree = st['tree']
        sel = tree.selection()
        if not sel:
            messagebox.showwarning('Выбор', 'Выдели строки для удаления (Ctrl/Shift для группы).')
            return
        if not messagebox.askyesno('Подтверждение', 'Удалить %d объектов?\nПеред удалением будет бэкап.' % len(sel)):
            return
        del_list = {}
        for item in sel:
            sid, t = tree.item(item, 'values')[0], tree.item(item, 'values')[1]
            del_list.setdefault(t, []).append(sid)
        lines = sc.delete(st['dir'], del_list,
                          os.path.join(HERE, 'logs'),
                          os.path.join(HERE, 'transfer_backup', 'cleanup'))
        for l in lines:
            self._log('  ' + l)
        self._log('>>> Чистка завершена, лог в logs/', 'ok')
        for item in sel:
            tree.delete(item)
        self._cleanup_lbl.config(text='удалено: %d' % len(sel))

    def _repair_tables(self, e_dir):
        tgt = e_dir.get().strip()
        if not os.path.isdir(tgt):
            messagebox.showwarning('Путь', 'Укажи папку карты.')
            return
        first = not getattr(self, '_repair_ran', False) or getattr(self, '_repair_tgt', '') != tgt
        self._repair_tgt = tgt
        if not first and not messagebox.askyesno('Починка', 'Применить правки к таблицам?\nПеред записью будет бэкап.'):
            return
        lines, total = sr.repair(tgt, None, os.path.join(HERE, 'transfer_backup', 'repair'), do=not first)
        for l in lines:
            self._log('  ' + l)
        if total:
            if first:
                self._repair_ran = True
                self._log('>>> Починка: скан — найдено %d проблем. Запусти ещё раз для применения (бэкап + лог).' % total, 'warn')
            else:
                os.makedirs(os.path.join(HERE, 'logs'), exist_ok=True)
                lp = os.path.join(HERE, 'logs', 'repair-%s.md' % time.strftime('%Y-%m-%d'))
                io.open(lp, 'ab').write((chr(10).join(lines) + chr(10) + chr(10)).encode('utf-8'))
                self._log('>>> Починка применена: %d правок, лог %s' % (total, lp), 'ok')
        else:
            self._log('>>> Починка: проблем не найдено', 'ok')

    def _cleanup_select_all(self, tree):
        # 18.09: выделить все строки списка
        tree.selection_set(tree.get_children())

    def _cleanup_filter(self, tree, q):
        # 18.09: скрыть строки без подстроки (по всем колонкам).
        # Пустой фильтр = вернуть все строки.
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
        # 18.09: починка таблиц приёмника с главного окна
        self._repair_tables(self.e_tgt)

    def _cleanup_open_log(self):
        p = os.path.join(HERE, 'logs')
        if os.path.isdir(p):
            fs = sorted([f for f in os.listdir(p) if f.startswith('cleanup-')])
            if fs:
                os.startfile(os.path.join(p, fs[-1]))
            else:
                messagebox.showinfo('Лог', 'Логов чистки пока нет.')
        else:
            messagebox.showinfo('Лог', 'Папки logs ещё нет.')
    def _manifest(self):
        self._save_cfg()
        cmd = [sys.executable, os.path.join(HERE, 'make_manifest.py'), CFG]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=HERE)
        self._log(((r.stdout or '') + (r.stderr or '')).strip())

    def _worker(self, cmd):
        # 17.09: потоковое чтение — журнал растёт в реальном времени
        # 18.09: cmd может быть списком команд (цепочка: code -> verify)
        try:
            cmds = cmd if cmd and isinstance(cmd[0], list) else [cmd]
            for c in cmds:
                self._worker_one(c)
        except Exception as e:
            self.q.put(('ОШИБКА ЗАПУСКА: %s' % e, 'err'))
        finally:
            self.running = False
            self.q.put(('__done__', None))

    def _worker_one(self, cmd):
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace',
                                    cwd=HERE, bufsize=1)
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                low = line.lower()
                tag = None
                if 'ошибка' in low or 'error' in low or 'код 1' in low:
                    tag = 'err'
                elif 'внимание' in low or 'warning' in low:
                    tag = 'warn'
                self.q.put((line, tag))
            proc.wait()
            self.q.put(('--- код выхода: %d ---' % proc.returncode,
                        'ok' if proc.returncode == 0 else 'err'))
        except Exception as e:
            self.q.put(('ОШИБКА ЗАПУСКА: %s' % e, 'err'))

    def _run(self, args):
        if self.running:
            messagebox.showwarning('Занято', 'Прогон уже выполняется — дождись завершения.')
            return
        self._collect_cfg()
        io.open(CFG, 'wb').write(json.dumps(self.cfg, indent=2, ensure_ascii=False).encode('utf-8'))
        # 18.09: allow_b берётся из конфига (cfg.code.allow_b),
        # флаг --allow-b оркестратор не принимает в argparse
        # 18.09: args может быть списком команд (цепочка)
        if args and isinstance(args[0], list):
            cmds = [[sys.executable, '-u', os.path.join(HERE, 'transfer_run.py')] + a for a in args]
            desc = ' -> '.join(' '.join(a) for a in args)
        else:
            cmds = [[sys.executable, '-u', os.path.join(HERE, 'transfer_run.py')] + args]
            desc = ' '.join(args)
        self._log('>>> ' + desc, 'ok')
        self.running = True
        self.status.config(text='выполняется: ' + desc)
        self.head_status.config(text='выполняется...', fg=T['warn'])
        threading.Thread(target=self._worker, args=(cmds,), daemon=True).start()

if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    app._load_cfg()
    root.mainloop()
