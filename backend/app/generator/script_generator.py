"""Script generator – uses LLM to produce murder-mystery content."""
from __future__ import annotations

import json
from typing import Any

from langfuse import observe

from app.llm.adapter import LLMAdapter, get_llm
from app.models.game import (
    Act,
    ChoiceOption,
    ChoiceQuestion,
    Clue,
    Role,
    RoleAlignment,
    Script,
    ScriptStyle,
    uid,
)

STYLE_LABELS: dict[ScriptStyle, str] = {
    ScriptStyle.DETECTIVE: "正统侦探/悬疑",
    ScriptStyle.DRAMA: "戏剧侦探/搞笑",
    ScriptStyle.DISCOVER: "寻迹侦探/探索",
    ScriptStyle.DESTINY: "命运侦探/浪漫",
    ScriptStyle.DREAM: "幻梦侦探/叙诡",
    ScriptStyle.DIMENSION: "赛博侦探/科幻",
    ScriptStyle.DEATH: "幽冥侦探/恐怖",
}

# ── helpers ────────────────────────────────────────────

def _strip_thinking(raw: str) -> str:
    """Remove <think>...</think> blocks from M2.7 responses."""
    import re
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def _clean_json(raw: str) -> str:
    """Strip thinking tags and markdown code fences."""
    raw = _strip_thinking(raw)
    raw = raw.strip()
    # Remove ```json ... ``` wrapper
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)
    return raw.strip()


def _try_fix_truncated_json(raw: str) -> str:
    """Attempt to fix truncated JSON by closing open brackets."""
    # Count unclosed brackets
    opens = raw.count("{") - raw.count("}")
    open_arrays = raw.count("[") - raw.count("]")
    # Remove trailing comma if present
    raw = raw.rstrip().rstrip(",")
    # If we're inside a string, close it
    if raw.count('"') % 2 == 1:
        raw += '"'
    # Close arrays and objects
    raw += "]" * open_arrays
    raw += "}" * opens
    return raw


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = _clean_json(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try fixing truncated JSON
        try:
            fixed = _try_fix_truncated_json(cleaned)
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM返回的JSON无法解析: {e}. 原文前200字: {cleaned[:200]}")


# ── outline generation ─────────────────────────────────

OUTLINE_SYSTEM = """\
你是一个专业的剧本杀编剧AI。你将根据给定的风格创作一个精彩的谋杀悬疑剧本大纲。
规则：
- 剧本必须有4个原创角色，其中1个是凶手，3个是无辜的
- 每个角色需要有独特的名字、背景故事和秘密
- 凶手的秘密应该是杀人的动机和手法
- 无辜角色各自持有部分线索
- 剧本应该有足够的悬疑性和趣味性
- 控制在10分钟可以玩完的体量
- 角色名字应该符合故事设定，不要使用张山、酷鹅、胡一菲、豆几这些名字
"""


def _outline_user_prompt(style: ScriptStyle) -> str:
    label = STYLE_LABELS[style]
    return f"""\
请为以下设定创作一个剧本杀大纲。

【风格】{label}

请生成4个原创的剧本角色，每个角色都有独特的名字和身份，名字应符合故事世界观。
注意：不要使用张山、酷鹅、胡一菲、豆几这些名字，请创造全新的角色名。

请严格按照以下JSON格式返回（不要添加任何其他文字）：
{{
  "title": "剧本名称",
  "prologue": "开场白/故事背景（2-3句话）",
  "truth": "完整真相（仅DM可见，包括凶手是谁、动机、手法、时间线）",
  "roles": [
    {{
      "name": "角色在剧本中的名字",
      "alignment": "murderer 或 innocent",
      "background": "角色背景（1-2句话，简洁）",
      "secret": "角色秘密（1-2句话，简洁）",
      "clues": ["线索1（一句话）", "线索2（一句话）"]
    }}
  ]
}}
注意：roles数组中恰好有4个角色，且恰好有1个alignment为"murderer"。
"""


@observe(name="剧本大纲生成")
async def generate_outline(
    style: ScriptStyle,
    llm: LLMAdapter | None = None,
) -> Script:
    """Generate the script outline (title, prologue, roles, truth)."""
    if llm is None:
        llm = get_llm()

    data: dict[str, Any] = {}
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            raw = await llm.generate(
                system_prompt=OUTLINE_SYSTEM,
                user_prompt=_outline_user_prompt(style),
                json_mode=True,
                max_tokens=8192,
                log_name="generate_outline",
            )
            if not raw or not raw.strip():
                raise ValueError("LLM返回了空响应")
            data = _parse_json(raw)
            # 校验：必须有4个roles，且恰好1个murderer
            role_list = data.get("roles", [])
            if len(role_list) != 4:
                raise ValueError(f"需要4个角色，但只生成了{len(role_list)}个（可能输出被截断）")
            murderer_count = sum(1 for r in role_list if r.get("alignment") == "murderer")
            if murderer_count != 1:
                raise ValueError(f"需要恰好1个凶手，但有{murderer_count}个")
            break
        except Exception as e:
            last_err = e
            print(f"[generate_outline] attempt {attempt+1} failed: {e}")
            if attempt < 2:
                print(f"[generate_outline] retrying...")
                continue
            raise ValueError(f"大纲生成失败(重试{attempt+1}次): {last_err}") from e

    roles: list[Role] = []
    murderer_role_id = ""
    for r in data["roles"]:
        rid = uid()
        alignment = (
            RoleAlignment.MURDERER
            if r["alignment"] == "murderer"
            else RoleAlignment.INNOCENT
        )
        if alignment == RoleAlignment.MURDERER:
            murderer_role_id = rid
        roles.append(
            Role(
                id=rid,
                name=r["name"],
                alignment=alignment,
                background=r.get("background", ""),
                secret=r.get("secret", ""),
                clues=r.get("clues", []),
            )
        )

    script = Script(
        style=style,
        title=data.get("title", "未命名剧本"),
        prologue=data.get("prologue", ""),
        roles=roles,
        truth=data.get("truth", ""),
        murderer_role_id=murderer_role_id,
    )
    return script


# ── act generation ─────────────────────────────────────

ACT_SYSTEM = """\
你是一个专业的剧本杀编剧AI。你需要根据已有的剧本大纲为指定幕生成详细内容。
规则：
- 每幕包含叙述文字、线索和2道选择题
- 线索应逐步揭示真相，但不能直接指出凶手
- 选择题应考验玩家的推理能力
- 第1幕：建立场景，发现案件，初步线索
- 第2幕：深入调查，发现矛盾和更多线索
- 第3幕：关键证据浮现，准备最终投票
- 语言风格要符合剧本的整体风格
"""


def _act_user_prompt(
    script: Script,
    act_number: int,
    previous_acts: list[Act],
) -> str:
    label = STYLE_LABELS[script.style]
    roles_desc = "\n".join(
        f"- {r.name}（{'凶手' if r.alignment == RoleAlignment.MURDERER else '无辜'}）：{r.background}"
        for r in script.roles
    )
    prev_desc = ""
    if previous_acts:
        prev_desc = "\n\n【已有幕内容】\n"
        for a in previous_acts:
            prev_desc += f"第{a.act_number}幕「{a.title}」：{a.narration[:100]}...\n"

    return f"""\
请为以下剧本生成第{act_number}幕内容。

【剧本名称】{script.title}
【风格】{label}
【开场白】{script.prologue}
【真相】{script.truth}
【角色】
{roles_desc}
{prev_desc}

请严格按照以下JSON格式返回（不要添加任何其他文字）：
{{
  "title": "第{act_number}幕标题",
  "narration": "本幕DM叙述文字（3-5句话，推动剧情发展）",
  "clues": [
    {{
      "title": "线索标题",
      "content": "线索详细内容"
    }}
  ],
  "choices": [
    {{
      "question": "选择题题目",
      "options": [
        {{"text": "选项A", "is_correct": false}},
        {{"text": "选项B", "is_correct": true}},
        {{"text": "选项C", "is_correct": false}}
      ],
      "explanation": "答案解析"
    }}
  ]
}}
注意：
- clues数组包含2-3条线索
- choices数组包含2道选择题，每题3个选项，只有1个正确
"""


@observe(name="章节生成")
async def generate_act(
    script: Script,
    act_number: int,
    previous_acts: list[Act],
    llm: LLMAdapter | None = None,
) -> Act:
    """Generate content for a single act. Retries up to 2 times on JSON errors."""
    if llm is None:
        llm = get_llm()

    data: dict[str, Any] = {}
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            raw = await llm.generate(
                system_prompt=ACT_SYSTEM,
                user_prompt=_act_user_prompt(script, act_number, previous_acts),
                json_mode=True,
                max_tokens=8192,
                log_name=f"generate_act({act_number})",
            )
            if not raw or not raw.strip():
                raise ValueError("LLM返回了空响应")
            data = _parse_json(raw)
            # Validate: choices must have 2+ options each
            for qi, q in enumerate(data.get("choices", [])):
                opts = q.get("options", [])
                if len(opts) < 2:
                    raise ValueError(f"选择题{qi+1}只有{len(opts)}个选项（需要至少2个），可能输出被截断")
            break
        except Exception as e:
            last_err = e
            if attempt < 2:
                print(f"[generate_act] attempt {attempt+1} failed: {e}")
                continue
            raise ValueError(f"章节生成失败(重试{attempt+1}次): {last_err}") from e

    clues = [
        Clue(
            id=uid(),
            title=c.get("title", "线索"),
            content=c.get("content", ""),
            act=act_number,
        )
        for c in data.get("clues", [])
    ]

    choices = []
    for q in data.get("choices", []):
        options = [
            ChoiceOption(
                id=uid(),
                text=o.get("text", ""),
                is_correct=o.get("is_correct", False),
            )
            for o in q.get("options", [])
        ]
        choices.append(
            ChoiceQuestion(
                id=uid(),
                question=q.get("question", ""),
                options=options,
                explanation=q.get("explanation", ""),
            )
        )

    return Act(
        act_number=act_number,
        title=data.get("title", f"第{act_number}幕"),
        narration=data.get("narration", ""),
        clues=clues,
        choices=choices,
        generated=True,
    )
