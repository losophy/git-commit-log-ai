import os
import subprocess
from typing import List, Optional

import config

GIT_ENCODING = "utf-8"


class GitError(Exception):
    pass


class GitContext:
    def __init__(self, repo_dir: str, project_short: str):
        self.repo_dir = repo_dir
        self.project_short = project_short
        self.status: Optional[str] = None
        self.diff: Optional[str] = None
        self.log: Optional[str] = None
        self.file_list: List[str] = []
        self.untracked: List[str] = []
        self.diff_truncated: bool = False

    def summary(self) -> str:
        lines = []
        if self.status:
            lines.append(f"变更状态（{len(self.file_list)} 个文件）:\n{self.status}")
        if self.untracked:
            lines.append(f"未跟踪新文件:\n" + "\n".join(self.untracked))
        if self.diff:
            head = "差异内容（已截断）:\n" if self.diff_truncated else "差异内容:\n"
            lines.append(head + self.diff)
        if self.log:
            lines.append("近期提交（风格参考）:\n" + self.log)
        return "\n\n".join(lines)


def _run_git(repo_dir: str, args: List[str]) -> str:
    kwargs = dict(
        cwd=repo_dir,
        capture_output=True,
        text=False,
        timeout=60,
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(["git", "-c", "core.quotepath=false", *args], **kwargs)
    except FileNotFoundError:
        raise GitError("未找到 git 命令，请确认已安装 Git 并在 PATH 中")
    except Exception as e:
        raise GitError(f"执行 git 命令失败: {e}")
    stdout = proc.stdout.decode(GIT_ENCODING, errors="replace")
    stderr = proc.stderr.decode(GIT_ENCODING, errors="replace")
    if proc.returncode != 0:
        raise GitError(stderr.strip() or stdout.strip() or f"git {' '.join(args)} 返回码 {proc.returncode}")
    return stdout


def is_git_repo(repo_dir: str) -> bool:
    try:
        _run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"]).strip()
        return True
    except GitError:
        return False


def _truncate(text: str, max_lines: int) -> "tuple[str, bool]":
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    head = lines[:max_lines]
    tail = f"\n...(已截断 {len(lines) - max_lines} 行，因超过 MAX_DIFF_LINES={max_lines})..."
    return "\n".join(head) + tail, True


def collect(repo_dir: str) -> GitContext:
    short = repo_dir.rstrip("/\\").split("\\")[-1].split("/")[-1] or repo_dir
    ctx = GitContext(repo_dir, short)

    status = _run_git(repo_dir, ["status", "--porcelain"]).rstrip("\n")
    ctx.status = status if status else "（无变更）"
    ctx.file_list = [
        line[3:].strip().strip('"').replace("'", "")
        for line in status.splitlines()
        if len(line) >= 4
    ]
    ctx.untracked = [
        line[3:].strip().strip('"') for line in status.splitlines() if line.startswith("??")
    ]

    max_lines = config.max_diff_lines()
    raw_diff = _run_git(repo_dir, ["diff", "HEAD"]).rstrip("\n")
    if raw_diff:
        ctx.diff, ctx.diff_truncated = _truncate(raw_diff, max_lines)
    else:
        ctx.diff = None

    count = config.recent_commits()
    if count > 0:
        log = _run_git(repo_dir, ["log", "-n", str(count), "--pretty=%h %s"]).strip()
        ctx.log = log if log else None
    else:
        ctx.log = None

    return ctx