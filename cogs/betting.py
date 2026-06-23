import discord
from discord.ext import commands
from utils import (
    load_bets, save_bets, get_balance, add_balance, check_message_reactions,
    BET_EMOJIS
)
from utils import OID


class BettingCog(commands.Cog, name="Betting"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        await self._multi_handle_bet_reaction_add(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        await self._multi_handle_bet_reaction_remove(reaction, user)

    async def _multi_handle_bet_reaction_add(self, reaction, user):
        if user.bot:
            return
        mid = reaction.message.id
        bets = load_bets()
        if mid not in bets:
            return
        b = bets[mid]
        emoji = str(reaction.emoji)
        if emoji not in BET_EMOJIS:
            return
        if b.get("resolved"):
            try:
                await reaction.message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass
            return

        try:
            option_index = BET_EMOJIS.index(emoji)
        except ValueError:
            return

        if option_index >= len(b.get("options", [])):
            try:
                await reaction.message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass
            return

        uid = str(user.id)

        if uid in b["entries"]:
            if b["entries"][uid] == option_index:
                return
            try:
                await reaction.message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass
            try:
                await user.send("You already have an active entry on this bet. Remove your existing reaction first to change your choice.")
            except Exception:
                pass
            return

        bal = get_balance(uid)
        if float(bal) < float(b["amount"]):
            try:
                await reaction.message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass
            try:
                await user.send(f"Insufficient Shiftycoin to join this bet (requires {b['amount']:.2f} SC).")
            except Exception:
                pass
            return

        add_balance(uid, -round(b["amount"], 2))
        b["entries"][uid] = option_index
        bets[mid] = b
        save_bets(bets)
        try:
            await user.send(f"You joined the bet ({b['options'][option_index]}) for {b['amount']:.2f} SC.")
        except Exception:
            pass

    async def _multi_handle_bet_reaction_remove(self, reaction, user):
        if user.bot:
            return
        mid = reaction.message.id
        bets = load_bets()
        if mid not in bets:
            return
        b = bets[mid]
        emoji = str(reaction.emoji)
        if emoji not in BET_EMOJIS:
            return
        if b.get("resolved"):
            return

        try:
            option_index = BET_EMOJIS.index(emoji)
        except ValueError:
            return

        uid = str(user.id)
        if uid not in b["entries"]:
            return
        if b["entries"].get(uid) != option_index:
            return
        b["entries"].pop(uid, None)
        add_balance(uid, round(b["amount"], 2))
        bets[mid] = b
        save_bets(bets)
        try:
            await user.send(f"Your bet entry was cancelled and {b['amount']:.2f} SC was refunded.")
        except Exception:
            pass

    @commands.group(name="bet", invoke_without_command=True)
    async def bet(self, ctx):
        await ctx.send("Bet commands: `!bet create \"Opt A | Opt B | Opt C\" 10 @arbiter [description...]` `!bet resolve <message_id> <1|2>` `!bet leave <message_id>` `!bet cancel <message_id>` `!bet status <message_id>`")

    @bet.command(name="create")
    async def bet_create(self, ctx, options: str, amount: float, arbiter: discord.Member, *, description: str = ""):
        """
        Create a bet with 2..9 options and an optional description.
        Usage: !bet create "Opt A | Opt B | Opt C" 10 @arbiter [description...]
        """
        try:
            amount = round(float(amount), 2)
        except Exception:
            await ctx.send("Invalid amount.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        if arbiter.bot:
            await ctx.send("Arbiter must be a real user (not a bot).")
            return

        if "|" not in options:
            await ctx.send("Options must be separated by `|` (e.g. `Opt A | Opt B`).")
            return
        opts = [o.strip() for o in options.split("|") if o.strip()]
        if len(opts) < 2:
            await ctx.send("Provide at least 2 options.")
            return
        if len(opts) > len(BET_EMOJIS):
            await ctx.send(f"Maximum {len(BET_EMOJIS)} options are supported.")
            return

        lines = [f"Bet created by {ctx.author.mention}", ""]
        if description:
            lines.append(description)
            lines.append("")
        for idx, o in enumerate(opts, start=1):
            lines.append(f"{BET_EMOJIS[idx-1]} {o}")
        lines.append("")
        lines.append(f"Amount per entry: **{amount:.2f} SC**")
        lines.append(f"Arbiter: {arbiter.mention}")
        lines.append("")
        lines.append("React with an option emoji to join. Remove your reaction to cancel your entry.")
        lines.append("The arbiter resolves the bet with `!bet resolve <bet_id> <option_number>`.")
        desc = "\n".join(lines)

        msg = await ctx.send(desc)
        try:
            await msg.edit(content=desc + f"\n\nBet ID: `{msg.id}`")
        except Exception:
            pass

        for i in range(len(opts)):
            try:
                await msg.add_reaction(BET_EMOJIS[i])
            except Exception:
                pass

        bets = load_bets()
        bets[msg.id] = {
            "creator": ctx.author.id,
            "options": opts,
            "amount": amount,
            "arbiter": arbiter.id,
            "entries": {},
            "resolved": False,
            "message_channel": ctx.channel.id,
            "description": description or ""
        }
        save_bets(bets)

    @bet.command(name="status")
    async def bet_status(self, ctx, message_id: int):
        bets = load_bets()
        b = bets.get(message_id)
        if not b:
            await ctx.send("Bet not found.")
            return
        counts = [0] * len(b["options"])
        for uid, opt in b["entries"].items():
            try:
                if 0 <= int(opt) < len(counts):
                    counts[int(opt)] += 1
            except Exception:
                continue
        opt_lines = []
        for idx, opt in enumerate(b["options"], start=1):
            opt_lines.append(f"{idx}. {opt} — {counts[idx-1]} entries ({BET_EMOJIS[idx-1]})")
        desc = (
            f"Bet {message_id} status:\n"
            f"Amount per entry: **{b['amount']:.2f} SC**\n"
            f"Arbiter: <@{b['arbiter']}>\n\n"
            + (f"{b.get('description')}\n\n" if b.get("description") else "")
            + "\n".join(opt_lines)
        )
        await ctx.send(desc)

    @bet.command(name="resolve")
    async def bet_resolve(self, ctx, message_id: int, winning: int):
        """
        Arbiter resolves a bet. winning is the 1-based index of the winning option.
        Payout: total pool divided equally among winners. If no winners, refund all.
        """
        bets = load_bets()
        b = bets.get(message_id)
        if not b:
            await ctx.send("Bet not found.")
            return
        if b.get("resolved"):
            await ctx.send("Bet already resolved.")
            return
        if ctx.author.id != int(b["arbiter"]) and ctx.author.id != int(OID):
            await ctx.send("Only the assigned arbiter (or owner) may resolve this bet.")
            return
        if not (1 <= winning <= len(b["options"])):
            await ctx.send(f"Winning option must be between 1 and {len(b['options'])}.")
            return

        # Reconcile on-message reactions into the bet entries before resolving.
        try:
            ch = None
            try:
                ch = self.bot.get_channel(int(b.get("message_channel")))
            except Exception:
                ch = None
            if ch is None:
                ch = ctx.channel

            summary = await check_message_reactions(ch, message_id)
            reaction_users = summary.get("reaction_users", {}) or {}
            print("Reaction users summary:", reaction_users)
            new_entries_map = {}
            for emoji, users in reaction_users.items():
                if emoji not in BET_EMOJIS:
                    continue
                try:
                    opt_idx = BET_EMOJIS.index(emoji)
                except ValueError:
                    continue
                if opt_idx >= len(b.get("options", [])):
                    continue
                for uid in users or []:
                    if uid is None:
                        continue
                    new_entries_map[str(uid)] = opt_idx

            stored = b.get("entries", {}) or {}
            stake = round(float(b.get("amount", 0.0)), 2)

            for uid in list(stored.keys()):
                if uid not in new_entries_map:
                    try:
                        add_balance(uid, stake)
                    except Exception:
                        pass
                    stored.pop(uid, None)

            for uid, opt_idx in new_entries_map.items():
                if uid in stored:
                    if stored.get(uid) != opt_idx:
                        stored[uid] = opt_idx
                    continue

                try:
                    bal = float(get_balance(uid))
                except Exception:
                    bal = 0.0
                if bal < stake:
                    try:
                        orig = await ch.fetch_message(message_id)
                        if 0 <= opt_idx < len(BET_EMOJIS):
                            try:
                                user_obj = self.bot.get_user(int(uid))
                                await orig.remove_reaction(BET_EMOJIS[opt_idx], user_obj or discord.Object(int(uid)))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    continue

                try:
                    add_balance(uid, -stake)
                    stored[uid] = opt_idx
                except Exception:
                    pass

            b["entries"] = stored
            bets[message_id] = b
            save_bets(bets)
        except Exception:
            pass

        entries = b["entries"] or {}
        total_entries = len(entries)
        amount = float(b["amount"])
        total_pool = round(amount * total_entries, 2)

        winners = [int(uid) for uid, opt in entries.items() if int(opt) == (winning - 1)]
        if total_entries == 0:
            b["resolved"] = True
            bets[message_id] = b
            save_bets(bets)
            await ctx.send("No entries in this bet. Nothing to do.")
            return

        if len(winners) == 0:
            for uid in entries.keys():
                try:
                    add_balance(uid, round(amount, 2))
                except Exception:
                    pass
            b["resolved"] = True
            bets[message_id] = b
            save_bets(bets)
            await ctx.send(f"No winners — all entries refunded ({total_entries} participants).")
        else:
            payout_each = round(total_pool / len(winners), 2)
            for uid in winners:
                try:
                    add_balance(uid, payout_each)
                except Exception:
                    pass
            b["resolved"] = True
            bets[message_id] = b
            save_bets(bets)
            winner_mentions = " ".join(f"<@{w}>" for w in winners)
            await ctx.send(
                f"Bet {message_id} resolved by {ctx.author.mention} — winning option: **{winning}** ({b['options'][winning-1]}).\n"
                f"Total pool: **{total_pool:.2f} SC** | Winners: {len(winners)} | Each receives: **{payout_each:.2f} SC**\n"
                f"Winners: {winner_mentions}"
            )

        try:
            ch = self.bot.get_channel(int(b["message_channel"]))
            if ch:
                try:
                    orig = await ch.fetch_message(message_id)
                    new_text = orig.content + f"\n\nRESOLVED: winning option {winning} ({b['options'][winning-1]})"
                    await orig.edit(content=new_text)
                    try:
                        await orig.clear_reactions()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    @bet.command(name="cancel")
    async def bet_cancel(self, ctx, message_id: int, *, reason: str = ""):
        """
        Cancel a bet. Only the bet creator, the arbiter, or the configured owner may cancel.
        Refunds all active entries and marks the bet resolved/cancelled.
        """
        bets = load_bets()
        b = bets.get(message_id)
        if not b:
            await ctx.send("Bet not found.")
            return
        if b.get("resolved"):
            await ctx.send("Bet already resolved or cancelled.")
            return

        creator_id = int(b.get("creator"))
        arbiter_id = int(b.get("arbiter"))
        try:
            owner_id = int(OID)
        except Exception:
            owner_id = OID

        allowed = ctx.author.id in (creator_id, arbiter_id) or str(ctx.author.id) == str(owner_id)
        if not allowed:
            await ctx.send("Only the bet creator, the arbiter, or the owner may cancel this bet.")
            return

        entries = b.get("entries", {}) or {}
        amount = round(float(b.get("amount", 0.0)), 2)
        refunded_count = 0
        if entries:
            for uid in list(entries.keys()):
                try:
                    add_balance(uid, amount)
                    refunded_count += 1
                except Exception:
                    pass

        b["resolved"] = True
        b["cancelled_by"] = ctx.author.id
        b["cancel_reason"] = reason or ""
        bets[message_id] = b
        save_bets(bets)

        try:
            ch = self.bot.get_channel(int(b.get("message_channel")))
            if ch:
                try:
                    orig = await ch.fetch_message(message_id)
                    new_text = orig.content + f"\n\nCANCELLED by {ctx.author.mention}"
                    if reason:
                        new_text += f": {reason}"
                    await orig.edit(content=new_text)
                    try:
                        await orig.clear_reactions()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

        await ctx.send(f"Bet {message_id} cancelled. Refunded {refunded_count} entr{'y' if refunded_count==1 else 'ies'}.")

    @bet.command(name="leave")
    async def bet_leave(self, ctx, message_id: int):
        """Remove your selection from a bet and refund your entry fee."""
        bets = load_bets()
        b = bets.get(message_id)
        if not b:
            await ctx.send("Bet not found.")
            return
        if b.get("resolved"):
            await ctx.send("This bet has already been resolved; you cannot leave now.")
            return

        uid = str(ctx.author.id)
        entries = b.get("entries", {}) or {}
        if uid not in entries:
            await ctx.send("You do not have an active entry on this bet.")
            return

        try:
            opt_index = int(entries.pop(uid))
        except Exception:
            opt_index = None

        amount = round(float(b.get("amount", 0.0)), 2)
        add_balance(ctx.author.id, amount)

        b["entries"] = entries
        bets[message_id] = b
        save_bets(bets)

        await ctx.send(f"{ctx.author.mention}, your entry was removed and {amount:.2f} SC has been refunded to you.")

        try:
            ch = self.bot.get_channel(int(b.get("message_channel")))
            if ch:
                try:
                    orig = await ch.fetch_message(message_id)
                    if opt_index is not None and 0 <= opt_index < len(BET_EMOJIS):
                        try:
                            await orig.remove_reaction(BET_EMOJIS[opt_index], ctx.author)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(BettingCog(bot))
