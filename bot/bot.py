"""bot.py — Auto-Mod-Pro V2 main bot entry point"""
import discord
from discord.ext import commands
import os, sys, asyncio, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.db import init_db, SessionLocal, get_guild

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("bot")

TOKEN    = os.environ.get("DISCORD_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members         = True
intents.guilds          = True

bot = discord.Bot(intents=intents, owner_id=OWNER_ID)

COGS = [
    "bot.cogs.moderation",
    "bot.cogs.automod",
    "bot.cogs.antiraid",
    "bot.cogs.welcome",
    "bot.cogs.leveling",
    "bot.cogs.tickets",
]


@bot.event
async def on_ready():
    init_db()
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="your server 🛡️"
    ))


@bot.event
async def on_guild_join(guild: discord.Guild):
    await asyncio.sleep(2)
    adder = None
    try:
        async for entry in guild.audit_logs(
                limit=10, action=discord.AuditLogAction.bot_add):
            if entry.target.id == bot.user.id:
                adder = entry.user
                break
    except Exception:
        pass

    if adder:
        db = SessionLocal()
        try:
            g = get_guild(db, guild.id)
            admins = [a for a in g.dashboard_admins.split(",") if a.strip()]
            if str(adder.id) not in admins:
                admins.append(str(adder.id))
                g.dashboard_admins = ",".join(admins)
                db.commit()
        finally:
            db.close()
        try:
            embed = discord.Embed(
                title="Thanks for adding Auto-Mod-Pro V2! 🛡️",
                description=(
                    f"I've been added to **{guild.name}**.\n\n"
                    "Open your dashboard and log in with Discord to configure me.\n"
                    "Use `/help` in the server for a command list."
                ),
                color=discord.Color.blurple()
            )
            await adder.send(embed=embed)
        except Exception:
            pass


@bot.slash_command(name="help", description="Show all commands")
async def help_cmd(ctx: discord.ApplicationContext):
    embed = discord.Embed(title="Auto-Mod-Pro V2 🛡️", color=discord.Color.blurple())
    embed.add_field(name="Moderation",
        value="`/warn` `/mute` `/unmute` `/kick` `/ban` `/unban`\n`/strikes` `/clearstrikes` `/shadowmute`",
        inline=False)
    embed.add_field(name="Info",
        value="`/rank` `/leaderboard` `/serverinfo` `/userinfo`",
        inline=False)
    embed.add_field(name="Tickets", value="`/ticket` `/closeticket`", inline=False)
    await ctx.respond(embed=embed, ephemeral=True)


@bot.slash_command(name="serverinfo", description="Show server information")
async def serverinfo(ctx: discord.ApplicationContext):
    g = ctx.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="Members",  value=str(g.member_count))
    embed.add_field(name="Channels", value=str(len(g.channels)))
    embed.add_field(name="Roles",    value=str(len(g.roles)))
    embed.add_field(name="Created",  value=g.created_at.strftime("%Y-%m-%d"))
    await ctx.respond(embed=embed)


@bot.slash_command(name="userinfo", description="Show info about a user")
async def userinfo(ctx: discord.ApplicationContext,
                   member: discord.Option(discord.Member, required=False)):
    member = member or ctx.author
    embed  = discord.Embed(title=str(member), color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID",      value=str(member.id))
    embed.add_field(name="Joined",  value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "N/A")
    embed.add_field(name="Created", value=member.created_at.strftime("%Y-%m-%d"))
    roles = ", ".join(r.mention for r in member.roles[1:]) or "None"
    embed.add_field(name="Roles", value=roles, inline=False)
    await ctx.respond(embed=embed)


for cog in COGS:
    try:
        bot.load_extension(cog)
        log.info(f"Loaded: {cog}")
    except Exception as e:
        log.error(f"Failed to load {cog}: {e}")

if __name__ == "__main__":
    if not TOKEN:
        log.error("DISCORD_TOKEN not set!")
        sys.exit(1)
    bot.run(TOKEN)
