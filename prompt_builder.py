import config


def build_messages(ctx) -> list:
    style = config.commit_style()
    lang = config.commit_language()

    if style == "simple":
        format_rule = (
            "以简洁的祁使句描述本次改动，单行不超过 50 个字符，"
            "如「修复登录超时问题」。"
        )
    else:
        format_rule = (
            "使用 Conventional Commits 规范：\n"
            "<type>(<scope>): <subject>\n\n<body>\n\n<footer>\n"
            "type 取 feat / fix / docs / style / refactor / perf / test / "
            "build / ci / chore / revert 之一。\n"
            "subject 用祁使句式、首字母可视语言风格决定，控制在 50 字符内；\n"
            "若有多个独立改动点，在 body 中用项目符号逐条列出；\n"
            "若含破坏性变更，在 footer 加 BREAKING CHANGE: 说明。"
        )

    if lang == "zh":
        format_rule += "\n提交信息使用中文编写。"
    elif lang == "en":
        format_rule += "\nWrite the commit message in English."
    elif lang == "auto":
        format_rule += (
            "\n根据最近提交历史的语言风格判断输出语言；若无历史，则用中文。"
        )

    system = (
        "你是一名资深的 Git 提交信息撰写助手。你只负责根据输入的变更内容生成一条\n"
        "高质量、符合规范的 Git 提交信息，不输出任何多余解释、代码或前后缀。\n\n"
        "先分析「变更状态」和「差异内容」，理解改动的目的与影响；\n"
        "「近期提交」只用于风格参考，不要照抄其内容；\n"
        "如果提交信息里需要提到文件路径，使用短路径；\n"
        "未跟踪的新文件也会被列出，若它们属于本次改动的一部分，请在提交信息中体现。\n\n"
        "格式要求：\n" + format_rule
    )

    user = (
        f"项目目录: {ctx.project_short}\n\n"
        f"变更内容如下：\n\n{ctx.summary()}\n\n"
        "请基于以上变更生成一条提交信息（只输出提交信息本身）。"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_file_summary(ctx) -> str:
    if not ctx.file_list:
        return "（无变更）"
    return "\n".join(f"- {f}" for f in ctx.file_list)