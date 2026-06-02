import { calculate, Field, Generations, Move, Pokemon } from '@smogon/calc'
import type { BattleState, CalcResult, PokemonSide, StatTable } from './types'

function removeEmptyValues<T extends Record<string, unknown>>(object: T) {
  return Object.fromEntries(
    Object.entries(object).filter(([, value]) => {
      if (value === undefined || value === null || value === '') return false
      if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) return false
      return true
    }),
  )
}

function normalizeEvs(evs: StatTable = {}) {
  return {
    hp: evs.hp ?? 0,
    atk: evs.atk ?? 0,
    def: evs.def ?? 0,
    spa: evs.spa ?? 0,
    spd: evs.spd ?? 0,
    spe: evs.spe ?? 0,
  }
}

function buildPokemon(gen: ReturnType<typeof Generations.get>, data: PokemonSide) {
  const pokemon = new Pokemon(
    gen,
    data.name,
    removeEmptyValues({
      level: data.level ?? 50,
      nature: data.nature,
      ability: data.ability,
      gender: data.gender,
      item: data.item,
      teraType: data.teraType,
      curHP: data.curHP,
      status: data.status,
      evs: normalizeEvs(data.evs),
      ivs: data.ivs,
      boosts: data.boosts,
    }),
  )

  if (data.curHPPercent !== undefined && data.curHPPercent !== null && data.curHP === undefined) {
    const percent = Number(data.curHPPercent)
    if (!Number.isNaN(percent)) {
      pokemon.originalCurHP = Math.max(1, Math.round((pokemon.maxHP(true) * percent) / 100))
    }
  }

  return pokemon
}

export function runDamageCalc(request: BattleState): CalcResult {
  if (!request.attacker?.name) throw new Error('缺少攻击方宝可梦')
  if (!request.defender?.name) throw new Error('缺少防守方宝可梦')
  if (!request.move?.name) throw new Error('缺少招式')

  const gen = Generations.get((request.gen ?? 9) as Parameters<typeof Generations.get>[0])
  const attacker = buildPokemon(gen, request.attacker)
  const defender = buildPokemon(gen, request.defender)
  const move = new Move(gen, request.move.name, removeEmptyValues({
    isCrit: request.move.isCrit,
    hits: request.move.hits,
    useZ: request.move.useZ,
    useMax: request.move.useMax,
  }))
  const field = new Field(removeEmptyValues({
    weather: request.field?.weather,
    terrain: request.field?.terrain,
    isGravity: request.field?.isGravity,
    isMagicRoom: request.field?.isMagicRoom,
    isWonderRoom: request.field?.isWonderRoom,
    attackerSide: request.field?.attackerSide,
    defenderSide: request.field?.defenderSide,
  }))

  const result = calculate(gen, attacker, defender, move, field)

  return {
    request,
    defenderHP: defender.curHP(),
    defenderMaxHP: defender.maxHP(),
    damage: result.damage,
    range: safeMethod(result, 'range') as [number, number] | null,
    desc: safeMethod(result, 'desc') as string | null,
    fullDesc: safeMethod(result, 'fullDesc') as string | null,
    moveDesc: safeMethod(result, 'moveDesc') as string | null,
    recoil: safeMethod(result, 'recoil') as string | null,
    recovery: safeMethod(result, 'recovery') as string | null,
  }
}

function safeMethod(result: unknown, methodName: string) {
  try {
    const value = (result as Record<string, unknown>)[methodName]
    if (typeof value === 'function') return value.call(result)
  } catch {
    return null
  }
  return null
}
