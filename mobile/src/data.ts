import ability from './data/ability.json'
import abilityEffect from './data/ability_effect.json'
import aliases from './data/aliases.json'
import item from './data/item.json'
import itemEffect from './data/item_effect.json'
import move from './data/move.json'
import name from './data/name.json'
import speciesContext from './data/species_context.json'

type NameMap = Record<string, string | string[]>

export const pokemonNameMap = name as NameMap
export const moveNameMap = move as NameMap
export const itemNameMap = item as NameMap
export const abilityNameMap = ability as NameMap
export const itemEffectMap = itemEffect as Record<string, string>
export const abilityEffectMap = abilityEffect as Record<string, string>
export const aliasesMap = aliases as unknown as Record<string, NameMap>
export const speciesContextMap = speciesContext as Record<string, unknown>

function normalizeCandidates(value: string | string[] | undefined): string[] {
  if (!value) return []
  return Array.isArray(value) ? value : [value]
}

function buildReverseNameMap(...maps: NameMap[]) {
  const reverse: Record<string, string> = {}

  for (const mapping of maps) {
    for (const [zh, value] of Object.entries(mapping)) {
      for (const en of normalizeCandidates(value)) {
        if (!en) continue
        if (!reverse[en] || zh.length < reverse[en].length) {
          reverse[en] = zh
        }
      }
    }
  }

  return reverse
}

export const pokemonEnToZh = buildReverseNameMap(pokemonNameMap, aliasesMap.pokemon ?? {})
export const moveEnToZh = buildReverseNameMap(moveNameMap, aliasesMap.move ?? {})
export const itemEnToZh = buildReverseNameMap(itemNameMap, aliasesMap.item ?? {})
export const abilityEnToZh = buildReverseNameMap(abilityNameMap, aliasesMap.ability ?? {})

export const natureEnToZh: Record<string, string> = {
  Adamant: '固执',
  Bold: '大胆',
  Calm: '温和',
  Careful: '慎重',
  Impish: '淘气',
  Jolly: '爽朗',
  Modest: '内敛',
  Timid: '胆小',
  Brave: '勇敢',
  Quiet: '冷静',
  Relaxed: '悠闲',
  Sassy: '自大',
}

export const weatherZh: Record<string, string> = {
  Sun: '晴天',
  Sunny: '晴天',
  Rain: '雨天',
  Sand: '沙暴',
  Hail: '冰雹',
  Snow: '雪景',
  HarshSunshine: '大晴天',
  HeavyRain: '大雨',
}

export const terrainZh: Record<string, string> = {
  Electric: '电气场地',
  Grassy: '青草场地',
  Misty: '薄雾场地',
  Psychic: '精神场地',
}

export function firstCandidate(value: string | string[] | undefined) {
  return normalizeCandidates(value)[0] ?? ''
}

export function toZh(kind: 'pokemon' | 'move' | 'item' | 'ability' | 'nature', value?: string) {
  if (!value) return ''
  if (kind === 'pokemon') return pokemonEnToZh[value] ?? value
  if (kind === 'move') return moveEnToZh[value] ?? value
  if (kind === 'item') return itemEnToZh[value] ?? value
  if (kind === 'ability') return abilityEnToZh[value] ?? value
  return natureEnToZh[value] ?? value
}
