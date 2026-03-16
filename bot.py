import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os

# ── Setup ──────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SKYCRYPT_API = "https://sky.shiiyu.moe/api/v2/profile"

STAT_DEFS = [
    ("health",              "❤ Health",          ""),
    ("defense",             "🛡 Defense",         ""),
    ("strength",            "⚔ Strength",         ""),
    ("intelligence",        "✨ Intelligence",    ""),
    ("crit_chance",         "🎯 Crit Chance",     "%"),
    ("crit_damage",         "💥 Crit Damage",     "%"),
    ("attack_speed",        "⚡ Attack Speed",    "%"),
    ("ferocity",            "🔥 Ferocity",        ""),
    ("speed",               "🏃 Speed",            ""),
    ("sea_creature_chance", "🎣 Sea Creature",    "%"),
    ("magic_find",          "🍀 Magic Find",      ""),
    ("pet_luck",            "🐾 Pet Luck",        ""),
]

# ── Ready event ────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

# ── /stats command ─────────────────────────────────────────────
@bot.tree.command(name="stats", description="View a player's SkyBlock stats")
@app_commands.describe(username="Minecraft username")
async def stats(interaction: discord.Interaction, username: str):
    await interaction.response.defer()  # shows "thinking..." while we fetch

    url = f"{SKYCRYPT_API}/{username}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.followup.send(
                    f"❌ Could not find player **{username}**. Check the username and make sure they have `/api new` enabled in Hypixel.",
                    ephemeral=True
                )
                return
            data = await resp.json()

    if "error" in data:
        await interaction.followup.send(f"❌ API error: {data['error']}", ephemeral=True)
        return

    profiles = data.get("profiles", {})
    if not profiles:
        await interaction.followup.send(
            f"❌ No SkyBlock profiles found for **{username}**.",
            ephemeral=True
        )
        return

    # Pick selected or most recently played profile
    selected = next((p for p in profiles.values() if p.get("selected")), None)
    if not selected:
        selected = max(profiles.values(), key=lambda p: p.get("last_save", 0))

    # Find player UUID
    members = selected.get("members", {})
    player_uuid = next(
        (uuid for uuid, m in members.items() if (m.get("username") or "").lower() == username.lower()),
        next(iter(members), None)
    )

    if not player_uuid:
        await interaction.followup.send("❌ Could not find player data in profile.", ephemeral=True)
        return

    member = members[player_uuid]
    stats_data = member.get("stats", {})
    ign = member.get("username", username)
    profile_name = selected.get("cute_name", "Unknown")

    # Build embed
    embed = discord.Embed(
        title=f"⚔ {ign}",
        description=f"📋 Profile: **{profile_name}**",
        color=0x5b9cf6
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")

    # Add known stats
    stat_lines = []
    for key, label, suffix in STAT_DEFS:
        val = stats_data.get(key)
        if val is not None:
            display = int(val) if val == int(val) else round(val, 1)
            stat_lines.append(f"{label}: **{display}{suffix}**")

    if stat_lines:
        # Split into two columns
        half = (len(stat_lines) + 1) // 2
        embed.add_field(name="Stats", value="\n".join(stat_lines[:half]), inline=True)
        if stat_lines[half:]:
            embed.add_field(name="\u200b", value="\n".join(stat_lines[half:]), inline=True)
    else:
        embed.add_field(name="⚠ No stats found", value="Make sure `/api new` is enabled in Hypixel.", inline=False)

    # Profile switcher hint
    profile_list = [p.get("cute_name", "?") for p in profiles.values()]
    if len(profile_list) > 1:
        embed.set_footer(text=f"Profiles: {' · '.join(profile_list)}  |  Use /profile to switch")

    await interaction.followup.send(embed=embed)


# ── /profile command (switch profile) ─────────────────────────
@bot.tree.command(name="profile", description="View a specific SkyBlock profile")
@app_commands.describe(username="Minecraft username", profile="Profile name (the fruit, e.g. Mango)")
async def profile_cmd(interaction: discord.Interaction, username: str, profile: str):
    await interaction.response.defer()

    url = f"{SKYCRYPT_API}/{username}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.followup.send(f"❌ Player **{username}** not found.", ephemeral=True)
                return
            data = await resp.json()

    profiles = data.get("profiles", {})
    target = next(
        (p for p in profiles.values() if p.get("cute_name", "").lower() == profile.lower()),
        None
    )

    if not target:
        names = [p.get("cute_name", "?") for p in profiles.values()]
        await interaction.followup.send(
            f"❌ Profile **{profile}** not found. Available profiles: {', '.join(names)}",
            ephemeral=True
        )
        return

    members = target.get("members", {})
    player_uuid = next(
        (uuid for uuid, m in members.items() if (m.get("username") or "").lower() == username.lower()),
        next(iter(members), None)
    )

    member    = members.get(player_uuid, {})
    stats_data = member.get("stats", {})
    ign        = member.get("username", username)

    embed = discord.Embed(
        title=f"⚔ {ign}",
        description=f"📋 Profile: **{target.get('cute_name', '?')}**",
        color=0x5b9cf6
    )
    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{ign}/64")

    stat_lines = []
    for key, label, suffix in STAT_DEFS:
        val = stats_data.get(key)
        if val is not None:
            display = int(val) if val == int(val) else round(val, 1)
            stat_lines.append(f"{label}: **{display}{suffix}**")

    if stat_lines:
        half = (len(stat_lines) + 1) // 2
        embed.add_field(name="Stats", value="\n".join(stat_lines[:half]), inline=True)
        if stat_lines[half:]:
            embed.add_field(name="\u200b", value="\n".join(stat_lines[half:]), inline=True)
    else:
        embed.add_field(name="⚠ No stats found", value="Make sure `/api new` is enabled in Hypixel.", inline=False)

    await interaction.followup.send(embed=embed)


# ── Run ────────────────────────────────────────────────────────
token = os.environ.get("DISCORD_TOKEN")
if not token:
    print("❌ DISCORD_TOKEN not set! Add it as an environment variable.")
else:
    bot.run(token)
