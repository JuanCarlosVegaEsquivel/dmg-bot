const { Client, GatewayIntentBits, REST, Routes, SlashCommandBuilder, EmbedBuilder, ApplicationCommandOptionType } = require("discord.js");
const axios  = require("axios");
const nbt    = require("prismarine-nbt");
const fs     = require("fs");
const path   = require("path");
const zlib   = require("zlib");

// ── Config ─────────────────────────────────────────────────────
const TOKEN       = process.env.DISCORD_TOKEN;
const HYPIXEL_KEY = process.env.HYPIXEL_API_KEY;
const BOT_COLOR   = 0xe84040;
const STATS_FILE  = "user_stats.json";

// ── Client ─────────────────────────────────────────────────────
const client = new Client({ intents: [GatewayIntentBits.Guilds] });

// ── NEU Data ───────────────────────────────────────────────────
let NEU_REFORGES  = {};
let NEU_ENCHANTS  = {};

async function loadNeuData() {
    console.log("📦 Loading NEU data...");
    try {
        const url = "https://github.com/NotEnoughUpdates/NotEnoughUpdates-REPO/archive/refs/heads/master.zip";
        const res = await axios.get(url, { responseType: "arraybuffer", timeout: 60000 });

        const AdmZip = require("adm-zip");
        const zip    = new AdmZip(Buffer.from(res.data));
        const entries = zip.getEntries();

        for (const entry of entries) {
            if (entry.entryName.includes("/constants/reforges.json"))
                NEU_REFORGES = JSON.parse(entry.getData().toString("utf8"));
            if (entry.entryName.includes("/constants/enchants.json"))
                NEU_ENCHANTS = JSON.parse(entry.getData().toString("utf8"));
        }
        console.log(`✅ NEU loaded — ${Object.keys(NEU_REFORGES).length} reforges, ${Object.keys(NEU_ENCHANTS).length} enchant entries`);
    } catch (e) {
        console.error("❌ NEU load error:", e.message);
    }
}

// ── User Stats Storage ─────────────────────────────────────────
function loadUserStats() {
    try { return JSON.parse(fs.readFileSync(STATS_FILE, "utf8")); }
    catch { return {}; }
}
function saveUserStats(data) {
    fs.writeFileSync(STATS_FILE, JSON.stringify(data, null, 2));
}

// ── Hypixel API ────────────────────────────────────────────────
async function getUUID(username) {
    const res = await axios.get(`https://api.mojang.com/users/profiles/minecraft/${username}`);
    return res.data.id;
}

async function getProfiles(uuid) {
    const res = await axios.get(`https://api.hypixel.net/v2/skyblock/profiles`, {
        params: { uuid },
        headers: { "API-Key": HYPIXEL_KEY }
    });
    return res.data.profiles || [];
}

async function fetchProfile(username, profileName = null) {
    const uuid     = await getUUID(username);
    const profiles = await getProfiles(uuid);
    if (!profiles.length) throw new Error(`No SkyBlock profiles found for **${username}**.`);

    let profile;
    if (profileName) {
        profile = profiles.find(p => p.cute_name?.toLowerCase() === profileName.toLowerCase());
        if (!profile) {
            const names = profiles.map(p => p.cute_name).join(", ");
            throw new Error(`Profile **${profileName}** not found. Available: ${names}`);
        }
    } else {
        profile = profiles.find(p => p.selected) || profiles[0];
    }

    const members = profile.members || {};
    const playerUUID = Object.keys(members).find(u => members[u].username?.toLowerCase() === username.toLowerCase())
                    || Object.keys(members)[0];
    const member = members[playerUUID];
    if (!member) throw new Error("Could not find player data inside profile.");

    return { member, profile, profiles, ign: member.username || username, uuid };
}

// ── NBT Parser ─────────────────────────────────────────────────
async function decodeInventory(b64) {
    try {
        const clean  = b64.replace(/\s+/g, "");
        const buf    = Buffer.from(clean, "base64");
        const gunzip = await new Promise((res, rej) => {
            zlib.gunzip(buf, (err, result) => err ? rej(err) : res(result));
        });

        const { parsed } = await nbt.parse(gunzip);
        const items = parsed?.value?.i?.value?.value || [];

        return items.map(item => {
            if (!item || !item.id) return null;
            const tag   = item.tag?.value || {};
            const extra = tag.ExtraAttributes?.value || {};
            const display = tag.display?.value || {};

            return {
                id:      item.id.value,
                count:   item.Count?.value || 1,
                skyId:   extra.id?.value || "",
                reforge: extra.modifier?.value || "",
                rarity:  extra.tier?.value || "COMMON",
                enchants: Object.entries(extra.enchantments?.value || {}).map(([k,v]) => ({ name: k, level: v.value })),
                displayName: display.Name?.value || "",
            };
        }).filter(Boolean);
    } catch (e) {
        console.error("NBT decode error:", e.message);
        return [];
    }
}

// ── Stat Calculation ───────────────────────────────────────────
const XP_TABLE = [0,50,175,375,675,1175,1925,2925,4425,6425,9925,14925,22425,32425,47425,67425,97425,147425,222425,322425,522425,822425,1222425,1722425,2322425,3022425,3822425,4722425,5722425,6822425,8022425,9322425,10722425,12222425,13822425,15522425,17322425,19222425,21222425,23322425,25522425,27822425,30222425,32722425,35322425,38022425,40822425,43722425,46722425,49922425,53222425,56722425,60322425,64022425,67822425,71722425,75722425,79822425,84022425,88322425];

function xpToLevel(xp, max = 60) {
    for (let i = 0; i < XP_TABLE.length; i++) {
        if (xp < XP_TABLE[i]) return Math.max(0, i - 1);
    }
    return max;
}

function getReforgeStats(reforgeName, rarity) {
    if (!reforgeName || !NEU_REFORGES) return {};
    const key = Object.keys(NEU_REFORGES).find(k => k.toLowerCase() === reforgeName.toLowerCase());
    if (!key) return {};
    return NEU_REFORGES[key]?.reforgeStats?.[rarity.toUpperCase()] || {};
}

async function calcPlayerStats(member) {
    const total = {
        health: 100, defense: 0, strength: 0, intelligence: 0,
        crit_chance: 30, crit_damage: 50, attack_speed: 0,
        ferocity: 0, speed: 100, true_defense: 0, vitality: 0,
        magic_find: 0,
    };

    const inv = member.inventory || {};

    // Parse armor + equipment
    for (const slot of ["inv_armor", "equipment_contents"]) {
        const b64 = inv[slot]?.data;
        if (!b64) continue;
        const items = await decodeInventory(b64);
        for (const item of items) {
            const refStats = getReforgeStats(item.reforge, item.rarity);
            for (const [stat, val] of Object.entries(refStats)) {
                if (stat in total) total[stat] += val;
            }

            // Superior enchant: +5% all stats
            const superior = item.enchants?.find(e => e.name === "ultimate_chimera" || e.name === "superior");
            if (superior) {
                for (const key of Object.keys(total)) total[key] *= 1.05;
            }
        }
    }

    // Skill bonuses
    const exp = member.player_data?.experience || {};
    const combatLvl     = xpToLevel(exp.SKILL_COMBAT    || 0);
    const enchantingLvl = xpToLevel(exp.SKILL_ENCHANTING || 0);
    const foragingLvl  = xpToLevel(exp.SKILL_FORAGING  || 0);

    total.strength    += combatLvl * 4;
    total.crit_chance += combatLvl * 0.5;
    total.intelligence += enchantingLvl * 1;

    return total;
}

// ── Damage Helpers ─────────────────────────────────────────────
function calcDamage(strength, critDmg, weaponDmg) {
    const base = (5 + weaponDmg) * (1 + strength / 100);
    const crit = base * (1 + critDmg / 100);
    return { base: Math.round(base), crit: Math.round(crit) };
}

function damageRating(crit) {
    if (crit >= 2_000_000) return "🔴 God Roll";
    if (crit >= 500_000)   return "🟠 Endgame";
    if (crit >= 100_000)   return "🟡 Late Game";
    if (crit >= 30_000)    return "🟢 Mid Game";
    if (crit >= 5_000)     return "🔵 Early Mid";
    return "⚪ Early Game";
}

function fmt(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
    return String(Math.round(n * 10) / 10);
}

// ── Boss Data ──────────────────────────────────────────────────
const BOSS_DATA = {
    "revenant_t1": { name:"🧟 Revenant T1", hp:500,        def:0,    type:"Zombie Slayer",        notes:"Easy intro boss. Any gear works." },
    "revenant_t2": { name:"🧟 Revenant T2", hp:20000,      def:0,    type:"Zombie Slayer",        notes:"Pestilence reduces your defense -25%." },
    "revenant_t3": { name:"🧟 Revenant T3", hp:400000,     def:0,    type:"Zombie Slayer",        notes:"Pestilence + Explosive Assault. 900 HP + 400 DEF min." },
    "revenant_t4": { name:"🧟 Revenant T4", hp:1500000,    def:0,    type:"Zombie Slayer",        notes:"1000 DPS. Rev Armor + Reaper Falchion. 800+ DEF." },
    "revenant_t5": { name:"🧟 Revenant T5", hp:10000000,   def:0,    type:"Zombie Slayer",        notes:"Immune to ability damage + arrows. Melee only. Reaper Falchion required." },
    "tarantula_t1":{ name:"🕷 Tarantula T1", hp:750,        def:0,    type:"Spider Slayer",        notes:"Simple boss. Spider Hat + any weapon." },
    "tarantula_t2":{ name:"🕷 Tarantula T2", hp:30000,      def:0,    type:"Spider Slayer",        notes:"Stand under a roof to prevent boss jumping behind." },
    "tarantula_t3":{ name:"🕷 Tarantula T3", hp:144000,     def:0,    type:"Spider Slayer",        notes:"Tarantula Armor + Livid Dagger recommended." },
    "tarantula_t4":{ name:"🕷 Tarantula T4", hp:576000,     def:0,    type:"Spider Slayer",        notes:"Fast and deadly. Tarantula Armor 2k kills + Recluse Fang. ~300 MP." },
    "sven_t1":     { name:"🐺 Sven T1",      hp:2000,       def:0,    type:"Wolf Slayer",          notes:"Fight in water — prevents slam attacks." },
    "sven_t2":     { name:"🐺 Sven T2",      hp:40000,      def:0,    type:"Wolf Slayer",          notes:"True Damage starts here. 500 DEF min." },
    "sven_t3":     { name:"🐺 Sven T3",      hp:750000,     def:0,    type:"Wolf Slayer",          notes:"Protected phase: pups guard boss. Fight in water — pups drown." },
    "sven_t4":     { name:"🐺 Sven T4",      hp:2000000,    def:0,    type:"Wolf Slayer",          notes:"Mastiff Armor required. Crit Damage halved. Let it hit you every 15s." },
    "voidgloom_t1":{ name:"🌀 Voidgloom T1", hp:300000,     def:300,  type:"Enderman Slayer",      notes:"Hitshield at 100%/66%/33% HP. SA Armor + AOTD min." },
    "voidgloom_t2":{ name:"🌀 Voidgloom T2", hp:1000000,    def:500,  type:"Enderman Slayer",      notes:"3/4 Shadow Assassin + Crystallized Heart min. ~200 MP." },
    "voidgloom_t3":{ name:"🌀 Voidgloom T3", hp:2500000,    def:750,  type:"Enderman Slayer",      notes:"Necromancy Souls required. Atomsplit Katana + FD Armor." },
    "voidgloom_t4":{ name:"🌀 Voidgloom T4", hp:6000000,    def:1000, type:"Enderman Slayer",      notes:"Invulnerability beams + Hitshield. FD 25k kills + Soul Whip." },
    "inferno_t1":  { name:"🔥 Inferno T1",   hp:500000,     def:100,  type:"Blaze Slayer",         notes:"Stay in green circle during Mania. Frozen Blaze or Crimson Armor." },
    "inferno_t2":  { name:"🔥 Inferno T2",   hp:2000000,    def:300,  type:"Blaze Slayer",         notes:"Twinclaws: use Holy Ice when you hear the sound cue." },
    "inferno_t3":  { name:"🔥 Inferno T3",   hp:5000000,    def:500,  type:"Blaze Slayer",         notes:"Laser beams deal 75% max HP True Damage. 3/4 Frozen Blaze or Crimson." },
    "inferno_t4":  { name:"🔥 Inferno T4",   hp:12000000,   def:750,  type:"Blaze Slayer",         notes:"Endgame only. Kindlebane + Mawdredge T2 required." },
    "vampire_t1":  { name:"🧛 Vampire T1",   hp:1000000,    def:200,  type:"Vampire Slayer (Rift)", notes:"Activate effigies before starting for Rift Damage boost." },
    "vampire_t2":  { name:"🧛 Vampire T2",   hp:2500000,    def:400,  type:"Vampire Slayer (Rift)", notes:"Twinclaws: use Holy Ice when you hear the sound cue." },
    "vampire_t3":  { name:"🧛 Vampire T3",   hp:5000000,    def:600,  type:"Vampire Slayer (Rift)", notes:"High Rift Damage needed." },
    "vampire_t4":  { name:"🧛 Vampire T4",   hp:10000000,   def:800,  type:"Vampire Slayer (Rift)", notes:"Endgame Rift. Best Rift gear required." },
    "vampire_t5":  { name:"🧛 Vampire T5",   hp:20000000,   def:1000, type:"Vampire Slayer (Rift)", notes:"Extremely difficult. Top-tier Rift gear only." },
    "kuudra_basic":   { name:"🦑 Kuudra Basic",    hp:5000000,   def:200,  type:"Kuudra", notes:"Req: Combat 22. Specialist role. Necron/Storm/Terror Armor." },
    "kuudra_hot":     { name:"🦑 Kuudra Hot",      hp:15000000,  def:400,  type:"Kuudra", notes:"Req: Combat 27 + 1000 rep. Ballista required for final blow." },
    "kuudra_burning": { name:"🦑 Kuudra Burning",  hp:30000000,  def:600,  type:"Kuudra", notes:"Req: Combat 32 + 3000 rep. Must STUN before shooting." },
    "kuudra_fiery":   { name:"🦑 Kuudra Fiery",    hp:60000000,  def:800,  type:"Kuudra", notes:"Req: Combat 37 + 7000 rep. Terror Armor + Terminator + 100% AS." },
    "kuudra_infernal":{ name:"🦑 Kuudra Infernal", hp:100000000, def:1000, type:"Kuudra", notes:"Req: Combat 42 + 12000 rep. Duplex Terminator + Precursor Eye." },
    "cata_f1": { name:"⚰ Bonzo (F1)",   hp:500000,   def:100,  type:"Catacombs", notes:"Intro floor. Almost any gear works." },
    "cata_f2": { name:"⚰ Scarf (F2)",   hp:1000000,  def:200,  type:"Catacombs", notes:"Soul summons. Need decent damage to clear adds." },
    "cata_f3": { name:"⚰ Professor (F3)",hp:2000000, def:300,  type:"Catacombs", notes:"Three phases. Guardian spawns at each phase." },
    "cata_f4": { name:"⚰ Thorn (F4)",   hp:4000000,  def:400,  type:"Catacombs", notes:"Spirit Bow phase. Must craft bow mid-fight." },
    "cata_f5": { name:"⚰ Livid (F5)",   hp:6000000,  def:500,  type:"Catacombs", notes:"Multiple Livid clones. Find and kill the real one." },
    "cata_f6": { name:"⚰ Sadan (F6)",   hp:10000000, def:600,  type:"Catacombs", notes:"Giant phase. Requires high damage to stagger." },
    "cata_f7": { name:"⚰ Necron (F7)",  hp:20000000, def:750,  type:"Catacombs", notes:"5 phases: Maxor, Storm, Goldor, Necron, Wither King." },
    "cata_m3": { name:"⚰ Professor (M3)",hp:8000000, def:600,  type:"Master Catacombs", notes:"Master mode. Endgame gear required." },
    "cata_m6": { name:"⚰ Sadan (M6)",   hp:30000000, def:900,  type:"Master Catacombs", notes:"Master mode. True endgame content." },
    "cata_m7": { name:"⚰ Necron (M7)",  hp:60000000, def:1000, type:"Master Catacombs", notes:"Hardest dungeon. Top-tier gear only." },
};

// ── Commands ───────────────────────────────────────────────────
const commands = [
    new SlashCommandBuilder()
        .setName("ping")
        .setDescription("Test if the bot is working"),

    new SlashCommandBuilder()
        .setName("info")
        .setDescription("About this bot"),

    new SlashCommandBuilder()
        .setName("setstats")
        .setDescription("Save your combat stats")
        .addIntegerOption(o => o.setName("strength").setDescription("Your Strength stat").setRequired(true))
        .addIntegerOption(o => o.setName("crit_chance").setDescription("Your Crit Chance %").setRequired(true))
        .addIntegerOption(o => o.setName("crit_damage").setDescription("Your Crit Damage %").setRequired(true))
        .addIntegerOption(o => o.setName("weapon_damage").setDescription("Your weapon damage stat").setRequired(true))
        .addStringOption(o => o.setName("username").setDescription("Your Minecraft username (optional)")),

    new SlashCommandBuilder()
        .setName("mystats")
        .setDescription("Show your saved combat stats"),

    new SlashCommandBuilder()
        .setName("damage")
        .setDescription("Calculate your damage (uses saved stats if not provided)")
        .addIntegerOption(o => o.setName("strength").setDescription("Override Strength"))
        .addIntegerOption(o => o.setName("crit_chance").setDescription("Override Crit Chance %"))
        .addIntegerOption(o => o.setName("crit_damage").setDescription("Override Crit Damage %"))
        .addIntegerOption(o => o.setName("weapon_damage").setDescription("Override weapon damage")),

    new SlashCommandBuilder()
        .setName("stats")
        .setDescription("View a player's SkyBlock profile")
        .addStringOption(o => o.setName("username").setDescription("Minecraft username").setRequired(true))
        .addStringOption(o => o.setName("profile").setDescription("Profile name (optional)")),

    new SlashCommandBuilder()
        .setName("bosses")
        .setDescription("Calculate your damage against a boss")
        .addStringOption(o => o.setName("boss").setDescription("Boss name (e.g. Voidgloom T4, Kuudra Infernal)").setRequired(true).setAutocomplete(true))
        .addIntegerOption(o => o.setName("strength").setDescription("Override Strength"))
        .addIntegerOption(o => o.setName("crit_damage").setDescription("Override Crit Damage %"))
        .addIntegerOption(o => o.setName("weapon_damage").setDescription("Override weapon damage")),
].map(c => c.toJSON());

// ── Register Commands ──────────────────────────────────────────
async function registerCommands() {
    const rest = new REST({ version: "10" }).setToken(TOKEN);
    await rest.put(Routes.applicationCommands(client.user.id), { body: commands });
    console.log(`✅ Registered ${commands.length} commands`);
}

// ── Event: Ready ───────────────────────────────────────────────
client.once("ready", async () => {
    console.log(`✅ Bot online: ${client.user.tag}`);
    await registerCommands();
    await loadNeuData();
});

// ── Event: Interaction ─────────────────────────────────────────
client.on("interactionCreate", async interaction => {

    // Autocomplete
    if (interaction.isAutocomplete()) {
        if (interaction.commandName === "bosses") {
            const focused = interaction.options.getFocused().toLowerCase();
            const choices = Object.entries(BOSS_DATA)
                .filter(([k, v]) => k.includes(focused) || v.name.toLowerCase().includes(focused))
                .slice(0, 25)
                .map(([k, v]) => ({ name: v.name, value: k }));
            await interaction.respond(choices);
        }
        return;
    }

    if (!interaction.isChatInputCommand()) return;

    const { commandName } = interaction;

    try {
        // ── /ping ────────────────────────────────────────────
        if (commandName === "ping") {
            await interaction.reply("✅ Bot is alive!");
        }

        // ── /info ────────────────────────────────────────────
        else if (commandName === "info") {
            const embed = new EmbedBuilder()
                .setTitle("⚔ Dmg Bot — SkyBlock Damage Optimizer")
                .setDescription("Optimize your Hypixel SkyBlock combat stats and damage.")
                .setColor(BOT_COLOR)
                .addFields(
                    { name: "📋 Commands", value: "`/setstats` — Save your stats\n`/mystats` — View saved stats\n`/damage` — Calculate damage\n`/stats <user>` — View profile\n`/bosses` — Damage vs bosses\n`/info` — This page" },
                    { name: "👨‍💻 Created by", value: "**VectorGOD19** 🏆" },
                    { name: "📌 Requirements", value: "SkyBlock API enabled in Hypixel." }
                )
                .setFooter({ text: "Dmg Bot • by VectorGOD19" });
            await interaction.reply({ embeds: [embed] });
        }

        // ── /setstats ────────────────────────────────────────
        else if (commandName === "setstats") {
            const strength    = interaction.options.getInteger("strength");
            const critChance  = interaction.options.getInteger("crit_chance");
            const critDamage  = interaction.options.getInteger("crit_damage");
            const weaponDmg   = interaction.options.getInteger("weapon_damage");
            const username    = interaction.options.getString("username") || "";

            const data = loadUserStats();
            data[interaction.user.id] = { strength, crit_chance: critChance, crit_damage: critDamage, weapon_damage: weaponDmg, username, discord_name: interaction.user.displayName };
            saveUserStats(data);

            const { base, crit } = calcDamage(strength, critDamage, weaponDmg);
            const embed = new EmbedBuilder()
                .setTitle("✅ Stats Saved!")
                .setColor(0x4caf7d)
                .setDescription("Use `/damage` or `/bosses` without typing stats every time.")
                .addFields(
                    { name: "📊 Saved Stats", value: `⚔ Strength: **${strength}**\n🎯 Crit Chance: **${critChance}%**\n💥 Crit Damage: **${critDamage}%**\n🗡 Weapon DMG: **${weaponDmg}**`, inline: true },
                    { name: "💥 Your Damage", value: `Normal: **${fmt(base)}**\nCrit: **${fmt(crit)}**\nRating: ${damageRating(crit)}`, inline: true }
                )
                .setFooter({ text: "Dmg Bot • by VectorGOD19" });
            await interaction.reply({ embeds: [embed] });
        }

        // ── /mystats ─────────────────────────────────────────
        else if (commandName === "mystats") {
            const data = loadUserStats();
            const s = data[interaction.user.id];
            if (!s) { await interaction.reply({ content: "❌ No stats saved. Use **/setstats** first!", ephemeral: true }); return; }

            const { base, crit } = calcDamage(s.strength, s.crit_damage, s.weapon_damage);
            const tips = [];
            if (s.crit_chance < 80) tips.push(`🎯 Crit Chance ${s.crit_chance}% → need **80%** min.`);
            if (s.crit_damage < 200) tips.push(`💥 Crit Damage ${s.crit_damage}% → aim for **200%+**.`);
            if (s.strength < 300) tips.push(`⚔ Strength ${s.strength} → aim for **300+**.`);

            const embed = new EmbedBuilder()
                .setTitle(`📊 ${interaction.user.displayName}'s Stats`)
                .setColor(BOT_COLOR)
                .addFields(
                    { name: "Combat Stats", value: `⚔ Strength: **${s.strength}**\n🎯 Crit Chance: **${s.crit_chance}%**\n💥 Crit Damage: **${s.crit_damage}%**\n🗡 Weapon DMG: **${s.weapon_damage}**`, inline: true },
                    { name: "💥 Damage", value: `Normal: **${fmt(base)}**\nCrit: **${fmt(crit)}**\nRating: ${damageRating(crit)}`, inline: true }
                );
            if (tips.length) embed.addFields({ name: "💡 Suggestions", value: tips.join("\n") });
            embed.setFooter({ text: "Use /setstats to update • Dmg Bot by VectorGOD19" });
            await interaction.reply({ embeds: [embed] });
        }

        // ── /damage ──────────────────────────────────────────
        else if (commandName === "damage") {
            const saved = loadUserStats()[interaction.user.id] || {};
            const strength    = interaction.options.getInteger("strength")    ?? saved.strength    ?? 0;
            const critChance  = interaction.options.getInteger("crit_chance") ?? saved.crit_chance ?? 30;
            const critDamage  = interaction.options.getInteger("crit_damage") ?? saved.crit_damage ?? 50;
            const weaponDmg   = interaction.options.getInteger("weapon_damage") ?? saved.weapon_damage ?? 100;

            if (!strength && !saved.strength) {
                await interaction.reply({ content: "❌ No stats found. Use **/setstats** first!", ephemeral: true });
                return;
            }

            const { base, crit } = calcDamage(strength, critDamage, weaponDmg);
            const simStr = calcDamage(strength + 50, critDamage, weaponDmg).crit;
            const simCD  = calcDamage(strength, critDamage + 50, weaponDmg).crit;
            const simWep = calcDamage(strength, critDamage, weaponDmg + 100).crit;

            const tips = [];
            if (critChance < 80) tips.push(`🎯 Crit Chance ${critChance}% → need **80%** min. Use Itchy reforge.`);
            if (critDamage < 200) tips.push(`💥 Crit Damage ${critDamage}% → aim for **200%+**. Giant/Fierce reforge.`);
            if (strength < 300) tips.push(`⚔ Strength ${strength} → aim for **300+**. Fierce reforge.`);
            if (!tips.length) tips.push("✅ Stats look solid! Focus on better weapon and armor upgrades.");

            const embed = new EmbedBuilder()
                .setTitle(`💥 Damage Calculator`)
                .setDescription(`Weapon DMG: **${weaponDmg}**`)
                .setColor(BOT_COLOR)
                .addFields(
                    { name: "📊 Your Stats", value: `⚔ Strength: **${strength}**\n🎯 Crit Chance: **${critChance}%**\n💥 Crit Damage: **${critDamage}%**`, inline: true },
                    { name: "🎯 Calculated Damage", value: `Normal: **${fmt(base)}**\nCrit: **${fmt(crit)}**\nRating: ${damageRating(crit)}`, inline: true },
                    { name: "📈 If you improve...", value: `+50 Strength → **${fmt(simStr)}** crit\n+50 Crit Dmg → **${fmt(simCD)}** crit\n+100 Wep Dmg → **${fmt(simWep)}** crit` },
                    { name: "💡 Suggestions", value: tips.join("\n\n") }
                )
                .setFooter({ text: "Dmg Bot • by VectorGOD19" });
            await interaction.reply({ embeds: [embed] });
        }

        // ── /stats ───────────────────────────────────────────
        else if (commandName === "stats") {
            await interaction.deferReply();
            const username = interaction.options.getString("username");
            const profile  = interaction.options.getString("profile");

            const { member, profile: prof, profiles, ign, uuid } = await fetchProfile(username, profile);
            const exp  = member.player_data?.experience || {};
            const skills = {
                combat:      xpToLevel(exp.SKILL_COMBAT      || 0),
                farming:     xpToLevel(exp.SKILL_FARMING     || 0),
                mining:      xpToLevel(exp.SKILL_MINING      || 0),
                fishing:     xpToLevel(exp.SKILL_FISHING     || 0),
                foraging:    xpToLevel(exp.SKILL_FORAGING    || 0),
                enchanting:  xpToLevel(exp.SKILL_ENCHANTING  || 0),
            };
            const skillAvg = (Object.values(skills).reduce((a,b)=>a+b,0) / Object.values(skills).length).toFixed(1);

            const slayers = member.slayer?.slayer_bosses || {};
            const slayerFmt = xp => xp >= 1e6 ? (xp/1e6).toFixed(1)+"M" : xp >= 1000 ? (xp/1000).toFixed(0)+"K" : String(xp);

            const cataXp  = member.dungeons?.dungeon_types?.catacombs?.experience || 0;
            const cataLvl = xpToLevel(cataXp, 50);
            const purse   = member.currencies?.coin_purse || 0;
            const bank    = member.profile?.bank_account  || 0;

            const profileNames = profiles.map(p => p.cute_name).join(" · ");

            const embed = new EmbedBuilder()
                .setTitle(`🍉 ${ign}'s ${prof.cute_name} Profile`)
                .setColor(BOT_COLOR)
                .setThumbnail(`https://mc-heads.net/avatar/${uuid}/64`)
                .addFields(
                    { name: "📚 Skills", value: `⚔ Combat: **${skills.combat}**\n🌾 Farming: **${skills.farming}**\n⛏ Mining: **${skills.mining}**\n🎣 Fishing: **${skills.fishing}**\n🌲 Foraging: **${skills.foraging}**\n📖 Enchanting: **${skills.enchanting}**`, inline: true },
                    { name: "⚔ Slayers (XP)", value: `🧟 Zombie: **${slayerFmt(slayers.zombie?.xp||0)}**\n🕷 Spider: **${slayerFmt(slayers.spider?.xp||0)}**\n🐺 Wolf: **${slayerFmt(slayers.wolf?.xp||0)}**\n🌀 Enderman: **${slayerFmt(slayers.enderman?.xp||0)}**\n🔥 Blaze: **${slayerFmt(slayers.blaze?.xp||0)}**\n🧛 Vampire: **${slayerFmt(slayers.vampire?.xp||0)}**`, inline: true },
                    { name: "📊 Overview", value: `⚗ Skill Avg: **${skillAvg}**\n⚰ Catacombs: **${cataLvl}**\n💰 Purse: **${fmt(purse)}**\n🏦 Bank: **${fmt(bank)}**`, inline: true }
                )
                .setFooter({ text: `Profiles: ${profileNames}  |  /profile to switch  |  by VectorGOD19` });
            await interaction.editReply({ embeds: [embed] });
        }

        // ── /bosses ──────────────────────────────────────────
        else if (commandName === "bosses") {
            const bossKey = interaction.options.getString("boss");
            const boss    = BOSS_DATA[bossKey];
            if (!boss) { await interaction.reply({ content: `❌ Boss **${bossKey}** not found. Type the name and select from the list.`, ephemeral: true }); return; }

            const saved   = loadUserStats()[interaction.user.id] || {};
            const strength  = interaction.options.getInteger("strength")    ?? saved.strength    ?? 0;
            const critDmg   = interaction.options.getInteger("crit_damage") ?? saved.crit_damage ?? 50;
            const weaponDmg = interaction.options.getInteger("weapon_damage") ?? saved.weapon_damage ?? 100;

            const { base, crit } = calcDamage(strength, critDmg, weaponDmg);
            const effHP = boss.hp * (1 + boss.def / 100);
            const hitsToKill = crit > 0 ? Math.ceil(effHP / crit) : "∞";

            const embed = new EmbedBuilder()
                .setTitle(boss.name)
                .setDescription(`**Type:** ${boss.type}`)
                .setColor(BOT_COLOR)
                .addFields(
                    { name: "📊 Boss Stats", value: `❤ HP: **${fmt(boss.hp)}**\n🛡 Defense: **${boss.def}**\n🛡 Effective HP: **${fmt(effHP)}**`, inline: true },
                    { name: "💥 Your Damage vs This Boss", value: `Normal hit: **${fmt(base)}**\nCrit hit: **${fmt(crit)}**\nHits to kill: **~${fmt(hitsToKill)}** crits`, inline: true },
                    { name: "💡 Tips", value: boss.notes },
                    { name: "📐 Damage Formula", value: "```\nBase = (5 + Weapon DMG) × (1 + Strength/100)\nCrit = Base × (1 + Crit DMG/100)\nEff. HP = Boss HP × (1 + Defense/100)\n```" }
                )
                .setFooter({ text: "Dmg Bot • by VectorGOD19 | Use /setstats for your stats" });
            await interaction.reply({ embeds: [embed] });
        }

    } catch (err) {
        console.error("Command error:", err.message);
        const msg = `❌ ${err.message}`;
        if (interaction.deferred) await interaction.editReply(msg);
        else await interaction.reply({ content: msg, ephemeral: true });
    }
});

// ── Start ──────────────────────────────────────────────────────
client.login(TOKEN);
