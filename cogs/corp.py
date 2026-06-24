import asyncio
import discord
from discord.ext import commands
from utils import (
    create_business, find_business, get_business_info, pay_from_business,
    load_businesses, save_businesses, add_balance, get_balance,
    load_payrolls, save_payrolls, _parse_user_identifier, _process_payrolls,
    log_transaction,
)
from utils import OID


class CorpCog(commands.Cog, name="Corp"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.loop.create_task(self._payroll_worker())

    async def _payroll_worker(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await _process_payrolls()
            except Exception:
                pass
            await asyncio.sleep(24 * 60 * 60)

    @commands.group(name="corp", invoke_without_command=True)
    async def corp(self, ctx):
        await ctx.send("Corporation commands: `!corp start <name>` `!corp pay <corp> <@user> <amount>` `!corp info <corp>`")

    @corp.command(name="start")
    async def corp_start(self, ctx, *, name: str):
        try:
            rec = create_business(ctx.author.id, name)
            await ctx.send(
                f"Business created: **{rec['name']}** (ID: `{rec['id']}`)\n"
                f"Owner: {ctx.author.mention}\n"
                f"SC account key: `{rec['account_key']}`\n"
                f"Bank balance: **0.00 SC**\n"
                f"Grant balance: **{rec['grant_balance']:.2f} SC**"
            )
        except Exception as e:
            await ctx.send(f"Failed to create business: {e}")

    @corp.command(name="pay")
    async def corp_pay(self, ctx, identifier: str, recipient: str, amount: float):
        rec, bid = find_business(identifier)
        if not rec:
            await ctx.send("Business not found (use id or exact name).")
            return

        allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or str(ctx.author.id) == str(OID))
        if not allowed:
            await ctx.send("You do not have permission to pay from this business.")
            return

        try:
            amount = round(float(amount), 2)
        except Exception:
            await ctx.send("Invalid amount.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        try:
            target_rec, target_bid = find_business(recipient)
            if target_rec:
                target_acct = target_rec.get("account_key")
                if not target_acct:
                    await ctx.send("Recipient business missing account key.")
                    return
                new_bal = pay_from_business(bid, ctx.author.id, target_acct, amount)
                await ctx.send(
                    f"Paid **{amount:.2f} SC** from **{rec['name']}** to business **{target_rec['name']}**.\n"
                    f"New {rec['name']} balance: **{new_bal:.2f} SC**"
                )
                return

            uid = None
            stripped = "".join(ch for ch in recipient if ch.isdigit())
            if stripped:
                try:
                    uid = int(stripped)
                except Exception:
                    uid = None

            if uid is None and ctx.guild:
                member = discord.utils.find(lambda m: m.name == recipient or (m.nick and m.nick == recipient), ctx.guild.members)
                if member:
                    uid = member.id

            if uid is None:
                try:
                    uid = int(recipient)
                except Exception:
                    uid = None

            if uid is None:
                await ctx.send("Could not resolve recipient as a business or user (use business id/name or @user).")
                return

            new_bal = pay_from_business(bid, ctx.author.id, uid, amount)
            await ctx.send(f"Paid **{amount:.2f} SC** from **{rec['name']}** to <@{uid}>.\nNew {rec['name']} balance: **{new_bal:.2f} SC**")
        except Exception as e:
            await ctx.send(f"Payment failed: {e}")

    @corp.command(name="info")
    async def corp_info(self, ctx, identifier: str):
        info = get_business_info(identifier)
        if not info:
            await ctx.send("Business not found (use id or exact name).")
            return
        owner = self.bot.get_user(int(info["owner"]))
        owner_display = owner.mention if owner else f"`{info['owner']}`"
        await ctx.send(
            f"Business: **{info['name']}** (ID: `{info['id']}`)\n"
            f"Owner: {owner_display}\n"
            f"Bank balance: **{info['main_balance']:.2f} SC**\n"
            f"Grant balance: **{info['grant_balance']:.2f} SC**\n"
            f"Created: {info.get('created_at')}"
        )

    @corp.command(name="grantpay")
    async def corp_grantpay(self, ctx, identifier: str, recipient: str, amount: float):
        """Pay from a business' grant balance to a user or another business."""
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
            await ctx.send("Payer business not found (use id or exact name).")
            return

        allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or str(ctx.author.id) == str(OID))
        if not allowed:
            await ctx.send("You do not have permission to use this business' grant funds.")
            return

        businesses = load_businesses()
        payer = businesses.get(bid)
        if not payer:
            await ctx.send("Business record missing while processing.")
            return
        payer_grant = round(float(payer.get("grant_balance", 0.0)), 2)
        if payer_grant < amount:
            await ctx.send(f"Insufficient grant funds. Available: **{payer_grant:.2f} SC**")
            return

        target_rec, target_bid = find_business(recipient)
        if target_rec:
            businesses[bid]["grant_balance"] = round(payer_grant - amount, 2)
            save_businesses(businesses)
            target_acct = businesses[target_bid].get("account_key")
            if not target_acct:
                await ctx.send("Recipient business missing account key.")
                return
            new_target_main = add_balance(target_acct, amount)
            log_transaction("grantpay", f"grant:{bid}", str(target_acct), amount, {"payer_business_id": bid, "payer_business_name": rec['name'], "recipient_business_id": target_bid, "recipient_business_name": target_rec['name']})
            payer_new_grant = businesses[bid]["grant_balance"]
            await ctx.send(
                f"Transferred **{amount:.2f} SC** from grant of **{rec['name']}** to SC account of **{target_rec['name']}**.\n"
                f"{rec['name']} grant remaining: **{payer_new_grant:.2f} SC** | "
                f"{target_rec['name']} SC balance: **{new_target_main:.2f} SC**"
            )
            return

        uid = None
        stripped = "".join(ch for ch in recipient if ch.isdigit())
        if stripped:
            try:
                uid = int(stripped)
            except Exception:
                uid = None

        if uid is None and ctx.guild:
            member = discord.utils.find(lambda m: m.name == recipient or (m.nick and m.nick == recipient), ctx.guild.members)
            if member:
                uid = member.id

        if uid is None:
            try:
                possible = int(recipient)
                uid = possible
            except Exception:
                uid = None

        if uid is None:
            await ctx.send("Could not resolve recipient as a business or user (use business id/name or @user).")
            return

        businesses[bid]["grant_balance"] = round(payer_grant - amount, 2)
        save_businesses(businesses)
        new_bal = add_balance(uid, amount)
        log_transaction("grantpay", f"grant:{bid}", str(uid), amount, {"payer_business_id": bid, "payer_business_name": rec['name']})
        await ctx.send(
            f"Transferred **{amount:.2f} SC** from grant of **{rec['name']}** to <@{uid}>.\n"
            f"{rec['name']} grant remaining: **{businesses[bid]['grant_balance']:.2f} SC**\n"
            f"Recipient new balance: **{new_bal:.2f} SC**"
        )

    @corp.command(name="deposit")
    async def corp_deposit(self, ctx, identifier: str, amount: float):
        """Deposit SC from your personal balance into a business account."""
        try:
            amount = round(float(amount), 2)
        except Exception:
            await ctx.send("Invalid amount.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        sender_id = ctx.author.id
        sender_bal = get_balance(sender_id)
        if sender_bal < amount:
            await ctx.send("Insufficient Shiftycoin balance.")
            return

        rec, bid = find_business(identifier)
        if not rec:
            await ctx.send("Business not found (use id or exact name).")
            return

        acct = rec.get("account_key")
        add_balance(sender_id, -amount)
        new_acct_bal = add_balance(acct, amount)
        log_transaction("deposit", str(sender_id), str(acct), -amount, {"business_id": bid, "business_name": rec['name']})
        new_sender_bal = get_balance(sender_id)

        await ctx.send(
            f"{ctx.author.mention} deposited **{amount:.2f} SC** into **{rec['name']}**.\n"
            f"Your new balance: **{new_sender_bal:.2f} SC**\n"
            f"Business balance: **{new_acct_bal:.2f} SC**"
        )

    @corp.group(name="payroll", invoke_without_command=True)
    async def corp_payroll(self, ctx):
        await ctx.send("Payroll commands: `!corp payroll add <business> <@user/id/name> <amount> <bank|grant>` `!corp payroll rm <payroll_id>` `!corp payroll list <payroll_id|business>` `!corp payroll run`")

    @corp_payroll.command(name="add")
    async def corp_payroll_add(self, ctx, identifier: str, recipient: str, amount: float, source: str = "bank"):
        """Add a daily payroll entry for a business (source: bank or grant)."""
        rec, bid = find_business(identifier)
        if not rec:
            await ctx.send("Business not found (use id or exact name).")
            return

        allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or str(ctx.author.id) == str(OID))
        if not allowed:
            await ctx.send("You do not have permission to manage payrolls for this business.")
            return

        try:
            amount = round(float(amount), 2)
        except Exception:
            await ctx.send("Invalid amount.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return

        source = source.lower()
        if source not in ("bank", "grant"):
            await ctx.send("Source must be 'bank' or 'grant'.")
            return

        import uuid, datetime
        uid = _parse_user_identifier(ctx, recipient)
        if uid is None:
            await ctx.send("Could not resolve recipient as a user (use mention, id, or exact name).")
            return

        payrolls = load_payrolls()
        pid = str(uuid.uuid4())
        payrolls[pid] = {
            "id": pid,
            "business_id": bid,
            "recipient_id": int(uid),
            "amount": round(amount, 2),
            "source": source,
            "last_paid": None,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z"
        }
        save_payrolls(payrolls)
        await ctx.send(f"Payroll created (ID: `{pid}`): pay <@{uid}> **{amount:.2f} SC** daily from **{rec['name']}** ({source}).")

    @corp_payroll.command(name="rm")
    async def corp_payroll_rm(self, ctx, payroll_id: str):
        payrolls = load_payrolls()
        p = payrolls.get(payroll_id)
        if not p:
            await ctx.send("Payroll ID not found.")
            return

        rec, bid = find_business(p.get("business_id"))
        if not rec:
            await ctx.send("Associated business record not found; cannot verify permission.")
            return
        allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or str(ctx.author.id) == str(OID))
        if not allowed:
            await ctx.send("You do not have permission to remove this payroll.")
            return

        payrolls.pop(payroll_id, None)
        save_payrolls(payrolls)
        await ctx.send(f"Payroll `{payroll_id}` removed.")

    @corp_payroll.command(name="list")
    async def corp_payroll_list(self, ctx, identifier: str):
        """Look up a payroll by ID, or list all payrolls for a business by name/ID."""
        payrolls = load_payrolls()
        p = payrolls.get(identifier)
        if p:
            await ctx.send(
                f"**Payroll** `{p['id']}`\n"
                f"Business: `{p.get('business_id')}` | Recipient: <@{p.get('recipient_id')}>\n"
                f"Amount: **{p.get('amount'):.2f} SC**/day | Source: {p.get('source')}\n"
                f"Last paid: {p.get('last_paid') or 'never'} | Created: {p.get('created_at')}"
            )
            return
        brec, bid = find_business(identifier)
        if brec:
            entries = [p for p in payrolls.values() if p.get("business_id") == bid]
            if not entries:
                await ctx.send(f"No payrolls found for **{brec['name']}**.")
                return
            lines = [
                f"`{p['id']}` | Recipient: <@{p.get('recipient_id')}> | **{p.get('amount'):.2f} SC**/day | {p.get('source')} | Last paid: {p.get('last_paid') or 'never'}"
                for p in entries
            ]
            chunk = f"Payrolls for **{brec['name']}**:\n"
            for ln in lines:
                if len(chunk) + len(ln) + 1 > 2000:
                    await ctx.send(chunk)
                    chunk = ""
                chunk += ln + "\n"
            if chunk:
                await ctx.send(chunk)
            return
        await ctx.send(f"No payroll or business found matching `{identifier}`.")

    @corp_payroll.command(name="run")
    async def corp_payroll_run(self, ctx, identifier: str = None):
        """Manually run payroll processing. OID or appropriate permissions required to force run for all businesses."""
        summary = await _process_payrolls()
        processed = summary.get("processed", [])
        skipped = summary.get("skipped", [])
        lines = []
        if processed:
            for p in processed:
                lines.append(f"Processed payroll `{p['id']}`: paid **{p['paid']:.2f} SC** ({p['days']} day(s)).")
        if skipped:
            for s in skipped:
                reason = s.get("reason")
                if reason == "insufficient_bank_funds" or reason == "insufficient_grant_funds":
                    lines.append(f"Skipped `{s['id']}`: insufficient funds (need {s['need']:.2f}, have {s['have']:.2f}).")
                else:
                    lines.append(f"Skipped `{s['id']}`: {reason}.")
        if not lines:
            await ctx.send("No payrolls processed.")
            return
        chunk = ""
        for ln in lines:
            if len(chunk) + len(ln) + 1 > 2000:
                await ctx.send(chunk)
                chunk = ""
            chunk += ln + "\n"
        if chunk:
            await ctx.send(chunk)


async def setup(bot):
    await bot.add_cog(CorpCog(bot))
