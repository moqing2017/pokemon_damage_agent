export type StatId = 'hp' | 'atk' | 'def' | 'spa' | 'spd' | 'spe'

export type StatTable = Partial<Record<StatId, number>>

export interface PokemonSide {
  name: string
  level?: number
  nature?: string
  ability?: string
  gender?: string
  item?: string
  teraType?: string
  curHP?: number
  curHPPercent?: number | null
  status?: string
  evs?: StatTable
  ivs?: StatTable
  boosts?: StatTable
}

export interface BattleState {
  gen?: number
  attacker: PokemonSide
  defender: PokemonSide
  move: {
    name: string
    isCrit?: boolean
    hits?: number
    useZ?: boolean
    useMax?: boolean
  }
  field?: {
    weather?: string
    terrain?: string
    isGravity?: boolean
    isMagicRoom?: boolean
    isWonderRoom?: boolean
    attackerSide?: Record<string, unknown>
    defenderSide?: Record<string, unknown>
  }
}

export interface NormalizationResult {
  normalized_text: string
  corrections: Array<{
    original: string
    normalized: string
    category: string
    reason: string
  }>
  unresolved: string[]
}

export interface ParsedBattle {
  status: 'ready' | 'need_clarification'
  need_move: boolean
  intent: {
    type: string
    description: string
  }
  battle: BattleState
  questions: string[]
  assumptions: string[]
  resolved_aliases: Array<Record<string, unknown>>
  unresolved: string[]
  normalization?: NormalizationResult
}

export interface EnrichedBattle {
  battle: BattleState
  move_candidates: string[]
  assumptions: string[]
  warnings: string[]
}

export interface CalcResult {
  request: BattleState
  defenderHP: number
  defenderMaxHP: number
  damage: number | number[] | number[][]
  range?: [number, number] | null
  desc?: string | null
  fullDesc?: string | null
  moveDesc?: string | null
  recoil?: string | null
  recovery?: string | null
}

export interface Settings {
  apiKey: string
  baseUrl: string
  model: string
}

export interface SessionState {
  battle?: BattleState
  assumptions: string[]
  lastResult?: CalcResult
}
