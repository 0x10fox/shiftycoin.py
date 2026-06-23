import asyncio
import discord
from discord.ext import commands
from cogs.converters import MemberOrUser


class UserCog(commands.Cog, name="User"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="user", invoke_without_command=True)
    async def user(self, ctx):
        """Root command for user management functions. Use subcommands: !user kick, !user ban, !user unban, !user mute, !user unmute."""
        await ctx.send("User management commands: `!user kick <user>` `!user ban <user>` `!user unban <user>` `!user mute <user> <duration>` `!user unmute <user>`")

    @user.command(name="kick")
    async def kick(self, ctx, member: discord.Member, *, reason=None):
        if not ctx.author.guild_permissions.kick_members:
            await ctx.send("You do not have permission to kick members.")
            return
        try:
            await member.kick(reason=reason)
            await ctx.send(f"{member.mention} has been kicked. Reason: {reason}")
        except Exception as e:
            await ctx.send(f"Failed to kick {member.mention}. Error: {e}")

    @user.command(name="ban")
    async def ban(self, ctx, member: MemberOrUser, *, reason=None):
        if not ctx.author.guild_permissions.ban_members:
            await ctx.send("You do not have permission to ban members.")
            return
        try:
            await member.ban(reason=reason)
            await ctx.send(f"{member.mention} has been banned. Reason: {reason}")
        except Exception as e:
            await ctx.send(f"Failed to ban {member.mention}. Error: {e}")

    @user.command(name="mute")
    async def mute(self, ctx, member: discord.Member, duration: int):
        if not ctx.author.guild_permissions.manage_roles:
            await ctx.send("You do not have permission to mute members.")
            return
        mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not mute_role:
            mute_role = await ctx.guild.create_role(name="Muted")
            for channel in ctx.guild.channels:
                await channel.set_permissions(mute_role, speak=False, send_messages=False, read_message_history=True, read_messages=False)
        try:
            await member.add_roles(mute_role)
            await ctx.send(f"{member.mention} has been muted for {duration} minutes.")
            await asyncio.sleep(duration * 60)
            await member.remove_roles(mute_role)
            await ctx.send(f"{member.mention} has been unmuted.")
        except Exception as e:
            await ctx.send(f"Failed to mute {member.mention}. Error: {e}")

    @user.command(name="unmute")
    async def unmute(self, ctx, member: discord.Member):
        if not ctx.author.guild_permissions.manage_roles:
            await ctx.send("You do not have permission to unmute members.")
            return
        mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not mute_role:
            await ctx.send("Muted role does not exist.")
            return
        try:
            await member.remove_roles(mute_role)
            await ctx.send(f"{member.mention} has been unmuted.")
        except Exception as e:
            await ctx.send(f"Failed to unmute {member.mention}. Error: {e}")

    @user.command(name="unban")
    async def unban(self, ctx, user: discord.User):
        if not ctx.author.guild_permissions.ban_members:
            await ctx.send("You do not have permission to unban members.")
            return
        try:
            await ctx.guild.unban(user)
            await ctx.send(f"{user.mention} has been unbanned.")
        except Exception as e:
            await ctx.send(f"Failed to unban {user.mention}. Error: {e}")


async def setup(bot):
    await bot.add_cog(UserCog(bot))
