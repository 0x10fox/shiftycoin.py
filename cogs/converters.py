from discord.ext import commands


class MemberOrUser(commands.Converter):
    """Accepts a guild member mention/name/ID, or falls back to a global user ID lookup."""
    async def convert(self, ctx, argument):
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except commands.BadArgument:
            pass
        try:
            return await commands.UserConverter().convert(ctx, argument)
        except commands.BadArgument:
            pass
        raise commands.BadArgument(f'Member or user "{argument}" not found.')
