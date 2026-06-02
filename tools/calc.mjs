import fs from "fs";
import { calculate, Generations, Pokemon, Move, Field } from "@smogon/calc";

function readJsonFromStdin() {
  const input = fs.readFileSync(0, "utf8");
  return JSON.parse(input);
}

function removeEmptyValues(obj) {
  if (!obj || typeof obj !== "object") return {};

  const cleaned = {};
  for (const [key, value] of Object.entries(obj)) {
    if (
      value !== undefined &&
      value !== null &&
      value !== "" &&
      !(typeof value === "object" && Object.keys(value).length === 0)
    ) {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

function normalizeEvs(evs = {}) {
  return {
    hp: evs.hp ?? 0,
    atk: evs.atk ?? 0,
    def: evs.def ?? 0,
    spa: evs.spa ?? 0,
    spd: evs.spd ?? 0,
    spe: evs.spe ?? 0
  };
}

function buildPokemon(gen, data) {
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
      boosts: data.boosts
    })
  );

  if (data.curHPPercent !== undefined && data.curHPPercent !== null && data.curHP === undefined) {
    const percent = Number(data.curHPPercent);
    if (!Number.isNaN(percent)) {
      pokemon.originalCurHP = Math.max(1, Math.round(pokemon.maxHP(true) * percent / 100));
    }
  }

  return pokemon;
}

function buildMove(gen, data) {
  return new Move(
    gen,
    data.name,
    removeEmptyValues({
      isCrit: data.isCrit,
      hits: data.hits,
      useZ: data.useZ,
      useMax: data.useMax
    })
  );
}

function buildField(data = {}) {
  return new Field(
    removeEmptyValues({
      weather: data.weather,
      terrain: data.terrain,
      isGravity: data.isGravity,
      isMagicRoom: data.isMagicRoom,
      isWonderRoom: data.isWonderRoom,
      attackerSide: data.attackerSide,
      defenderSide: data.defenderSide
    })
  );
}

function safeMethod(result, methodName) {
  try {
    if (typeof result[methodName] === "function") {
      return result[methodName]();
    }
  } catch (err) {
    return null;
  }
  return null;
}

function main() {
  const rawRequest = readJsonFromStdin();
  const request = rawRequest.battle ?? rawRequest;

  const genNumber = request.gen ?? 9;
  const gen = Generations.get(genNumber);

  for (const field of ["attacker", "defender", "move"]) {
    if (!request[field]) {
      throw new Error(`Missing required field: ${field}`);
    }
  }
  if (!request.attacker.name) throw new Error("Missing required field: attacker.name");
  if (!request.defender.name) throw new Error("Missing required field: defender.name");
  if (!request.move.name) throw new Error("Missing required field: move.name");

  const attacker = buildPokemon(gen, request.attacker);
  const defender = buildPokemon(gen, request.defender);
  const move = buildMove(gen, request.move);
  const field = buildField(request.field);

  const result = calculate(gen, attacker, defender, move, field);

  const response = {
    request,
    defenderHP: defender.curHP(),
    defenderMaxHP: defender.maxHP(),
    damage: result.damage,
    range: safeMethod(result, "range"),
    desc: safeMethod(result, "desc"),
    fullDesc: safeMethod(result, "fullDesc"),
    moveDesc: safeMethod(result, "moveDesc"),
    recoil: safeMethod(result, "recoil"),
    recovery: safeMethod(result, "recovery")
  };

  console.log(JSON.stringify(response, null, 2));
}

try {
  main();
} catch (err) {
  console.error(JSON.stringify({
    error: err.message,
    stack: err.stack
  }, null, 2));
  process.exit(1);
}
