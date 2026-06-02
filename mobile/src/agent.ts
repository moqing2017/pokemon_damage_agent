import { deepseekJson } from './deepseek'
import {
  abilityEffectMap,
  abilityNameMap,
  aliasesMap,
  firstCandidate,
  itemEffectMap,
  itemNameMap,
  moveNameMap,
  pokemonNameMap,
  speciesContextMap,
  terrainZh,
  toZh,
  weatherZh,
} from './data'
import { runDamageCalc } from './calc'
import type { BattleState, CalcResult, EnrichedBattle, NormalizationResult, ParsedBattle, PokemonSide, SessionState, Settings } from './types'

const NORMALIZATION_PROMPT = `
你是宝可梦对战中文术语标准化器。
任务：把用户输入中的宝可梦、招式、道具、特性、常见对战术语纠正为标准简体中文名或标准说法。
规则：
1. 优先使用 fuzzy_candidates 给出的本地候选，但候选只是提示，最终由你根据语义判断。
2. 可以修正常见错别字、同音字、近音写法、别名和口误。
3. 不要改变伤害计算语义，比如“被威吓一次”“一招”“确一”“扑击”都要保留。
4. 无法确定时不要强行改，放入 unresolved。
只输出 JSON：
{
  "normalized_text": "",
  "corrections": [{"original": "", "normalized": "", "category": "", "reason": ""}],
  "unresolved": []
}`

const EXTRACTION_PROMPT = `
你是宝可梦伤害计算 Agent 的战况解析器。
你会收到 user_text、normalization、alias_hits、effect_context、species_context 和 current_state。
目标：从中文自然语言中抽取可计算战况，并保留已有上下文。
规则：
1. 必要字段是 attacker.name、defender.name、move.name；如果没有明确招式，可设置 need_move=true。
2. gen 默认 9，level 默认 50。未明确太晶时 teraType 必须为空。
3. 不要编造用户没说的信息。EV、性格、道具、特性、当前 HP、天气、场地等未知信息留空或 0，交给默认补全阶段。
4. “确一/一招打死/一下打死/秒杀”解析为 intent.type="one_turn_ko"。
5. “被抛下狠话一次”表示对应宝可梦攻击和特攻 -1；“被威吓一次”表示对应宝可梦攻击 -1。
6. “特性威吓/威吓特性”才写 ability="Intimidate"；“被威吓”是已发生效果，不是自身特性。
7. 解析 boosts 前必须参考 effect_context 中相关道具/特性的效果文本。例如清净坠饰、白色香草等可能改变能力下降是否生效，具体由你根据效果文本判断，并在 assumptions 说明。
8. 如果 species_context 显示宝可梦有性别/形态差异，必须考虑性别/形态对种族值、特性和技能表的影响；用户明确性别时写入 gender 和对应 name，默认时选择主流配置并说明。
9. 如果用户是在修正上一轮，例如“幽尾玄鱼肯定用波动冲”“不是这个道具”，应基于 current_state 更新对应槽位，不要丢失原有攻击方、防守方、天气等上下文。
只输出 JSON：
{
  "status": "ready",
  "need_move": false,
  "intent": {"type": "", "description": ""},
  "battle": {
    "gen": 9,
    "attacker": {"name": "", "level": 50, "nature": "", "ability": "", "gender": "", "item": "", "teraType": "", "curHPPercent": null, "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}, "ivs": {}, "boosts": {}},
    "defender": {"name": "", "level": 50, "nature": "", "ability": "", "gender": "", "item": "", "teraType": "", "curHPPercent": null, "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}, "ivs": {}, "boosts": {}},
    "move": {"name": "", "isCrit": false},
    "field": {"weather": "", "terrain": "", "attackerSide": {}, "defenderSide": {}}
  },
  "questions": [],
  "assumptions": [],
  "resolved_aliases": [],
  "unresolved": []
}`

const DEFAULT_PROMPT = `
你是宝可梦对战伤害计算助手。把 battle 中缺失的信息补成可计算的常见配置。
规则：
1. 只输出合法 JSON，不要输出解释文字。
2. 不要改变用户明确给出的宝可梦、招式、太晶、boosts、天气、场地、道具、特性。
3. 不知道天气默认无天气；不知道场地默认无场地；不知道当前 HP 默认 100；不知道世代默认 9。
4. 缺少努力值、性格、道具、特性、性别/形态时，由你根据常见对战配置选择一个合理配置，并在 assumptions 简短说明。
5. 必须结合招式分类调整配置。比如用户指定物理招式时，不要继续保留纯特攻向默认，除非这是用户明确给出的配置。
6. battle 或用户补充中出现道具/特性时，必须阅读 effect_context 对应效果，并决定能力变化、伤害修正等是否应生效。不要让程序硬兜底。
7. species_context 显示性别/形态差异时，结合招式和主流配置选择 form/gender；例如物攻向幽尾玄鱼通常选择雄性/默认形态，特攻向才考虑雌性形态。
8. 默认不太晶。除非用户明确说太晶/钛晶/tera + 属性，否则不要设置 teraType。
输出：
{
  "battle": {},
  "move_candidates": [],
  "assumptions": [],
  "warnings": []
}`

export async function handleUserMessage(
  text: string,
  settings: Settings,
  session: SessionState,
  onProgress?: (message: string) => void,
) {
  onProgress?.('正在标准化术语')
  const normalization = await normalizeUserText(text, settings)

  onProgress?.('正在解析战况')
  const parsed = await extractBattle(text, settings, session, normalization)

  const required = buildRequiredQuestions(parsed)
  const defaultable = buildDefaultableItems(parsed)
  if (required.length > 0) {
    return {
      kind: 'questions' as const,
      normalization,
      questions: required,
      defaultable,
      session,
    }
  }

  onProgress?.('正在补全默认配置')
  const enriched = await enrichBattle(parsed.battle, text, settings, defaultable)

  onProgress?.('正在计算伤害')
  const result = runDamageCalc(enriched.battle)
  const nextSession: SessionState = {
    battle: enriched.battle,
    assumptions: enriched.assumptions ?? [],
    lastResult: result,
  }

  return {
    kind: 'result' as const,
    normalization,
    parsed,
    enriched,
    result,
    session: nextSession,
  }
}

export async function normalizeUserText(text: string, settings: Settings) {
  return deepseekJson<NormalizationResult>(settings, NORMALIZATION_PROMPT, {
    user_text: text,
    fuzzy_candidates: fuzzyTermCandidates(text),
  }, 1200)
}

async function extractBattle(text: string, settings: Settings, session: SessionState, normalization: NormalizationResult) {
  const normalizedText = normalization.normalized_text || text
  const aliasHits = findAliasHits(normalizedText)
  const battle = session.battle
  return deepseekJson<ParsedBattle>(settings, EXTRACTION_PROMPT, {
    user_text: normalizedText,
    original_user_text: text,
    normalization,
    alias_hits: aliasHits,
    effect_context: buildEffectContext(aliasHits, battle),
    species_context: buildSpeciesContext(aliasHits, battle),
    current_state: session,
  }, 3200)
}

async function enrichBattle(battle: BattleState, followupText: string, settings: Settings, defaultable: string[]) {
  const aliasHits = findAliasHits(followupText)
  return deepseekJson<EnrichedBattle>(settings, DEFAULT_PROMPT, {
    battle,
    followup_text: followupText,
    defaultable_items: defaultable,
    effect_context: buildEffectContext(aliasHits, battle),
    species_context: buildSpeciesContext(aliasHits, battle),
  }, 4500)
}

function buildRequiredQuestions(parsed: ParsedBattle) {
  const questions = [...(parsed.questions ?? [])]
  if (!parsed.battle?.attacker?.name) questions.push('攻击方是哪只宝可梦？')
  if (!parsed.battle?.defender?.name) questions.push('防守方是哪只宝可梦？')
  if (parsed.need_move || !parsed.battle?.move?.name) questions.push('使用哪个招式？不知道的话我会列常见攻击招式。')
  return Array.from(new Set(questions)).slice(0, 3)
}

function buildDefaultableItems(parsed: ParsedBattle) {
  const battle = parsed.battle
  const items: string[] = []
  if (!battle.gen) items.push('世代默认第九世代')
  if (!battle.field?.weather) items.push('天气默认无天气')
  if (!battle.field?.terrain) items.push('场地默认无场地')
  if (!hasAnyEvs(battle.attacker) || !battle.attacker.nature || !battle.attacker.item || !battle.attacker.ability) {
    items.push('攻击方配置用常见配置')
  }
  if (!hasAnyEvs(battle.defender) || !battle.defender.nature || !battle.defender.item || !battle.defender.ability) {
    items.push('防守方配置用常见配置')
  }
  if (battle.attacker.curHPPercent == null) items.push('攻击方当前 HP 默认满血')
  if (battle.defender.curHPPercent == null) items.push('防守方当前 HP 默认满血')
  if (!battle.attacker.teraType && !battle.defender.teraType) items.push('默认双方不太晶')
  return items
}

function hasAnyEvs(side: PokemonSide) {
  return Object.values(side.evs ?? {}).some((value) => Number(value) !== 0)
}

function findAliasHits(text: string) {
  const mappings: Array<[string, Record<string, string | string[]>]> = [
    ['pokemon', pokemonNameMap],
    ['move', moveNameMap],
    ['item', itemNameMap],
    ['ability', abilityNameMap],
    ['pokemon', aliasesMap.pokemon ?? {}],
    ['move', aliasesMap.move ?? {}],
    ['item', aliasesMap.item ?? {}],
    ['ability', aliasesMap.ability ?? {}],
  ]

  const hits = []
  for (const [category, mapping] of mappings) {
    for (const [zh, candidates] of Object.entries(mapping)) {
      if (zh && text.includes(zh)) {
        hits.push({ text: zh, category, candidates: Array.isArray(candidates) ? candidates : [candidates] })
      }
    }
  }
  return hits.slice(0, 80)
}

function fuzzyTermCandidates(text: string) {
  return findAliasHits(text).slice(0, 40)
}

function buildEffectContext(aliasHits: ReturnType<typeof findAliasHits>, battle?: BattleState) {
  const items = new Set<string>()
  const abilities = new Set<string>()

  for (const hit of aliasHits) {
    const candidate = firstCandidate(hit.candidates)
    if (hit.category === 'item' && candidate) items.add(candidate)
    if (hit.category === 'ability' && candidate) abilities.add(candidate)
  }

  for (const side of [battle?.attacker, battle?.defender]) {
    if (side?.item) items.add(side.item)
    if (side?.ability) abilities.add(side.ability)
  }

  return {
    items: Object.fromEntries([...items].map((name) => [name, itemEffectMap[name] ?? ''])),
    abilities: Object.fromEntries([...abilities].map((name) => [name, abilityEffectMap[name] ?? ''])),
  }
}

function buildSpeciesContext(aliasHits: ReturnType<typeof findAliasHits>, battle?: BattleState) {
  const names = new Set<string>()
  for (const hit of aliasHits) {
    if (hit.category === 'pokemon') {
      const candidate = firstCandidate(hit.candidates)
      if (candidate) names.add(candidate)
    }
  }
  if (battle?.attacker?.name) names.add(battle.attacker.name)
  if (battle?.defender?.name) names.add(battle.defender.name)

  const output: Record<string, unknown> = {}
  for (const name of names) {
    const base = name.replace(/-(F|M)(-.+)?$/, '')
    if (speciesContextMap[name]) output[name] = speciesContextMap[name]
    if (speciesContextMap[base]) output[base] = speciesContextMap[base]
  }
  return output
}

export function formatBattleConfig(battle: BattleState) {
  return [
    `规则：第 ${battle.gen ?? 9} 世代`,
    `攻击方：${formatSide(battle.attacker)}`,
    `防守方：${formatSide(battle.defender)}`,
    `招式：${toZh('move', battle.move.name) || battle.move.name}`,
    `场地：天气 ${weatherZh[battle.field?.weather ?? ''] ?? '无'}，场地 ${terrainZh[battle.field?.terrain ?? ''] ?? '无'}`,
  ]
}

function formatSide(side: PokemonSide) {
  const details = [
    toZh('pokemon', side.name) || side.name,
    `等级${side.level ?? 50}`,
    formatEvs(side.evs),
    side.nature ? `${toZh('nature', side.nature)}性格` : '',
    side.gender ? `性别${side.gender}` : '',
    side.ability ? `特性${toZh('ability', side.ability)}` : '',
    side.item ? `道具${toZh('item', side.item)}` : '',
    side.teraType ? `太晶${side.teraType}` : '不太晶',
    `当前HP ${side.curHPPercent ?? 100}%`,
    `能力变化：${formatBoosts(side.boosts)}`,
  ].filter(Boolean)

  return details.join('，')
}

function formatEvs(evs = {}) {
  const labels: Record<string, string> = { hp: 'HP', atk: '攻击', def: '防御', spa: '特攻', spd: '特防', spe: '速度' }
  const parts = Object.entries(evs).filter(([, value]) => Number(value) > 0).map(([key, value]) => `${value}${labels[key]}`)
  return parts.length ? parts.join(' / ') : '0努力值'
}

function formatBoosts(boosts = {}) {
  const labels: Record<string, string> = { atk: '攻击', def: '防御', spa: '特攻', spd: '特防', spe: '速度' }
  const parts = Object.entries(boosts).filter(([, value]) => Number(value) !== 0).map(([key, value]) => `${labels[key] ?? key}${Number(value) > 0 ? '+' : ''}${value}`)
  return parts.length ? parts.join('，') : '无'
}

export function formatCalcResult(result: CalcResult) {
  const damageValues = flattenDamage(result.damage)
  const minDamage = Math.min(...damageValues)
  const maxDamage = Math.max(...damageValues)
  const minPercent = round((minDamage / result.defenderHP) * 100)
  const maxPercent = round((maxDamage / result.defenderHP) * 100)
  const ko = minDamage >= result.defenderHP ? '确定一回合击杀' : maxDamage >= result.defenderHP ? '有概率一回合击杀' : `${Math.ceil(result.defenderHP / maxDamage)}回合左右击杀`
  const moveName = toZh('move', result.request.move.name) || result.request.move.name

  return [
    `${toZh('pokemon', result.request.attacker.name)} 使用 ${moveName} 攻击 ${toZh('pokemon', result.request.defender.name)}`,
    `伤害范围：${minDamage}-${maxDamage} HP，目标当前 HP ${result.defenderHP}/${result.defenderMaxHP}`,
    `百分比范围：${minPercent} - ${maxPercent}%`,
    `结论：${ko}`,
    `${moveName}（${ko}，${minPercent} - ${maxPercent}%）`,
  ]
}

function flattenDamage(damage: CalcResult['damage']): number[] {
  if (typeof damage === 'number') return [damage]
  return damage.flatMap((value) => (Array.isArray(value) ? value : [value]))
}

function round(value: number) {
  return Number(value.toFixed(1))
}
