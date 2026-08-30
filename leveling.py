"""leveling.py — XP and leveling system"""
import discord
from discord.ext import commands
import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild, get_member, xp_for_level, Member


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        db = SessionLocal()
        try:
            g = get_guild(db, message.guild.id)
            if not g.xp_enabled:
                return

            m = get_member(db, message.guild.id, message.author.id, str(message.author))

            # Cooldown check
            now = datetime.utcnow()
            if m.last_xp_at and (now - m.last_xp_at).total_seconds() < g.xp_cooldown:
                return

            m.xp         += g.xp_per_message
            m.messages   += 1
            m.last_xp_at  = now

            # Level up check
            new_level = 0
            while m.xp >= xp_for_level(new_level + 1):
                new_level += 1

            leveled_up = new_level > m.level
            m.level = new_level
            db.commit()

            if leveled_up:
                await self._announce_levelup(message.author, message.guild, m.level, g)
        finally:
            db.close()

    async def _announce_levelup(self, member: discord.Member, guild: discord.Guild,
                                 level: int, g):
        embed = discord.Embed(
            title="⬆️ Level Up!",
            description=f"{member.mention} reached **level {level}**! 🎉",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        target_ch_id = g.level_channel
        ch = guild.get_channel(target_ch_id) if target_ch_id else None
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

    @discord.slash_command(name="rank", description="Check your rank and XP")
    async def rank(self, ctx: discord.ApplicationContext,
                   member: discord.Option(discord.Member, required=False)):
        member = member or ctx.author
        db = SessionLocal()
        try:
            m = get_member(db, ctx.guild_id, member.id, str(member))
            next_xp = xp_for_level(m.level + 1)
            embed = discord.Embed(title=f"Rank — {member}", color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Level",    value=str(m.level))
            embed.add_field(name="XP",       value=f"{m.xp} / {next_xp}")
            embed.add_field(name="Messages", value=str(m.messages))

            # Progress bar
            pct = min(int((m.xp / max(next_xp, 1)) * 20), 20)
            bar = "█" * pct + "░" * (20 - pct)
            embed.add_field(name="Progress", value=f"`{bar}` {int(pct*5)}%", inline=False)
            await ctx.respond(embed=embed)
        finally:
            db.close()

    @discord.slash_command(name="leaderboard", description="Show the XP leaderboard")
    async def leaderboard(self, ctx: discord.ApplicationContext):
        db = SessionLocal()
        try:
            top = (db.query(Member)
                   .filter_by(guild_id=ctx.guild_id)
                   .order_by(Member.xp.desc())
                   .limit(10).all())

            embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold())
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, m in enumerate(top):
                prefix = medals[i] if i < 3 else f"`{i+1}.`"
                lines.append(f"{prefix} <@{m.user_id}> — Lvl **{m.level}** ({m.xp} XP)")

            embed.description = "\n".join(lines) or "No data yet."
            await ctx.respond(embed=embed)
        finally:
            db.close()

    @discord.slash_command(name="setxp", description="Set XP settings")
    @discord.default_permissions(administrator=True)
    async def setxp(self, ctx: discord.ApplicationContext,
                    xp_per_msg: discord.Option(int, "XP per message", default=15, min_value=1, max_value=100),
                    cooldown: discord.Option(int, "Cooldown seconds", default=60, min_value=5, max_value=300),
                    level_channel: discord.Option(discord.TextChannel, "Level-up announcement channel", required=False)):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            g.xp_per_message = xp_per_msg
            g.xp_cooldown    = cooldown
            if level_channel:
                g.level_channel = level_channel.id
            db.commit()
            await ctx.respond(f"✅ XP: {xp_per_msg}/msg, cooldown: {cooldown}s.", ephemeral=True)
        finally:
            db.close()


def setup(bot):
    bot.add_cog(Leveling(bot))
