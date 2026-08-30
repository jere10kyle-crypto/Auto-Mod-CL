"""tickets.py — Ticket system with buttons and private channels"""
import discord
from discord.ext import commands
import sys, os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild, Ticket


class CloseButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger,
                       custom_id="close_ticket")
    async def close(self, button, interaction: discord.Interaction):
        db = SessionLocal()
        try:
            t = db.query(Ticket).filter_by(channel_id=interaction.channel.id).first()
            if t:
                t.status    = "closed"
                t.closed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

        await interaction.response.send_message("🔒 Ticket closed. Channel will be deleted in 5s.")
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="Ticket closed")
        except Exception:
            pass


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(CloseButton())

    @discord.slash_command(name="ticket", description="Open a support ticket")
    async def ticket(self, ctx: discord.ApplicationContext,
                     reason: discord.Option(str, "Reason for ticket",
                                            default="Support needed")):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            if not g.ticket_enabled:
                return await ctx.respond(
                    "❌ Ticket system is not enabled. Ask an admin to enable it.",
                    ephemeral=True
                )

            # Check for existing open ticket
            existing = db.query(Ticket).filter_by(
                guild_id=ctx.guild_id, user_id=ctx.author.id, status="open"
            ).first()
            if existing:
                ch = ctx.guild.get_channel(existing.channel_id)
                if ch:
                    return await ctx.respond(
                        f"You already have an open ticket: {ch.mention}", ephemeral=True
                    )

            # Create channel
            category = ctx.guild.get_channel(g.ticket_category) if g.ticket_category else None
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctx.author:             discord.PermissionOverwrite(read_messages=True, send_messages=True),
                ctx.guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            # Add admin roles
            for role in ctx.guild.roles:
                if role.permissions.administrator:
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True)

            ch = await ctx.guild.create_text_channel(
                f"ticket-{ctx.author.name}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket: {reason}"
            )

            # Save to DB
            t = Ticket(guild_id=ctx.guild_id, user_id=ctx.author.id, channel_id=ch.id)
            db.add(t)
            db.commit()

            # Post in the ticket channel
            embed = discord.Embed(
                title="🎫 Support Ticket",
                description=(
                    f"**User:** {ctx.author.mention}\n"
                    f"**Reason:** {reason}\n\n"
                    "Staff will be with you shortly.\n"
                    "Click the button below to close this ticket."
                ),
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            await ch.send(embed=embed, view=CloseButton())
            await ctx.respond(f"✅ Ticket created: {ch.mention}", ephemeral=True)

            # Log if configured
            if g.ticket_log:
                log_ch = ctx.guild.get_channel(g.ticket_log)
                if log_ch:
                    log_embed = discord.Embed(
                        title="New Ticket",
                        description=f"{ctx.author.mention} opened {ch.mention}\n**Reason:** {reason}",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    try:
                        await log_ch.send(embed=log_embed)
                    except Exception:
                        pass
        finally:
            db.close()

    @discord.slash_command(name="closeticket", description="Close the current ticket")
    async def closeticket(self, ctx: discord.ApplicationContext):
        db = SessionLocal()
        try:
            t = db.query(Ticket).filter_by(channel_id=ctx.channel_id, status="open").first()
            if not t:
                return await ctx.respond("This is not an open ticket channel.", ephemeral=True)
            t.status    = "closed"
            t.closed_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        await ctx.respond("🔒 Closing ticket in 5 seconds…")
        import asyncio
        await asyncio.sleep(5)
        try:
            await ctx.channel.delete(reason="Ticket closed")
        except Exception:
            pass

    @discord.slash_command(name="ticketsetup", description="Configure the ticket system")
    @discord.default_permissions(administrator=True)
    async def ticketsetup(self, ctx: discord.ApplicationContext,
                          enabled: discord.Option(str, "on or off", choices=["on", "off"]),
                          category: discord.Option(discord.CategoryChannel, "Ticket category", required=False),
                          log_channel: discord.Option(discord.TextChannel, "Log channel", required=False)):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            g.ticket_enabled = (enabled == "on")
            if category:
                g.ticket_category = category.id
            if log_channel:
                g.ticket_log = log_channel.id
            db.commit()
            state = "✅ Enabled" if g.ticket_enabled else "❌ Disabled"
            await ctx.respond(f"{state} ticket system.", ephemeral=True)
        finally:
            db.close()


def setup(bot):
    bot.add_cog(Tickets(bot))
