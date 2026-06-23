import datetime
import discord
from discord.ext import commands
from utils import _load_log_channels, _save_log_channels


class SrvlCog(commands.Cog, name="SRVL"):
    def __init__(self, bot):
        self.bot = bot

    def _find_log_channel_for_guild(self, guild: discord.Guild):
        mapping = _load_log_channels()
        gid = str(guild.id)
        ch = None

        cid = mapping.get(gid)
        if cid:
            try:
                ch = guild.get_channel(int(cid))
            except Exception:
                ch = None
            if not ch and gid in mapping:
                mapping.pop(gid, None)
                _save_log_channels(mapping)

        return ch

    async def _send_log_embed(self, guild: discord.Guild, title: str, description: str, color: discord.Colour = discord.Colour.orange()):
        ch = self._find_log_channel_for_guild(guild)
        if not ch:
            return
        embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.now(datetime.UTC))
        try:
            await ch.send(embed=embed)
        except Exception:
            pass

    @commands.group(name="srvl", invoke_without_command=True)
    async def srvl(self, ctx):
        """Root group for the SRVL system. Use subcommands: channelset, channelrm."""
        await ctx.send("SRVL commands: `!srvl set` `!srvl rm`")

    @srvl.command(name="set")
    async def add_log_channel(self, ctx, channel: discord.TextChannel = None):
        """Administrator command: set a channel in this guild to receive SRVL messages."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You do not have permission to use this command.")
            return
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server.")
            return

        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel) or target.guild.id != ctx.guild.id:
            await ctx.send("Please specify a text channel from this server.")
            return

        mapping = _load_log_channels()
        mapping[str(ctx.guild.id)] = str(target.id)
        _save_log_channels(mapping)
        await ctx.send(f"SRVL channel for this server set to {target.mention}.")

    @srvl.command(name="rm")
    async def remove_log_channel(self, ctx, channel: discord.TextChannel = None):
        """Administrator command: remove the configured SRVL channel for this guild."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You do not have permission to use this command.")
            return
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server .")
            return

        mapping = _load_log_channels()
        gid = str(ctx.guild.id)
        configured = mapping.get(gid)

        if not configured:
            await ctx.send("No SRVL channel is configured for this server.")
            return

        if channel and str(channel.id) != configured:
            await ctx.send(f"The configured SRVL channel is <#{configured}>, not {channel.mention}.")
            return

        mapping.pop(gid, None)
        _save_log_channels(mapping)
        await ctx.send("SRVL channel for this server has been removed.")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None:
            return
        if message.author and message.author.bot:
            return
        author = message.author
        channel = message.channel
        content = message.content or ""
        files_info = ""
        if message.attachments:
            urls = [a.url for a in message.attachments]
            files_info = "\nAttachments:\n" + "\n".join(urls)
        if len(content) > 1500:
            content = content[:1500] + "… (truncated)"
        desc = (
            f"Message deleted in {channel.mention}\n"
            f"Author: {author.mention} (`{author.id}`)\n"
            f"Message ID: `{message.id}`\n\n"
            f"Content:\n{content}"
            f"{files_info}"
        )
        await self._send_log_embed(message.guild, "Message Deleted", desc, discord.Colour.red())

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.guild is None:
            return
        if before.author and before.author.bot:
            return
        author = before.author
        channel = before.channel
        content_before = before.content or ""
        content_after = after.content or ""
        files_info = ""
        if before.attachments:
            urls = [a.url for a in before.attachments]
            files_info = "\nAttachments:\n" + "\n".join(urls)
        if len(content_before) > 1500:
            content_before = content_before[:1500] + "… (truncated)"
        if len(content_after) > 1500:
            content_after = content_after[:1500] + "… (truncated)"
        desc = (
            f"Message edited in {channel.mention}\n"
            f"Author: {author.mention} (`{author.id}`)\n"
            f"Message ID: `{before.id}`\n\n"
            f"Before:\n{content_before}"
            f"\nAfter:\n{content_after}"
            f"{files_info}"
        )
        await self._send_log_embed(before.guild, "Message Edited", desc, discord.Colour.orange())

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        reason = None
        try:
            async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
                if entry.target and getattr(entry.target, "id", None) == user.id:
                    reason = entry.reason
                    moderator = entry.user
                    break
        except Exception:
            moderator = None

        desc = f"User: {user} (`{getattr(user, 'id', 'unknown')}`)\n"
        if moderator:
            desc += f"Banned by: {moderator.mention} (`{moderator.id}`)\n"
        if reason:
            desc += f"Reason: {reason}\n"
        await self._send_log_embed(guild, "Member Banned", desc, discord.Colour.dark_red())

    @commands.Cog.listener(name="on_member_update")
    async def on_member_update_mute(self, before: discord.Member, after: discord.Member):
        before_roles = {r.id: r for r in before.roles}
        after_roles = {r.id: r for r in after.roles}

        muted_before = None
        muted_after = None
        for r in before.roles:
            if r.name.lower() == "muted":
                muted_before = r
                break
        for r in after.roles:
            if r.name.lower() == "muted":
                muted_after = r
                break

        if not muted_before and muted_after:
            desc = (
                f"User muted: {after.mention} (`{after.id}`)\n"
                f"Role: {muted_after.name}\n"
            )
            await self._send_log_embed(after.guild, "Member Muted", desc, discord.Colour.orange())

        if muted_before and not muted_after:
            desc = (
                f"User unmuted: {after.mention} (`{after.id}`)\n"
                f"Role removed: {muted_before.name}\n"
            )
            await self._send_log_embed(after.guild, "Member Unmuted", desc, discord.Colour.green())

    @commands.Cog.listener(name="on_member_update")
    async def on_member_update_nick(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            desc = (
                f"User nickname changed: {after.mention} (`{after.id}`)\n"
                f"Before: {before.nick}\n"
                f"After: {after.nick}\n"
            )
            await self._send_log_embed(after.guild, "Member Nickname Changed", desc, discord.Colour.blue())


async def setup(bot):
    await bot.add_cog(SrvlCog(bot))
