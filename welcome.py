"""welcome.py — Welcome messages and auto-role assignment"""
import discord
from discord.ext import commands
import sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        db = SessionLocal()
        try:
            g = get_guild(db, member.guild.id)

            # Auto-role
            if g.auto_role_id:
                role = member.guild.get_role(g.auto_role_id)
                if role:
                    try:
                        await member.add_roles(role, reason="Auto-role on join")
                    except Exception:
                        pass

            # Welcome message
            if g.welcome_enabled and g.welcome_channel:
                ch = member.guild.get_channel(g.welcome_channel)
                if ch:
                    text = (g.welcome_message
                            .replace("{user}", member.mention)
                            .replace("{username}", str(member))
                            .replace("{server}", member.guild.name)
                            .replace("{count}", str(member.guild.member_count)))
                    embed = discord.Embed(
                        description=text,
                        color=discord.Color.blurple(),
                        timestamp=datetime.utcnow()
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    embed.set_footer(text=f"Member #{member.guild.member_count}")
                    try:
                        await ch.send(embed=embed)
                    except Exception:
                        pass
        finally:
            db.close()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        db = SessionLocal()
        try:
            g = get_guild(db, member.guild.id)
            if g.welcome_enabled and g.welcome_channel:
                ch = member.guild.get_channel(g.welcome_channel)
                if ch:
                    embed = discord.Embed(
                        description=f"👋 **{member}** has left the server.",
                        color=discord.Color.red(),
                        timestamp=datetime.utcnow()
                    )
                    try:
                        await ch.send(embed=embed)
                    except Exception:
                        pass
        finally:
            db.close()

    @discord.slash_command(name="setwelcome", description="Set the welcome channel and message")
    @discord.default_permissions(administrator=True)
    async def setwelcome(self, ctx: discord.ApplicationContext,
                         channel: discord.Option(discord.TextChannel, "Welcome channel"),
                         message: discord.Option(str,
                             "Message — use {user} {server} {count}",
                             default="Welcome {user} to **{server}**! You are member #{count}.")):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            g.welcome_enabled = True
            g.welcome_channel = channel.id
            g.welcome_message = message
            db.commit()
            await ctx.respond(
                f"✅ Welcome messages enabled in {channel.mention}.\n"
                f"Preview: {message.replace('{user}', ctx.author.mention).replace('{server}', ctx.guild.name).replace('{count}', str(ctx.guild.member_count))}",
                ephemeral=True
            )
        finally:
            db.close()

    @discord.slash_command(name="setautorole", description="Set a role to auto-assign on join")
    @discord.default_permissions(administrator=True)
    async def setautorole(self, ctx: discord.ApplicationContext,
                          role: discord.Option(discord.Role, "Role to assign"),
                          enabled: discord.Option(str, "on or off", choices=["on", "off"], default="on")):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            if enabled == "on":
                g.auto_role_id = role.id
                await ctx.respond(f"✅ Auto-role set to {role.mention}.", ephemeral=True)
            else:
                g.auto_role_id = None
                await ctx.respond("✅ Auto-role disabled.", ephemeral=True)
            db.commit()
        finally:
            db.close()


def setup(bot):
    bot.add_cog(Welcome(bot))
