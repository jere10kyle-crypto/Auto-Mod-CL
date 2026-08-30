"""moderation.py — Manual moderation commands with automatic punishment tiers"""
import discord
from discord.ext import commands
from discord import SlashCommandGroup
import asyncio, sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild, get_member, strike_count, add_strike, add_mod_log, Strike, Member


def mod_embed(action: str, user: discord.Member, mod: discord.Member,
              reason: str, color: discord.Color, extra: str = "") -> discord.Embed:
    e = discord.Embed(title=f"🔨 {action}", color=color, timestamp=datetime.utcnow())
    e.add_field(name="User",      value=f"{user.mention} `{user.id}`")
    e.add_field(name="Moderator", value=mod.mention)
    e.add_field(name="Reason",    value=reason or "No reason provided", inline=False)
    if extra:
        e.add_field(name="Details", value=extra, inline=False)
    return e


async def send_log(guild: discord.Guild, embed: discord.Embed, db=None, guild_id=None):
    if db is None or guild_id is None:
        return
    g = get_guild(db, guild_id)
    if g.mod_log_channel:
        ch = guild.get_channel(g.mod_log_channel)
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass


async def apply_punishment(ctx, member: discord.Member, strikes: int, guild_cfg, db):
    """Apply the appropriate punishment tier based on total strikes."""
    reason = f"Auto-punishment: {strikes} strikes"

    if strikes >= guild_cfg.tier5_strikes:
        try:
            await member.ban(reason=reason)
            add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "ban", reason)
        except Exception:
            pass
        return f"Banned (tier 5: {strikes} strikes)"

    if strikes >= guild_cfg.tier4_strikes:
        if guild_cfg.tier4_action == "ban":
            try:
                await member.ban(reason=reason)
                add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "ban", reason)
            except Exception:
                pass
        else:
            try:
                await member.kick(reason=reason)
                add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "kick", reason)
            except Exception:
                pass
        return f"{guild_cfg.tier4_action.title()} (tier 4: {strikes} strikes)"

    if strikes >= guild_cfg.tier3_strikes:
        until = discord.utils.utcnow() + timedelta(minutes=guild_cfg.tier3_minutes)
        try:
            await member.timeout(until, reason=reason)
            add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "mute", reason, guild_cfg.tier3_minutes)
        except Exception:
            pass
        return f"Timed out {guild_cfg.tier3_minutes}m (tier 3)"

    if strikes >= guild_cfg.tier2_strikes:
        until = discord.utils.utcnow() + timedelta(minutes=guild_cfg.tier2_minutes)
        try:
            await member.timeout(until, reason=reason)
            add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "mute", reason, guild_cfg.tier2_minutes)
        except Exception:
            pass
        return f"Timed out {guild_cfg.tier2_minutes}m (tier 2)"

    if strikes >= guild_cfg.tier1_strikes:
        until = discord.utils.utcnow() + timedelta(minutes=guild_cfg.tier1_minutes)
        try:
            await member.timeout(until, reason=reason)
            add_mod_log(db, ctx.guild.id, member.id, str(member), ctx.guild.me.id, "mute", reason, guild_cfg.tier1_minutes)
        except Exception:
            pass
        return f"Timed out {guild_cfg.tier1_minutes}m (tier 1)"

    return None


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /warn ──────────────────────────────────────────────────────────────────
    @discord.slash_command(name="warn", description="Warn a member (adds a strike)")
    @discord.default_permissions(moderate_members=True)
    async def warn(self, ctx: discord.ApplicationContext,
                   member: discord.Option(discord.Member, "Member to warn"),
                   reason: discord.Option(str, "Reason", default="No reason provided")):
        if member.bot or member == ctx.author:
            return await ctx.respond("Cannot warn that user.", ephemeral=True)

        db = SessionLocal()
        try:
            g    = get_guild(db, ctx.guild_id)
            total = add_strike(db, ctx.guild_id, member.id, ctx.author.id, reason)
            add_mod_log(db, ctx.guild_id, member.id, str(member), ctx.author.id, "warn", reason)

            punishment = await apply_punishment(ctx, member, total, g, db)

            embed = mod_embed("Warning Issued", member, ctx.author, reason,
                              discord.Color.yellow(),
                              f"Total strikes: **{total}**" + (f"\n{punishment}" if punishment else ""))
            await ctx.respond(embed=embed)
            await send_log(ctx.guild, embed, db, ctx.guild_id)

            try:
                dm = discord.Embed(title=f"⚠️ You were warned in {ctx.guild.name}",
                                   color=discord.Color.yellow())
                dm.add_field(name="Reason",  value=reason)
                dm.add_field(name="Strikes", value=str(total))
                await member.send(embed=dm)
            except Exception:
                pass
        finally:
            db.close()

    # ── /mute ──────────────────────────────────────────────────────────────────
    @discord.slash_command(name="mute", description="Timeout a member")
    @discord.default_permissions(moderate_members=True)
    async def mute(self, ctx: discord.ApplicationContext,
                   member: discord.Option(discord.Member, "Member to mute"),
                   minutes: discord.Option(int, "Duration in minutes", default=10),
                   reason: discord.Option(str, "Reason", default="No reason provided")):
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        try:
            await member.timeout(until, reason=reason)
        except discord.Forbidden:
            return await ctx.respond("I don't have permission to timeout that member.", ephemeral=True)

        db = SessionLocal()
        try:
            add_mod_log(db, ctx.guild_id, member.id, str(member), ctx.author.id, "mute", reason, minutes)
        finally:
            db.close()

        embed = mod_embed("Member Muted", member, ctx.author, reason,
                          discord.Color.orange(), f"Duration: **{minutes}m**")
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, embed)

    # ── /unmute ────────────────────────────────────────────────────────────────
    @discord.slash_command(name="unmute", description="Remove timeout from a member")
    @discord.default_permissions(moderate_members=True)
    async def unmute(self, ctx: discord.ApplicationContext,
                     member: discord.Option(discord.Member, "Member to unmute")):
        try:
            await member.timeout(None)
        except discord.Forbidden:
            return await ctx.respond("I don't have permission.", ephemeral=True)

        db = SessionLocal()
        try:
            add_mod_log(db, ctx.guild_id, member.id, str(member), ctx.author.id, "unmute", "")
        finally:
            db.close()

        embed = mod_embed("Member Unmuted", member, ctx.author, "", discord.Color.green())
        await ctx.respond(embed=embed)

    # ── /kick ──────────────────────────────────────────────────────────────────
    @discord.slash_command(name="kick", description="Kick a member")
    @discord.default_permissions(kick_members=True)
    async def kick(self, ctx: discord.ApplicationContext,
                   member: discord.Option(discord.Member, "Member to kick"),
                   reason: discord.Option(str, "Reason", default="No reason provided")):
        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await ctx.respond("I don't have permission to kick that member.", ephemeral=True)

        db = SessionLocal()
        try:
            add_mod_log(db, ctx.guild_id, member.id, str(member), ctx.author.id, "kick", reason)
        finally:
            db.close()

        embed = mod_embed("Member Kicked", member, ctx.author, reason, discord.Color.red())
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, embed)

    # ── /ban ───────────────────────────────────────────────────────────────────
    @discord.slash_command(name="ban", description="Ban a member")
    @discord.default_permissions(ban_members=True)
    async def ban(self, ctx: discord.ApplicationContext,
                  member: discord.Option(discord.Member, "Member to ban"),
                  reason: discord.Option(str, "Reason", default="No reason provided"),
                  delete_days: discord.Option(int, "Delete message history (days)", default=1, min_value=0, max_value=7)):
        try:
            await member.ban(reason=reason, delete_message_days=delete_days)
        except discord.Forbidden:
            return await ctx.respond("I don't have permission to ban that member.", ephemeral=True)

        db = SessionLocal()
        try:
            add_mod_log(db, ctx.guild_id, member.id, str(member), ctx.author.id, "ban", reason)
        finally:
            db.close()

        embed = mod_embed("Member Banned", member, ctx.author, reason, discord.Color.dark_red())
        await ctx.respond(embed=embed)
        await send_log(ctx.guild, embed)

    # ── /unban ─────────────────────────────────────────────────────────────────
    @discord.slash_command(name="unban", description="Unban a user by ID")
    @discord.default_permissions(ban_members=True)
    async def unban(self, ctx: discord.ApplicationContext,
                    user_id: discord.Option(str, "User ID to unban"),
                    reason: discord.Option(str, "Reason", default="No reason provided")):
        try:
            user = await ctx.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user, reason=reason)
        except (discord.NotFound, ValueError):
            return await ctx.respond("User not found or not banned.", ephemeral=True)
        except discord.Forbidden:
            return await ctx.respond("I don't have permission.", ephemeral=True)

        db = SessionLocal()
        try:
            add_mod_log(db, ctx.guild_id, int(user_id), str(user), ctx.author.id, "unban", reason)
        finally:
            db.close()

        embed = discord.Embed(title="✅ User Unbanned", color=discord.Color.green(),
                              timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{user} `{user_id}`")
        embed.add_field(name="Moderator", value=ctx.author.mention)
        embed.add_field(name="Reason",    value=reason, inline=False)
        await ctx.respond(embed=embed)

    # ── /strikes ───────────────────────────────────────────────────────────────
    @discord.slash_command(name="strikes", description="View a member's strikes")
    @discord.default_permissions(moderate_members=True)
    async def strikes(self, ctx: discord.ApplicationContext,
                      member: discord.Option(discord.Member, "Member to check")):
        db = SessionLocal()
        try:
            rows = (db.query(Strike)
                    .filter_by(guild_id=ctx.guild_id, user_id=member.id, active=True)
                    .order_by(Strike.created_at.desc()).limit(10).all())
            total = len(rows)

            embed = discord.Embed(title=f"Strikes for {member}", color=discord.Color.orange())
            embed.description = f"**Total active strikes: {total}**"
            for s in rows:
                embed.add_field(
                    name=s.created_at.strftime("%Y-%m-%d %H:%M"),
                    value=s.reason, inline=False)
            await ctx.respond(embed=embed, ephemeral=True)
        finally:
            db.close()

    # ── /clearstrikes ──────────────────────────────────────────────────────────
    @discord.slash_command(name="clearstrikes", description="Clear all strikes for a member")
    @discord.default_permissions(administrator=True)
    async def clearstrikes(self, ctx: discord.ApplicationContext,
                           member: discord.Option(discord.Member, "Member to clear")):
        db = SessionLocal()
        try:
            db.query(Strike).filter_by(
                guild_id=ctx.guild_id, user_id=member.id, active=True
            ).update({"active": False})
            db.commit()
            await ctx.respond(f"✅ Cleared all strikes for {member.mention}.", ephemeral=True)
        finally:
            db.close()

    # ── /shadowmute ────────────────────────────────────────────────────────────
    @discord.slash_command(name="shadowmute", description="Shadow mute a member (they can't tell)")
    @discord.default_permissions(administrator=True)
    async def shadowmute(self, ctx: discord.ApplicationContext,
                         member: discord.Option(discord.Member, "Member to shadow mute"),
                         toggle: discord.Option(str, "on or off", choices=["on", "off"])):
        db = SessionLocal()
        try:
            m = get_member(db, ctx.guild_id, member.id, str(member))
            m.shadow_muted = (toggle == "on")
            db.commit()
            state = "enabled" if m.shadow_muted else "disabled"
            await ctx.respond(f"✅ Shadow mute {state} for {member.mention}.", ephemeral=True)
        finally:
            db.close()


def setup(bot):
    bot.add_cog(Moderation(bot))
