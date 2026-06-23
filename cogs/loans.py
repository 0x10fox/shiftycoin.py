import discord
from discord.ext import commands
from utils import (
    get_loan_record, take_loan_for_user, repay_loan_for_user,
    accrue_interest_for_user, accrue_interest_all, get_balance, add_balance,
    BASE_LOAN_RATE
)


class LoanCog(commands.Cog, name="Loans"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="loan", invoke_without_command=True)
    async def sc_loan(self, ctx):
        await ctx.send("Loan commands: `!loan take <amt>` `!loan repay <amt>` `!loan info` `!loan accrue`")

    @sc_loan.command(name="take")
    async def sc_loan_take(self, ctx, amount: float):
        uid = ctx.author.id
        try:
            amount = round(amount, 2)
            if amount <= 0:
                await ctx.send("Amount must be positive.")
                return
            if amount > 500.0:
                await ctx.send("Maximum single loan amount is 500 SC.")
                return
            rec = take_loan_for_user(uid, amount)
            await ctx.send(
                f"{ctx.author.mention} took a loan of **{amount} SC**.\n"
                f"Loan balance: **{rec['balance']} SC** | Monthly rate: **{rec['rate']*100:.2f}%** | Active loans: {rec['active_count']}"
            )
        except Exception as e:
            await ctx.send(f"Loan failed: {e}")

    @sc_loan.command(name="repay")
    async def sc_loan_repay(self, ctx, amount: float):
        uid = ctx.author.id
        try:
            amount = round(amount, 2)
            if amount <= 0:
                await ctx.send("Amount must be positive.")
                return
            bal = get_balance(uid)
            if bal < amount:
                await ctx.send("Insufficient Shiftycoin balance to repay that amount.")
                return
            add_balance(uid, -amount)
            rec, repaid, over = repay_loan_for_user(uid, amount)
            msg = f"{ctx.author.mention} repaid **{repaid} SC** on their loan. New loan balance: **{rec['balance']} SC**."
            if over > 0:
                msg += f" Overpayment of **{over} SC** was refunded to your balance."
            await ctx.send(msg)
        except Exception as e:
            await ctx.send(f"Repayment failed: {e}")

    @sc_loan.command(name="info")
    async def sc_loan_info(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        rec = get_loan_record(target.id)
        last = rec.get("last_accrued") or "never"
        await ctx.send(
            f"{target.mention} loan info:\n"
            f"Balance: **{rec['balance']} SC**\n"
            f"Monthly rate: **{rec.get('rate', BASE_LOAN_RATE)*100:.2f}%**\n"
            f"Active loans: {rec.get('active_count', 0)}\n"
            f"Last interest applied: {last}"
        )

    @sc_loan.command(name="accrue")
    async def sc_loan_accrue(self, ctx):
        """Manually trigger accrual for the invoking user (or for all if user has manage_guild)."""
        uid = ctx.author.id
        if ctx.author.guild_permissions.manage_guild:
            results = accrue_interest_all()
            if not results:
                await ctx.send("No loans required accrual.")
                return
            msg_lines = ["Accrued interest for users:"]
            for uid_str, info in results.items():
                msg_lines.append(f"<@{uid_str}>: +{info['interest']} SC over {info['months']} month(s)")
            await ctx.send("\n".join(msg_lines))
            return

        months, interest = accrue_interest_for_user(uid)
        if months == 0:
            await ctx.send("No interest to accrue for your loans at this time.")
        else:
            new_rec = get_loan_record(uid)
            await ctx.send(f"Accrued interest for {months} month(s): **{interest} SC**. New loan balance: **{new_rec['balance']} SC**")


async def setup(bot):
    await bot.add_cog(LoanCog(bot))
