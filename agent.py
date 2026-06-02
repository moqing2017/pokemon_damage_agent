import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY","")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("BASE_URL") or "https://api.deepseek.com"
if not DEEPSEEK_API_KEY:
    raise RuntimeError("缺少 DEEPSEEK_API_KEY，请在 .env 文件里配置。")

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=BASE_URL,
)

SHOW_LLM_RETRY_DETAILS = False

from pathlib import Path
from typing import Any
DATA_DIR = Path("data")

def load_json_file(filename: str) -> dict[str, Any]:
    path = DATA_DIR / filename

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def progress_step(message: str):
    print(f"\n{message} ...", end="", flush=True)
    start = time.time()
    try:
        yield
    except Exception:
        print(" 失败")
        raise
    else:
        elapsed = time.time() - start
        print(f" 完成（{elapsed:.1f}s）")


POKEMON_NAME_MAP = load_json_file("name.json")
MOVE_NAME_MAP = load_json_file("move.json")
ITEM_NAME_MAP = load_json_file("item.json")
ABILITY_NAME_MAP = load_json_file("ability.json")
ITEM_EFFECT_MAP = load_json_file("item_effect.json")
ABILITY_EFFECT_MAP = load_json_file("ability_effect.json")
SPECIES_CONTEXT_MAP = load_json_file("species_context.json")
ALIASES_MAP = load_json_file("aliases.json")


def build_reverse_name_map(*maps: dict[str, Any]) -> dict[str, str]:
    reverse = {}
    for mapping in maps:
        for zh, values in mapping.items():
            candidates = values if isinstance(values, list) else [values]
            for en in candidates:
                if not en:
                    continue
                # Prefer official-looking shorter names over verbose form composites.
                if en not in reverse or len(zh) < len(reverse[en]):
                    reverse[en] = zh
    return reverse


POKEMON_EN_TO_ZH = build_reverse_name_map(POKEMON_NAME_MAP, ALIASES_MAP.get("pokemon", {}))
MOVE_EN_TO_ZH = build_reverse_name_map(MOVE_NAME_MAP, ALIASES_MAP.get("move", {}))
ITEM_EN_TO_ZH = build_reverse_name_map(ITEM_NAME_MAP, ALIASES_MAP.get("item", {}))
ABILITY_EN_TO_ZH = build_reverse_name_map(ABILITY_NAME_MAP, ALIASES_MAP.get("ability", {}))

NATURE_EN_TO_ZH = {
    "Adamant": "固执",
    "Bold": "大胆",
    "Calm": "温和",
    "Careful": "慎重",
    "Impish": "淘气",
    "Jolly": "爽朗",
    "Modest": "内敛",
    "Timid": "胆小",
}

ABILITY_EN_TO_ZH.update({
    "Dauntless Shield": "不屈之盾",
    "Defiant": "不服输",
    "Intimidate": "威吓",
    "Protosynthesis": "古代活性",
    "Quark Drive": "夸克充能",
})

STAT_EN_TO_ZH = {
    "hp": "HP",
    "atk": "攻击",
    "def": "防御",
    "spa": "特攻",
    "spd": "特防",
    "spe": "速度",
}

TYPE_ALIASES = {
    "一般": "Normal",
    "普": "Normal",
    "格斗": "Fighting",
    "斗": "Fighting",
    "飞行": "Flying",
    "飞": "Flying",
    "毒": "Poison",
    "地面": "Ground",
    "地": "Ground",
    "岩石": "Rock",
    "岩": "Rock",
    "虫": "Bug",
    "幽灵": "Ghost",
    "鬼": "Ghost",
    "钢": "Steel",
    "火": "Fire",
    "水": "Water",
    "草": "Grass",
    "电": "Electric",
    "超能": "Psychic",
    "超": "Psychic",
    "冰": "Ice",
    "龙": "Dragon",
    "恶": "Dark",
    "妖精": "Fairy",
    "妖": "Fairy",
}

TYPE_EN_TO_ZH = {
    "Normal": "一般",
    "Fighting": "格斗",
    "Flying": "飞行",
    "Poison": "毒",
    "Ground": "地面",
    "Rock": "岩石",
    "Bug": "虫",
    "Ghost": "幽灵",
    "Steel": "钢",
    "Fire": "火",
    "Water": "水",
    "Grass": "草",
    "Electric": "电",
    "Psychic": "超能",
    "Ice": "冰",
    "Dragon": "龙",
    "Dark": "恶",
    "Fairy": "妖精",
}

def apply_aliases(text: str) -> str:
    """把常见中文名提前替换成英文，降低 LLM 解析压力。"""
    for zh, en in POKEMON_NAME_MAP.items():
        text = text.replace(zh, en)
    for zh, en in MOVE_NAME_MAP.items():
        text = text.replace(zh, en)
    for zh, en in ITEM_NAME_MAP.items():
        text = text.replace(zh, en)
    for zh, en in ABILITY_NAME_MAP.items():
        text = text.replace(zh, en)
    return text


EXTRACTION_PROMPT = """
你是一个宝可梦对战伤害计算 Agent 的战况解析器。

你的输入包含：
1. user_text：用户原始输入
2. alias_hits：本地 JSON 字典命中的宝可梦、招式、道具、别名候选
3. current_state：已有战况状态
4. mode：quick 或 strict

你必须根据 alias_hits 辅助解析用户输入，但 alias_hits 只是候选，不是最终答案；最终槽位由你结合上下文、语义和 current_state 决定。

规则：
1. 如果 alias_hits 中某项只有一个 candidates，可以优先使用这个候选，但仍要判断它在句子中的角色是否正确。
2. 如果 alias_hits 中某项有多个 candidates，不能擅自选择，必须 status = "need_clarification"，并在 questions 中追问。
3. category = "pokemon" 的候选只能用于 attacker.name 或 defender.name。
4. category = "move" 的候选只能用于 move.name。
5. category = "item" 的候选只能用于 attacker.item 或 defender.item。
6. category = "ability" 的候选只能用于 attacker.ability 或 defender.ability；如果原文是“被威吓一次”这类被动效果，不要写 ability，按规则 16 写 boosts。
7. category = "alias" 且 data.type = "compound" 时，需要把 data.meaning 里的信息合并进 battle。
8. 不要编造用户没有提供的信息。
9. 必要字段是 attacker.name、defender.name、move.name。
10. 缺少必要字段时，必须追问。
11. gen 默认 9，level 默认 50。
12. EV 没写默认 0。
12a. 太晶默认不使用，teraType 必须保持空字符串。只有用户明确说“太晶/钛晶/tera + 属性”时才写入 teraType。
13. quick 模式下，如果必要字段齐全，可以直接 ready。
14. strict 模式下，如果缺少 EV、nature、item、ability、boosts、weather、terrain 等影响伤害的信息，先列入 questions；如果用户之后表示不知道，交给常见配置补全阶段处理。
15. “确一/能不能确一/一击击杀/秒杀”解析为 intent.type = "one_turn_ko"。
16. “被抛了一次/被抛下狠话一次/吃了一次抛下狠话”表示该宝可梦被 Parting Shot 降低 1 段攻击和 1 段特攻；如果语义是攻击方被抛，则写入 attacker.boosts.atk = -1 且 attacker.boosts.spa = -1。
17. “被威吓一次/吃了一次威吓”通常表示该宝可梦攻击降低 1 段；如果语义是攻击方被威吓，则写入 attacker.boosts.atk = -1。只有“特性威吓/威吓特性/某宝可梦是威吓”才写入 ability = "Intimidate"。
18. 解析 boosts 前必须结合 effect_context 里的道具/特性效果文本判断。例如某道具/特性会阻止或重置能力下降时，不要机械地保留负向 boosts；具体结论由你根据 effect_context 决定，并在 assumptions 说明。
19. 如果 effect_context 缺少关键道具/特性效果，而这个效果会影响伤害计算，应该放入 questions 或 unresolved，不要编造。
20. 对 species_context 中列出的有性别/形态差异宝可梦，必须考虑 gender/form 对种族值、特性和技能表的影响。用户明确说性别时，写入 gender 并选择对应 name（例如 Basculegion-F）；用户允许默认时，选择主流配置并在 assumptions 说明；如果默认会显著影响结果且无法判断主流，必须追问。
21. “当前 HP/血量/半血/满血”写入对应宝可梦 curHPPercent；未提及时留空，由主流程追问或默认满血。
22. 如果用户提到 mega/太晶/强化/削弱/墙/天气/场地但无法确定具体效果，把原文放进 unresolved，不要硬编。
23. 如果没有提到具体招式，move.name 留空，并设置 need_move = true。

输出必须是合法 JSON，格式如下：

{
  "status": "ready",
  "need_move": false,
  "intent": {
    "type": "",
    "description": ""
  },
  "battle": {
    "gen": 9,
    "attacker": {
      "name": "",
      "level": 50,
      "nature": "",
      "ability": "",
      "gender": "",
      "item": "",
      "teraType": "",
      "curHPPercent": null,
      "evs": {
        "hp": 0,
        "atk": 0,
        "def": 0,
        "spa": 0,
        "spd": 0,
        "spe": 0
      },
      "ivs": {},
      "boosts": {}
    },
    "defender": {
      "name": "",
      "level": 50,
      "nature": "",
      "ability": "",
      "gender": "",
      "item": "",
      "teraType": "",
      "curHPPercent": null,
      "evs": {
        "hp": 0,
        "atk": 0,
        "def": 0,
        "spa": 0,
        "spd": 0,
        "spe": 0
      },
      "ivs": {},
      "boosts": {}
    },
    "move": {
      "name": "",
      "isCrit": false
    },
    "field": {
      "weather": "",
      "terrain": "",
      "attackerSide": {},
      "defenderSide": {}
    }
  },
  "questions": [],
  "assumptions": [],
  "resolved_aliases": [],
  "unresolved": []
}
"""

COMMON_SET_PROMPT = """
你是宝可梦对战伤害计算助手。把 battle 中缺失的信息补成可计算的常见配置。

要求：
1. 只输出合法 JSON。
2. 不要改变已明确给出的宝可梦、招式、太晶、boosts。
3. 不知道天气默认空字符串；不知道场地默认空字符串；不知道世代默认 9；不知道当前 HP 默认 100。
4. 缺努力值、性格、道具、能力时，由你根据常见对战配置选择 1 个合理配置；不要留给程序兜底。
5. 输出尽量短，assumptions 和 warnings 每项不超过 20 字。
6. 如果你选择了形态、道具、性格、特性或努力值，必须在 assumptions 里简短说明。
7. 如果 battle 或用户补充中出现道具/特性，必须阅读 effect_context 中对应效果；如果缺失关键效果，写入 warnings 或 questions，不要编造机制。
8. 如果 species_context 显示宝可梦有性别/形态差异，必须结合招式和主流配置选择 form/gender；如果采用主流默认，写入 assumptions。比如物攻向幽尾玄鱼通常选择雄性/默认形态，特攻向才考虑雌性形态。
9. 默认不太晶。除非用户明确补充太晶属性，否则不要设置 teraType，也不要在常见配置里主动太晶。

输出格式：
{
  "battle": {},
  "move_candidates": [],
  "assumptions": [],
  "warnings": []
}
"""

NORMALIZATION_PROMPT = """
你是宝可梦对战中文术语标准化器。

任务：把用户输入中的宝可梦、招式、道具、常见对战术语纠正为标准简体中文名称或标准说法。

规则：
1. 优先使用 fuzzy_candidates 中给出的本地候选。
2. 可以修正常见错别字、同音字、近音写法、口误，例如“朴刀将军”应纠正为“仆刀将军”。
3. 不要改变伤害计算语义，例如“被威吓一次”“一下”“确一”“扑击”都要保留。
4. 如果无法确定，不要强行改，写入 unresolved。
5. 只输出合法 JSON。

输出格式：
{
  "normalized_text": "",
  "corrections": [
    {
      "original": "",
      "normalized": "",
      "category": "",
      "reason": ""
    }
  ],
  "unresolved": []
}
"""

def find_ambiguous_hits(alias_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ambiguous = []

    for hit in alias_hits:
        candidates = hit.get("candidates")

        if isinstance(candidates, list) and len(candidates) > 1:
            ambiguous.append(hit)

    return ambiguous

def build_ambiguity_questions(alias_hits: list[dict[str, Any]]) -> list[str]:
    questions = []

    for hit in find_ambiguous_hits(alias_hits):
        text = hit["text"]
        candidates = hit["candidates"]
        category = hit["category"]

        questions.append(
            f"你说的「{text}」属于 {category}，有多个可能：{', '.join(candidates)}。请选择一个。"
        )

    return questions


def parse_json_content(content: str) -> Dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError("响应中没有 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:index + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return json.loads(repair_json_like_text(candidate))

    return json.loads(repair_json_like_text(text))


def repair_json_like_text(text: str) -> str:
    repaired = text.strip()
    repaired = re.sub(r"//.*", "", repaired)
    repaired = re.sub(r"/\*.*?\*/", "", repaired, flags=re.S)
    repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)", r'\1"\2"\3', repaired)
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    return repaired


def all_standard_terms() -> list[tuple[str, str, list[str]]]:
    terms = []
    for category, mapping in (
        ("pokemon", POKEMON_NAME_MAP),
        ("move", MOVE_NAME_MAP),
        ("item", ITEM_NAME_MAP),
        ("ability", ABILITY_NAME_MAP),
        ("pokemon_alias", ALIASES_MAP.get("pokemon", {})),
        ("move_alias", ALIASES_MAP.get("move", {})),
        ("item_alias", ALIASES_MAP.get("item", {})),
        ("ability_alias", ALIASES_MAP.get("ability", {})),
    ):
        for zh, candidates in mapping.items():
            terms.append((category, zh, candidates))
    return terms


def chinese_windows(text: str, min_len: int = 2, max_len: int = 8) -> list[str]:
    chars = re.findall(r"[\u4e00-\u9fff]+", text)
    windows = set()
    for chunk in chars:
        upper = min(max_len, len(chunk))
        for size in range(min_len, upper + 1):
            for start in range(0, len(chunk) - size + 1):
                windows.add(chunk[start:start + size])
    return list(windows)


PINYIN_CACHE: dict[str, str] = {}


def pinyin_key(text: str) -> str:
    if not lazy_pinyin:
        return ""
    if text not in PINYIN_CACHE:
        PINYIN_CACHE[text] = "".join(lazy_pinyin(text))
    return PINYIN_CACHE[text]


def fuzzy_term_candidates(user_text: str, limit: int = 30) -> list[dict[str, Any]]:
    matches = []
    windows = chinese_windows(user_text)

    for category, standard_text, candidates in all_standard_terms():
        if standard_text in user_text:
            matches.append({
                "original_text": standard_text,
                "standard_text": standard_text,
                "category": category,
                "candidates": candidates,
                "score": 1.0,
            })
            continue

        best_original = ""
        best_score = 0.0
        best_rank = (0.0, 0, 0)
        best_same_length_original = ""
        best_same_length_score = 0.0
        best_same_length_rank = (0.0, 0, 0)
        for window in windows:
            if abs(len(window) - len(standard_text)) > 1:
                continue
            score = SequenceMatcher(None, window, standard_text).ratio()
            if pinyin_key(window) and pinyin_key(window) == pinyin_key(standard_text):
                score = max(score, 0.94)
            rank = (
                score,
                1 if window[-1:] == standard_text[-1:] else 0,
                1 if window[:1] == standard_text[:1] else 0,
            )
            if len(window) == len(standard_text) and rank > best_same_length_rank:
                best_same_length_score = score
                best_same_length_original = window
                best_same_length_rank = rank
            if rank > best_rank:
                best_score = score
                best_original = window
                best_rank = rank

        threshold = 0.72 if len(standard_text) >= 4 else 0.84
        if best_same_length_score >= threshold:
            best_score = best_same_length_score
            best_original = best_same_length_original
        if best_score >= threshold:
            matches.append({
                "original_text": best_original,
                "standard_text": standard_text,
                "category": category,
                "candidates": candidates,
                "score": round(best_score, 3),
            })

    matches.sort(key=lambda item: (item["score"], len(item["standard_text"])), reverse=True)

    deduped = []
    seen = set()
    for match in matches:
        key = (match["original_text"], match["standard_text"], match["category"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
        if len(deduped) >= limit:
            break

    return deduped


def normalize_user_text(user_text: str) -> dict[str, Any]:
    candidates = fuzzy_term_candidates(user_text)
    payload = {
        "user_text": user_text,
        "fuzzy_candidates": candidates,
        "known_semantics": {
            "被威吓一次": "对应宝可梦攻击降低 1 段",
            "被抛下狠话一次": "对应宝可梦攻击和特攻降低 1 段",
            "确一/一下死": "一回合击杀"
        }
    }

    try:
        normalized = deepseek_json(NORMALIZATION_PROMPT, payload, max_tokens=1000)
    except Exception:
        raise RuntimeError("LLM 术语标准化失败，无法可靠处理错别字和别名。")

    normalized["normalized_text"] = normalized.get("normalized_text") or user_text
    normalized["corrections"] = dedupe_corrections(normalized.get("corrections") or [])
    normalized.setdefault("unresolved", [])
    return normalized


def dedupe_corrections(corrections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for correction in corrections:
        key = (correction.get("original"), correction.get("normalized"))
        if key in seen:
            continue
        seen.add(key)
        output.append(correction)
    return output


def extract_battle_state(
    user_text: str,
    current_state: dict | None = None,
    mode: str = "quick",
    normalization: dict | None = None,
) -> dict:
    normalization = normalization or normalize_user_text(user_text)
    normalized_text = normalization.get("normalized_text") or user_text
    alias_hits = find_alias_hits(normalized_text)
    effect_context = build_effect_context(
        alias_hits=alias_hits,
        battle=current_state.get("battle") if current_state else None,
    )

    payload = {
        "mode": mode,
        "user_text": normalized_text,
        "original_user_text": user_text,
        "normalization": normalization,
        "alias_hits": alias_hits,
        "effect_context": effect_context,
        "species_context": build_species_context(
            alias_hits=alias_hits,
            battle=current_state.get("battle") if current_state else None,
        ),
        "current_state": current_state or {}
    }

    parsed = deepseek_json(EXTRACTION_PROMPT, payload, max_tokens=2500)
    clear_unmentioned_tera(extract_battle(parsed), user_text, normalized_text)
    parsed["normalization"] = normalization
    return parsed


def first_candidate(hit: Dict[str, Any]) -> str | None:
    candidates = hit.get("candidates")
    if isinstance(candidates, list) and candidates:
        return candidates[0]
    if isinstance(candidates, str):
        return candidates
    return None


def collect_effect_names_from_hits(alias_hits: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    items = set()
    abilities = set()
    for hit in alias_hits:
        candidate = first_candidate(hit)
        if not candidate:
            continue
        if hit.get("category") == "item":
            items.add(candidate)
        elif hit.get("category") == "ability":
            abilities.add(candidate)
    return items, abilities


def collect_effect_names_from_battle(battle: Dict[str, Any] | None) -> tuple[set[str], set[str]]:
    items = set()
    abilities = set()
    if not battle:
        return items, abilities

    for side in ("attacker", "defender"):
        pokemon = battle.get(side, {})
        if pokemon.get("item"):
            items.add(pokemon["item"])
        if pokemon.get("ability"):
            abilities.add(pokemon["ability"])
    return items, abilities


def build_effect_context(
    alias_hits: list[dict[str, Any]] | None = None,
    battle: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    item_names = set()
    ability_names = set()

    if alias_hits:
        hit_items, hit_abilities = collect_effect_names_from_hits(alias_hits)
        item_names.update(hit_items)
        ability_names.update(hit_abilities)

    battle_items, battle_abilities = collect_effect_names_from_battle(battle)
    item_names.update(battle_items)
    ability_names.update(battle_abilities)

    return {
        "items": {
            name: ITEM_EFFECT_MAP.get(name, "")
            for name in sorted(item_names)
        },
        "abilities": {
            name: ABILITY_EFFECT_MAP.get(name, "")
            for name in sorted(ability_names)
        },
        "missing_effects": {
            "items": sorted(name for name in item_names if not ITEM_EFFECT_MAP.get(name)),
            "abilities": sorted(name for name in ability_names if not ABILITY_EFFECT_MAP.get(name)),
        }
    }


def species_context_key(name: str | None) -> str | None:
    if not name:
        return None
    if name in SPECIES_CONTEXT_MAP:
        return name
    base = re.sub(r"-(F|M)(-.+)?$", "", name)
    if base in SPECIES_CONTEXT_MAP:
        return base
    return None


def collect_species_names_from_hits(alias_hits: list[dict[str, Any]] | None) -> set[str]:
    names = set()
    for hit in alias_hits or []:
        if hit.get("category") == "pokemon":
            candidate = first_candidate(hit)
            if candidate:
                names.add(candidate)
    return names


def collect_species_names_from_battle(battle: Dict[str, Any] | None) -> set[str]:
    names = set()
    if not battle:
        return names
    for side in ("attacker", "defender"):
        name = battle.get(side, {}).get("name")
        if name:
            names.add(name)
    return names


def build_species_context(
    alias_hits: list[dict[str, Any]] | None = None,
    battle: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    names = collect_species_names_from_hits(alias_hits)
    names.update(collect_species_names_from_battle(battle))

    context = {}
    for name in sorted(names):
        key = species_context_key(name)
        if key:
            context[key] = SPECIES_CONTEXT_MAP[key]
    return context


def run_damage_calc(calc_request: Dict[str, Any]) -> Dict[str, Any]:
    if "battle" in calc_request:
        calc_request = calc_request["battle"]

    proc = subprocess.run(
        ["node", "tools/calc.mjs"],
        input=json.dumps(calc_request, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )

    if proc.returncode != 0:
        raise RuntimeError(
            "伤害计算工具执行失败：\n"
            f"STDOUT:\n{proc.stdout}\n\n"
            f"STDERR:\n{proc.stderr}"
        )

    return json.loads(proc.stdout)


def extract_battle(calc_request: Dict[str, Any]) -> Dict[str, Any]:
    return calc_request.get("battle", calc_request)


def deepseek_json(system_prompt: str, payload: Dict[str, Any], max_tokens: int = 2000) -> Dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt + "\n\n重要：最终回答必须是一个 JSON object，不要输出解释文字。",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
                temperature=0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if content:
                return parse_json_content(content)

            finish_reason = response.choices[0].finish_reason
            last_error = RuntimeError(f"DeepSeek 返回空内容，finish_reason={finish_reason}")
        except Exception as err:
            last_error = err

        if attempt < 3:
            if SHOW_LLM_RETRY_DETAILS:
                print(f"\nDeepSeek 调用失败/空响应，正在重试 {attempt}/3：{last_error}")
            else:
                print(f"\nDeepSeek 响应不稳定，正在重试 {attempt}/3 ...", end="", flush=True)
            time.sleep(1.5 * attempt)

    raise RuntimeError(f"DeepSeek 连续 3 次没有返回可用 JSON：{last_error}")


def is_unknown_answer(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {
        "",
        "不知道",
        "不清楚",
        "不确定",
        "默认",
        "随便",
        "按默认",
        "unknown",
        "default",
        "idk",
    }


def is_intimidated_effect(text: str) -> bool:
    return bool(re.search(r"被\s*威吓|吃了?一?次?威吓|威吓一次", text))


def has_any_evs(pokemon: Dict[str, Any]) -> bool:
    evs = pokemon.get("evs") or {}
    return any((value or 0) != 0 for value in evs.values())


def build_missing_questions(parsed: Dict[str, Any]) -> list[str]:
    battle = extract_battle(parsed)
    questions = []

    if parsed.get("status") == "need_clarification":
        questions.extend(parsed.get("questions") or [])

    if not battle.get("attacker", {}).get("name"):
        questions.append("攻击方是哪只宝可梦？")
    if not battle.get("defender", {}).get("name"):
        questions.append("防守方是哪只宝可梦？")

    attacker = battle.get("attacker", {})
    defender = battle.get("defender", {})
    field = battle.get("field", {})

    if not parsed.get("need_move") and not battle.get("move", {}).get("name"):
        parsed["need_move"] = True

    if not battle.get("gen"):
        questions.append("按第几世代规则计算？不知道的话我默认第九世代。")
    if not field.get("weather"):
        questions.append("天气是什么？不知道的话默认无天气。")
    if not field.get("terrain"):
        questions.append("场地是什么？不知道的话默认无场地。")
    if not has_any_evs(attacker):
        questions.append("攻击方努力值/性格/道具/能力是什么？不知道的话我用常见配置估算。")
    if not has_any_evs(defender):
        questions.append("防守方努力值/性格/道具/能力是什么？不知道的话我用常见配置估算。")
    if attacker.get("curHPPercent") is None and attacker.get("curHP") is None:
        questions.append("攻击方当前 HP 是多少？不知道的话默认满血。")
    if defender.get("curHPPercent") is None and defender.get("curHP") is None:
        questions.append("防守方当前 HP 是多少？不知道的话默认满血。")
    if parsed.get("need_move") or not battle.get("move", {}).get("name"):
        questions.append("攻击方用什么招式？不知道的话我会列常见攻击招式逐个计算。")

    return dedupe_keep_order(questions)


def build_required_questions(parsed: Dict[str, Any]) -> list[str]:
    battle = extract_battle(parsed)
    questions = []

    if not battle.get("attacker", {}).get("name"):
        questions.append("攻击方是哪只宝可梦？")
    if not battle.get("defender", {}).get("name"):
        questions.append("防守方是哪只宝可梦？")

    return questions


def build_defaultable_items(parsed: Dict[str, Any]) -> list[str]:
    battle = extract_battle(parsed)
    attacker = battle.get("attacker", {})
    defender = battle.get("defender", {})
    field = battle.get("field", {})
    items = []

    if not battle.get("gen"):
        items.append("世代默认第九世代")
    if not field.get("weather"):
        items.append("天气默认无天气")
    if not field.get("terrain"):
        items.append("场地默认无场地")
    if not attacker.get("teraType") and not defender.get("teraType"):
        items.append("默认不太晶")
    if not has_any_evs(attacker) or not attacker.get("nature") or not attacker.get("ability"):
        items.append("攻击方配置用常见配置")
    if not has_any_evs(defender) or not defender.get("nature") or not defender.get("ability"):
        items.append("防守方配置用常见配置")
    if attacker.get("curHPPercent") is None and attacker.get("curHP") is None:
        items.append("攻击方当前 HP 默认满血")
    if defender.get("curHPPercent") is None and defender.get("curHP") is None:
        items.append("防守方当前 HP 默认满血")
    if species_context_key(attacker.get("name")) and not attacker.get("gender"):
        items.append("攻击方性别/形态按主流配置默认")
    if species_context_key(defender.get("name")) and not defender.get("gender"):
        items.append("防守方性别/形态按主流配置默认")
    if parsed.get("need_move") or not battle.get("move", {}).get("name"):
        items.append("未指定招式时列常见攻击招式")

    return dedupe_keep_order(items)


def defaultable_prompt(items: list[str]) -> str:
    if not items:
        return ""
    return "；".join(items)


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item not in seen:
            seen.add(item)
            output.append(item)
    return output


def fill_builtin_defaults(battle: Dict[str, Any]) -> Dict[str, Any]:
    battle.setdefault("gen", 9)
    battle.setdefault("field", {})
    battle["field"].setdefault("weather", "")
    battle["field"].setdefault("terrain", "")
    battle["field"].setdefault("attackerSide", {})
    battle["field"].setdefault("defenderSide", {})

    for side in ("attacker", "defender"):
        pokemon = battle.setdefault(side, {})
        pokemon.setdefault("level", 50)
        pokemon.setdefault("evs", {})
        pokemon.setdefault("ivs", {})
        pokemon.setdefault("boosts", {})
        if pokemon.get("curHPPercent") is None and pokemon.get("curHP") is None:
            pokemon["curHPPercent"] = 100

    battle.setdefault("move", {})
    return battle


def normalize_followup_text(text: str) -> str:
    return (
        text.replace("钛晶", "太晶")
        .replace("钛", "太")
        .replace("藏马然特", "藏玛然特")
    )


def user_mentions_tera(*texts: str) -> bool:
    combined = " ".join(texts)
    return bool(re.search(r"太晶|钛晶|tera|Tera", combined))


def clear_unmentioned_tera(battle: Dict[str, Any], *texts: str) -> list[str]:
    if user_mentions_tera(*texts):
        return []

    notes = []
    for side, label in (("attacker", "攻击方"), ("defender", "防守方")):
        pokemon = battle.get(side, {})
        if pokemon.get("teraType"):
            pokemon["teraType"] = ""
            notes.append(f"{label}未明确太晶，已按默认不太晶")
    return notes


def apply_followup_overrides(battle: Dict[str, Any], followup_text: str) -> list[str]:
    assumptions = []
    text = normalize_followup_text(followup_text)

    tera_match = re.search(r"(?:太晶|太)(一般|普|格斗|斗|飞行|飞|毒|地面|地|岩石|岩|虫|幽灵|鬼|钢|火|水|草|电|超能|超|冰|龙|恶|妖精|妖)", text)
    if tera_match:
        tera_type = TYPE_ALIASES.get(tera_match.group(1))
        if tera_type:
            battle.setdefault("attacker", {})["teraType"] = tera_type
            assumptions.append(f"攻击方太晶{tera_match.group(1)}")

    if is_unknown_answer(text.replace("，", "").replace(",", "").strip()) or "不知道" in text:
        battle.setdefault("field", {}).setdefault("weather", "")
        battle.setdefault("field", {}).setdefault("terrain", "")
        for side in ("attacker", "defender"):
            pokemon = battle.setdefault(side, {})
            pokemon.setdefault("curHPPercent", 100)
            pokemon.setdefault("level", 50)
        assumptions.append("未知项按默认")

    return assumptions


def apply_followup_entities(battle: Dict[str, Any], followup_text: str) -> list[str]:
    assumptions = []
    if not followup_text.strip():
        return assumptions

    normalization = normalize_user_text(normalize_followup_text(followup_text))
    normalized_text = normalization.get("normalized_text") or followup_text
    hits = find_alias_hits(normalized_text)

    pokemon_hits = [
        hit for hit in hits
        if hit.get("category") == "pokemon" and first_candidate(hit)
    ]
    pokemon_hits.sort(key=lambda hit: normalized_text.find(hit["text"]) if hit["text"] in normalized_text else 9999)

    for hit in pokemon_hits:
        candidate = first_candidate(hit)
        if not candidate:
            continue
        if not battle.get("attacker", {}).get("name"):
            battle.setdefault("attacker", {})["name"] = candidate
            assumptions.append(f"补充攻击方为{hit['text']}")
        elif not battle.get("defender", {}).get("name") and candidate != battle.get("attacker", {}).get("name"):
            battle.setdefault("defender", {})["name"] = candidate
            assumptions.append(f"补充防守方为{hit['text']}")

    move_hits = [
        hit for hit in hits
        if hit.get("category") == "move" and first_candidate(hit)
    ]
    move_hits.sort(key=lambda hit: normalized_text.find(hit["text"]) if hit["text"] in normalized_text else 9999)
    if move_hits and not battle.get("move", {}).get("name"):
        battle.setdefault("move", {})["name"] = first_candidate(move_hits[0])
        assumptions.append(f"补充招式为{move_hits[0]['text']}")

    ability_hits = [
        hit for hit in hits
        if hit.get("category") == "ability" and first_candidate(hit)
    ]
    ability_hits.sort(key=lambda hit: normalized_text.find(hit["text"]) if hit["text"] in normalized_text else 9999)
    if ability_hits and not is_intimidated_effect(normalized_text):
        slot = "defender" if any(word in normalized_text for word in ["防守", "对面", "目标"]) else "attacker"
        battle.setdefault(slot, {})["ability"] = first_candidate(ability_hits[0])
        assumptions.append(f"补充{'攻击方' if slot == 'attacker' else '防守方'}特性为{ability_hits[0]['text']}")

    return assumptions


def enrich_with_common_defaults(
    user_text: str,
    parsed: Dict[str, Any],
    followup_text: str,
) -> Dict[str, Any]:
    battle = fill_builtin_defaults(extract_battle(parsed))
    local_assumptions = []
    local_assumptions.extend(apply_followup_entities(battle, followup_text))
    local_assumptions.extend(apply_followup_overrides(battle, followup_text))

    payload = {
        "original_user_text": user_text,
        "followup_text": followup_text,
        "battle": battle,
        "defaultable_items": build_defaultable_items({"battle": battle, "need_move": parsed.get("need_move", False)}),
        "effect_context": build_effect_context(battle=battle),
        "species_context": build_species_context(battle=battle),
        "meaning_rules": {
            "parting_shot_once": "被抛下狠话一次 => 对应宝可梦 atk -1, spa -1",
            "intimidate_once": "被威吓一次 => 对应宝可梦 atk -1",
            "item_and_ability_effects": "判断道具/特性影响时必须优先使用 effect_context，不要靠程序兜底",
            "one_turn_ko": "确一 => 一回合击杀",
            "unknown_defaults": {
                "gen": 9,
                "weather": "none",
                "terrain": "none",
                "current_hp": "full"
            }
        }
    }

    try:
        enriched = deepseek_json(COMMON_SET_PROMPT, payload, max_tokens=5000)
    except Exception as err:
        raise RuntimeError(f"LLM 常见配置补全失败，无法安全选择默认配置：{err}")

    enriched.setdefault("battle", battle)
    enriched["battle"] = fill_builtin_defaults(enriched["battle"])
    local_assumptions.extend(clear_unmentioned_tera(enriched["battle"], user_text, followup_text))
    enriched["assumptions"] = dedupe_keep_order(local_assumptions + (enriched.get("assumptions") or []))
    return enriched


def percent_to_curhp(calc_result: Dict[str, Any], percent: int | float | None) -> int | None:
    if percent is None:
        return None
    max_hp = calc_result.get("defenderMaxHP")
    if not max_hp:
        return None
    return max(1, round(max_hp * float(percent) / 100))


def flatten_damage(damage: Any) -> list[int]:
    if isinstance(damage, list):
        values = []
        for item in damage:
            values.extend(flatten_damage(item))
        return values
    if isinstance(damage, (int, float)):
        return [int(damage)]
    return []


def ko_label(calc_result: Dict[str, Any]) -> str:
    damage_values = flatten_damage(calc_result.get("damage"))
    defender_hp = calc_result.get("defenderHP") or calc_result.get("defenderMaxHP")
    if not damage_values or not defender_hp:
        return "无法判断击杀回合"

    min_damage = min(damage_values) if isinstance(calc_result.get("damage"), list) else damage_values[0]
    max_damage = max(damage_values)

    # Multi-hit moves expose a summed range via result.range().
    if calc_result.get("range"):
        min_damage, max_damage = calc_result["range"]

    if min_damage >= defender_hp:
        return "确定一回合击杀"
    if max_damage >= defender_hp:
        return "有概率一回合击杀"
    if min_damage * 2 >= defender_hp:
        return "确定二回合击杀"
    if max_damage * 2 >= defender_hp:
        return "有概率二回合击杀"
    return "不能一回合击杀"


def extract_percent_range(calc_result: Dict[str, Any]) -> str:
    move_desc = calc_result.get("moveDesc")
    if move_desc:
        return move_desc

    full_desc = calc_result.get("fullDesc") or calc_result.get("desc") or ""
    match = re.search(r"(\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?%)", full_desc)
    return match.group(1) if match else ""


def format_move_summary(move_name: str, calc_result: Dict[str, Any]) -> str:
    move_name = translate_move(move_name)
    percent = extract_percent_range(calc_result)
    detail = f"，{percent}" if percent else ""
    return f"- {move_name}（{ko_label(calc_result)}{detail}）"


def calc_for_move_candidates(battle: Dict[str, Any], move_candidates: list[str]) -> list[tuple[str, Dict[str, Any]]]:
    results = []
    seen = set()

    for move_name in move_candidates:
        if not move_name or move_name in seen:
            continue
        seen.add(move_name)

        request = json.loads(json.dumps(battle, ensure_ascii=False))
        request.setdefault("move", {})
        request["move"]["name"] = move_name

        try:
            results.append((move_name, run_damage_calc(request)))
        except Exception:
            continue

    return results


def clone_json(data: Any) -> Any:
    return json.loads(json.dumps(data, ensure_ascii=False))


def merge_dict(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_dict(base[key], value)
        elif value not in (None, "", {}, []):
            base[key] = value
    return base


def merge_battle_state(current_battle: Dict[str, Any] | None, new_battle: Dict[str, Any]) -> Dict[str, Any]:
    if not current_battle:
        return clone_json(new_battle)

    merged = clone_json(current_battle)
    merge_dict(merged, new_battle)
    return merged


def should_inherit_context(parsed: Dict[str, Any], session_state: Dict[str, Any]) -> bool:
    if not session_state.get("battle"):
        return False

    battle = extract_battle(parsed)
    has_attacker = bool(battle.get("attacker", {}).get("name"))
    has_defender = bool(battle.get("defender", {}).get("name"))

    # A complete matchup starts a fresh calculation; partial follow-ups inherit.
    return not (has_attacker and has_defender)


def is_stateful_update(text: str, session_state: Dict[str, Any]) -> bool:
    if not session_state.get("battle"):
        return False
    keywords = [
        "不是", "改", "换", "修正", "应该是", "其实是", "是", "补充",
        "天气", "场地", "太晶", "钛晶", "道具", "性格", "努力", "血",
        "攻击方", "防守方", "对面", "目标", "我方",
    ]
    return any(keyword in text for keyword in keywords)


def infer_pokemon_slot(text: str, battle: Dict[str, Any]) -> str:
    if any(word in text for word in ["防守", "对面", "目标", "被打", "挨打"]):
        return "defender"
    if any(word in text for word in ["攻击", "我方", "打手", "使用者"]):
        return "attacker"
    if not battle.get("attacker", {}).get("name"):
        return "attacker"
    if not battle.get("defender", {}).get("name"):
        return "defender"
    return "attacker"


def apply_text_update_to_battle(battle: Dict[str, Any], user_text: str) -> tuple[Dict[str, Any], list[str]]:
    updated = clone_json(battle)
    notes = []
    normalized = normalize_user_text(user_text)
    text = normalized.get("normalized_text") or user_text
    hits = find_alias_hits(text)

    pokemon_hits = [
        hit for hit in hits
        if hit.get("category") == "pokemon" and first_candidate(hit)
    ]
    pokemon_hits.sort(key=lambda hit: text.find(hit["text"]) if hit["text"] in text else 9999)

    move_hits = [
        hit for hit in hits
        if hit.get("category") == "move" and first_candidate(hit)
    ]
    move_hits.sort(key=lambda hit: text.find(hit["text"]) if hit["text"] in text else 9999)

    item_hits = [
        hit for hit in hits
        if hit.get("category") == "item" and first_candidate(hit)
    ]
    item_hits.sort(key=lambda hit: text.find(hit["text"]) if hit["text"] in text else 9999)

    ability_hits = [
        hit for hit in hits
        if hit.get("category") == "ability" and first_candidate(hit)
    ]
    ability_hits.sort(key=lambda hit: text.find(hit["text"]) if hit["text"] in text else 9999)

    if pokemon_hits:
        slot = infer_pokemon_slot(text, updated)
        chosen_hit = pokemon_hits[-1] if "不是" in text and len(pokemon_hits) > 1 else pokemon_hits[0]
        candidate = first_candidate(chosen_hit)
        if candidate:
            updated.setdefault(slot, {})["name"] = candidate
            notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}改为{chosen_hit['text']}")

    if move_hits:
        updated.setdefault("move", {})["name"] = first_candidate(move_hits[0])
        notes.append(f"招式改为{move_hits[0]['text']}")

    if item_hits:
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["item"] = first_candidate(item_hits[0])
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}道具改为{item_hits[0]['text']}")

    if ability_hits and not is_intimidated_effect(text):
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["ability"] = first_candidate(ability_hits[0])
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}特性改为{ability_hits[0]['text']}")

    tera_match = re.search(r"(?:太晶|太)(一般|普|格斗|斗|飞行|飞|毒|地面|地|岩石|岩|虫|幽灵|鬼|钢|火|水|草|电|超能|超|冰|龙|恶|妖精|妖)", normalize_followup_text(text))
    if tera_match:
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["teraType"] = TYPE_ALIASES.get(tera_match.group(1), "")
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}太晶{tera_match.group(1)}")

    if any(word in text for word in ["雌", "母", "女"]):
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["gender"] = "F"
        key = species_context_key(updated.get(slot, {}).get("name"))
        if key:
            female_form = next((form["name"] for form in SPECIES_CONTEXT_MAP[key]["forms"] if form.get("gender") == "F"), None)
            if female_form:
                updated[slot]["name"] = female_form
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}改为雌性")
    elif any(word in text for word in ["雄", "公", "男"]):
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["gender"] = "M"
        key = species_context_key(updated.get(slot, {}).get("name"))
        if key:
            male_form = next((form["name"] for form in SPECIES_CONTEXT_MAP[key]["forms"] if form.get("gender") in {"M", "M/default"}), None)
            if male_form:
                updated[slot]["name"] = male_form
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}改为雄性")

    if "雨" in text:
        updated.setdefault("field", {})["weather"] = "Rain"
        notes.append("天气改为雨天")
    elif "晴" in text or "晴天" in text:
        updated.setdefault("field", {})["weather"] = "Sun"
        notes.append("天气改为晴天")
    elif "无天气" in text or "没天气" in text:
        updated.setdefault("field", {})["weather"] = ""
        notes.append("天气改为无天气")

    hp_match = re.search(r"(\d{1,3})\s*%?\s*(?:血|hp|HP)", text)
    if hp_match:
        slot = "defender" if any(word in text for word in ["防守", "对面", "目标"]) else "attacker"
        updated.setdefault(slot, {})["curHPPercent"] = max(1, min(100, int(hp_match.group(1))))
        notes.append(f"{'攻击方' if slot == 'attacker' else '防守方'}HP改为{hp_match.group(1)}%")

    if is_intimidated_effect(text):
        updated.setdefault("attacker", {}).setdefault("boosts", {})["atk"] = -1
        notes.append("攻击方攻击-1")

    return updated, dedupe_keep_order(notes)


def calculate_and_print(
    user_text: str,
    battle: Dict[str, Any],
    move_candidates: list[str] | None = None,
    explain: bool = True,
) -> dict[str, Any]:
    print("\n" + format_battle_config(battle))
    print("\n[4] 正在计算伤害...")
    move_candidates = move_candidates or []

    if battle.get("move", {}).get("name"):
        calc_result = run_damage_calc(battle)
        print(format_result(calc_result))
        print(format_move_summary(battle["move"]["name"], calc_result))
        if explain:
            print("\nLLM 解释：")
            print(explain_with_llm(user_text, battle, calc_result))
        return {
            "battle": battle,
            "results": [(battle["move"]["name"], calc_result)],
        }

    results = calc_for_move_candidates(battle, move_candidates)
    if not results:
        print("没有找到可计算的攻击招式候选，请指定攻击方使用的招式。")
        return {
            "battle": battle,
            "results": [],
        }

    print("常见招式伤害：")
    for move_name, calc_result in results:
        print(format_move_summary(move_name, calc_result))
    if explain:
        print("\nLLM 解释：")
        print(explain_results_with_llm(user_text, battle, results))
    return {
        "battle": battle,
        "results": results,
    }


def translate_pokemon(name: str | None) -> str:
    if not name:
        return ""
    return POKEMON_EN_TO_ZH.get(name, name)


def translate_move(name: str | None) -> str:
    if not name:
        return ""
    return MOVE_EN_TO_ZH.get(name, name)


def translate_item(name: str | None) -> str:
    if not name:
        return ""
    return ITEM_EN_TO_ZH.get(name, name)


def translate_nature(name: str | None) -> str:
    if not name:
        return ""
    return NATURE_EN_TO_ZH.get(name, name)


def translate_ability(name: str | None) -> str:
    if not name:
        return ""
    return ABILITY_EN_TO_ZH.get(name, name)


def format_evs(evs: Dict[str, Any] | None) -> str:
    if not evs:
        return "无努力值"

    parts = []
    for stat in ("hp", "atk", "def", "spa", "spd", "spe"):
        value = evs.get(stat, 0) or 0
        if value:
            parts.append(f"{value}{STAT_EN_TO_ZH[stat]}")
    return " / ".join(parts) if parts else "无努力值"


def format_boosts(boosts: Dict[str, Any] | None) -> str:
    if not boosts:
        return "无能力变化"

    parts = []
    for stat in ("atk", "def", "spa", "spd", "spe"):
        value = boosts.get(stat)
        if value:
            sign = "+" if value > 0 else ""
            parts.append(f"{STAT_EN_TO_ZH[stat]}{sign}{value}")
    return "，".join(parts) if parts else "无能力变化"


def format_pokemon_config(label: str, pokemon: Dict[str, Any]) -> str:
    parts = [
        f"{label}：{translate_pokemon(pokemon.get('name')) or '未指定'}",
        f"等级{pokemon.get('level', 50)}",
        format_evs(pokemon.get("evs")),
    ]
    if pokemon.get("nature"):
        parts.append(f"{translate_nature(pokemon.get('nature'))}性格")
    if pokemon.get("ability"):
        parts.append(f"特性{translate_ability(pokemon.get('ability'))}")
    if pokemon.get("gender"):
        gender_text = {"M": "雄性", "F": "雌性", "N": "无性别"}.get(pokemon.get("gender"), pokemon.get("gender"))
        parts.append(gender_text)
    if pokemon.get("item"):
        parts.append(f"道具{translate_item(pokemon.get('item'))}")
    if pokemon.get("teraType"):
        parts.append(f"太晶{TYPE_EN_TO_ZH.get(pokemon.get('teraType'), pokemon.get('teraType'))}")
    if pokemon.get("curHPPercent") is not None:
        parts.append(f"当前HP {pokemon.get('curHPPercent')}%")
    elif pokemon.get("curHP") is not None:
        parts.append(f"当前HP {pokemon.get('curHP')}")
    parts.append(f"能力变化：{format_boosts(pokemon.get('boosts'))}")
    return "- " + "，".join(parts)


def format_battle_config(battle: Dict[str, Any]) -> str:
    field = battle.get("field", {})
    move = battle.get("move", {})
    lines = ["计算使用配置："]
    lines.append(f"- 规则：第{battle.get('gen', 9)}世代")
    lines.append(format_pokemon_config("攻击方", battle.get("attacker", {})))
    lines.append(format_pokemon_config("防守方", battle.get("defender", {})))
    lines.append(f"- 招式：{translate_move(move.get('name')) or '未指定'}")
    lines.append(
        f"- 场地：天气 {field.get('weather') or '无'}，场地 {field.get('terrain') or '无'}"
    )
    return "\n".join(lines)


def format_result(calc_result: Dict[str, Any]) -> str:
    """先用 Python 做一个稳定输出，不依赖 LLM 二次生成。"""
    request = calc_result.get("request", {})
    attacker = request.get("attacker", {})
    defender = request.get("defender", {})
    move = request.get("move", {})
    damage = calc_result.get("damage")
    damage_range = calc_result.get("range")
    percent = extract_percent_range(calc_result)

    lines = []
    lines.append("计算结果：")
    lines.append(
        f"- 对局：{translate_pokemon(attacker.get('name'))} 使用 {translate_move(move.get('name'))} 攻击 {translate_pokemon(defender.get('name'))}"
    )
    lines.append(
        f"- 攻击方配置：{format_evs(attacker.get('evs'))}"
        f"{'，' + translate_nature(attacker.get('nature')) + '性格' if attacker.get('nature') else ''}"
        f"{'，道具' + translate_item(attacker.get('item')) if attacker.get('item') else ''}"
        f"{'，特性' + translate_ability(attacker.get('ability')) if attacker.get('ability') else ''}"
        f"{'，太晶' + TYPE_EN_TO_ZH.get(attacker.get('teraType'), attacker.get('teraType')) if attacker.get('teraType') else ''}"
        f"，能力变化：{format_boosts(attacker.get('boosts'))}"
    )
    lines.append(
        f"- 防守方配置：{format_evs(defender.get('evs'))}"
        f"{'，' + translate_nature(defender.get('nature')) + '性格' if defender.get('nature') else ''}"
        f"{'，道具' + translate_item(defender.get('item')) if defender.get('item') else ''}"
        f"{'，特性' + translate_ability(defender.get('ability')) if defender.get('ability') else ''}"
    )

    if damage is not None:
        lines.append(f"- 伤害随机数：{damage}")

    if damage_range is not None:
        hp_text = ""
        if calc_result.get("defenderHP"):
            hp_text = f"，目标当前 HP {calc_result.get('defenderHP')}/{calc_result.get('defenderMaxHP')}"
        lines.append(f"- 伤害范围：{damage_range[0]}-{damage_range[1]} HP{hp_text}")

    if percent:
        lines.append(f"- 百分比范围：{percent}")
    lines.append(f"- 结论：{ko_label(calc_result)}")

    return "\n".join(lines)


def explain_with_llm(
    user_text: str,
    calc_request: Dict[str, Any],
    calc_result: Dict[str, Any],
) -> str:
    """可选：让 DeepSeek 把工具结果解释成人话，但不要让它重新算伤害。"""
    system_prompt = """
你是宝可梦对战伤害计算助手。
你只负责解释确定性计算工具的输出，不要自行重新计算。
回答必须使用中文，最多 3 句话。
重点说明能否一回合击杀、伤害百分比、使用了哪些默认假设。
不要重新计算，不要输出英文原始描述。
"""

    payload = {
        "original_user_text": user_text,
        "battle": calc_request,
        "stable_result": {
            "summary": format_move_summary(calc_request.get("move", {}).get("name", ""), calc_result),
            "percent": extract_percent_range(calc_result),
            "damage_range": calc_result.get("range"),
            "ko_label": ko_label(calc_result),
        },
    }

    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
                ],
                temperature=0.2,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            if content:
                return content.strip()
            last_error = RuntimeError(f"空解释，finish_reason={response.choices[0].finish_reason}")
        except Exception as err:
            last_error = err

        if attempt < 2:
            time.sleep(1)

    return f"LLM 解释暂不可用：{last_error}"


def explain_results_with_llm(
    user_text: str,
    battle: Dict[str, Any],
    results: list[tuple[str, Dict[str, Any]]],
) -> str:
    if not results:
        return ""

    payload_results = [
        {
            "move": translate_move(move_name),
            "summary": format_move_summary(move_name, calc_result),
            "percent": extract_percent_range(calc_result),
            "ko_label": ko_label(calc_result),
        }
        for move_name, calc_result in results
    ]

    system_prompt = """
你是宝可梦对战伤害计算助手。
用中文解释确定性计算结果，最多 4 句话。
如果有多个招式，按一回合击杀能力和伤害高低概括，不要重新计算。
"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps({
                        "original_user_text": user_text,
                        "battle": battle,
                        "results": payload_results,
                    }, ensure_ascii=False, indent=2),
                },
            ],
            temperature=0.2,
            max_tokens=600,
        )
        return response.choices[0].message.content or ""
    except Exception as err:
        return f"LLM 解释暂不可用：{err}"


def main() -> None:
    print("Pokémon Damage Agent")
    print("示例：Gen9，252 SpA Choice Specs Flutter Mane 的 Moonblast 打 252 HP / 4 SpD Garchomp")
    print("输入 exit 退出，reset 清空上下文，status 查看当前战况。")

    session_state: Dict[str, Any] = {
        "battle": None,
        "assumptions": [],
        "move_candidates": [],
        "last_results": [],
        "last_user_text": "",
    }

    while True:
        user_text = input("\nBattle> ").strip()

        if user_text.lower() in {"exit", "quit"}:
            break
        if user_text.lower() in {"reset", "clear", "重新开始"}:
            session_state = {
                "battle": None,
                "assumptions": [],
                "move_candidates": [],
                "last_results": [],
                "last_user_text": "",
            }
            print("已清空上下文。")
            continue
        if user_text.lower() in {"status", "state", "当前"}:
            if not session_state.get("battle"):
                print("当前还没有保存战况。")
            else:
                print(format_battle_config(session_state["battle"]))
            continue
        try:
            if is_stateful_update(user_text, session_state):
                with progress_step("[1] 正在基于上一次战况应用修正"):
                    battle, notes = apply_text_update_to_battle(session_state["battle"], user_text)
                    battle = fill_builtin_defaults(battle)
                if notes:
                    print("已应用：")
                    for note in notes:
                        print("-", note)

                result_state = calculate_and_print(user_text, battle, session_state.get("move_candidates") or [])
                session_state["battle"] = result_state["battle"]
                session_state["last_results"] = result_state["results"]
                session_state["assumptions"] = dedupe_keep_order((session_state.get("assumptions") or []) + notes)
                session_state["last_user_text"] = user_text
                continue

            with progress_step("[1] 正在标准化术语"):
                normalization = normalize_user_text(user_text)
            normalized_text = normalization.get("normalized_text") or user_text
            if normalized_text != user_text:
                print(f"术语标准化：{normalized_text}")
            for correction in normalization.get("corrections") or []:
                print(
                    f"- {correction.get('original')} -> {correction.get('normalized')}"
                )

            alias_hits = find_alias_hits(normalized_text)
            ambiguity_questions = build_ambiguity_questions(alias_hits)

            if ambiguity_questions:
                print("\n需要确认：")
                for q in ambiguity_questions:
                    print("-", q)
                continue

            with progress_step("[2] 正在解析战况"):
                parsed = extract_battle_state(
                    user_text,
                    current_state={"battle": session_state.get("battle")} if session_state.get("battle") else None,
                    mode="strict",
                    normalization=normalization
                )
            inherit_context = should_inherit_context(parsed, session_state)
            parsed_for_questions = parsed
            if inherit_context:
                parsed_for_questions = clone_json(parsed)
                parsed_for_questions["battle"] = merge_battle_state(
                    session_state.get("battle"),
                    extract_battle(parsed)
                )

            followup_parts = []
            required_questions = build_required_questions(parsed_for_questions)
            if required_questions:
                print("\n还缺少无法默认的关键信息：")
                for index, question in enumerate(required_questions, start=1):
                    print(f"{index}. {question}")
                required_text = input("\n请补充> ").strip()
                if required_text:
                    followup_parts.append(required_text)
                    battle_preview = extract_battle(parsed_for_questions)
                    apply_followup_entities(battle_preview, required_text)
                    parsed_for_questions["battle"] = battle_preview
                    parsed["battle"] = merge_battle_state(extract_battle(parsed), battle_preview)

                remaining_required = build_required_questions(parsed_for_questions)
                if remaining_required:
                    print("\n这些关键信息仍然没补齐，先不计算：")
                    for question in remaining_required:
                        print("-", question)
                    continue

            default_items = build_defaultable_items(parsed_for_questions)
            if default_items:
                print("\n其余信息可以默认：")
                print(defaultable_prompt(default_items))
                default_text = input("直接回车/输入“不知道”按默认；也可以在这里补充> ").strip()
                if default_text:
                    followup_parts.append(default_text)

            followup_text = "；".join(followup_parts)

            with progress_step("[3] 正在补全默认值和常见配置"):
                enriched = enrich_with_common_defaults(user_text, parsed, followup_text)
            battle = merge_battle_state(session_state.get("battle"), extract_battle(enriched)) if inherit_context else extract_battle(enriched)
            move_candidates = enriched.get("move_candidates") or []

            print("采用的假设：")
            for assumption in enriched.get("assumptions") or []:
                print("-", assumption)
            for warning in enriched.get("warnings") or []:
                print("-", warning)

            result_state = calculate_and_print(user_text, battle, move_candidates)
            session_state["battle"] = result_state["battle"]
            session_state["last_results"] = result_state["results"]
            session_state["move_candidates"] = move_candidates
            session_state["assumptions"] = enriched.get("assumptions") or []
            session_state["last_user_text"] = user_text

        except Exception as err:
            print(f"\n错误：{err}")

def find_simple_hits(
    user_text: str,
    mapping: dict[str, Any],
    category: str,
    source: str
) -> list[dict[str, Any]]:
    hits = []

    for text, candidates in mapping.items():
        if text in user_text:
            hits.append({
                "text": text,
                "category": category,
                "source": source,
                "candidates": candidates
            })

    return hits


def find_alias_hits(user_text: str) -> list[dict[str, Any]]:
    hits = []

    # 官方中文名
    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=POKEMON_NAME_MAP,
        category="pokemon",
        source="name.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=MOVE_NAME_MAP,
        category="move",
        source="move.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=ITEM_NAME_MAP,
        category="item",
        source="item.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=ABILITY_NAME_MAP,
        category="ability",
        source="ability.json"
    ))

    # aliases.json 里的普通别名
    alias_pokemon = ALIASES_MAP.get("pokemon", {})
    alias_move = ALIASES_MAP.get("move", {})
    alias_item = ALIASES_MAP.get("item", {})
    alias_ability = ALIASES_MAP.get("ability", {})

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=alias_pokemon,
        category="pokemon",
        source="aliases.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=alias_move,
        category="move",
        source="aliases.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=alias_item,
        category="item",
        source="aliases.json"
    ))

    hits.extend(find_simple_hits(
        user_text=user_text,
        mapping=alias_ability,
        category="ability",
        source="aliases.json"
    ))

    # aliases.json 里的组合别名
    compound_map = ALIASES_MAP.get("compound", {})

    for text, meaning in compound_map.items():
        if text in user_text:
            hits.append({
                "text": text,
                "category": "compound",
                "source": "aliases.json",
                "meaning": meaning
            })

    # 长词优先，避免“讲究眼镜”和“眼镜”同时命中时短词干扰
    hits.sort(key=lambda x: len(x["text"]), reverse=True)

    return hits



if __name__ == "__main__":
    main()
# if __name__ == "__main__":
#     text = "眼镜鬼仙月爆打252HP地龙多少？"
#     hits = find_alias_hits(text)
#     print(json.dumps(hits, ensure_ascii=False, indent=2))
