import argparse
import sys
from pathlib import Path

import config
from git_collector import GitContext, GitError, collect, is_git_repo
from gui import run_gui


def show_message(title: str, message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def resolve_target(root_arg: str | None) -> Path:
    if root_arg:
        return Path(root_arg).resolve()
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    candidates.append(Path.cwd().resolve())
    for c in candidates:
        if c.is_dir() and is_git_repo(str(c)):
            return c
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="git-commit-log-ai：用大模型生成 Git 提交信息。"
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Git 项目目录（省略时：exe 版本取 exe 所在目录，源码版本取当前目录）",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="命令行模式：不弹窗，直接把生成的提交信息打印到标准输出",
    )
    args = parser.parse_args()

    target = resolve_target(args.project)

    if not target.is_dir():
        if args.print:
            print(f"目录不存在: {target}")
        else:
            show_message("目录不存在", f"目录不存在：\n{target}")
        return 1

    if args.print:
        if not is_git_repo(str(target)):
            print(f"[{target}] 不是 Git 仓库（当前目录中不存在 .git）。")
            return 1
        try:
            ctx = collect(str(target))
        except GitError as e:
            print(f"收集变更失败: {e}")
            return 1

        from llm_client import LLMError, generate_commit_message

        print(f"项目: {ctx.project_short}")
        print(ctx.summary())
        print("-" * 60)
        try:
            msg = generate_commit_message(ctx)
        except LLMError as e:
            print(f"生成失败: {e}")
            return 1
        print("提交信息:")
        print(msg)
        return 0

    # GUI 模式：默认目录不是 Git 仓库也没关系，可以在界面里重新选择项目目录
    ctx = None
    try:
        if is_git_repo(str(target)):
            ctx = collect(str(target))
    except GitError:
        ctx = None

    try:
        run_gui(str(target), ctx)
    except Exception as e:
        show_message("启动界面失败", str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())