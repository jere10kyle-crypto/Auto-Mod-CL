"""antiraid.py — Raid protection and new account restrictions"""
import discord
from discord.ext import commands
import asyncio, sys, os
from datetime import datetime, timezone
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild, add_mod_log


class AntiRaid(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # guild_id → deque of join timestamps
        self._join_cache: dict[int, deque] = {}

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = SessionLocal()
        try:
            g = get_guild(db, member.guild.id)
            if not g.raid_enabled:
                return

            # ── New account detection (<7 days old) ───────────────────────────
            age_days = (datetime.now(timezone.utc) - member.created_at).days
            if age_days < 7:
                if g.verify_enabled and g.verify_role_id:
                    role = member.guild.get_role(g.verify_role_id)
                    if role:
                        try:
                            await member.add_roles(role, reason="New account - verification required")
                        except Exception:
                            pass
                # optionally DM them
                try:
                    await member.send(
                        f"👋 Welcome to **{member.guild.name}**! Your account is new. "
                        "Please complete verification if prompted."
                    )
                except Exception:
                    pass

            # ── Lockdown check ────────────────────────────────────────────────
            if g.lockdown:
                try:
                    await member.kick(reason="Server is in lockdown mode")
                    add_mod_log(db, member.guild.id, member.id, str(member),
                                self.bot.user.id, "kick", "Server lockdown")
                except Exception:
                    pass
                return

            # ── Mass-join detection ───────────────────────────────────────────
            gid = member.guild.id
            if gid not in self._join_cache:
                self._join_cache[gid] = deque(maxlen=100)

            now = datetime.utcnow().timestamp()
            self._join_cache[gid].append(now)

            window    = g.raid_window
            threshold = g.raid_threshold
            recent = sum(1 for ts in self._join_cache[gid] if now - ts <= window)

            if recent >= threshold:
                await self._trigger_lockdown(member.guild, g, db, recent, window)
        finally:
            db.close()

    async def _trigger_lockdown(self, guild: discord.Guild, g, db, count: int, window: int):
        """Enable lockdown and alert admins."""
        g.lockdown = True
        db.commit()

        embed = discord.Embed(
            title="🚨 RAID DETECTED — Lockdown Enabled",
            description=(
                f"**{count}** members joined in **{window}s**.\n"
                "New joins are being kicked. Use `/lockdown off` to disable."
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.utcnow()
        )

        if g.mod_log_channel:
            ch = guild.get_channel(g.mod_log_channel)
            if ch:
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

    @discord.slash_command(name="lockdown", description="Enable or disable server lockdown")
    @discord.default_permissions(administrator=True)
    async def lockdown_cmd(self, ctx: discord.ApplicationContext,
                           state: discord.Option(str, "on or off", choices=["on", "off"])):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            g.lockdown = (state == "on")
            db.commit()
            status = "🔒 Lockdown **enabled** — new joins will be kicked." if g.lockdown \
                     else "🔓 Lockdown **disabled**."
            await ctx.respond(status)
        finally:
            db.close()

    @discord.slash_command(name="raidstatus", description="Show anti-raid configuration")
    @discord.default_permissions(administrator=True)
    async def raidstatus(self, ctx: discord.ApplicationContext):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            embed = discord.Embed(title="Anti-Raid Settings", color=discord.Color.orange())
            embed.add_field(name="Enabled",    value="✅" if g.raid_enabled else "❌")
            embed.add_field(name="Threshold",  value=f"{g.raid_threshold} joins/{g.raid_window}s")
            embed.add_field(name="Action",     value=g.raid_action)
            embed.add_field(name="Lockdown",   value="🔒 Active" if g.lockdown else "🔓 Inactive")
            embed.add_field(name="Verify",     value="✅" if g.verify_enabled else "❌")
            await ctx.respond(embed=embed, ephemeral=True)
        finally:
            db.close()


def setup(bot):
    bot.add_cog(AntiRaid(bot))
