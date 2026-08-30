"""automod.py — Auto-moderation: word filter, spam, caps, emoji, mention spam"""
import discord
from discord.ext import commands
import asyncio, sys, os, re
from collections import defaultdict, deque
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.db import SessionLocal, get_guild, get_member, add_strike, add_mod_log, BannedWord, Member
from bot.utils.text_normalize import contains_banned, caps_ratio, count_emojis, extract_urls
from bot.cogs.moderation import apply_punishment, send_log, mod_embed


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # guild_id → deque of (user_id, timestamp) for spam tracking
        self._msg_cache: dict[int, deque] = defaultdict(lambda: deque(maxlen=50))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return
        if message.author.bot:
            return
        if message.author.guild_permissions.administrator:
            return

        db = SessionLocal()
        try:
            guild_cfg = get_guild(db, message.guild.id)
            member_rec = get_member(db, message.guild.id, message.author.id, str(message.author))

            # ── Shadow mute ───────────────────────────────────────────────────
            if member_rec.shadow_muted:
                try:
                    await asyncio.sleep(0.4)
                    await message.delete()
                except Exception:
                    pass
                return

            # ── Word filter ───────────────────────────────────────────────────
            banned_rows = db.query(BannedWord).filter_by(guild_id=message.guild.id).all()
            banned_list = [b.word for b in banned_rows]
            hit = contains_banned(message.content, banned_list)
            if hit:
                try:
                    await message.delete()
                except Exception:
                    pass
                await self._strike_user(
                    message, f"Banned word detected", db, guild_cfg
                )
                return

            # ── Link protection ───────────────────────────────────────────────
            if guild_cfg.link_enabled and extract_urls(message.content):
                whitelist = [w.strip().lower() for w in guild_cfg.link_whitelist.split(",") if w.strip()]
                urls = extract_urls(message.content)
                blocked = any(
                    not any(w in url.lower() for w in whitelist)
                    for url in urls
                ) if whitelist else bool(urls)
                if blocked:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self._strike_user(message, "Unauthorized link", db, guild_cfg)
                    return

            # ── Caps spam ─────────────────────────────────────────────────────
            if guild_cfg.caps_enabled:
                ratio = caps_ratio(message.content)
                if ratio >= guild_cfg.caps_percent / 100:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self._strike_user(message, "Excessive caps", db, guild_cfg)
                    return

            # ── Emoji spam ────────────────────────────────────────────────────
            if guild_cfg.emoji_enabled:
                if count_emojis(message.content) > guild_cfg.emoji_limit:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self._strike_user(message, "Emoji spam", db, guild_cfg)
                    return

            # ── Mention spam ──────────────────────────────────────────────────
            if guild_cfg.mention_enabled:
                if len(message.mentions) > guild_cfg.mention_limit:
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    await self._strike_user(message, "Mention spam", db, guild_cfg)
                    return

            # ── Message spam (rate) ───────────────────────────────────────────
            if guild_cfg.spam_enabled:
                now = datetime.utcnow().timestamp()
                cache = self._msg_cache[message.guild.id]
                cache.append((message.author.id, now))

                window = guild_cfg.spam_window
                threshold = guild_cfg.spam_threshold
                recent = sum(
                    1 for uid, ts in cache
                    if uid == message.author.id and now - ts <= window
                )
                if recent > threshold:
                    # delete recent messages from this user in this channel
                    try:
                        def is_spammer(m):
                            return m.author.id == message.author.id
                        await message.channel.purge(limit=threshold + 2, check=is_spammer)
                    except Exception:
                        pass
                    await self._strike_user(message, "Message spam", db, guild_cfg)
                    return

        finally:
            db.close()

    async def _strike_user(self, message: discord.Message, reason: str, db, guild_cfg):
        """Add a strike and apply punishment tier."""
        total = add_strike(db, message.guild.id, message.author.id,
                           self.bot.user.id, reason)
        add_mod_log(db, message.guild.id, message.author.id,
                    str(message.author), self.bot.user.id, "warn", reason)

        punishment = await apply_punishment(
            type("ctx", (), {
                "guild": message.guild, "guild_id": message.guild.id,
                "bot": self.bot
            })(),
            message.author, total, guild_cfg, db
        )

        try:
            warn_msg = await message.channel.send(
                f"⚠️ {message.author.mention} — **{reason}** "
                f"(Strike **{total}**){' — ' + punishment if punishment else ''}",
                delete_after=8
            )
        except Exception:
            pass

        embed = mod_embed("Auto-Mod Action", message.author,
                          message.guild.me, reason,
                          discord.Color.orange(),
                          f"Strikes: **{total}**" + (f"\n{punishment}" if punishment else ""))
        await send_log(message.guild, embed, db, message.guild.id)


    # ── /automod settings ──────────────────────────────────────────────────────
    @discord.slash_command(name="automod", description="View auto-mod settings")
    @discord.default_permissions(administrator=True)
    async def automod_status(self, ctx: discord.ApplicationContext):
        db = SessionLocal()
        try:
            g = get_guild(db, ctx.guild_id)
            embed = discord.Embed(title="Auto-Mod Settings", color=discord.Color.blurple())
            embed.add_field(name="Spam",     value=f"{'✅' if g.spam_enabled else '❌'} {g.spam_threshold} msg/{g.spam_window}s")
            embed.add_field(name="Caps",     value=f"{'✅' if g.caps_enabled else '❌'} {g.caps_percent}%")
            embed.add_field(name="Emoji",    value=f"{'✅' if g.emoji_enabled else '❌'} limit {g.emoji_limit}")
            embed.add_field(name="Mentions", value=f"{'✅' if g.mention_enabled else '❌'} limit {g.mention_limit}")
            embed.add_field(name="Links",    value=f"{'✅' if g.link_enabled else '❌'}")
            await ctx.respond(embed=embed, ephemeral=True)
        finally:
            db.close()

    @discord.slash_command(name="addword", description="Add a banned word")
    @discord.default_permissions(administrator=True)
    async def addword(self, ctx: discord.ApplicationContext,
                      word: discord.Option(str, "Word to ban")):
        db = SessionLocal()
        try:
            exists = db.query(BannedWord).filter_by(guild_id=ctx.guild_id, word=word.lower()).first()
            if exists:
                return await ctx.respond("That word is already banned.", ephemeral=True)
            db.add(BannedWord(guild_id=ctx.guild_id, word=word.lower()))
            db.commit()
            await ctx.respond(f"✅ Added `{word}` to the banned words list.", ephemeral=True)
        finally:
            db.close()

    @discord.slash_command(name="removeword", description="Remove a banned word")
    @discord.default_permissions(administrator=True)
    async def removeword(self, ctx: discord.ApplicationContext,
                         word: discord.Option(str, "Word to remove")):
        db = SessionLocal()
        try:
            row = db.query(BannedWord).filter_by(guild_id=ctx.guild_id, word=word.lower()).first()
            if not row:
                return await ctx.respond("That word is not in the list.", ephemeral=True)
            db.delete(row)
            db.commit()
            await ctx.respond(f"✅ Removed `{word}` from the banned words list.", ephemeral=True)
        finally:
            db.close()

    @discord.slash_command(name="bannedwords", description="List all banned words")
    @discord.default_permissions(administrator=True)
    async def bannedwords(self, ctx: discord.ApplicationContext):
        db = SessionLocal()
        try:
            rows = db.query(BannedWord).filter_by(guild_id=ctx.guild_id).all()
            words = ", ".join(f"`{r.word}`" for r in rows) or "None"
            embed = discord.Embed(title="Banned Words", description=words,
                                  color=discord.Color.red())
            await ctx.respond(embed=embed, ephemeral=True)
        finally:
            db.close()


def setup(bot):
    bot.add_cog(AutoMod(bot))
