import discord
from discord.ext import commands
from utils import (
    create_user_token, revoke_user_token, get_token_info, TOKEN_TTL_HOURS,
    create_api_key, revoke_api_key, list_api_keys,
    OID,
)


class ApiCog(commands.Cog, name="API"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="api", invoke_without_command=True)
    async def api(self, ctx):
        await ctx.send("API commands: `!api token` `!api revoke` `!api status`")

    @api.command(name="token")
    async def api_token(self, ctx):
        """Generate a new API token and DM it to you. Replaces any existing token."""
        token, expires_at = create_user_token(str(ctx.author.id))
        try:
            await ctx.author.send(
                f"Your Shiftycoin API token (valid for {TOKEN_TTL_HOURS}h):\n"
                f"```\n{token}\n```\n"
                f"Expires: `{expires_at}`\n\n"
                f"Include it in requests as:\n"
                f"`Authorization: Bearer {token}`"
            )
            await ctx.send(f"{ctx.author.mention} your API token has been sent to your DMs.")
        except discord.Forbidden:
            await ctx.send("Could not DM you. Please enable DMs from server members.")

    @api.command(name="revoke")
    async def api_revoke(self, ctx):
        """Revoke your current API token."""
        if revoke_user_token(str(ctx.author.id)):
            await ctx.send(f"{ctx.author.mention} your API token has been revoked.")
        else:
            await ctx.send("You don't have an active token to revoke.")

    @api.command(name="status")
    async def api_status(self, ctx):
        """Check whether you have an active API token and when it expires."""
        info = get_token_info(str(ctx.author.id))
        if not info:
            await ctx.send("You have no API token. Use `!api token` to generate one.")
            return
        if info["expired"]:
            await ctx.send(
                f"Your API token expired at `{info['expires_at']}`. "
                "Use `!api token` to generate a new one."
            )
        else:
            await ctx.send(
                f"You have an active API token.\n"
                f"Created: `{info['created_at']}`\n"
                f"Expires: `{info['expires_at']}`"
            )


    # ── App-key management (OID only) ─────────────────────────────────────────

    @api.group(name="key", invoke_without_command=True)
    async def api_key(self, ctx):
        await ctx.send("App key commands: `!api key create <name>` `!api key revoke <name>` `!api key list`")

    @api_key.command(name="create")
    async def api_key_create(self, ctx, *, name: str):
        """Generate a new named app key and DM it to you. OID only."""
        if str(ctx.author.id) != str(OID):
            await ctx.send("Only the bot owner can manage app keys.")
            return
        try:
            key, record = create_api_key(name)
        except ValueError as e:
            await ctx.send(str(e))
            return
        try:
            await ctx.author.send(
                f"New app key **{record['name']}**:\n"
                f"```\n{key}\n```\n"
                f"Created: `{record['created_at']}`\n\n"
                f"Include it in requests as:\n"
                f"`X-API-Key: {key}`"
            )
            await ctx.send(f"App key **{name}** created and sent to your DMs.")
        except discord.Forbidden:
            await ctx.send("Could not DM you. Please enable DMs from server members.")

    @api_key.command(name="revoke")
    async def api_key_revoke(self, ctx, *, name: str):
        """Revoke an app key by name. OID only."""
        if str(ctx.author.id) != str(OID):
            await ctx.send("Only the bot owner can manage app keys.")
            return
        if revoke_api_key(name):
            await ctx.send(f"App key **{name}** has been revoked.")
        else:
            await ctx.send(f'No app key named "{name}" was found.')

    @api_key.command(name="list")
    async def api_key_list(self, ctx):
        """List all app keys (name, created date, key preview). OID only."""
        if str(ctx.author.id) != str(OID):
            await ctx.send("Only the bot owner can manage app keys.")
            return
        keys = list_api_keys()
        if not keys:
            await ctx.send("No app keys exist yet. Use `!api key create <name>` to create one.")
            return
        lines = [f"**{k['name']}** — created `{k['created_at']}` — key: `{k['key_preview']}`" for k in keys]
        await ctx.send("App keys:\n" + "\n".join(lines))


async def setup(bot):
    await bot.add_cog(ApiCog(bot))
