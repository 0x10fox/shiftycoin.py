import discord
from discord.ext import commands
from utils import (
    get_balance, add_balance, load_shiftycoin, mass_redistribute_shiftycoin,
    REWARD_EMOTE, PENALTY_EMOTE, REACTIONS_PER_SC, OID,
    log_transaction, get_transaction, get_transactions_for_user,
)
from cogs.converters import MemberOrUser

APPLIED_REACTIONS = {}


class ShiftycoinCog(commands.Cog, name="Shiftycoin"):
    def __init__(self, bot):
        self.bot = bot

    async def _sync_and_apply(self, message: discord.Message):
        if message.author.bot:
            return
        mid = message.id
        if mid not in APPLIED_REACTIONS:
            APPLIED_REACTIONS[mid] = {"reward": 0, "penalty": 0}

        reward_count = 0
        penalty_count = 0
        for r in message.reactions:
            emoji_str = str(r.emoji)
            if emoji_str == REWARD_EMOTE:
                reward_count = r.count
            elif emoji_str == PENALTY_EMOTE:
                penalty_count = r.count

        reward_units = reward_count // REACTIONS_PER_SC
        penalty_units = penalty_count // REACTIONS_PER_SC

        prev_reward = APPLIED_REACTIONS[mid]["reward"]
        prev_penalty = APPLIED_REACTIONS[mid]["penalty"]

        delta_reward = reward_units - prev_reward
        delta_penalty = penalty_units - prev_penalty

        if delta_reward != 0:
            sc_delta = delta_reward * 10
            add_balance(message.author.id, sc_delta)
            if sc_delta > 0:
                log_transaction("reaction_reward", "system:reactions", str(message.author.id), sc_delta, {"message_id": mid})
            else:
                log_transaction("reaction_reward_removed", str(message.author.id), "system:reactions", -abs(sc_delta), {"message_id": mid})
        if delta_penalty != 0:
            sc_delta = delta_penalty * -20
            add_balance(message.author.id, sc_delta)
            if sc_delta < 0:
                log_transaction("reaction_penalty", str(message.author.id), "system:reactions", -abs(sc_delta), {"message_id": mid})
            else:
                log_transaction("reaction_penalty_removed", "system:reactions", str(message.author.id), sc_delta, {"message_id": mid})

        APPLIED_REACTIONS[mid]["reward"] = reward_units
        APPLIED_REACTIONS[mid]["penalty"] = penalty_units

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or reaction.message.author.bot:
            return
        try:
            msg = await reaction.message.channel.fetch_message(reaction.message.id)
        except Exception:
            msg = reaction.message
        await self._sync_and_apply(msg)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or reaction.message.author.bot:
            return
        try:
            msg = await reaction.message.channel.fetch_message(reaction.message.id)
        except Exception:
            msg = reaction.message
        await self._sync_and_apply(msg)

    @commands.group(name="sc", invoke_without_command=True)
    async def sc(self, ctx):
        """Root command for shiftycoin. Use subcommands: balance, send, request."""
        await ctx.send("Shiftycoin commands: `!sc bal` `!sc send` `!sc request`")

    @sc.command(name="bal")
    async def balance(self, ctx, member: MemberOrUser = None):
        """Show your balance or another member's balance."""
        target = member or ctx.author
        bal = get_balance(target.id)
        if member:
            await ctx.send(f"{ctx.author.mention}: {target.mention}'s balance: **{float(bal):.2f} SC**")
        else:
            await ctx.send(f"{ctx.author.mention}, your balance: **{float(bal):.2f} SC**")

    @sc.command(name="send")
    async def send(self, ctx, member: MemberOrUser, amount: float):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        sender_id = ctx.author.id
        receiver_id = member.id
        sender_bal = get_balance(sender_id)
        if sender_bal < amount:
            await ctx.send("Insufficient balance.")
            return
        add_balance(sender_id, -amount)
        new_receiver_bal = add_balance(receiver_id, amount)
        log_transaction("send", str(sender_id), str(receiver_id), amount)
        new_sender_bal = get_balance(sender_id)
        await ctx.send(
            f"{ctx.author.mention} sent **{amount} SC** to {member.mention}.\n"
            f"Your new balance: **{new_sender_bal} SC**\n"
            f"{member.mention}'s new balance: **{new_receiver_bal} SC**"
        )

    @sc.command(name="request")
    async def request_sc(self, ctx, member: MemberOrUser, amount: float):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        if member.bot:
            await ctx.send("Cannot request from a bot.")
            return

        amount = round(amount, 2)
        bot = self.bot

        class PayView(discord.ui.View):
            def __init__(self_, requester_id: int, payer_id: int, amount: float):
                super().__init__(timeout=None)
                self_.requester_id = requester_id
                self_.payer_id = payer_id
                self_.amount = amount
                self_.paid = False

            @discord.ui.button(label="Pay", style=discord.ButtonStyle.green)
            async def pay(self_, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self_.payer_id:
                    await interaction.response.send_message("This request is not for you.", ephemeral=True)
                    return
                if self_.paid:
                    await interaction.response.send_message("This request has already been paid.", ephemeral=True)
                    return

                payer_bal = get_balance(self_.payer_id)
                if payer_bal < self_.amount:
                    await interaction.response.send_message("Insufficient balance to pay.", ephemeral=True)
                    return

                add_balance(self_.payer_id, -self_.amount)
                new_receiver_bal = add_balance(self_.requester_id, self_.amount)
                log_transaction("send", str(self_.payer_id), str(self_.requester_id), self_.amount)
                self_.paid = True

                button.disabled = True
                await interaction.response.edit_message(
                    content=f"You paid **{self_.amount} SC** to <@{self_.requester_id}>. Your new balance: **{get_balance(self_.payer_id)} SC**",
                    view=self_
                )

                requester = bot.get_user(self_.requester_id)
                if requester:
                    try:
                        await requester.send(f"<@{self_.payer_id}> paid you **{self_.amount} SC**. Your new balance: **{new_receiver_bal} SC**")
                    except Exception:
                        pass

        dm_content = (
            f"{ctx.author.mention} is requesting **{amount} SC** from you.\n"
            "Click the button below to pay them."
        )
        view = PayView(ctx.author.id, member.id, amount)

        try:
            await member.send(dm_content, view=view)
        except discord.Forbidden:
            await ctx.send(f"Could not DM {member.mention}. They may have DMs disabled.")
            return
        except Exception:
            await ctx.send("Failed to send request DM.")
            return

        await ctx.send(f"Request sent to {member.mention} for **{amount} SC**. They will receive a DM with the request.")

    @sc.command(name="redistribute")
    async def redistribute(self, ctx):
        if str(ctx.author.id) != str(OID):
            await ctx.send("You do not have permission to use this command.")
            return
        new_balances = mass_redistribute_shiftycoin()
        if not new_balances:
            await ctx.send("there is no economy :(")
            return
        await ctx.send(f"The Great Redistribution has occurred. The playing field has been leveled for all {len(new_balances)} individuals. \n"
                       "**May the users of our Shiftycoin find renewed hope and opportunity in this new era of equality.**")

    @sc.group(name="ledger", invoke_without_command=True)
    async def sc_ledger(self, ctx, tx_id: str = None):
        """Look up a transaction by its UUID."""
        if tx_id is None:
            await ctx.send("Usage: `!sc ledger <tx_id>` or `!sc ledger user [@user]`")
            return
        tx = get_transaction(tx_id)
        if not tx:
            await ctx.send(f"Transaction `{tx_id}` not found.")
            return
        lines = [
            f"**Transaction:** `{tx['id']}`",
            f"**Type:** {tx['type']}",
            f"**Amount:** {'+' if tx['amount'] >= 0 else ''}{tx['amount']:.2f} SC",
            f"**From:** `{tx['from_id']}`",
            f"**To:** `{tx['to_id']}`",
            f"**Time:** {tx['timestamp']}",
        ]
        if tx.get("metadata"):
            for k, v in tx["metadata"].items():
                lines.append(f"**{k}:** {v}")
        await ctx.send("\n".join(lines))

    @sc_ledger.command(name="user")
    async def sc_ledger_user(self, ctx, member: MemberOrUser = None):
        """List your recent transactions, or another user's (owner only)."""
        target = member or ctx.author
        if target.id != ctx.author.id and str(ctx.author.id) != str(OID):
            await ctx.send("You can only view your own transactions.")
            return
        txs = get_transactions_for_user(str(target.id))
        if not txs:
            await ctx.send(f"No transactions found for {target.mention}.")
            return
        lines = [
            f"`{tx['id']}` | **{tx['type']}** | **{'+' if tx['amount'] >= 0 else ''}{tx['amount']:.2f} SC** | {tx['timestamp'][:10]}"
            for tx in txs[:20]
        ]
        header = f"Recent transactions for {target.mention} (up to 20):\n"
        await ctx.send(header + "\n".join(lines))

    @sc.command(name="globalbal")
    async def globalbal(self, ctx):
        shiftycoin = load_shiftycoin()
        def get_global_balance():
            shiftycoin = load_shiftycoin()
            total = sum(float(v) for v in shiftycoin.values())
            return round(total, 2)
        if not shiftycoin:
            await ctx.send("No balances recorded.")
            return

        items = sorted(shiftycoin.items(), key=lambda kv: -float(kv[1]))
        lines = [f"<@{uid}>: **{float(bal):.2f} SC**" for uid, bal in items]

        header = "Shiftycoin balances:\n"
        chunk = header
        for line in lines:
            if len(chunk) + len(line) + 1 > 2000:
                await ctx.send(chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await ctx.send(chunk)
        total = get_global_balance()
        await ctx.send(f"Global Shiftycoin balance: **{total} SC**")


async def setup(bot):
    await bot.add_cog(ShiftycoinCog(bot))
