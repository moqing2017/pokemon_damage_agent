import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { ABILITIES, ITEMS, MOVES, SPECIES, toID } from "@smogon/calc";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(__dirname, "..");
const DATA_DIR = path.join(ROOT_DIR, "data");

const POKEAPI = "https://pokeapi.co/api/v2";
const LANGUAGE = "zh-hans";

function canonicalMapFromKeys(keys) {
  const map = new Map();
  for (const key of keys) {
    map.set(toID(key), key);
  }
  return map;
}

const calcSpecies = canonicalMapFromKeys(Object.keys(SPECIES[9]));
const calcMoves = canonicalMapFromKeys(Object.keys(MOVES[9]));
const calcItems = canonicalMapFromKeys(ITEMS[9]);
const calcAbilities = canonicalMapFromKeys(ABILITIES[9]);

function localizedName(names, language = LANGUAGE) {
  return names?.find((entry) => entry.language?.name?.toLowerCase() === language)?.name;
}

function chineseName(names) {
  return localizedName(names, "zh-hans") || localizedName(names, "zh-hant");
}

function addMapping(target, zh, en) {
  if (!zh || !en) return;

  if (!target[zh]) {
    target[zh] = [];
  }
  if (!target[zh].includes(en)) {
    target[zh].push(en);
  }
}

async function readExisting(filename) {
  try {
    const text = await fs.readFile(path.join(DATA_DIR, filename), "utf8");
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function mergeExistingMissingOnly(target, existing) {
  for (const [zh, values] of Object.entries(existing)) {
    if (target[zh]) continue;

    const list = Array.isArray(values) ? values : [values];
    for (const en of list) {
      addMapping(target, zh, en);
    }
  }
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${url}`);
  }
  return response.json();
}

async function listResources(resource) {
  const first = await fetchJson(`${POKEAPI}/${resource}?limit=1`);
  const data = await fetchJson(`${POKEAPI}/${resource}?limit=${first.count}`);
  return data.results;
}

async function mapWithConcurrency(items, limit, mapper) {
  const results = new Array(items.length);
  let next = 0;

  async function worker() {
    while (next < items.length) {
      const index = next++;
      results[index] = await mapper(items[index], index);
    }
  }

  await Promise.all(Array.from({ length: limit }, worker));
  return results;
}

function titleCaseSlug(slug) {
  return slug
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("-");
}

async function buildSimpleMap(resource, canonicalMap) {
  const output = {};
  const resources = await listResources(resource);

  await mapWithConcurrency(resources, 24, async (entry) => {
    const detail = await fetchJson(entry.url);
    const zh = chineseName(detail.names);
    const en = canonicalMap.get(toID(localizedName(detail.names, "en") || detail.name));
    addMapping(output, zh, en);
  });

  return output;
}

function englishEffect(detail) {
  const entry = detail.effect_entries?.find((item) => item.language?.name === "en");
  return entry?.short_effect || entry?.effect || "";
}

async function buildEffectMap(resource, canonicalMap) {
  const output = {};
  const resources = await listResources(resource);

  await mapWithConcurrency(resources, 24, async (entry) => {
    const detail = await fetchJson(entry.url);
    const en = canonicalMap.get(toID(localizedName(detail.names, "en") || detail.name));
    const effect = englishEffect(detail);
    if (en && effect) {
      output[en] = effect;
    }
  });

  return output;
}

async function buildPokemonMap() {
  const output = await buildSimpleMap("pokemon-species", calcSpecies);
  const speciesByApiName = new Map();

  for (const [zh, values] of Object.entries(output)) {
    for (const en of values) {
      speciesByApiName.set(toID(en), zh);
    }
  }

  const forms = await listResources("pokemon-form");

  await mapWithConcurrency(forms, 16, async (entry) => {
    const detail = await fetchJson(entry.url);
    const canonical =
      calcSpecies.get(toID(detail.name)) ||
      calcSpecies.get(toID(titleCaseSlug(detail.name))) ||
      calcSpecies.get(toID(localizedName(detail.names, "en")));

    if (!canonical) return;

    const directZh = chineseName(detail.names);
    if (directZh) {
      addMapping(output, directZh, canonical);
      return;
    }

    const formZh = chineseName(detail.form_names);
    if (!formZh) return;

    const pokemon = await fetchJson(detail.pokemon.url);
    const baseZh = speciesByApiName.get(toID(pokemon.species.name));
    if (baseZh) {
      addMapping(output, `${baseZh}-${formZh}`, canonical);
    }
  });

  return output;
}

function buildSpeciesContext() {
  const output = {};
  const grouped = new Map();

  for (const [name, data] of Object.entries(SPECIES[9])) {
    const base = data.baseSpecies || name;
    if (!grouped.has(base)) {
      grouped.set(base, []);
    }
    grouped.get(base).push({ name, data });
  }

  for (const [base, forms] of grouped.entries()) {
    const genderForms = forms.filter(({ name }) => /-(F|M)(-|$)/.test(name));
    if (!genderForms.length) continue;

    const allNames = new Set([base, ...forms.map(({ name }) => name)]);
    output[base] = {
      note: "Forms differ by sex/form. Ask when it materially affects damage, or choose the mainstream set with an assumption when the user allows defaults.",
      forms: [...allNames]
        .filter((name) => SPECIES[9][name])
        .sort()
        .map((name) => ({
          name,
          gender: /-F($|-)/.test(name) ? "F" : /-M($|-)/.test(name) ? "M" : "M/default",
          baseStats: SPECIES[9][name].bs,
          abilities: SPECIES[9][name].abilities,
        })),
    };
  }

  return output;
}

async function writeJson(filename, data) {
  const sorted = Object.fromEntries(
    Object.entries(data)
      .sort(([a], [b]) => a.localeCompare(b, "zh-Hans"))
      .map(([key, values]) => [
        key,
        Array.isArray(values) ? [...new Set(values)].sort() : values
      ])
  );

  await fs.writeFile(
    path.join(DATA_DIR, filename),
    `${JSON.stringify(sorted, null, 2)}\n`,
    "utf8"
  );

  return Object.keys(sorted).length;
}

async function main() {
  const [pokemon, moves, items, abilities, itemEffects, abilityEffects] = await Promise.all([
    buildPokemonMap(),
    buildSimpleMap("move", calcMoves),
    buildSimpleMap("item", calcItems),
    buildSimpleMap("ability", calcAbilities),
    buildEffectMap("item", calcItems),
    buildEffectMap("ability", calcAbilities),
  ]);

  mergeExistingMissingOnly(pokemon, await readExisting("name.json"));
  mergeExistingMissingOnly(moves, await readExisting("move.json"));
  mergeExistingMissingOnly(items, await readExisting("item.json"));
  mergeExistingMissingOnly(abilities, await readExisting("ability.json"));

  const counts = {
    "name.json": await writeJson("name.json", pokemon),
    "move.json": await writeJson("move.json", moves),
    "item.json": await writeJson("item.json", items),
    "ability.json": await writeJson("ability.json", abilities),
    "item_effect.json": await writeJson("item_effect.json", itemEffects),
    "ability_effect.json": await writeJson("ability_effect.json", abilityEffects),
    "species_context.json": await writeJson("species_context.json", buildSpeciesContext()),
  };

  console.log(JSON.stringify(counts, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
