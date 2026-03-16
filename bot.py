import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import math

# ── Setup ──────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SKYCRYPT_API = "https://sky.shiiyu.moe/api/v2/profile"
BOT_COLOR    = 0xe84040   # red like combat

# ── Ready ──────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Sync error: {e}")

# ── Helpers ────────────────────────────────────────────────────
def fmt(val):
    if val is None:
        return "—"
    n = float(val)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n)) if n == int(n) else str(round(n, 1))

async def fetch_profile(username: str, profile_name: str = None):
    """Fetch SkyCrypt data and return (member_data, profile, all_profiles, ign) or None on error."""
    url = f"{SKYCRYPT_API}/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None, "Player not found. Check username and make sure `/api new` is enabled in Hypixel."
            data = await resp.json()

    if "error" in data:
        return None, data["error"]

    profiles = data.get("profiles", {})
    if not profiles:
        return None, "No SkyBlock profiles found."

    if profile_name:
        profile = next((p for p in profiles.values() if p.get("cute_name", "").lower() == profile_name.lower()), None)
        if not profile:
            names = ", ".join(p.get("cute_name", "?") for p in profiles.values())
            return None, f"Profile **{profile_name}** not found. Available: {names}"
    else:
        profile = next((p for p in profiles.values() if p.get("selected")), None)
        if not profile:
            profile = max(profiles.values(), key=lambda p: p.get("last_save", 0))

    members = profile.get("members", {})
    player_uuid = next(
        (uuid for uuid, m in members.items() if (m.get("username") or "").lower() == username.lower()),
        next(iter(members), None)
    )

    if not player_uuid:
        return None, "Could not find player data inside profile."

    member = members[player_uuid]
    ign    = member.get("username", username)
    return (member, profile, profiles, ign), None

def calc_damage(stats: dict, weapon_dmg: int = 100):
    """
    SkyBlock damage formula:
      Base hit  = (5 + weapon_damage) × (1 + Strength / 100)
      Crit hit  = Base hit × (1 + Crit Damage / 100)
    Returns (base_hit, crit_hit)
    """
    strength   = stats.get("strength",    0)
    crit_dmg   = stats.get("crit_damage", 50)
    base  = (5 + weapon_dmg) * (1 + strength / 100)
    crit  = base * (1 + crit_dmg / 100)
    return int(base), int(crit)

def damage_rating(crit: int) -> str:
    if crit >= 2_000_000: return "🔴 God Roll"
    if crit >= 500_000:   return "🟠 Endgame"
    if crit >= 100_000:   return "🟡 Late Game"
    if crit >= 30_000:    return "🟢 Mid Game"
    if crit >= 5_000:     return "🔵 Early Mid"
    return "⚪ Early Game"

def profile_footer(profiles: dict, current_id: str) -> str:
    names = [p.get("cute_name", "?") for p in profiles.values()]
    return f"Profiles: {' · '.join(names)}  |  Use /profile to switch  |  by VectorGOD19"

# ── /stats ─────────────────────────────────────────────────────
@bot.tree.command(name="stats", description="View a player's SkyBlock combat stats")
@app_commands.describe(username="Minecraft username", profile="Profile name (optional, e.g. Watermelon)")
async def stats_cmd(interaction: discord.Interaction, username: str, profile: str = None):
    await interaction.response.defer()

    result, err = await fetch_profile(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return

    member, prof, all_profiles, ign = result
    s      = member.get("stats", {})
    pname  = prof.get("cute_name", "?")

    embed = discord.Embed(
        title=f"⚔ {ign}'s {pname} Profile",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")

    # ── Combat stats grid (3 columns) ──
    col1 = (
        f"❤ **Health**\n{fmt(s.get('health', 0))}\n\n"
        f"🛡 **Defense**\n{fmt(s.get('defense', 0))}\n\n"
        f"⚔ **Strength**\n{fmt(s.get('strength', 0))}\n\n"
        f"✨ **Intelligence**\n{fmt(s.get('intelligence', 0))}"
    )
    col2 = (
        f"🎯 **Crit Chance**\n{fmt(s.get('crit_chance', 0))}%\n\n"
        f"💥 **Crit Damage**\n{fmt(s.get('crit_damage', 0))}%\n\n"
        f"⚡ **Attack Speed**\n{fmt(s.get('attack_speed', 0))}%\n\n"
        f"🔥 **Ferocity**\n{fmt(s.get('ferocity', 0))}"
    )
    col3 = (
        f"🏃 **Speed**\n{fmt(s.get('speed', 0))}\n\n"
        f"🍀 **Magic Find**\n{fmt(s.get('magic_find', 0))}\n\n"
        f"🎣 **Sea Creature**\n{fmt(s.get('sea_creature_chance', 0))}%\n\n"
        f"🐾 **Pet Luck**\n{fmt(s.get('pet_luck', 0))}"
    )

    embed.add_field(name="\u200b", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.add_field(name="\u200b", value=col3, inline=True)

    # ── Quick damage preview ──
    base, crit = calc_damage(s)
    rating = damage_rating(crit)
    embed.add_field(
        name="⚔ Damage Preview (100 dmg weapon)",
        value=f"Normal: **{fmt(base)}** | Crit: **{fmt(crit)}** | {rating}",
        inline=False
    )

    embed.set_footer(text=profile_footer(all_profiles, prof.get("profile_id", "")))
    await interaction.followup.send(embed=embed)


# ── /damage ────────────────────────────────────────────────────
@bot.tree.command(name="damage", description="Calculate your SkyBlock damage and what to improve")
@app_commands.describe(username="Minecraft username", weapon_damage="Your weapon's damage stat (default 100)", profile="Profile name (optional)")
async def damage_cmd(interaction: discord.Interaction, username: str, weapon_damage: int = 100, profile: str = None):
    await interaction.response.defer()

    result, err = await fetch_profile(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return

    member, prof, all_profiles, ign = result
    s = member.get("stats", {})

    strength  = s.get("strength",    0)
    crit_c    = s.get("crit_chance",  0)
    crit_d    = s.get("crit_damage", 50)
    ferocity  = s.get("ferocity",    0)

    base, crit = calc_damage(s, weapon_damage)
    rating     = damage_rating(crit)

    # ── What to improve ──
    tips = []

    if crit_c < 80:
        needed = 80 - crit_c
        tips.append(f"🎯 **Crit Chance** is {fmt(crit_c)}% — aim for **80%** minimum (+{round(needed,1)}% needed). Use Crit potions, Itchy reforge, or Obsidian Chestplate.")
    if crit_d < 200:
        tips.append(f"💥 **Crit Damage** is {fmt(crit_d)}% — aim for **200%+**. Reforge armor to **Giant** or **Fierce**, upgrade Talismans.")
    if strength < 300:
        tips.append(f"⚔ **Strength** is {fmt(strength)} — aim for **300+**. Reforge to **Fierce/Giant**, use Strength potions.")
    if ferocity < 10:
        tips.append(f"🔥 **Ferocity** is {fmt(ferocity)} — even a bit helps. Get Duplex pet perk or Raider's Axe ability.")
    if crit_c >= 80 and crit_d >= 200 and strength >= 300:
        tips.append("✅ Your combat stats look solid! Focus on upgrading your weapon damage stat and getting better armor.")

    embed = discord.Embed(
        title=f"💥 Damage Calculator — {ign}",
        description=f"Profile: **{prof.get('cute_name', '?')}** | Weapon DMG stat: **{weapon_damage}**",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")

    embed.add_field(
        name="📊 Your Stats",
        value=(
            f"⚔ Strength: **{fmt(strength)}**\n"
            f"🎯 Crit Chance: **{fmt(crit_c)}%**\n"
            f"💥 Crit Damage: **{fmt(crit_d)}%**\n"
            f"🔥 Ferocity: **{fmt(ferocity)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="🎯 Calculated Damage",
        value=(
            f"Normal hit: **{fmt(base)}**\n"
            f"Crit hit: **{fmt(crit)}**\n"
            f"Rating: {rating}"
        ),
        inline=True
    )

    # Simulate upgrades
    sim_str   = int((5 + weapon_damage) * (1 + (strength + 50) / 100) * (1 + crit_d / 100))
    sim_cd    = int((5 + weapon_damage) * (1 + strength / 100) * (1 + (crit_d + 50) / 100))
    sim_wep   = int((5 + weapon_damage + 100) * (1 + strength / 100) * (1 + crit_d / 100))

    embed.add_field(
        name="📈 If you improve...",
        value=(
            f"+50 Strength → **{fmt(sim_str)}** crit\n"
            f"+50 Crit Dmg → **{fmt(sim_cd)}** crit\n"
            f"+100 Wep Dmg → **{fmt(sim_wep)}** crit"
        ),
        inline=False
    )

    if tips:
        embed.add_field(
            name="💡 Top Suggestions",
            value="\n\n".join(tips[:3]),
            inline=False
        )

    embed.set_footer(text=profile_footer(all_profiles, prof.get("profile_id", "")))
    await interaction.followup.send(embed=embed)


# ── /profile ───────────────────────────────────────────────────
@bot.tree.command(name="profile", description="View stats for a specific SkyBlock profile")
@app_commands.describe(username="Minecraft username", profile="Profile name (e.g. Watermelon)")
async def profile_cmd(interaction: discord.Interaction, username: str, profile: str):
    await interaction.response.defer()
    # Reuse stats logic with forced profile name
    interaction.extras["forced_profile"] = profile
    result, err = await fetch_profile(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return

    member, prof, all_profiles, ign = result
    s = member.get("stats", {})

    embed = discord.Embed(title=f"⚔ {ign}'s {prof.get('cute_name','?')} Profile", color=BOT_COLOR)
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")

    col1 = f"❤ **Health**\n{fmt(s.get('health',0))}\n\n🛡 **Defense**\n{fmt(s.get('defense',0))}\n\n⚔ **Strength**\n{fmt(s.get('strength',0))}\n\n✨ **Intelligence**\n{fmt(s.get('intelligence',0))}"
    col2 = f"🎯 **Crit Chance**\n{fmt(s.get('crit_chance',0))}%\n\n💥 **Crit Damage**\n{fmt(s.get('crit_damage',0))}%\n\n⚡ **Attack Speed**\n{fmt(s.get('attack_speed',0))}%\n\n🔥 **Ferocity**\n{fmt(s.get('ferocity',0))}"
    col3 = f"🏃 **Speed**\n{fmt(s.get('speed',0))}\n\n🍀 **Magic Find**\n{fmt(s.get('magic_find',0))}\n\n🎣 **Sea Creature**\n{fmt(s.get('sea_creature_chance',0))}%\n\n🐾 **Pet Luck**\n{fmt(s.get('pet_luck',0))}"

    embed.add_field(name="\u200b", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.add_field(name="\u200b", value=col3, inline=True)

    base, crit = calc_damage(s)
    embed.add_field(name="⚔ Damage Preview (100 dmg weapon)", value=f"Normal: **{fmt(base)}** | Crit: **{fmt(crit)}** | {damage_rating(crit)}", inline=False)
    embed.set_footer(text=profile_footer(all_profiles, prof.get("profile_id","")))
    await interaction.followup.send(embed=embed)


# ── /info ──────────────────────────────────────────────────────
@bot.tree.command(name="info", description="About this bot")
async def info_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚔ Dmg Bot — SkyBlock Damage Optimizer",
        description="A bot to view and optimize your Hypixel SkyBlock combat stats and damage.",
        color=BOT_COLOR
    )
    embed.add_field(
        name="📋 Commands",
        value=(
            "`/stats <user>` — View combat stats\n"
            "`/damage <user> [weapon_dmg]` — Calculate damage + suggestions\n"
            "`/profile <user> <profile>` — View a specific profile\n"
            "`/info` — This page"
        ),
        inline=False
    )
    embed.add_field(
        name="📌 Requirements",
        value="Players must have API enabled in Hypixel.\nRun `/api new` in-game to enable it.",
        inline=False
    )
    embed.add_field(
        name="👨‍💻 Created by",
        value="**VectorGOD19** 🏆\n*Made for the SkyBlock grind*",
        inline=False
    )
    embed.add_field(
        name="📡 Data source",
        value="[SkyCrypt](https://sky.shiiyu.moe) — Hypixel SkyBlock stats site",
        inline=False
    )
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.response.send_message(embed=embed)


# ── Run ────────────────────────────────────────────────────────
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("❌ DISCORD_TOKEN not set!")
else:
    bot.run(token)
