import discord
from discord import app_commands
import aiohttp
import os
 
# ── Setup ──────────────────────────────────────────────────────
intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)
 
SKYCRYPT_API = "https://sky.shiiyu.moe/api/v2/profile"
BOT_COLOR    = 0xe84040
 
# ── Ready ──────────────────────────────────────────────────────
@client.event
async def on_ready():
    print(f"✅ Bot online: {client.user}")
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Sync error: {e}")
 
# ── /ping — test command ───────────────────────────────────────
@tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Bot is alive! Try `/stats <username>` now.")
 
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
        "`/stats <user>` — View combat stats\n"
        "`/damage <user> [weapon_dmg]` — Calculate damage + suggestions\n"
        "`/profile <user> <profile>` — View a specific profile\n"
        "`/info` — This page"
    ), inline=False)
    embed.add_field(name="👨‍💻 Created by", value="**VectorGOD19** 🏆", inline=False)
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.response.send_message(embed=embed)
 
# ── Helpers ────────────────────────────────────────────────────
def fmt(val):
    if val is None: return "—"
    n = float(val)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}K"
    return str(int(n)) if n == int(n) else str(round(n, 1))
 
def calc_damage(s, weapon_dmg=100):
    strength = s.get("strength", 0)
    crit_d   = s.get("crit_damage", 50)
    base = (5 + weapon_dmg) * (1 + strength / 100)
    crit = base * (1 + crit_d / 100)
    return int(base), int(crit)
 
def damage_rating(crit):
    if crit >= 2_000_000: return "🔴 God Roll"
    if crit >= 500_000:   return "🟠 Endgame"
    if crit >= 100_000:   return "🟡 Late Game"
    if crit >= 30_000:    return "🟢 Mid Game"
    if crit >= 5_000:     return "🔵 Early Mid"
    return "⚪ Early Game"
 
async def fetch(username, profile_name=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://sky.shiiyu.moe/"
    }
    urls_to_try = [
        f"https://sky.shiiyu.moe/api/v2/profile/{username}",
        f"https://api.slothpixel.me/api/skyblock/profile/{username}",
    ]
    data = None
    for url in urls_to_try:
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    print(f"Trying {url} -> status {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        break
                    else:
                        print(f"Failed {resp.status}, trying next...")
        except Exception as e:
            print(f"Error with {url}: {e}")
            continue
    if not data:
        return None, f"Could not load data for **{username}**. Make sure the SkyBlock API is enabled: SkyBlock Menu -> Settings -> API Settings -> enable all toggles."
 
    if "error" in data:
        return None, data["error"]
 
    profiles = data.get("profiles", {})
    if not profiles:
        return None, "No SkyBlock profiles found."
 
    if profile_name:
        prof = next((p for p in profiles.values() if p.get("cute_name","").lower() == profile_name.lower()), None)
        if not prof:
            names = ", ".join(p.get("cute_name","?") for p in profiles.values())
            return None, f"Profile **{profile_name}** not found. Available: {names}"
    else:
        prof = next((p for p in profiles.values() if p.get("selected")), None)
        if not prof:
            prof = max(profiles.values(), key=lambda p: p.get("last_save", 0))
 
    members = prof.get("members", {})
    uuid = next((u for u, m in members.items() if (m.get("username") or "").lower() == username.lower()), next(iter(members), None))
    if not uuid:
        return None, "Could not find player inside profile."
 
    member = members[uuid]
    ign    = member.get("username", username)
    return (member, prof, profiles, ign), None
 
# ── /stats ─────────────────────────────────────────────────────
@tree.command(name="stats", description="View a player's SkyBlock combat stats")
@app_commands.describe(username="Minecraft username", profile="Profile name (optional, e.g. Watermelon)")
async def stats(interaction: discord.Interaction, username: str, profile: str = None):
    await interaction.response.defer()
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return
 
    member, prof, all_profiles, ign = result
    s = member.get("stats", {})
 
    embed = discord.Embed(title=f"⚔ {ign}'s {prof.get('cute_name','?')} Profile", color=BOT_COLOR)
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")
 
    col1 = f"❤ **Health**\n{fmt(s.get('health'))}\n\n🛡 **Defense**\n{fmt(s.get('defense'))}\n\n⚔ **Strength**\n{fmt(s.get('strength'))}\n\n✨ **Intelligence**\n{fmt(s.get('intelligence'))}"
    col2 = f"🎯 **Crit Chance**\n{fmt(s.get('crit_chance'))}%\n\n💥 **Crit Damage**\n{fmt(s.get('crit_damage'))}%\n\n⚡ **Attack Speed**\n{fmt(s.get('attack_speed'))}%\n\n🔥 **Ferocity**\n{fmt(s.get('ferocity'))}"
    col3 = f"🏃 **Speed**\n{fmt(s.get('speed'))}\n\n🍀 **Magic Find**\n{fmt(s.get('magic_find'))}\n\n🎣 **Sea Creature**\n{fmt(s.get('sea_creature_chance'))}%\n\n🐾 **Pet Luck**\n{fmt(s.get('pet_luck'))}"
 
    embed.add_field(name="\u200b", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.add_field(name="\u200b", value=col3, inline=True)
 
    base, crit = calc_damage(s)
    embed.add_field(name="⚔ Damage Preview (100 dmg weapon)", value=f"Normal: **{fmt(base)}** | Crit: **{fmt(crit)}** | {damage_rating(crit)}", inline=False)
 
    names = " · ".join(p.get("cute_name","?") for p in all_profiles.values())
    embed.set_footer(text=f"Profiles: {names}  |  /profile to switch  |  by VectorGOD19")
    await interaction.followup.send(embed=embed)
 
# ── /damage ────────────────────────────────────────────────────
@tree.command(name="damage", description="Calculate your damage and what to improve")
@app_commands.describe(username="Minecraft username", weapon_damage="Weapon damage stat (default 100)", profile="Profile name (optional)")
async def damage(interaction: discord.Interaction, username: str, weapon_damage: int = 100, profile: str = None):
    await interaction.response.defer()
    result, err = await fetch(username, profile)
    if err:
        await interaction.followup.send(f"❌ {err}", ephemeral=True)
        return
 
    member, prof, all_profiles, ign = result
    s        = member.get("stats", {})
    strength = s.get("strength", 0)
    crit_c   = s.get("crit_chance", 0)
    crit_d   = s.get("crit_damage", 50)
    ferocity = s.get("ferocity", 0)
 
    base, crit = calc_damage(s, weapon_damage)
 
    embed = discord.Embed(
        title=f"💥 Damage Calculator — {ign}",
        description=f"Profile: **{prof.get('cute_name','?')}** | Weapon DMG: **{weapon_damage}**",
        color=BOT_COLOR
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")
 
    embed.add_field(name="📊 Your Stats", value=(
        f"⚔ Strength: **{fmt(strength)}**\n"
        f"🎯 Crit Chance: **{fmt(crit_c)}%**\n"
        f"💥 Crit Damage: **{fmt(crit_d)}%**\n"
        f"🔥 Ferocity: **{fmt(ferocity)}**"
    ), inline=True)
 
    embed.add_field(name="🎯 Calculated Damage", value=(
        f"Normal hit: **{fmt(base)}**\n"
        f"Crit hit: **{fmt(crit)}**\n"
        f"Rating: {damage_rating(crit)}"
    ), inline=True)
 
    sim_str = int((5 + weapon_damage) * (1 + (strength + 50) / 100) * (1 + crit_d / 100))
    sim_cd  = int((5 + weapon_damage) * (1 + strength / 100) * (1 + (crit_d + 50) / 100))
    sim_wep = int((5 + weapon_damage + 100) * (1 + strength / 100) * (1 + crit_d / 100))
 
    embed.add_field(name="📈 If you improve...", value=(
        f"+50 Strength → **{fmt(sim_str)}** crit\n"
        f"+50 Crit Dmg → **{fmt(sim_cd)}** crit\n"
        f"+100 Wep Dmg → **{fmt(sim_wep)}** crit"
    ), inline=False)
 
    tips = []
    if crit_c < 80:
        tips.append(f"🎯 **Crit Chance** {fmt(crit_c)}% → need **80%** min. Use Itchy reforge or Crit potions.")
    if crit_d < 200:
        tips.append(f"💥 **Crit Damage** {fmt(crit_d)}% → aim for **200%+**. Reforge armor to Giant/Fierce.")
    if strength < 300:
        tips.append(f"⚔ **Strength** {fmt(strength)} → aim for **300+**. Fierce reforge, Strength potions.")
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
 
    member, prof, all_profiles, ign = result
    s = member.get("stats", {})
 
    embed = discord.Embed(title=f"⚔ {ign}'s {prof.get('cute_name','?')} Profile", color=BOT_COLOR)
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")
 
    col1 = f"❤ **Health**\n{fmt(s.get('health'))}\n\n🛡 **Defense**\n{fmt(s.get('defense'))}\n\n⚔ **Strength**\n{fmt(s.get('strength'))}\n\n✨ **Intelligence**\n{fmt(s.get('intelligence'))}"
    col2 = f"🎯 **Crit Chance**\n{fmt(s.get('crit_chance'))}%\n\n💥 **Crit Damage**\n{fmt(s.get('crit_damage'))}%\n\n⚡ **Attack Speed**\n{fmt(s.get('attack_speed'))}%\n\n🔥 **Ferocity**\n{fmt(s.get('ferocity'))}"
    col3 = f"🏃 **Speed**\n{fmt(s.get('speed'))}\n\n🍀 **Magic Find**\n{fmt(s.get('magic_find'))}\n\n🎣 **Sea Creature**\n{fmt(s.get('sea_creature_chance'))}%\n\n🐾 **Pet Luck**\n{fmt(s.get('pet_luck'))}"
 
    embed.add_field(name="\u200b", value=col1, inline=True)
    embed.add_field(name="\u200b", value=col2, inline=True)
    embed.add_field(name="\u200b", value=col3, inline=True)
 
    base, crit = calc_damage(s)
    embed.add_field(name="⚔ Damage Preview", value=f"Normal: **{fmt(base)}** | Crit: **{fmt(crit)}** | {damage_rating(crit)}", inline=False)
    embed.set_footer(text="Dmg Bot • by VectorGOD19")
    await interaction.followup.send(embed=embed)
 
# ── Run ────────────────────────────────────────────────────────
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("❌ DISCORD_TOKEN not set!")
else:
    client.run(token)
 
