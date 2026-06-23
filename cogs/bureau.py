from discord.ext import commands
from utils import (
    collect_taxes, TAX_ACCOUNT, load_shiftycoin, add_balance,
    find_business, load_businesses, save_businesses
)
from utils import OID


class BureauCog(commands.Cog, name="Bureau"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="bureau", invoke_without_command=True)
    async def bureau(self, ctx):
        """Root command for Bureau of Shiftycoin Administration interface commands. Use subcommands: collect, brackets, centralbal, grant."""
        await ctx.send("Bureau of Shiftycoin Administration commands: `!bureau collect` `!bureau brackets` `!bureau centralbal` `!bureau grant`")

    @bureau.command(name="collect")
    async def _collecttax(self, ctx, mode: str = None):
        force = False
        if mode:
            if isinstance(mode, str) and mode.lower() in ("force", "true", "1"):
                if ctx.author.id == OID:
                    force = True
        summary = collect_taxes(force=force)
        months = summary.get("months", 0)
        total = summary.get("total_collected", 0.0)
        per_user = summary.get("per_user", {})
        if months == 0 and total == 0.0:
            await ctx.send("No tax collection performed: taxes are already up to date for this month.")
            return
        lines = [f"Collected taxes for {months} month(s). Total collected: **{total} SC**."]
        shown = 0
        for uid, amt in sorted(per_user.items(), key=lambda kv: -kv[1]):
            if shown >= 8:
                break
            lines.append(f"<@{uid}>: **{amt} SC**")
            shown += 1
        if len(per_user) > shown:
            lines.append(f"...and {len(per_user) - shown} more users taxed.")
        await ctx.send("\n".join(lines))

    @bureau.command(name="centralbal")
    async def taxbal(self, ctx):
        """Show the central balance."""
        shiftycoin = load_shiftycoin()
        bal = shiftycoin.get(str(TAX_ACCOUNT))
        if bal is None:
            await ctx.send(f"Account ({TAX_ACCOUNT}) not found.")
            return
        try:
            bal_f = float(bal)
        except Exception:
            bal_f = 0.0
        await ctx.send(f"({TAX_ACCOUNT}) balance: **{bal_f:.2f} SC**")

    @bureau.command(name="brackets")
    async def tax_brackets(self, ctx):
        """Show configured tax brackets and rates."""
        lines = [
            "Configured tax brackets (balance -> tax rate):",
            "≥ 1,000,000,000 SC -> 99%",
            "> 100,000,000 SC -> 80%",
            "> 10,000,000 SC -> 65%",
            "> 1,000,000 SC -> 40%",
            "> 500,000 SC -> 30%",
            "> 100,000 SC -> 20%",
            "> 50,000 SC -> 10%",
            "> 10,000 SC -> 5%",
            "> 1,000 SC -> 3%",
            "≤ 1,000 SC -> 0%"
        ]
        await ctx.send("\n".join(lines))

    @bureau.command(name="grant")
    async def bureau_grant(self, ctx, identifier: str, amount: float):
        """OID-only: move SC from TAX_ACCOUNT into a business' grant balance."""
        if str(ctx.author.id) != str(OID):
            await ctx.send("You do not have permission to use this command.")
            return

        try:
            amount = round(float(amount), 2)
        except Exception:
            await ctx.send("Invalid amount.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        rec, bid = find_business(identifier)
        if not rec:
            await ctx.send("Business not found (use id or exact name).")
            return

        add_balance(TAX_ACCOUNT, -amount)
        businesses = load_businesses()
        if bid not in businesses:
            await ctx.send("Business record not found while updating.")
            return
        businesses[bid]["grant_balance"] = round(float(businesses[bid].get("grant_balance", 0.0)) + amount, 2)
        save_businesses(businesses)

        new_tax_bal = round(float(load_shiftycoin().get(str(TAX_ACCOUNT), 0.0)), 2)
        await ctx.send(
            f"Transferred **{amount:.2f} SC** from {TAX_ACCOUNT} to business **{rec['name']}** (grant account).\n"
            f"New {TAX_ACCOUNT} balance: **{new_tax_bal:.2f} SC**\n"
            f"Business grant balance: **{businesses[bid]['grant_balance']:.2f} SC**"
        )


async def setup(bot):
    await bot.add_cog(BureauCog(bot))
