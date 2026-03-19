import discord
from discord import app_commands
import aiohttp
import os
import json
import zipfile
import io
 
# ── Setup ──────────────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)
 
HYPIXEL_API  = "https://api.hypixel.net/v2"
MOJANG_API   = "https://api.mojang.com/users/profiles/minecraft"
BOT_COLOR    = 0xe84040
 
# ── Ready ──────────────────────────────────────────────────────
NEU_DATA = {}  # loaded on startup
 
async def load_neu_data():
    """Download NEU repo constants (reforges, etc) on startup."""
    global NEU_DATA
    neu_zip_url = "https://github.com/NotEnoughUpdates/NotEnoughUpdates-REPO/archive/refs/heads/master.zip"
    print("📦 Downloading NEU data...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(neu_zip_url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    print(f"❌ Failed to download NEU data: {resp.status}")
                    return
                data = await resp.read()
 
        zf = zipfile.ZipFile(io.BytesIO(data))
        constants = {}
 
        for name in zf.namelist():
            # Only load constants folder JSONs (small, fast)
            if "/constants/" in name and name.endswith(".json"):
                short = name.split("/constants/")[1]
                try:
                    constants[short] = json.loads(zf.read(name))
                except:
                    pass
 
        NEU_DATA["constants"] = constants
        print(f"✅ Loaded {len(constants)} NEU constant files")
 
    except Exception as e:
        print(f"❌ NEU load error: {e}")
 
@client.event
async def on_ready():
    print(f"✅ Bot online: {client.user}")
    await load_neu_data()
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Sync error: {e}")
 
# ── Helpers ────────────────────────────────────────────────────
def fmt(val):
    if val is None: return "—"
    n = float(val)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n)) if n == int(n) else str(round(n, 1))
 
def calc_damage(strength=0, crit_damage=50, weapon_dmg=100):
    base = (5 + weapon_dmg) * (1 + strength / 100)
    crit = base * (1 + crit_damage / 100)
    return int(base), int(crit)
 
def damage_rating(crit):
    if crit >= 2_000_000: return "🔴 God Roll"
    if crit >= 500_000:   return "🟠 Endgame"
    if crit >= 100_000:   return "🟡 Late Game"
    if crit >= 30_000:    return "🟢 Mid Game"
    if crit >= 5_000:     return "🔵 Early Mid"
    return "⚪ Early Game"
 
def xp_to_level(xp, max_level=60):
    """Convert skill XP to level using SkyBlock XP table."""
    XP_TABLE = [
        0, 50, 175, 375, 675, 1175, 1925, 2925, 4425, 6425,
        9925, 14925, 22425, 32425, 47425, 67425, 97425, 147425,
        222425, 322425, 522425, 822425, 1222425, 1722425, 2322425,
        3022425, 3822425, 4722425, 5722425, 6822425, 8022425,
        9322425, 10722425, 12222425, 13822425, 15522425, 17322425,
        19222425, 21222425, 23322425, 25522425, 27822425, 30222425,
        32722425, 35322425, 38022425, 40822425, 43722425, 46722425,
        49922425, 53222425, 56722425, 60322425, 64022425, 67822425,
        71722425, 75722425, 79822425, 84022425, 88322425
    ]
    for i, req in enumerate(XP_TABLE):
        if xp < req:
            return max(0, i - 1)
    return max_level
 
async def get_uuid(username: str, session: aiohttp.ClientSession):
    """Get player UUID from Mojang API."""
    async with session.get(f"{MOJANG_API}/{username}") as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("id")
 
async def fetch(username: str, profile_name: str = None):
    """Fetch player data from Hypixel API."""
    api_key = os.environ.get("HYPIXEL_API_KEY")
    if not api_key:
        return None, "HYPIXEL_API_KEY not set in environment variables."
 
    headers = {"API-Key": api_key}
 
    async with aiohttp.ClientSession() as session:
        # Step 1: Get UUID from Mojang
        uuid = await get_uuid(username, session)
        if not uuid:
            return None, f"Player **{username}** not found. Check the username."
 
        print(f"UUID for {username}: {uuid}")
 
        # Step 2: Get SkyBlock profiles from Hypixel
        async with session.get(
            f"{HYPIXEL_API}/skyblock/profiles",
            headers=headers,
            params={"uuid": uuid}
        ) as resp:
            print(f"Hypixel API status: {resp.status}")
            if resp.status == 403:
                return None, "Invalid API key. Check the HYPIXEL_API_KEY variable in Railway."
            if resp.status == 429:
                return None, "Rate limited. Try again in a minute."
            if resp.status != 200:
                return None, f"Hypixel API error (HTTP {resp.status})."
            data = await resp.json()
 
    if not data.get("success"):
        return None, f"API returned error: {data.get('cause', 'Unknown error')}"
 
    profiles = data.get("profiles")
    if not profiles:
        return None, f"No SkyBlock profiles found for **{username}**. Make sure they've played SkyBlock."
 
    # Pick profile
    if profile_name:
        profile = next((p for p in profiles if p.get("cute_name", "").lower() == profile_name.lower()), None)
        if not profile:
            names = ", ".join(p.get("cute_name", "?") for p in profiles)
            return None, f"Profile **{profile_name}** not found. Available: {names}"
    else:
        profile = next((p for p in profiles if p.get("selected")), None) or profiles[0]
 
    member = profile.get("members", {}).get(uuid)
    if not member:
        return None, "Could not find your data inside the profile."
 
    return (member, profile, profiles, username, uuid), None
 
def parse_stats(member: dict):
    """Extract useful stats from member data."""
    # SkyBlock stores skill XP, not final stats directly
    # We calculate what we can from the raw data
    exp = member.get("player_data", {}).get("experience", {})
 
    skills = {
        "combat":   xp_to_level(exp.get("SKILL_COMBAT",   0)),
        "farming":  xp_to_level(exp.get("SKILL_FARMING",  0)),
        "fishing":  xp_to_level(exp.get("SKILL_FISHING",  0)),
        "mining":   xp_to_level(exp.get("SKILL_MINING",   0)),
        "foraging": xp_to_level(exp.get("SKILL_FORAGING", 0)),
        "enchanting": xp_to_level(exp.get("SKILL_ENCHANTING", 0)),
        "alchemy":  xp_to_level(exp.get("SKILL_ALCHEMY",  0)),
        "taming":   xp_to_level(exp.get("SKILL_TAMING",   0)),
    }
 
    # Skill average
    valid = [v for v in skills.values() if v > 0]
    skill_avg = round(sum(valid) / len(valid), 1) if valid else 0
 
    # Slayer levels
    slayers = member.get("slayer", {}).get("slayer_bosses", {})
    slayer_info = {}
    for name in ["zombie", "spider", "wolf", "enderman", "blaze", "vampire"]:
        xp = slayers.get(name, {}).get("xp", 0)
        slayer_info[name] = xp
 
    # Dungeons
    dungeon_data = member.get("dungeons", {}).get("dungeon_types", {}).get("catacombs", {})
    cata_xp      = dungeon_data.get("experience", 0)
    cata_level   = xp_to_level(cata_xp, max_level=50)
 
    # Stats (base combat stats)
    raw_stats = member.get("player_stats", {})
 
    # Networth approximation from purse
    purse = member.get("currencies", {}).get("coin_purse", 0)
    bank  = member.get("profile", {}).get("bank_account", 0)
 
    return {
        "skills":     skills,
        "skill_avg":  skill_avg,
        "slayers":    slayer_info,
        "cata_level": cata_level,
        "cata_xp":    cata_xp,
        "purse":      purse,
        "bank":       bank,
        "raw_stats":  raw_stats,
    }
 
# ── /ping ──────────────────────────────────────────────────────
@tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Bot is alive!")
 
# ── /info ──────────────────────────────────────────────────────
@tree.command(name="info", description="About this bot")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔ Dmg Bot — SkyBlock Damage Optimizer",
        description="Optimize your Hypixel SkyBlock combat stats and damage.",
        color=BOT_COLOR
    )
    embed.add_field(name="📋 Commands", value=(
        "`/ping` — Test the bot\n"
        "`/stats <user>` — View skills, slayers & profile overview\n"
        "`/damage <user> [weapon_dmg]` — Calculate damage + suggestions\n"
        "`/profile <user> <profile>` — View a specific profile\n"
        "`/info` — This page"
    ), inline=False)
    embed.add_field(name="👨‍💻 Created by", value="**VectorGOD19** 🏆", inline=False)
    embed.add_field(name="📌 Data source", value="Official Hypixel API v2", inline=False)
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.response.send_message(embed=embed)
 
# ── /stats ─────────────────────────────────────────────────────
@tree.command(name="stats", description="View a player's SkyBlock profile overview")
@app_commands.describe(username="Minecraft username", profile="Profile name (optional, e.g. Watermelon)")
async def stats(interaction: discord.Interaction, username: str, profile: str = None):
    await interaction.response.defer()
 
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return
 
    member, prof, all_profiles, ign, uuid = result
    s = parse_stats(member)
 
    embed = discord.Embed(
        title=f"🍉 {ign}'s {prof.get('cute_name', '?')} Profile",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{uuid}/64")
 
    # Skills
    sk = s["skills"]
    embed.add_field(name="📚 Skills", value=(
        f"⚔ Combat: **{sk['combat']}**\n"
        f"🌾 Farming: **{sk['farming']}**\n"
        f"⛏ Mining: **{sk['mining']}**\n"
        f"🎣 Fishing: **{sk['fishing']}**\n"
        f"🌲 Foraging: **{sk['foraging']}**\n"
        f"📖 Enchanting: **{sk['enchanting']}**"
    ), inline=True)
 
    # Slayers
    sl = s["slayers"]
    def slayer_fmt(xp):
        if xp >= 1_000_000: return f"{xp/1_000_000:.1f}M"
        if xp >= 1_000:     return f"{xp/1_000:.0f}K"
        return str(xp)
 
    embed.add_field(name="⚔ Slayers (XP)", value=(
        f"🧟 Zombie: **{slayer_fmt(sl.get('zombie',0))}**\n"
        f"🕷 Spider: **{slayer_fmt(sl.get('spider',0))}**\n"
        f"🐺 Wolf: **{slayer_fmt(sl.get('wolf',0))}**\n"
        f"🌀 Enderman: **{slayer_fmt(sl.get('enderman',0))}**\n"
        f"🔥 Blaze: **{slayer_fmt(sl.get('blaze',0))}**\n"
        f"🧛 Vampire: **{slayer_fmt(sl.get('vampire',0))}**"
    ), inline=True)
 
    # Overview
    embed.add_field(name="📊 Overview", value=(
        f"⚗ Skill Avg: **{s['skill_avg']}**\n"
        f"⚰ Catacombs: **{s['cata_level']}**\n"
        f"💰 Purse: **{fmt(s['purse'])}**\n"
        f"🏦 Bank: **{fmt(s['bank'])}**"
    ), inline=True)
 
    # Damage preview (estimated from combat level)
    combat_lvl = sk["combat"]
    est_strength = combat_lvl * 4
    _, crit = calc_damage(strength=est_strength, crit_damage=100)
    embed.add_field(
        name="⚔ Estimated Damage (use /damage for accurate calc)",
        value=f"Crit ≈ **{fmt(crit)}** | {damage_rating(crit)}",
        inline=False
    )
 
    names = " · ".join(p.get("cute_name", "?") for p in all_profiles)
    embed.set_footer(text=f"Profiles: {names}  |  /profile to switch  |  by VectorGOD19")
    await interaction.followup.send(embed=embed)
 
# ── /damage ────────────────────────────────────────────────────
@tree.command(name="damage", description="Calculate your damage and what to improve")
@app_commands.describe(
    username="Minecraft username",
    weapon_damage="Your weapon's damage stat (default 100)",
    strength="Your total Strength stat",
    crit_damage="Your total Crit Damage %",
    crit_chance="Your total Crit Chance %",
    profile="Profile name (optional)"
)
async def damage(
    interaction: discord.Interaction,
    username: str,
    weapon_damage: int = 100,
    strength: int = 0,
    crit_damage: int = 50,
    crit_chance: int = 30,
    profile: str = None
):
    await interaction.response.defer()
 
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return
 
    member, prof, all_profiles, ign, uuid = result
 
    base, crit = calc_damage(strength, crit_damage, weapon_damage)
 
    embed = discord.Embed(
        title=f"💥 Damage Calculator — {ign}",
        description=f"Profile: **{prof.get('cute_name','?')}** | Weapon DMG: **{weapon_damage}**",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{uuid}/64")
 
    embed.add_field(name="📊 Your Stats", value=(
        f"⚔ Strength: **{fmt(strength)}**\n"
        f"🎯 Crit Chance: **{fmt(crit_chance)}%**\n"
        f"💥 Crit Damage: **{fmt(crit_damage)}%**\n"
    ), inline=True)
 
    embed.add_field(name="🎯 Calculated Damage", value=(
        f"Normal hit: **{fmt(base)}**\n"
        f"Crit hit: **{fmt(crit)}**\n"
        f"Rating: {damage_rating(crit)}"
    ), inline=True)
 
    # Simulate improvements
    sim_str = int((5 + weapon_damage) * (1 + (strength + 50) / 100) * (1 + crit_damage / 100))
    sim_cd  = int((5 + weapon_damage) * (1 + strength / 100) * (1 + (crit_damage + 50) / 100))
    sim_wep = int((5 + weapon_damage + 100) * (1 + strength / 100) * (1 + crit_damage / 100))
 
    embed.add_field(name="📈 If you improve...", value=(
        f"+50 Strength → **{fmt(sim_str)}** crit\n"
        f"+50 Crit Dmg → **{fmt(sim_cd)}** crit\n"
        f"+100 Wep Dmg → **{fmt(sim_wep)}** crit"
    ), inline=False)
 
    tips = []
    if crit_chance < 80:
        tips.append(f"🎯 **Crit Chance** {crit_chance}% → need **80%** min. Use Itchy reforge or Crit potions.")
    if crit_damage < 200:
        tips.append(f"💥 **Crit Damage** {crit_damage}% → aim for **200%+**. Reforge armor to Giant/Fierce.")
    if strength < 300:
        tips.append(f"⚔ **Strength** {strength} → aim for **300+**. Fierce reforge, Strength potions.")
    if not tips:
        tips.append("✅ Stats look solid! Focus on better weapon damage and armor upgrades.")
 
    embed.add_field(name="💡 Suggestions", value="\n\n".join(tips[:3]), inline=False)
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.followup.send(embed=embed)
 
# ── /profile ───────────────────────────────────────────────────
@tree.command(name="profile", description="View stats for a specific SkyBlock profile")
@app_commands.describe(username="Minecraft username", profile="Profile name (e.g. Watermelon)")
async def profile_cmd(interaction: discord.Interaction, username: str, profile: str):
    await interaction.response.defer()
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return
 
    member, prof, all_profiles, ign, uuid = result
    s = parse_stats(member)
    sk = s["skills"]
 
    embed = discord.Embed(
        title=f"🍉 {ign}'s {prof.get('cute_name','?')} Profile",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{uuid}/64")
 
    embed.add_field(name="📚 Skills", value=(
        f"⚔ Combat: **{sk['combat']}**\n"
        f"🌾 Farming: **{sk['farming']}**\n"
        f"⛏ Mining: **{sk['mining']}**\n"
        f"🎣 Fishing: **{sk['fishing']}**\n"
        f"🌲 Foraging: **{sk['foraging']}**\n"
        f"📖 Enchanting: **{sk['enchanting']}**"
    ), inline=True)
 
    sl = s["slayers"]
    def slayer_fmt(xp):
        if xp >= 1_000_000: return f"{xp/1_000_000:.1f}M"
        if xp >= 1_000:     return f"{xp/1_000:.0f}K"
        return str(xp)
 
    embed.add_field(name="⚔ Slayers", value=(
        f"🧟 Zombie: **{slayer_fmt(sl.get('zombie',0))}**\n"
        f"🕷 Spider: **{slayer_fmt(sl.get('spider',0))}**\n"
        f"🐺 Wolf: **{slayer_fmt(sl.get('wolf',0))}**\n"
        f"🌀 Enderman: **{slayer_fmt(sl.get('enderman',0))}**\n"
        f"🔥 Blaze: **{slayer_fmt(sl.get('blaze',0))}**\n"
        f"🧛 Vampire: **{slayer_fmt(sl.get('vampire',0))}**"
    ), inline=True)
 
    embed.add_field(name="📊 Overview", value=(
        f"⚗ Skill Avg: **{s['skill_avg']}**\n"
        f"⚰ Catacombs: **{s['cata_level']}**\n"
        f"💰 Purse: **{fmt(s['purse'])}**\n"
        f"🏦 Bank: **{fmt(s['bank'])}**"
    ), inline=True)
 
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.followup.send(embed=embed)
 
 
 
# ── /rawstats — debug command ──────────────────────────────────
@tree.command(name="rawstats", description="Show all raw combat stats from the API")
@app_commands.describe(username="Minecraft username", profile="Profile name (optional)")
async def rawstats(interaction: discord.Interaction, username: str, profile: str = None):
    await interaction.response.defer()
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send("❌ " + err, ephemeral=True)
        return
    member, prof, all_profiles, ign, uuid = result
    top_keys = list(member.keys())
    msg1 = "**Top-level keys:** " + ", ".join(top_keys)
    locations = {
        "member.stats":        member.get("stats", {}),
        "member.player_stats": member.get("player_stats", {}),
        "member.player_data":  member.get("player_data", {}),
    }
    parts = [msg1]
    for name, data in locations.items():
        if data and isinstance(data, dict):
            preview = str(dict(list(data.items())[:10]))[:500]
            parts.append("**" + name + ":**" + chr(10) + "```" + preview + "```")
    full = chr(10).join(parts)
    chunks = [full[i:i+1900] for i in range(0, len(full), 1900)]
    for chunk in chunks:
        await interaction.followup.send(chunk)
 
 
# ── /neutest — verify NEU data loaded ─────────────────────────
@tree.command(name="neutest", description="Check if NEU data loaded correctly")
async def neutest(interaction: discord.Interaction):
    constants = NEU_DATA.get("constants", {})
    if not constants:
        await interaction.response.send_message("❌ NEU data not loaded yet. Try again in a minute.")
        return
    files = list(constants.keys())
    preview = ", ".join(files[:20])
    # Check if reforge data exists
    reforge_file = next((f for f in files if "reforge" in f.lower()), None)
    reforge_info = "✅ Found: " + reforge_file if reforge_file else "❌ Not found"
    await interaction.response.send_message(
        f"✅ **NEU Data Loaded!**\n"
        f"Files: **{len(files)}**\n"
        f"Reforge data: {reforge_info}\n"
        f"First 20 files: `{preview}`"
    )
 
# ── Run ────────────────────────────────────────────────────────
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("❌ DISCORD_TOKEN not set!")
else:
    client.run(token)
 
