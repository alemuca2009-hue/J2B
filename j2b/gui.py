"""Minimal desktop UI (Tkinter): pick a jar, convert, read the summary.

Tkinter ships with CPython, so this adds no dependency. The conversion runs on
a worker thread and posts messages to the UI through a queue.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path

from .converter import ConversionError, Converter
from .history import ConversionHistory
from .knowledge import CaseMemory, KnowledgeBase
from .models import ConversionOptions
from .version import __version__


def launch() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"J2B Studio {__version__}")
    root.geometry("880x620")
    root.configure(bg="#0b0f17")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background="#0b0f17")
    style.configure("TLabel", background="#0b0f17", foreground="#dbe4f0")
    style.configure("Muted.TLabel", foreground="#8b9bb4")
    style.configure("TButton", padding=6)
    style.configure("TCheckbutton", background="#0b0f17", foreground="#dbe4f0")

    state: dict[str, object] = {"mod": "", "output": ""}
    messages: "queue.Queue[str]" = queue.Queue()

    header = ttk.Frame(root, padding=(16, 14, 16, 6))
    header.pack(fill="x")
    ttk.Label(header, text="Java → Bedrock conversion", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
    ttk.Label(
        header,
        text="Converts what it can prove. Everything else is reported as partial, manual or unsupported.",
        style="Muted.TLabel",
    ).pack(anchor="w", pady=(2, 0))

    picker = ttk.Frame(root, padding=(16, 6))
    picker.pack(fill="x")
    path_var = tk.StringVar(value="No mod selected")
    ttk.Label(picker, textvariable=path_var, style="Muted.TLabel").pack(side="left", fill="x", expand=True)

    def choose() -> None:
        chosen = filedialog.askopenfilename(
            title="Select a mod jar",
            filetypes=[("Mod archives", "*.jar *.zip"), ("All files", "*.*")],
        )
        if chosen:
            state["mod"] = chosen
            path_var.set(chosen)

    ttk.Button(picker, text="Choose mod…", command=choose).pack(side="right")

    reference = ttk.Frame(root, padding=(16, 6))
    reference.pack(fill="x")
    reference_var = tk.StringVar()
    ttk.Label(reference, text="Reference jar / resource ZIP (optional)").pack(side="left")
    ttk.Entry(reference, textvariable=reference_var).pack(side="left", fill="x", expand=True, padx=8)

    def choose_reference() -> None:
        chosen = filedialog.askopenfilename(
            title="Select Java reference models and textures",
            filetypes=[("Java resources", "*.jar *.zip"), ("All files", "*.*")],
        )
        if chosen:
            reference_var.set(chosen)

    ttk.Button(reference, text="Browse…", command=choose_reference).pack(side="right")

    options = ttk.Frame(root, padding=(16, 6))
    options.pack(fill="x")
    pack_name_var = tk.StringVar()
    ttk.Label(options, text="Pack name").pack(side="left")
    ttk.Entry(options, textvariable=pack_name_var, width=30).pack(side="left", padx=(8, 16))
    mcaddon_var = tk.BooleanVar(value=True)
    learning_var = tk.BooleanVar(value=True)
    machines_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(options, text="Package .mcaddon", variable=mcaddon_var).pack(side="left", padx=(0, 14))
    ttk.Checkbutton(options, text="Record learning", variable=learning_var).pack(side="left", padx=(0, 14))
    ttk.Checkbutton(
        options, text="Machine stations", variable=machines_var
    ).pack(side="left")

    log = tk.Text(root, height=22, bg="#0e1520", fg="#c9d6e6", insertbackground="#c9d6e6", relief="flat", wrap="word")
    log.pack(fill="both", expand=True, padx=16, pady=(8, 6))
    log.insert("end", "Ready.\n")
    log.configure(state="disabled")

    def append(text: str = "") -> None:
        log.configure(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")

    actions = ttk.Frame(root, padding=(16, 0, 16, 14))
    actions.pack(fill="x")
    convert_button = ttk.Button(actions, text="Convert")
    convert_button.pack(side="left")
    open_button = ttk.Button(actions, text="Open output folder", state="disabled")
    open_button.pack(side="left", padx=8)
    status_var = tk.StringVar(value="")
    ttk.Label(actions, textvariable=status_var, style="Muted.TLabel").pack(side="left", padx=10)

    def pump() -> None:
        while not messages.empty():
            append(messages.get())
        root.after(120, pump)

    def run_conversion(output_root: str) -> None:
        options_value = ConversionOptions(
            output_dir=output_root,
            pack_name=pack_name_var.get().strip(),
            make_mcaddon=mcaddon_var.get(),
            record_learning=learning_var.get(),
            machine_stations=machines_var.get(),
            vanilla_path=reference_var.get().strip(),
        )
        converter = Converter(
            options=options_value,
            knowledge=KnowledgeBase(),
            memory=CaseMemory() if learning_var.get() else None,
            progress=lambda text: messages.put(f"· {text}"),
        )
        try:
            result = converter.convert(str(state["mod"]))
        except ConversionError as exc:
            messages.put(f"Failed: {exc}")
            root.after(0, lambda: messagebox.showerror("Conversion failed", str(exc)))
            root.after(0, lambda: convert_button.configure(state="normal"))
            return

        stats = result.stats or result.compute_stats()
        counts = stats["status_counts"]
        for feature in result.features:
            if feature.status in ("manual", "unsupported"):
                messages.put(f"  [ ] {feature.id} — {feature.limitations[0] if feature.limitations else feature.display}")
        messages.put("")
        messages.put(
            f"Done: {counts.get('converted', 0)} converted, {counts.get('partial', 0)} partial, "
            f"{counts.get('manual', 0)} manual, {counts.get('unsupported', 0)} unsupported."
        )
        messages.put(f"Estimated fidelity: {stats['estimated_fidelity'] * 100:.1f}%")
        messages.put(f"Validation errors: {sum(1 for check in result.validation if check.severity == 'error')}")
        messages.put(f"Output: {result.packs.root}")
        state["output"] = str(result.packs.root)

        def enable() -> None:
            convert_button.configure(state="normal")
            open_button.configure(state="normal")
            status_var.set(Path(str(state["output"])).name)

        root.after(0, enable)

    def start() -> None:
        if not state["mod"]:
            messagebox.showinfo("No mod selected", "Choose a mod jar first.")
            return
        output_root = filedialog.askdirectory(title="Choose an output folder")
        if not output_root:
            output_root = "j2b_output"
        convert_button.configure(state="disabled")
        open_button.configure(state="disabled")
        status_var.set("Converting…")
        append("")
        append(f"Converting {Path(str(state['mod'])).name}")
        threading.Thread(target=run_conversion, args=(output_root,), daemon=True).start()

    def open_output() -> None:
        target = str(state.get("output") or "")
        if not target:
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", target])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
        except OSError as exc:
            messagebox.showerror("Cannot open folder", str(exc))

    convert_button.configure(command=start)
    open_button.configure(command=open_output)
    pump()

    history = ConversionHistory().stats()
    if history.get("available") and history.get("conversions"):
        append(
            f"History: {history['conversions']} conversions, average fidelity "
            f"{history['average_fidelity'] * 100:.1f}%"
        )

    root.mainloop()
    return 0
