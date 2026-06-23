import time
from discord.ext import commands
from utils import BOT_START, _format_duration


class DirectoryCog(commands.Cog, name="Directory"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx):
        """HELLO ARE YOU AWAKE SIR?"""
        ws_latency_ms = round((self.bot.latency or 0.0) * 1000)
        await ctx.send(f"dong. socket latency: {ws_latency_ms} ms")

    @commands.command(name="uptime")
    async def uptime(self, ctx):
        """Show how long the bot has been running."""
        elapsed = time.time() - BOT_START
        await ctx.send(f"uptime: { _format_duration(elapsed) }")

    @commands.group(name="dir", invoke_without_command=True)
    async def dir(self, ctx):
        """Root directory. Use subcommands: !dir sc, !dir loan, !dir corp, !dir bj, !dir bet, !dir user, !dir bureau, !dir srvl"""
        await ctx.send(
            "**Root directory**\n\n"
            "`!dir sc` - Shiftycoin commands\n"
            "`!dir loan` - Loan system commands\n"
            "`!dir corp` - Business/corporation commands\n"
            "`!dir bj` - Blackjack game commands\n"
            "`!dir bet` - Betting system commands\n"
            "`!dir user` - User management commands\n"
            "`!dir bureau` - Bureau of Shiftycoin Administration commands\n"
            "`!dir srvl` - SRVL commands\n"
            "`!dir api` - API management commands\n\n"
            "**Reactions with ⭐ increases recieving user's Shiftycoin balance by 10.** \n"
            "**Reactions with 💀 decreases recieving user's Shiftycoin balance by 20.**"
        )

    @dir.command(name="sc")
    async def directory_sc(self, ctx):
        await ctx.send(
            "**Shiftycoin Commands**\n"
            "`!sc bal` - show your balance\n"
            "`!sc send <@user> <amount>` - send shiftycoin to another user\n"
            "`!sc request <@user> <amount>` - request shiftycoin from another user\n"
        )

    @dir.command(name="loan")
    async def directory_loan(self, ctx):
        await ctx.send(
            "**Loan System Commands**\n"
            "`!loan take <amount>` - take out a loan\n"
            "`!loan repay <amount>` - repay part or all of your loan\n"
            "`!loan info <@user>` - show your or another user's loan info\n"
            "`!loan accrue` - apply interest to your loans (admins can apply to all)\n"
        )

    @dir.command(name="corp")
    async def directory_corp(self, ctx):
        await ctx.send(
            "**Business Commands**\n"
            "`!corp start <name>` - create a new business\n"
            "`!corp pay <business> <business/@user> <amount>` - pay a user from a business account\n"
            "`!corp deposit <business> <amount>` - deposit from your balance into a business account\n"
            "`!corp info <business>` - show info about a business\n"
            "`!corp grantpay <business> <recipient> <amount>` - pay from a business grant to a user or another business\n"
            "*Payroll System Commands*\n"
            "`!corp payroll add <business> <recipient> <amount> <bank|grant>` - add a daily payroll entry\n"
            "`!corp payroll rm <payroll_id>` - remove a payroll entry\n"
            "`!corp payroll list [business]` - list payroll entries, optionally filtered to a business \n"
        )

    @dir.command(name="bj")
    async def directory_bj(self, ctx):
        await ctx.send(
            "**Blackjack Commands**\n"
            "`!bj start <bet (optional)>` - start a new game (default bet is semi random)\n"
            "`!bj hit` - draw a card\n"
            "`!bj stand` - end your turn, dealer plays\n"
            "`!bj hand` - show current hand\n"
        )

    @dir.command(name="bet")
    async def directory_bet(self, ctx):
        await ctx.send(
            "**Betting Commands**\n"
            "`!bet create \"Opt A | Opt B | Opt C\" 10 @arbiter [description...]` - create a new bet\n"
            "`!bet resolve <bet_id> <1|2>` - resolve a bet\n"
            "`!bet leave <bet_id>` - leave a bet\n"
            "`!bet cancel <bet_id>` - cancel a bet\n"
            "`!bet status <bet_id>` - show the status of a bet\n"
        )

    @dir.command(name="user")
    async def directory_user(self, ctx):
        await ctx.send(
            "**User Management Commands**\n"
            "`!user kick <@user>` - kick a user from the server\n"
            "`!user ban <@user>` - ban a user from the server\n"
            "`!user unban <user id>` - unban a user from the server\n"
            "`!user mute <@user> <duration in minutes>` - mute a user for a duration\n"
            "`!user unmute <@user>` - unmute a user\n"
        )

    @dir.command(name="bureau")
    async def directory_bureau(self, ctx):
        await ctx.send(
            "**Bureau of Shiftycoin Administration Commands**\n"
            "`!bureau brackets` - show the configured tax brackets and rates\n"
            "`!bureau centralbal` - show the balance of the central tax collection account\n"
        )

    @dir.command(name="srvl")
    async def directory_srvl(self, ctx):
        await ctx.send(
            "**SRVL Commands**\n"
            "`!srvl set <channel>` - set the SRVL channel for this server\n"
            "`!srvl rm` - remove the configured SRVL channel for this server\n"
        )

    @dir.command(name="api")
    async def directory_api(self, ctx):
        await ctx.send(
            "**API Management Commands**\n"
            "`!api token` - generate a new API token and DM it to you\n"
            "`!api revoke` - remove your existing API token\n"
            "`!api status` - check whether you have an active API token and when it expires"
        )


async def setup(bot):
    await bot.add_cog(DirectoryCog(bot))
