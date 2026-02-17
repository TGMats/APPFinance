import tkinter as tk

from finance_app import FinanceApp, init_db


if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    FinanceApp(root)
    root.mainloop()
