import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import sqlite3
from datetime import datetime
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt

DB_NAME = "finance_app.db"

USERS = [
    {"id": "me", "label": "Tomas", "default_bills": 1000.0},
    {"id": "carol", "label": "Carol", "default_bills": 1000.0},
]

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Bills per user
    c.execute("""CREATE TABLE IF NOT EXISTS bills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    monthly_target REAL
                )""")

    # Allocation percentages of leftover per user
    c.execute("""CREATE TABLE IF NOT EXISTS allocations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    category TEXT,
                    percentage REAL
                )""")

    # Income log: one row per allocation (Bills, Savings, etc.), grouped by 'date' timestamp
    c.execute("""CREATE TABLE IF NOT EXISTS income (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    amount REAL,
                    category TEXT,
                    allocated REAL,
                    date TEXT
                )""")

    # Bonus log: similar structure but stored separately
    c.execute("""CREATE TABLE IF NOT EXISTS bonus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    amount REAL,
                    category TEXT,
                    allocated REAL,
                    date TEXT
                )""")

    # App/user settings
    c.execute("""CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,        -- 'me', 'carol', or 'both'
                    key TEXT,            -- 'font_size' | 'theme' | 'currency' | 'ref_total'
                    value TEXT
                )""")

    # Ensure defaults for each user
    for u in USERS:
        # bills default
        c.execute("SELECT 1 FROM bills WHERE user_id=?", (u["id"],))
        if not c.fetchone():
            c.execute("INSERT INTO bills (user_id, monthly_target) VALUES (?, ?)",
                      (u["id"], u["default_bills"]))
        # allocations defaults (Savings, Investing, Fun)
        for cat in ["Savings", "Investing", "Fun"]:
            c.execute("SELECT 1 FROM allocations WHERE user_id=? AND category=?",
                      (u["id"], cat))
            if not c.fetchone():
                c.execute("INSERT INTO allocations (user_id, category, percentage) VALUES (?, ?, ?)",
                          (u["id"], cat, 0.0))

    conn.commit()
    conn.close()


class FinanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Finance Tracker")
        self.current_user = "me"

        # ttk style + base fonts
        self.style = ttk.Style(self.root)
        try:
            # Use a consistent theme we can restyle
            self.style.theme_use("clam")
        except Exception:
            pass

        # Initialize currency symbol early
        self.currency_symbol = "£"  # default if no settings yet

        # ---- Header with profile switcher
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(6,0), padx=8)
        ttk.Label(header, text="Profile:").pack(side="left", padx=(0,6))
        self.profile_var = tk.StringVar(value="Tomas")
        self.profile_map_label_to_id = {u["label"]: u["id"] for u in USERS}
        self.profile_map_id_to_label = {u["id"]: u["label"] for u in USERS}

        self.profile_combo = ttk.Combobox(
            header, state="readonly",
            values=[u["label"] for u in USERS],
            textvariable=self.profile_var, width=12
        )
        self.profile_combo.pack(side="left")
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_change)

        # ---- Notebook tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(expand=True, fill="both", padx=8, pady=8)

        # Create tab frames first (prevents attribute errors)
        self.income_tab = ttk.Frame(self.notebook)
        self.bills_tab = ttk.Frame(self.notebook)
        self.alloc_tab = ttk.Frame(self.notebook)
        self.history_tab = ttk.Frame(self.notebook)
        self.settings_tab = ttk.Frame(self.notebook)

        self.notebook.add(self.income_tab, text="Income")
        self.notebook.add(self.bills_tab, text="Bills")
        self.notebook.add(self.alloc_tab, text="Allocations")
        self.notebook.add(self.history_tab, text="History")
        self.notebook.add(self.settings_tab, text="Settings")

        # Set up tabs (these use the frames created above)
        self.setup_income_tab()
        self.setup_bills_tab()
        self.setup_allocations_tab()
        self.setup_history_tab()
        self.setup_settings_tab()  # NEW

        # global keybind for Undo (Ctrl+Z)
        self.root.bind("<Control-z>", lambda e: self.undo_last())

        # Settings (load + apply immediately)
        self.apply_settings()        # load & apply

        # initial paints
        self.update_totals()
        self.refresh_bills()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- UTIL ----------------
    def _current_month_str(self):
        """Return 'YYYY-MM' for current month in local time."""
        return datetime.now().strftime("%Y-%m")

    # ---------------- SETTINGS (helpers) ----------------
    def read_settings_for_user(self, user_id):
        """Get effective settings for a user. 'user_id' overrides 'both'."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Start with 'both'
        c.execute("SELECT key, value FROM settings WHERE user_id='both'")
        base = {k: v for k, v in c.fetchall()}
        # Overlay user-specific
        c.execute("SELECT key, value FROM settings WHERE user_id=?", (user_id,))
        for k, v in c.fetchall():
            base[k] = v
        conn.close()
        return base

    def write_setting(self, scope_user_id, key, value):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("DELETE FROM settings WHERE user_id=? AND key=?", (scope_user_id, key))
        c.execute("INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?)",
                  (scope_user_id, key, value))
        conn.commit()
        conn.close()

    def apply_settings(self):
        """Load and apply settings for current user; updates fonts, colors, currency live."""
        s = self.read_settings_for_user(self.current_user)
        # ----- Font size
        size_map = {"Small": 10, "Medium": 12, "Large": 14}
        font_choice = s.get("font_size", "Medium")
        font_px = size_map.get(font_choice, 12)

        # Update Tk named fonts so ttk widgets pick it up
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(size=font_px)
        text_font = tkfont.nametofont("TkTextFont")
        text_font.configure(size=font_px)
        fixed_font = tkfont.nametofont("TkFixedFont")
        fixed_font.configure(size=font_px)
        menu_font = tkfont.nametofont("TkMenuFont")
        menu_font.configure(size=font_px)
        heading_font = tkfont.nametofont("TkHeadingFont")
        heading_font.configure(size=font_px)
        small_font = tkfont.nametofont("TkSmallCaptionFont")
        small_font.configure(size=max(8, font_px-1))
        # Force redraw
        self.root.update_idletasks()

        # ----- Theme (Light/Dark) via ttk.Style
        theme_choice = s.get("theme", "Light")
        if theme_choice == "Dark":
            bg = "#1f2430"
            fg = "#e6e6e6"
            field_bg = "#2b313e"
            sel_bg = "#3a4152"
            highlight = "#4f5870"
        else:
            bg = self.root.cget("bg")
            if bg in ("", "SystemButtonFace"):
                bg = "#F0F0F0"
            fg = "#000000"
            field_bg = "#FFFFFF"
            sel_bg = "#D9E1F2"
            highlight = "#C0C6D6"

        self.root.configure(bg=bg)
        # Frame/Label/Button
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("TButton", background=bg, foreground=fg)
        self.style.map("TButton", background=[("active", sel_bg)])
        self.style.configure("TNotebook", background=bg)
        self.style.configure("TNotebook.Tab", background=field_bg, foreground=fg)
        self.style.map("TNotebook.Tab", background=[("selected", sel_bg)])
        self.style.configure("TEntry", fieldbackground=field_bg, foreground=fg)
        self.style.configure("TCombobox", fieldbackground=field_bg, foreground=fg)
        # default bar
        self.style.configure("Horizontal.TProgressbar", background=sel_bg)
        # GREEN progress bar style for Bills
        self.style.configure("green.Horizontal.TProgressbar", background="#35b66f")

        # Treeview
        self.style.configure("Treeview",
                             background=field_bg,
                             foreground=fg,
                             fieldbackground=field_bg)
        self.style.configure("Treeview.Heading",
                             background=highlight,
                             foreground=fg)

        # ----- Currency
        self.currency_symbol = s.get("currency", "£")
        # Reference total for Carol (if present)
        self.ref_total = float(s.get("ref_total", "0") or 0.0)

        # Refresh labels/graphs to reflect currency immediately
        self.update_totals()
        self.refresh_bills()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- PROFILE SWITCH ----------------
    def on_profile_change(self, _evt=None):
        label = self.profile_var.get()
        self.current_user = self.profile_map_label_to_id.get(label, "me")
        # Apply settings for that user first (font/theme/currency)
        self.apply_settings()
        # Refresh all tabs
        self.update_totals()
        self.refresh_bills()
        self.load_allocations()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- INCOME TAB ----------------
    def setup_income_tab(self):
        # Create income tab layout and prettier totals + goals allocations area
        container = ttk.Frame(self.income_tab, padding=8)
        container.pack(fill="both", expand=True)

        # Input row
        row = ttk.Frame(container)
        row.pack(fill="x", pady=(6, 8))
        ttk.Label(row, text="Income:").pack(side="left", padx=(0,8))
        self.income_entry = ttk.Entry(row, width=14)
        self.income_entry.pack(side="left")
        self.income_entry.bind("<Return>", lambda e: self.add_income())
        ttk.Button(row, text="Add Income", command=self.add_income).pack(side="left", padx=6)
        ttk.Button(row, text="Add Bonus", command=self.add_bonus).pack(side="left", padx=6)
        ttk.Button(row, text="Undo Last", command=self.undo_last).pack(side="left", padx=6)

        # Totals "cards" frame
        self.totals_frame = ttk.Frame(container)
        self.totals_frame.pack(fill="x", pady=(6, 12))

        # We'll show Bills, Savings, Investing, Fun as main cards
        self.total_labels = {}
        card_names = [("Bills", "#35b66f"), ("Savings", "#1f77b4"), ("Investing", "#2ca02c"), ("Fun", "#9467bd")]
        for i, (name, color) in enumerate(card_names):
            card = ttk.Frame(self.totals_frame, relief="raised", padding=(8,6))
            card.grid(row=0, column=i, padx=6, sticky="nsew")
            label_title = ttk.Label(card, text=name, font=("Segoe UI", 9, "bold"))
            label_title.pack(anchor="center")
            label_value = ttk.Label(card, text=f"{self.currency_symbol}0.00", font=("Segoe UI", 11))
            label_value.pack(anchor="center")
            # store label so update_totals can change it
            self.total_labels[name.lower()] = label_value
            # expand equally
            self.totals_frame.columnconfigure(i, weight=1)

        # Goals allocations area (dynamic)
        self.goals_totals_frame = ttk.LabelFrame(container, text="Goals allocation", padding=8)
        self.goals_totals_frame.pack(fill="x", pady=(6, 12))
        self.goal_total_labels = {}  # mapping goal_name -> ttk.Label

        # Graph area (keep your existing style)
        self.graph_frame = ttk.Frame(container)
        self.graph_frame.pack(fill="both", expand=True)

        # Initial populate
        self.update_totals()

    # ---------------- add_income ----------------
    def add_income(self):
        try:
            income = float(self.income_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number.")
            return
        if income <= 0:
            messagebox.showerror("Error", "Income must be greater than 0.")
            return

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Get monthly bills target
        c.execute("SELECT monthly_target FROM bills WHERE user_id=?", (self.current_user,))
        row = c.fetchone()
        monthly_target = row[0] if row else 1000.0

        # Compute bills allocation differently for Tomas vs Carol
        current_month = self._current_month_str()

        if self.current_user == "carol":
            # Carol: allocate enough to finish THIS MONTH's bills first.
            c.execute(
                """SELECT COALESCE(SUM(allocated),0) FROM income
                   WHERE user_id=? AND category='Bills' AND substr(date,1,7)=?""",
                (self.current_user, current_month)
            )
            paid_this_month = c.fetchone()[0] or 0.0
            remaining_this_month = max(0.0, monthly_target - paid_this_month)
            bills_alloc = min(income, remaining_this_month)
        else:
            # Tomas: treat as weekly contribution = monthly_target / 4
            weekly_bill = monthly_target / 4.0
            bills_alloc = min(income, weekly_bill)

        leftover = income - bills_alloc

        # Allocations (must total 100)
        c.execute("SELECT category, percentage FROM allocations WHERE user_id=?", (self.current_user,))
        allocations = c.fetchall()
        total_pct = sum(a[1] for a in allocations)
        if round(total_pct, 6) != 100.0:
            conn.close()
            messagebox.showerror("Error", "Allocations must add up to 100%.")
            return

        # One timestamp for the whole "income session"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Insert bills row
        c.execute("""INSERT INTO income (user_id, amount, category, allocated, date)
                     VALUES (?, ?, ?, ?, ?)""",
                  (self.current_user, income, "Bills", bills_alloc, ts))

        # Insert allocation rows
        for cat, pct in allocations:
            alloc_amount = leftover * (pct / 100.0)
            c.execute("""INSERT INTO income (user_id, amount, category, allocated, date)
                         VALUES (?, ?, ?, ?, ?)""",
                      (self.current_user, income, cat, alloc_amount, ts))

        conn.commit()
        conn.close()

        self.income_entry.delete(0, tk.END)
        self.update_totals()
        self.refresh_bills()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- ADD BONUS ----------------
    def add_bonus(self):
        """Add a bonus: does NOT allocate to Bills. Uses allocation percentages to split leftover across goals."""
        try:
            amount = float(self.income_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for bonus.")
            return
        if amount <= 0:
            messagebox.showerror("Error", "Bonus must be greater than 0.")
            return

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Get allocations excluding 'Bills' (only goals)
        c.execute("SELECT category, percentage FROM allocations WHERE user_id=? AND category<>'Bills'", (self.current_user,))
        allocations = c.fetchall()
        if not allocations:
            conn.close()
            messagebox.showerror("Error", "No allocations defined to receive bonus.")
            return

        total_pct = sum(a[1] for a in allocations)
        if round(total_pct, 6) == 0:
            conn.close()
            messagebox.showerror("Error", "Allocations percentages must be set (not zero) to distribute bonus.")
            return

        # Normalize if not exactly 100% across non-bills (we'll distribute proportionally)
        norm_factor = (100.0 / total_pct) if round(total_pct, 6) != 100.0 else 1.0

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Insert bonus rows (per category)
        for cat, pct in allocations:
            pct_norm = pct * norm_factor
            alloc_amount = amount * (pct_norm / 100.0)
            c.execute("""INSERT INTO bonus (user_id, amount, category, allocated, date)
                         VALUES (?, ?, ?, ?, ?)""", (self.current_user, amount, cat, alloc_amount, ts))

        conn.commit()
        conn.close()

        self.income_entry.delete(0, tk.END)
        messagebox.showinfo("Bonus", f"Bonus of {self.currency_symbol}{amount:.2f} added and split across goals.")
        self.update_totals()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- UNDO LAST (income or bonus) ----------------
    def undo_last(self):
        """Remove the most recent session (income or bonus) for the current user."""
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Get last datetime from income
        c.execute("""SELECT date FROM income WHERE user_id=? ORDER BY datetime(date) DESC LIMIT 1""", (self.current_user,))
        inc_row = c.fetchone()
        inc_ts = inc_row[0] if inc_row else None
        # Get last datetime from bonus
        c.execute("""SELECT date FROM bonus WHERE user_id=? ORDER BY datetime(date) DESC LIMIT 1""", (self.current_user,))
        bonus_row = c.fetchone()
        bonus_ts = bonus_row[0] if bonus_row else None

        # Determine which is later
        chosen_table = None
        chosen_ts = None
        if inc_ts and bonus_ts:
            # compare string datetimes (format YYYY-MM-DD HH:MM:SS)
            chosen_table = "income" if inc_ts >= bonus_ts else "bonus"
            chosen_ts = inc_ts if inc_ts >= bonus_ts else bonus_ts
        elif inc_ts:
            chosen_table = "income"
            chosen_ts = inc_ts
        elif bonus_ts:
            chosen_table = "bonus"
            chosen_ts = bonus_ts
        else:
            conn.close()
            messagebox.showinfo("Undo", "No income or bonus to undo.")
            return

        # Show details and delete
        c.execute(f"SELECT category, allocated FROM {chosen_table} WHERE user_id=? AND date=?", (self.current_user, chosen_ts))
        details = c.fetchall()
        c.execute(f"DELETE FROM {chosen_table} WHERE user_id=? AND date=?", (self.current_user, chosen_ts))
        conn.commit()
        conn.close()

        lines = [f"{cat}: {self.currency_symbol}{amt:.2f}" for cat, amt in details]
        messagebox.showinfo("Undo", f"Removed last {chosen_table} entry:\n" + "\n".join(lines))

        # Refresh UI
        self.update_totals()
        self.refresh_bills()
        self.refresh_graph()
        self.refresh_history()

    # ---------------- UPDATED update_totals ----------------
    def update_totals(self):
        """
        Populate the totals 'cards' and the Goals Allocation area.
        Uses grouped sums per category in income+bonus tables.
        """
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # sum income allocated by category
        c.execute("""SELECT category, COALESCE(SUM(allocated),0) FROM income
                     WHERE user_id=? GROUP BY category""", (self.current_user,))
        inc_rows = c.fetchall()
        # sum bonus allocated by category and add to totals_map
        c.execute("""SELECT category, COALESCE(SUM(allocated),0) FROM bonus
                     WHERE user_id=? GROUP BY category""", (self.current_user,))
        bonus_rows = c.fetchall()
        conn.close()

        totals_map = {"bills": 0.0, "savings": 0.0, "investing": 0.0, "fun": 0.0}
        goals_map = {}  # name -> amount

        # income rows
        for cat, total in inc_rows:
            key = cat.lower()
            if key in totals_map:
                totals_map[key] += total
            elif cat == "Bills":
                totals_map["bills"] += total
            else:
                goals_map[cat] = goals_map.get(cat, 0.0) + total

        # bonus rows (only goals normally)
        for cat, total in bonus_rows:
            key = cat.lower()
            if key in totals_map and cat == "Bills":
                totals_map[key] += total
            else:
                goals_map[cat] = goals_map.get(cat, 0.0) + total

        # Update main cards labels (if created)
        try:
            self.total_labels["bills"].config(text=f"{self.currency_symbol}{totals_map['bills']:.2f}")
            self.total_labels["savings"].config(text=f"{self.currency_symbol}{totals_map['savings']:.2f}")
            self.total_labels["investing"].config(text=f"{self.currency_symbol}{totals_map['investing']:.2f}")
            self.total_labels["fun"].config(text=f"{self.currency_symbol}{totals_map['fun']:.2f}")
        except Exception:
            pass

        # Rebuild goals area
        for child in self.goals_totals_frame.winfo_children():
            child.destroy()
        self.goal_total_labels = {}

        if goals_map:
            for i, (gname, amt) in enumerate(sorted(goals_map.items())):
                lbl_name = ttk.Label(self.goals_totals_frame, text=f"{gname}:", font=("Arial", 10, "bold"))
                lbl_name.grid(row=i, column=0, sticky="w", padx=6, pady=2)
                lbl_amt = ttk.Label(self.goals_totals_frame, text=f"{self.currency_symbol}{amt:.2f}", font=("Arial", 10))
                lbl_amt.grid(row=i, column=1, sticky="e", padx=6, pady=2)
                self.goal_total_labels[gname] = lbl_amt
        else:
            # friendly placeholder
            ttk.Label(self.goals_totals_frame, text="No goal allocations yet").pack(padx=6, pady=4)

    # ---------------- BILLS TAB ----------------
    def setup_bills_tab(self):
        row = ttk.Frame(self.bills_tab)
        row.pack(pady=8)
        ttk.Label(row, text="Monthly Bills Target:").pack(side="left", padx=(0,8))
        self.bills_entry = ttk.Entry(row, width=10)
        self.bills_entry.pack(side="left")
        ttk.Button(row, text="Update Bills", command=self.update_bills).pack(side="left", padx=6)

        self.bills_progress_label = ttk.Label(self.bills_tab, text="")
        self.bills_progress_label.pack(pady=5)

        self.bills_progress = ttk.Progressbar(self.bills_tab, length=360, mode="determinate")
        self.bills_progress.configure(style="green.Horizontal.TProgressbar")
        self.bills_progress.pack(pady=8)

    def update_bills(self):
        try:
            new_target = float(self.bills_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Enter a valid number.")
            return

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("UPDATE bills SET monthly_target=? WHERE user_id=?", (new_target, self.current_user))
        conn.commit()
        conn.close()
        self.refresh_bills()

    def refresh_bills(self):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        # Load monthly target
        c.execute("SELECT monthly_target FROM bills WHERE user_id=?", (self.current_user,))
        row = c.fetchone()
        monthly_target = row[0] if row else 1100.0

        # Paid so far in CURRENT MONTH (income only; bonuses shouldn't go to bills)
        current_month = self._current_month_str()
        c.execute("""SELECT COALESCE(SUM(allocated),0) FROM income
                     WHERE user_id=? AND category='Bills' AND substr(date,1,7)=?""",
                  (self.current_user, current_month))
        paid_this_month = c.fetchone()[0] or 0.0
        conn.close()

        # Update UI
        self.bills_entry.delete(0, tk.END)
        self.bills_entry.insert(0, str(int(monthly_target) if float(monthly_target).is_integer() else f"{monthly_target:.2f}"))
        self.bills_progress_label.config(
            text=f"Bills paid (this month): {self.currency_symbol}{paid_this_month:.2f} / {self.currency_symbol}{monthly_target:.2f}"
        )
        pct = 0 if monthly_target <= 0 else min(100, int((paid_this_month / monthly_target) * 100))
        self.bills_progress["value"] = pct

    # ---------------- ALLOCATIONS TAB ----------------
    def setup_allocations_tab(self):
        ctrl = ttk.Frame(self.alloc_tab)
        ctrl.pack(fill="x", pady=(8,0))
        ttk.Button(ctrl, text="Add New Goal", command=self.add_goal).pack(side="left", padx=6)
        ttk.Button(ctrl, text="Save Allocations", command=self.save_allocations).pack(side="left", padx=6)

        self.alloc_frame = ttk.Frame(self.alloc_tab)
        self.alloc_frame.pack(pady=10, fill="x")
        # dynamic graph frame reused from earlier design
        self.graph_frame = ttk.Frame(self.alloc_tab)
        self.graph_frame.pack(pady=10, fill="both", expand=True)

        self.load_allocations()

    def load_allocations(self):
        """Render allocation rows. If current user is Carol, show flat-value inputs and live %s."""
        for w in self.alloc_frame.winfo_children():
            w.destroy()

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""SELECT id, category, percentage FROM allocations
                     WHERE user_id=? ORDER BY id ASC""", (self.current_user,))
        rows = c.fetchall()
        conn.close()

        self.alloc_entries = []  # list of dicts per entry with widgets
        # If carol, we want to allow flat mode and show help
        is_carol = (self.current_user == "carol")

        if is_carol:
            # Help label
            help_lbl = ttk.Label(self.alloc_frame, text="Carol: you can enter flat values. App will compute % of Reference Total. Leave one flat empty to auto-fill it.")
            help_lbl.pack(fill="x", padx=6, pady=(0,6))

        for i, (alloc_id, cat, pct) in enumerate(rows):
            row = ttk.Frame(self.alloc_frame)
            row.pack(pady=2, fill="x")
            ttk.Label(row, text=cat, width=18).pack(side="left")

            # percent entry (always present)
            pct_var = tk.StringVar(value=str(pct))
            pct_entry = ttk.Entry(row, width=8, textvariable=pct_var)
            pct_entry.pack(side="left", padx=(4,8))

            flat_var = tk.StringVar(value="")
            flat_entry = None
            pct_display = ttk.Label(row, text="%")  # placeholder for live display in Carol mode

            if is_carol:
                # Show flat entry
                flat_entry = ttk.Entry(row, width=12, textvariable=flat_var)
                flat_entry.pack(side="left", padx=(0,8))
                # Percent display (read-only) to show what the flat represents of ref_total
                pct_display = ttk.Label(row, text="0.00%")
                pct_display.pack(side="left", padx=(0,8))

                # Bind events: when flat changes, update percent; when percent changes, update flat
                def make_flat_callback(fvar, pvar, pd_label):
                    def on_flat_change(*_):
                        val = fvar.get().strip()
                        try:
                            flat_val = float(val) if val != "" else None
                        except Exception:
                            flat_val = None
                        # Recompute percentages for this set below (we trigger overall recalculation)
                        self._carol_on_flat_changed()
                    return on_flat_change

                def make_pct_callback(fvar, pvar, pd_label):
                    def on_pct_change(*_):
                        # When user types percentage we update flat for that row from ref_total
                        self._carol_on_pct_changed()
                    return on_pct_change

                flat_var.trace_add("write", make_flat_callback(flat_var, pct_var, pct_display))
                pct_var.trace_add("write", make_pct_callback(flat_var, pct_var, pct_display))

            else:
                pct_display.pack_forget()

            # Keep references
            self.alloc_entries.append({
                "id": alloc_id,
                "category": cat,
                "pct_var": pct_var,
                "pct_entry": pct_entry,
                "flat_var": flat_var,
                "flat_entry": flat_entry,
                "pct_display": pct_display
            })

        # If carol, run an initial sync to populate displays
        if is_carol:
            self._carol_sync_all_widgets()

    # ---------------- CAROL helpers for flat/percent sync ----------------
    def _carol_get_ref_total(self):
        # reference total stored in self.ref_total (set by apply_settings)
        return getattr(self, "ref_total", 0.0)

    def _carol_on_flat_changed(self):
        """Called when any flat input changes: recalc percents and auto-fill last missing flat if applicable."""
        ref = self._carol_get_ref_total()
        # gather flats
        flats = []
        empty_indices = []
        for i, e in enumerate(self.alloc_entries):
            v = e["flat_var"].get().strip()
            if v == "":
                flats.append(None)
                empty_indices.append(i)
            else:
                try:
                    flats.append(float(v))
                except Exception:
                    flats.append(None)
                    empty_indices.append(i)
        # If ref is zero, we cannot compute percentages; show zeros
        if ref <= 0:
            # set percent displays to 0
            for e, flat in zip(self.alloc_entries, flats):
                e["pct_display"].config(text="0.00%")
            return

        # If exactly one empty, autofill it
        if len(empty_indices) == 1:
            idx = empty_indices[0]
            sum_filled = sum(f for f in flats if f is not None)
            auto_val = max(0.0, ref - sum_filled)
            # set that flat var (this triggers trace, but we want to avoid infinite loop; var.trace callbacks will run but it's fine)
            self.alloc_entries[idx]["flat_var"].set(f"{auto_val:.2f}")

        # Now update percents from flats
        for e in self.alloc_entries:
            v = e["flat_var"].get().strip()
            try:
                fv = float(v)
            except Exception:
                fv = 0.0
            pct = (fv / ref * 100.0) if ref > 0 else 0.0
            e["pct_display"].config(text=f"{pct:.2f}%")
            # Also update the pct_var to match (so saving will persist percentages)
            e["pct_var"].set(f"{pct:.6f}")

    def _carol_on_pct_changed(self):
        """When a percent field is modified manually, update flat values from reference total."""
        ref = self._carol_get_ref_total()
        if ref <= 0:
            return
        for e in self.alloc_entries:
            pv = e["pct_var"].get().strip()
            try:
                p = float(pv)
            except Exception:
                p = 0.0
            flat = ref * (p / 100.0)
            # Set flat without triggering more heavy recalcs (we do allow trace to update displays)
            e["flat_var"].set(f"{flat:.2f}")
        # After this, percents and flats are consistent; update pct_display
        for e in self.alloc_entries:
            try:
                p = float(e["pct_var"].get())
            except Exception:
                p = 0.0
            e["pct_display"].config(text=f"{p:.2f}%")

    def _carol_sync_all_widgets(self):
        """Initial sync: populate flat entries from pct (if ref_total present) and set pct displays."""
        ref = self._carol_get_ref_total()
        if ref <= 0:
            # just set pct displays from pct_var
            for e in self.alloc_entries:
                try:
                    p = float(e["pct_var"].get())
                except Exception:
                    p = 0.0
                e["pct_display"].config(text=f"{p:.2f}%")
                if e["flat_entry"] is not None:
                    e["flat_var"].set("")
            return

        # fill flat entries from pct
        for e in self.alloc_entries:
            try:
                p = float(e["pct_var"].get())
            except Exception:
                p = 0.0
            flat = ref * (p / 100.0)
            if e["flat_entry"] is not None:
                e["flat_var"].set(f"{flat:.2f}")
            e["pct_display"].config(text=f"{p:.2f}%")

    # ---------------- add_goal / save_allocations ----------------
    def add_goal(self):
        win = tk.Toplevel(self.root)
        win.title("Add Goal")
        ttk.Label(win, text="Goal Name:").pack(pady=6)
        name_entry = ttk.Entry(win, width=24)
        name_entry.pack(pady=4)

        def save_goal():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Error", "Enter a valid name.")
                return
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("""INSERT INTO allocations (user_id, category, percentage)
                         VALUES (?, ?, 0.0)""", (self.current_user, name))
            conn.commit()
            conn.close()
            win.destroy()
            self.load_allocations()

        ttk.Button(win, text="Save", command=save_goal).pack(pady=8)

    def save_allocations(self):
        """
        Save allocations percentages to DB.
        For Carol: if flat values present, compute percentages from ref_total.
        """
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()

        is_carol = (self.current_user == "carol")
        # gather percentages to save
        to_save = []
        ok = True
        for e in self.alloc_entries:
            try:
                # parse pct_var (it should already be consistent if Carol)
                pct = float(e["pct_var"].get())
            except Exception:
                ok = False
                pct = 0.0
            to_save.append((pct, e["id"]))

        if not ok:
            conn.rollback()
            conn.close()
            messagebox.showerror("Error", "All percentages must be valid numbers.")
            return

        total = sum(p for p, _ in to_save)
        if round(total, 6) != 100.0:
            conn.rollback()
            conn.close()
            messagebox.showerror("Error", f"Total percentages must equal 100% (currently {total:.6f}%).")
            return

        # Save into DB
        for pct, alloc_id in to_save:
            c.execute("UPDATE allocations SET percentage=? WHERE id=?", (pct, alloc_id))

        conn.commit()
        conn.close()
        self.load_allocations()
        self.refresh_graph()
        messagebox.showinfo("Allocations", "Allocations saved.")

    def refresh_graph(self):
        for w in self.graph_frame.winfo_children():
            w.destroy()

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("""SELECT category, COALESCE(SUM(allocated),0) FROM (
                         SELECT category, allocated FROM income WHERE user_id=?
                         UNION ALL
                         SELECT category, allocated FROM bonus WHERE user_id=?
                     ) GROUP BY category""", (self.current_user, self.current_user))
        rows = c.fetchall()
        conn.close()

        if not rows:
            return

        cats, totals = zip(*rows)
        fig, ax = plt.subplots(figsize=(6, 3.5))
        ax.bar(cats, totals)
        ax.set_ylabel(f"{self.currency_symbol} Total")
        ax.set_title("Totals by Category")
        ax.tick_params(axis='x', labelrotation=20)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.graph_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------------- HISTORY TAB (grouped) ----------------
    def setup_history_tab(self):
        self.history_tab_inner = ttk.Frame(self.history_tab)
        self.history_tab_inner.pack(fill="both", expand=True)
        self.history_tree = ttk.Treeview(self.history_tab_inner)
        self.history_tree["columns"] = ("Amount", "Type")
        self.history_tree.heading("#0", text="Entry (timestamp)")
        self.history_tree.heading("Amount", text="Amount Allocated")
        self.history_tree.heading("Type", text="Type")
        self.history_tree.column("#0", width=320)
        self.history_tree.column("Amount", width=160, anchor="e")
        self.history_tree.column("Type", width=80, anchor="center")
        self.history_tree.pack(expand=True, fill="both")

    def refresh_history(self):
        for i in self.history_tree.get_children():
            self.history_tree.delete(i)

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Union distinct timestamps from both tables
        c.execute("""
    SELECT date, ttype, total FROM (
        SELECT date, 'income' as ttype, COALESCE(SUM(allocated),0) as total
        FROM income WHERE user_id=? GROUP BY date
        UNION ALL
        SELECT date, 'bonus' as ttype, COALESCE(SUM(allocated),0) as total
        FROM bonus WHERE user_id=? GROUP BY date
    )
    ORDER BY datetime(date) DESC
""", (self.current_user, self.current_user))
        sessions = c.fetchall()

        for date_str, ttype, total in sessions:
            parent = self.history_tree.insert("", "end",
                                             text=f"📂 {date_str}  ({self.currency_symbol}{total:.2f})",
                                             values=(f"{self.currency_symbol}{total:.2f}", ttype), open=False)
            # fetch children depending on type
            if ttype == "income":
                c.execute("SELECT category, allocated FROM income WHERE user_id=? AND date=? ORDER BY category ASC",
                          (self.current_user, date_str))
            else:
                c.execute("SELECT category, allocated FROM bonus WHERE user_id=? AND date=? ORDER BY category ASC",
                          (self.current_user, date_str))
            for category, amount in c.fetchall():
                self.history_tree.insert(parent, "end", text=category, values=(f"{self.currency_symbol}{amount:.2f}", ttype))

        conn.close()

    # ---------------- SETTINGS TAB ----------------
    def setup_settings_tab(self):
        row = 0
        ttk.Label(self.settings_tab, text="Font Size").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.font_var = tk.StringVar(value="Medium")
        ttk.Combobox(self.settings_tab, textvariable=self.font_var, state="readonly",
                     values=["Small", "Medium", "Large"], width=12)\
            .grid(row=row, column=1, sticky="w", padx=8)
        row += 1

        ttk.Label(self.settings_tab, text="Theme").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.theme_var = tk.StringVar(value="Light")
        ttk.Combobox(self.settings_tab, textvariable=self.theme_var, state="readonly",
                     values=["Light", "Dark"], width=12)\
            .grid(row=row, column=1, sticky="w", padx=8)
        row += 1

        ttk.Label(self.settings_tab, text="Currency").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.currency_var = tk.StringVar(value="£")
        ttk.Combobox(self.settings_tab, textvariable=self.currency_var, state="readonly",
                     values=["£", "$", "€"], width=12)\
            .grid(row=row, column=1, sticky="w", padx=8)
        row += 1

        # Reference total (for Carol)
        ttk.Label(self.settings_tab, text="Reference Total (Carol)").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.ref_total_var = tk.StringVar(value="0")
        ttk.Entry(self.settings_tab, textvariable=self.ref_total_var, width=14).grid(row=row, column=1, sticky="w", padx=8)
        row += 1

        # Bills target from settings (applies to selected user(s))
        ttk.Label(self.settings_tab, text="Bills Target").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.settings_bills_var = tk.StringVar(value="1000")
        ttk.Entry(self.settings_tab, textvariable=self.settings_bills_var, width=14)\
            .grid(row=row, column=1, sticky="w", padx=8)
        row += 1

        # Apply to whom
        ttk.Label(self.settings_tab, text="Apply To").grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.apply_to_var = tk.StringVar(value="me")
        frame_apply = ttk.Frame(self.settings_tab)
        frame_apply.grid(row=row, column=1, sticky="w", padx=8)
        ttk.Radiobutton(frame_apply, text="Me", value="me", variable=self.apply_to_var).pack(side="left")
        ttk.Radiobutton(frame_apply, text="Carol", value="carol", variable=self.apply_to_var).pack(side="left", padx=6)
        ttk.Radiobutton(frame_apply, text="Both", value="both", variable=self.apply_to_var).pack(side="left")
        row += 1

        # Save button
        ttk.Button(self.settings_tab, text="Save Settings", command=self.save_settings)\
            .grid(row=row, column=0, columnspan=2, padx=8, pady=12, sticky="w")

        # Load current effective settings into controls
        self.populate_settings_controls()

    def populate_settings_controls(self):
        """Read effective settings for current user and set the widgets."""
        s = self.read_settings_for_user(self.current_user)
        self.font_var.set(s.get("font_size", "Medium"))
        self.theme_var.set(s.get("theme", "Light"))
        self.currency_var.set(s.get("currency", "£"))
        self.ref_total_var.set(s.get("ref_total", "0"))
        # Pre-fill bills target from the current user's bills table
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT monthly_target FROM bills WHERE user_id=?", (self.current_user,))
        row = c.fetchone()
        conn.close()
        self.settings_bills_var.set(str(int(row[0]) if row and float(row[0]).is_integer() else (f"{row[0]:.2f}" if row else "1000")))

    def save_settings(self):
        scope = self.apply_to_var.get()  # 'me' | 'carol' | 'both'
        font_choice = self.font_var.get()
        theme_choice = self.theme_var.get()
        currency_choice = self.currency_var.get()
        ref_val_raw = self.ref_total_var.get().strip()

        # Persist settings in chosen scope
        self.write_setting(scope, "font_size", font_choice)
        self.write_setting(scope, "theme", theme_choice)
        self.write_setting(scope, "currency", currency_choice)

        # Save reference total if valid number
        try:
            ref_val = float(ref_val_raw)
            self.write_setting(scope, "ref_total", str(ref_val))
        except ValueError:
            # ignore invalid - don't save
            pass

        # Bills target update can be applied to 1 or 2 users
        bt_raw = self.settings_bills_var.get().strip()
        try:
            new_target = float(bt_raw)
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            targets = []
            if scope == "both":
                targets = ["me", "carol"]
            else:
                targets = [scope]
            for uid in targets:
                c.execute("UPDATE bills SET monthly_target=? WHERE user_id=?", (new_target, uid))
            conn.commit()
            conn.close()
        except ValueError:
            messagebox.showwarning("Settings", "Bills target was not a valid number, so it was not changed.")

        # Re-apply (uses current_user to compute effective settings)
        self.apply_settings()
        self.populate_settings_controls()
        messagebox.showinfo("Settings", f"Settings saved for '{scope}'. Applied to current view.")

# ---------------- MAIN ----------------
if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = FinanceApp(root)
    root.mainloop()
