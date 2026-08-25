import os
import queue
import re
import threading

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import config
from git_collector import (
    GitContext,
    GitError,
    add_all,
    collect,
    commit,
    current_branch,
    has_upstream,
    push,
)
from llm_client import LLMError, generate_commit_message
from prompt_builder import build_file_summary


class App:
    def __init__(self, root: tk.Tk, repo_dir: str, ctx: GitContext | None = None):
        self.root = root
        self.repo_dir = repo_dir
        self.ctx = ctx
        self.message = ""
        self._busy = False
        self._current_op = None

        if ctx is not None:
            root.title(f"git-commit-log-ai · {ctx.project_short}")
        else:
            root.title("git-commit-log-ai · 请选择项目目录")
        root.geometry("820x720")
        root.minsize(680, 600)

        self._build_dir_bar(root)

        main = ttk.Frame(root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=3)
        main.rowconfigure(1, weight=1)

        ttk.Label(main, text="变更文件", font=(None, 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(main, text="提交信息（可编辑）", font=(None, 10, "bold")).grid(row=0, column=1, sticky="w")

        file_frame = ttk.Frame(main)
        file_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        file_frame.rowconfigure(0, weight=1)
        file_frame.columnconfigure(0, weight=1)

        self.file_text = tk.Text(file_frame, wrap="none", width=34, height=20, state="disabled")
        fb = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_text.yview)
        self.file_text.configure(yscrollcommand=fb.set)
        self.file_text.grid(row=0, column=0, sticky="nsew")
        fb.grid(row=0, column=1, sticky="ns")

        if self.ctx is not None:
            self.file_text.config(state="normal")
            self.file_text.insert("1.0", build_file_summary(self.ctx))
            self.file_text.config(state="disabled")
        else:
            self.file_text.config(state="normal")
            self.file_text.insert("1.0", "尚未选择项目。\n\n请点击上方「选择项目」按钮，\n选择一个 Git 项目根目录。")
            self.file_text.config(state="disabled")

        msg_frame = ttk.Frame(main)
        msg_frame.grid(row=1, column=1, sticky="nsew")
        msg_frame.rowconfigure(0, weight=1)
        msg_frame.columnconfigure(0, weight=1)

        self.msg_text = tk.Text(msg_frame, wrap="word", width=60, height=20, font=("Consolas", 10))
        mb = ttk.Scrollbar(msg_frame, orient="vertical", command=self.msg_text.yview)
        self.msg_text.configure(yscrollcommand=mb.set)
        self.msg_text.grid(row=0, column=0, sticky="nsew")
        mb.grid(row=0, column=1, sticky="ns")
        self.msg_text.bind("<KeyRelease>", lambda e: self.sync_message())

        btns = ttk.Frame(main)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.status = ttk.Label(btns, text="", foreground="#666")
        self.status.pack(side=tk.LEFT, padx=(0, 10))

        self.progress = ttk.Progressbar(btns, mode="indeterminate", length=180)
        self.progress.pack(side=tk.LEFT, padx=(0, 10))

        self.quit_btn = ttk.Button(btns, text="退出", command=self.root.destroy, padding=(16, 8))
        self.quit_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.push_btn = ttk.Button(btns, text="推送到 GitHub", command=self.push_changes, padding=(16, 8))
        self.push_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.commit_btn = ttk.Button(btns, text="提交变更文件", command=self.commit_changes, padding=(16, 8))
        self.commit_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self.gen_btn = ttk.Button(btns, text="重新生成", command=self.regenerate, padding=(16, 8))
        self.gen_btn.pack(side=tk.RIGHT, padx=(0, 12))

        if self.ctx is None:
            self._disable_all_buttons()
            self.status.config(text="未选择 Git 项目目录", foreground="#a00")
        else:
            self.msg_text.delete("1.0", "end")
            self.msg_text.insert("1.0", "正在生成提交信息…")
            root.after(100, self.generate)

    def _build_dir_bar(self, root: tk.Tk):
        bar = ttk.LabelFrame(root, text="项目目录", padding=8)
        bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        bar.columnconfigure(1, weight=1)

        self.dir_var = tk.StringVar(value=self.repo_dir)
        ttk.Label(bar, textvariable=self.dir_var, foreground="#333", anchor="w").grid(
            row=0, column=0, sticky="ew"
        )
        env_tip = tk.StringVar(value="模型配置在 .env 文件中，点「打开 .env」可修改")
        ttk.Label(bar, textvariable=env_tip, foreground="#777").grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        self.env_btn = ttk.Button(bar, text="打开 .env", command=self.open_env)
        self.env_btn.grid(row=0, column=2, padx=(8, 0), sticky="e")
        ttk.Button(bar, text="选择项目", command=self.choose_directory).grid(
            row=0, column=1, padx=(8, 0), sticky="e"
        )

    def open_env(self):
        env = config.app_base_dir() / ".env"
        if not env.exists():
            example = config.app_base_dir() / ".env.example"
            if example.exists():
                env.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                env.write_text(
                    "API_KEY=你的APIKey\n"
                    "BASE_URL=https://api.deepseek.com\n"
                    "MODEL=deepseek-chat\n",
                    encoding="utf-8",
                )
        if os.name == "nt":
            os.startfile(str(env))
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(env)])

    def choose_directory(self):
        chosen = filedialog.askdirectory(initialdir=self.repo_dir, title="选择 Git 项目目录")
        if not chosen:
            return
        try:
            ctx = collect(chosen)
        except GitError as e:
            self.repo_dir = chosen
            self.dir_var.set(chosen)
            self.status.config(text=f"不是 Git 项目或读取失败：{e}", foreground="#a00")
            return
        self.ctx = ctx
        self.repo_dir = chosen
        self.dir_var.set(chosen)
        self.root.title(f"git-commit-log-ai · {ctx.project_short}")
        self.file_text.config(state="normal")
        self.file_text.delete("1.0", "end")
        self.file_text.insert("1.0", build_file_summary(ctx))
        self.file_text.config(state="disabled")
        self.msg_text.delete("1.0", "end")
        self.msg_text.insert("1.0", "正在生成提交信息…")
        self._restore_after_generate()
        self.generate()

    def sync_message(self):
        self.message = self.msg_text.get("1.0", "end-1c")

    def generate(self, refresh: bool = False):
        if self._busy:
            return
        self._busy = True
        self._current_op = "generate"
        self._disable_all_buttons()
        self.root.config(cursor="watch")
        text = "正在重新检查变更并生成提交信息…" if refresh else "正在分析变更并生成提交信息…"
        self.status.config(text=text, foreground="#666")
        self.progress.start(12)

        self._result_queue = queue.Queue()
        model = config.model()
        repo_dir = self.repo_dir
        ctx = self.ctx

        def worker():
            try:
                current_ctx = collect(repo_dir) if refresh else ctx
                result = generate_commit_message(current_ctx, model=model)
                self._result_queue.put(("ok", current_ctx, result))
            except GitError as e:
                self._result_queue.put(("giterr", e))
            except Exception as e:
                self._result_queue.put(("err", e))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self._poll_result)

    def _poll_result(self):
        try:
            kind, *payload = self._result_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._poll_result)
            return
        op = self._current_op
        self._current_op = None
        if op == "commit":
            self._handle_commit(kind, payload)
        elif op == "push":
            self._handle_push(kind, payload)
        else:
            self._handle_generate(kind, payload)

    def _handle_generate(self, kind, payload):
        if kind == "ok":
            ctx, result = payload
            self._on_generate_done(result=result, ctx=ctx)
        else:
            self._on_generate_done(error=payload[0])

    def _on_generate_done(self, result=None, error=None, ctx=None):
        self.progress.stop()
        self.root.config(cursor="")
        self._restore_after_generate()
        self._busy = False

        if ctx is not None:
            self.ctx = ctx
            self.file_text.config(state="normal")
            self.file_text.delete("1.0", "end")
            self.file_text.insert("1.0", build_file_summary(ctx))
            self.file_text.config(state="disabled")

        if error is None:
            self.message = result
            self.msg_text.delete("1.0", "end")
            self.msg_text.insert("1.0", result)
            self.status.config(text="生成完成", foreground="#2a7a2a")
        elif isinstance(error, GitError):
            self.status.config(text=f"重新收集变更失败：{error}", foreground="#a00")
        elif isinstance(error, LLMError):
            self.status.config(text="", foreground="#a00")
            self.msg_text.delete("1.0", "end")
            self.msg_text.insert(
                "1.0", f"生成失败：{error}\n\n你可以手动参考左侧变更列表填写提交信息。"
            )
        else:
            self.status.config(text="", foreground="#a00")
            self.msg_text.delete("1.0", "end")
            self.msg_text.insert("1.0", f"生成失败：{error}")

    def regenerate(self):
        self.sync_message()
        self.generate(refresh=True)

    def _disable_all_buttons(self):
        self.gen_btn.config(state="disabled")
        self.commit_btn.config(state="disabled")
        self.push_btn.config(state="disabled")

    def _restore_after_generate(self):
        self.gen_btn.config(state="normal")
        self.commit_btn.config(state="normal")
        self.push_btn.config(state="disabled")

    def _restore_after_commit_or_push(self):
        self.gen_btn.config(state="normal")
        self.commit_btn.config(state="normal")
        self.push_btn.config(state="normal")

    def commit_changes(self):
        self.sync_message()
        if self.ctx is None or self._busy:
            return
        message = self.message.strip()
        if not message:
            self.status.config(text="提交信息为空，无法提交", foreground="#a00")
            return
        if not messagebox.askyesno(
            "确认提交",
            "即将把全部变更（含未跟踪新文件）提交为一个 commit：\n\n"
            "  git add -A\n  git commit -F -\n\n"
            f"提交信息：\n{message}\n\n是否继续？",
            parent=self.root,
        ):
            return
        self._busy = True
        self._current_op = "commit"
        self._disable_all_buttons()
        self.status.config(text="正在提交变更文件…", foreground="#666")
        self.progress.start(12)
        self._result_queue = queue.Queue()
        repo_dir, msg = self.repo_dir, message

        def worker():
            try:
                add_all(repo_dir)
                try:
                    out = commit(repo_dir, msg)
                except GitError as e:
                    if "nothing to commit" in str(e):
                        self._result_queue.put(("commit_nothing",))
                        return
                    raise
                branch = current_branch(repo_dir)
                m = re.search(r"\[[^\]]+\s([0-9a-f]+)\]", out)
                short_hash = m.group(1) if m else ""
                self._result_queue.put(("commit_ok", branch, short_hash))
            except GitError as e:
                self._result_queue.put(("giterr", e))
            except Exception as e:
                self._result_queue.put(("err", e))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self._poll_result)

    def _handle_commit(self, kind, payload):
        self.progress.stop()
        self.root.config(cursor="")
        self._busy = False
        if kind == "commit_ok":
            self._restore_after_commit_or_push()
            branch, short_hash = payload
            suffix = f"{branch} {short_hash}" if short_hash else branch
            self.status.config(
                text=f"提交成功（{suffix}），可点击「推送到 GitHub」", foreground="#2a7a2a"
            )
        else:
            self._restore_after_generate()
            if kind == "commit_nothing":
                self.status.config(text="没有可提交的变更", foreground="#a00")
            elif kind == "giterr":
                self.status.config(text=self._friendly_git_error(payload[0], op="提交"), foreground="#a00")
            else:
                self.status.config(text=f"提交失败：{payload[0]}", foreground="#a00")

    def push_changes(self):
        if self.ctx is None or self._busy:
            return
        if not messagebox.askyesno(
            "确认推送",
            "即将把本地提交推送到远程仓库：\n\n  git push\n\n是否继续？",
            parent=self.root,
        ):
            return
        self._busy = True
        self._current_op = "push"
        self._disable_all_buttons()
        self.status.config(text="正在推送到远程仓库…", foreground="#666")
        self.progress.start(12)
        self._result_queue = queue.Queue()
        repo_dir = self.repo_dir

        def worker():
            try:
                if not has_upstream(repo_dir):
                    branch = current_branch(repo_dir)
                    self._result_queue.put(("push_no_upstream", branch))
                    return
                out = push(repo_dir)
                self._result_queue.put(("push_ok", out))
            except GitError as e:
                self._result_queue.put(("giterr", e))
            except Exception as e:
                self._result_queue.put(("err", e))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self._poll_result)

    def _handle_push(self, kind, payload):
        self.progress.stop()
        self.root.config(cursor="")
        self._busy = False
        self._restore_after_commit_or_push()
        if kind == "push_ok":
            out = payload[0]
            if "Everything up-to-date" in out or "Already up to date" in out:
                self.status.config(text="已是最新，无需推送", foreground="#2a7a2a")
            else:
                self.status.config(text="推送成功", foreground="#2a7a2a")
        elif kind == "push_no_upstream":
            branch = payload[0]
            self.status.config(
                text=f"当前分支 {branch} 无上游分支，请手动执行：git push -u origin {branch}",
                foreground="#a00",
            )
        elif kind == "giterr":
            self.status.config(text=self._friendly_git_error(payload[0], op="推送"), foreground="#a00")
        else:
            self.status.config(text=f"推送失败：{payload[0]}", foreground="#a00")

    def _friendly_git_error(self, e, op: str):
        msg = str(e)
        if "Please tell me who you are" in msg:
            return f"{op}失败：未配置 git 身份，请先执行 git config --global user.name / user.email"
        if "does not appear to be a git repository" in msg:
            return f"{op}失败：未配置远程仓库（origin），请先添加远程仓库"
        if "could not read Username" in msg or "Authentication failed" in msg or "Permission denied" in msg:
            return f"{op}失败：远程仓库认证失败，请检查凭据"
        if "Could not resolve host" in msg or "unable to access" in msg:
            return f"{op}失败：无法访问远程仓库，请检查网络"
        return f"{op}失败：{msg}"


def run_gui(repo_dir: str, ctx: GitContext) -> None:
    root = tk.Tk()
    App(root, repo_dir, ctx)
    root.mainloop()