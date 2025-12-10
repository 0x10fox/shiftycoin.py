import os
import random
import asyncio
import discord
import json
from discord.ext import commands
import datetime


# config
config = json.load(open('config.json'))
TOKEN = os.getenv("DISCORD_TOKEN", config.get("token"))
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.message_content = True

# deck, scoring
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]

def new_deck(shuffle=True):
    deck = [f"{r}{s}" for r in RANKS for s in SUITS]
    if shuffle:
        random.shuffle(deck)
    return deck

def card_value(card):
    rank = card[:-1]  # drop suit
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)

def score_hand(cards):
    # Return best score <=21 if possible, else minimal over 21
    total = 0
    aces = 0
    for c in cards:
        v = card_value(c)
        total += v
        if c[:-1] == "A":
            aces += 1
    # reduce Aces from 11 to 1 as needed
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def hand_str(cards, hide_first=False):
    if hide_first and cards:
        return "?? " + " ".join(cards[1:])
    return " ".join(cards)

# game state management
class BlackjackGame:
    def __init__(self):
        self.deck = new_deck()
        self.player = []
        self.dealer = []
        self.finished = False
        self.result = None  # "win", "lose", "push"
        self.shiftycoinResult = 0

    def deal_initial(self):
        self.player.append(self.deck.pop())
        self.dealer.append(self.deck.pop())
        self.player.append(self.deck.pop())
        self.dealer.append(self.deck.pop())

    def player_hit(self):
        self.player.append(self.deck.pop())
        return self.player[-1]

    def dealer_play(self):
        # Dealer reveals and hits until >=17
        while score_hand(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
    
    def evaluateSC(self, uid):
        p = score_hand(self.player)
        d = score_hand(self.dealer)
        w = 0
        if p > 21:
            self.shiftycoinResult = (p / 10) * -1
        elif d > 21:
            self.shiftycoinResult = p / 10
            w = 1
        elif p > d:
            self.shiftycoinResult = p / 10
            w = 1
        elif p < d:
            self.shiftycoinResult = (p / 10) * -1
        else:
            self.shiftycoinResult = 0
        if get_bet([uid]) != 0 & w == 1 :
            self.shiftycoinResult = get_bet([uid])
            #print (self.shiftycoinResult, "win w bet")
        elif get_bet([uid]) != 0 & w == 0 :
            self.shiftycoinResult = get_bet([uid]) * -1
            #print (self.shiftycoinResult, "lose w bet")
        if self.finished == True :
            return self.shiftycoinResult
        else :
            return 0

    def evaluate(self):
        p = score_hand(self.player)
        d = score_hand(self.dealer)
        if p > 21:
            self.result = "lose"
        elif d > 21:
            self.result = "win"
        elif p > d:
            self.result = "win"
        elif p < d:
            self.result = "lose"
        else:
            self.result = "push"
        self.finished = True
        return self.result

# shiftycoin management
SHIFTYCOIN_FILE = "shiftycoin.json"
LOANS_FILE = "loans.json"

def load_shiftycoin():
    if os.path.exists(SHIFTYCOIN_FILE):
        with open(SHIFTYCOIN_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_shiftycoin(data):
    with open(SHIFTYCOIN_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def get_balance(user_id):
    shiftycoin = load_shiftycoin()
    return shiftycoin.get(str(user_id), 0.0)

def add_balance(user_id, amount):
    shiftycoin = load_shiftycoin()
    user_id = str(user_id)
    shiftycoin[user_id] = shiftycoin.get(user_id, 0.0) + amount
    save_shiftycoin(shiftycoin)
    return shiftycoin[user_id]

# betting json logic for bj
bet = {}
def add_bet(user_id, amount):
    user_id = str(user_id)
    bet[user_id] = amount
    #print (bet, "bet added")
    return bet[user_id]

def get_bet(user_id):
    user_id = str(user_id)
    return bet.get(user_id, 0.0)


# loans logic
BASE_LOAN_RATE = 0.02        # base monthly interest rate (2%)
RATE_STEP_PER_LOAN = 0.005   # increase per active loan (0.5%)
LOANS_FILE = globals().get("LOANS_FILE", "loans.json")

def load_loans():
    if os.path.exists(LOANS_FILE):
        with open(LOANS_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_loans(data):
    with open(LOANS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def _today_date():
    return datetime.date.today()

def _first_of_month(dt: datetime.date):
    return datetime.date(dt.year, dt.month, 1)

def _months_between(d1: datetime.date, d2: datetime.date):
    # number of full month boundaries from d1 (inclusive) to d2 (exclusive)
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)

def get_loan_record(user_id):
    loans = load_loans()
    return loans.get(str(user_id), {"balance": 0.0, "active_count": 0, "rate": BASE_LOAN_RATE, "last_accrued": None})

def set_loan_record(user_id, record):
    loans = load_loans()
    loans[str(user_id)] = record
    save_loans(loans)

def compute_rate_for_count(count):
    if count <= 0:
        return BASE_LOAN_RATE
    return round(BASE_LOAN_RATE + RATE_STEP_PER_LOAN * (count - 1), 6)

def accrue_interest_for_user(user_id):
    """Apply monthly interest for any months passed since last_accrued.
    Returns (applied_months, interest_amount_applied) or (0, 0.0)."""
    rec = get_loan_record(user_id)
    balance = float(rec.get("balance", 0.0))
    if balance <= 0.0:
        # nothing to do but ensure last_accrued is up to date
        rec["last_accrued"] = _first_of_month(_today_date()).isoformat()
        set_loan_record(user_id, rec)
        return 0, 0.0

    last_iso = rec.get("last_accrued")
    if last_iso:
        try:
            last_date = datetime.date.fromisoformat(last_iso)
        except Exception:
            last_date = _first_of_month(_today_date())
    else:
        # if never accrued, set it to the month the loan was created (approx)
        last_date = _first_of_month(_today_date())

    today_first = _first_of_month(_today_date())
    months = _months_between(last_date, today_first)
    if months <= 0:
        return 0, 0.0

    rate = float(rec.get("rate", compute_rate_for_count(rec.get("active_count", 0))))
    interest_total = 0.0
    # apply compound monthly interest for each month passed
    for _ in range(months):
        interest = round(balance * rate, 2)
        balance = round(balance + interest, 2)
        interest_total = round(interest_total + interest, 2)

    rec["balance"] = round(balance, 2)
    rec["last_accrued"] = today_first.isoformat()
    rec["rate"] = rate
    set_loan_record(user_id, rec)
    return months, interest_total

def take_loan_for_user(user_id, amount):
    """Create/increase a loan. Returns updated record."""
    if amount <= 0:
        raise ValueError("Loan amount must be positive.")
    rec = get_loan_record(user_id)
    # apply any pending interest before taking a new loan
    accrue_interest_for_user(user_id)
    rec = get_loan_record(user_id)  # reload after accrual
    rec["active_count"] = rec.get("active_count", 0) + 1
    rec["rate"] = compute_rate_for_count(rec["active_count"])
    rec["balance"] = round(float(rec.get("balance", 0.0)) + round(amount, 2), 2)
    # set last_accrued to current month start so interest won't be applied until next month
    rec["last_accrued"] = _first_of_month(_today_date()).isoformat()
    set_loan_record(user_id, rec)
    # deposit loan amount to user's shiftycoin balance
    add_balance(user_id, amount)
    return rec

def repay_loan_for_user(user_id, amount):
    """Repay part or all of a loan. Returns (new_record, repaid_amount, overpayment_returned)."""
    if amount <= 0:
        raise ValueError("Repay amount must be positive.")
    rec = get_loan_record(user_id)
    # apply pending interest before repayment
    accrue_interest_for_user(user_id)
    rec = get_loan_record(user_id)
    balance = float(rec.get("balance", 0.0))
    if balance <= 0:
        return rec, 0.0, round(amount, 2)  # nothing owed, return all

    repay = round(amount, 2)
    if repay >= balance:
        over = round(repay - balance, 2)
        repaid = balance
        rec["balance"] = 0.0
        # reduce active_count by 1 when fully paid off (if >0)
        if rec.get("active_count", 0) > 0:
            rec["active_count"] = max(0, rec["active_count"] - 1)
        rec["rate"] = compute_rate_for_count(rec.get("active_count", 0))
        set_loan_record(user_id, rec)
        # if overpayment, refund to shiftycoin balance
        if over > 0:
            add_balance(user_id, over)
        return rec, round(repaid, 2), over
    else:
        rec["balance"] = round(balance - repay, 2)
        set_loan_record(user_id, rec)
        return rec, repay, 0.0

def accrue_interest_all():
    loans = load_loans()
    results = {}
    for uid, rec in loans.items():
        months_before = 0
        try:
            last_iso = rec.get("last_accrued")
            last_date = datetime.date.fromisoformat(last_iso) if last_iso else _first_of_month(_today_date())
        except Exception:
            last_date = _first_of_month(_today_date())
        months = _months_between(last_date, _first_of_month(_today_date()))
        if months > 0:
            months_applied, interest = accrue_interest_for_user(int(uid))
            results[uid] = {"months": months_applied, "interest": interest}
    return results


# track blackjack games per user (by user id)
ACTIVE_GAMES = {}


# bot
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("shiftycoin broker has entered the chatroom.")

@bot.group(name="sc", invoke_without_command=True)
async def sc(ctx):
    """Root command for shiftycoin. Use subcommands: balance, send, request."""
    await ctx.send("Shiftycoin commands: `!sc bal` `!sc send` `!sc request`")

@sc.command(name="bal")
async def balance(ctx):
    bal = get_balance(ctx.author.id)
    await ctx.send(f"{ctx.author.mention}, your balance: **{bal} SC**")

@sc.command(name="send")
async def send(ctx, member: discord.Member, amount: float):
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
    new_sender_bal = get_balance(sender_id)
    await ctx.send(
        f"{ctx.author.mention} sent **{amount} SC** to {member.mention}.\n"
        f"Your new balance: **{new_sender_bal} SC**\n"
        f"{member.mention}'s new balance: **{new_receiver_bal} SC**"
    )

    @sc.command(name="request")
    async def request_sc(ctx, member: discord.Member, amount: float):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        if member.bot:
            await ctx.send("Cannot request from a bot.")
            return

        amount = round(amount, 2)

        class PayView(discord.ui.View):
            def __init__(self, requester_id: int, payer_id: int, amount: float):
                super().__init__(timeout=None)
                self.requester_id = requester_id
                self.payer_id = payer_id
                self.amount = amount
                self.paid = False

            @discord.ui.button(label="Pay", style=discord.ButtonStyle.green)
            async def pay(self, interaction: discord.Interaction, button: discord.ui.Button):
                # only the intended payer can press
                if interaction.user.id != self.payer_id:
                    await interaction.response.send_message("This request is not for you.", ephemeral=True)
                    return
                if self.paid:
                    await interaction.response.send_message("This request has already been paid.", ephemeral=True)
                    return

                payer_bal = get_balance(self.payer_id)
                if payer_bal < self.amount:
                    await interaction.response.send_message("Insufficient balance to pay.", ephemeral=True)
                    return

                # perform transfer
                add_balance(self.payer_id, -self.amount)
                new_receiver_bal = add_balance(self.requester_id, self.amount)
                self.paid = True

                # disable the button and edit the original message
                button.disabled = True
                await interaction.response.edit_message(
                    content=f"You paid **{self.amount} SC** to <@{self.requester_id}>. Your new balance: **{get_balance(self.payer_id)} SC**",
                    view=self
                )

                # notify requester (try DM, fallback to no-op)
                requester = bot.get_user(self.requester_id)
                if requester:
                    try:
                        await requester.send(f"<@{self.payer_id}> paid you **{self.amount} SC**. Your new balance: **{new_receiver_bal} SC**")
                    except Exception:
                        # ignore if requester can't be DMed
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


# loan commands
@bot.group(name="loan", invoke_without_command=True)
async def sc_loan(ctx):
    await ctx.send("Loan commands: `!loan take <amt>` `!loan repay <amt>` `!loan info` `!loan accrue`")

@sc_loan.command(name="take")
async def sc_loan_take(ctx, amount: float):
    uid = ctx.author.id
    try:
        amount = round(amount, 2)
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        rec = take_loan_for_user(uid, amount)
        await ctx.send(
            f"{ctx.author.mention} took a loan of **{amount} SC**.\n"
            f"Loan balance: **{rec['balance']} SC** | Monthly rate: **{rec['rate']*100:.2f}%** | Active loans: {rec['active_count']}"
        )
    except Exception as e:
        await ctx.send(f"Loan failed: {e}")

@sc_loan.command(name="repay")
async def sc_loan_repay(ctx, amount: float):
    uid = ctx.author.id
    try:
        amount = round(amount, 2)
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        # ensure user has enough shiftycoin to repay (auto-withdraw)
        bal = get_balance(uid)
        if bal < amount:
            await ctx.send("Insufficient Shiftycoin balance to repay that amount.")
            return
        # withdraw from balance first
        add_balance(uid, -amount)
        rec, repaid, over = repay_loan_for_user(uid, amount)
        msg = f"{ctx.author.mention} repaid **{repaid} SC** on their loan. New loan balance: **{rec['balance']} SC**."
        if over > 0:
            msg += f" Overpayment of **{over} SC** was refunded to your balance."
        await ctx.send(msg)
    except Exception as e:
        await ctx.send(f"Repayment failed: {e}")

@sc_loan.command(name="info")
async def sc_loan_info(ctx, member: discord.Member=None):
    target = member or ctx.author
    rec = get_loan_record(target.id)
    # apply no accrual here, just show current stored state
    last = rec.get("last_accrued") or "never"
    await ctx.send(
        f"{target.mention} loan info:\n"
        f"Balance: **{rec['balance']} SC**\n"
        f"Monthly rate: **{rec.get('rate', BASE_LOAN_RATE)*100:.2f}%**\n"
        f"Active loans: {rec.get('active_count', 0)}\n"
        f"Last interest applied: {last}"
    )

@sc_loan.command(name="accrue")
async def sc_loan_accrue(ctx):
    """Manually trigger accrual for the invoking user (or for all if user has manage_guild)."""
    uid = ctx.author.id
    # if user has manage_guild permission, allow them to accrue all loans
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


@bot.group(name="bj", invoke_without_command=True)
async def bj(ctx):
    """Root command for blackjack. Use subcommands: start, hit, stand, hand, stop."""
    await ctx.send("Blackjack commands: `!bj start <custom bet (optional)>` `!bj hit` `!bj stand` `!bj hand` `!bj stop`")

@bj.command(name="start")
async def bj_start(ctx, bet = 0):
    uid = ctx.author.id
    if uid in ACTIVE_GAMES and not ACTIVE_GAMES[uid].finished:
        await ctx.send("You already have an active game. Use `!bj hit` or `!bj stand`.")
        return
    game = BlackjackGame()
    game.deal_initial()
    ACTIVE_GAMES[uid] = game
    pscore = score_hand(game.player)
    add_bet([uid], bet)
    # Check natural blackjack
    dealer_up = game.dealer[0]
    desc = (
        f"Dealt. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
        f"Dealer shows: {dealer_up}\n"
        "Use `!bj hit` to draw or `!bj stand` to stand."
    )
    # immediate blackjack check
    if pscore == 21:
        game.dealer_play()
        result = game.evaluate()
        desc += f"\n\nBlackjack! Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: {result.upper()}"
    await ctx.send(desc)
    if game.evaluateSC(uid) != 0:
        scChange = game.evaluateSC(uid)
        newBalance = add_balance(uid, scChange)
        await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")
        

@bj.command(name="hit")
async def bj_hit(ctx):
    uid = ctx.author.id
    game = ACTIVE_GAMES.get(uid)
    if not game or game.finished:
        await ctx.send("No active game. Start one with `!bj start`.")
        return
    card = game.player_hit()
    pscore = score_hand(game.player)
    if pscore > 21:
        game.dealer_play()
        game.evaluate()
        await ctx.send(
            f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
            f"You busted! Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: LOSE"
        )
        if game.evaluateSC(uid) != 0:
            scChange = game.evaluateSC(uid)
            newBalance = add_balance(uid, scChange)
            await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")
    elif pscore == 21:
        # auto stand behavior
        game.dealer_play()
        result = game.evaluate()
        await ctx.send(
            f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
            f"Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: {result.upper()}"
        )
        if game.evaluateSC(uid) != 0:
            scChange = game.evaluateSC(uid)
            newBalance = add_balance(uid, scChange)
            await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")
    else:
        await ctx.send(
            f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
            "Use `!bj hit` or `!bj stand`."
        )

@bj.command(name="stand")
async def bj_stand(ctx):
    uid = ctx.author.id
    game = ACTIVE_GAMES.get(uid)
    if not game or game.finished:
        await ctx.send("No active game. Start one with `!bj start`.")
        return
    game.dealer_play()
    result = game.evaluate()
    await ctx.send(
        f"You stand. Your hand: {hand_str(game.player)} (Total: {score_hand(game.player)})\n"
        f"Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\n"
        f"Result: {result.upper()}"
    )
    if game.evaluateSC(uid) != 0:
        scChange = game.evaluateSC(uid)
        newBalance = add_balance(uid, scChange)
        await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")

@bj.command(name="hand")
async def bj_hand(ctx):
    uid = ctx.author.id
    game = ACTIVE_GAMES.get(uid)
    if not game or game.finished:
        await ctx.send("No active game.")
        return
    await ctx.send(
        f"Your hand: {hand_str(game.player)} (Total: {score_hand(game.player)})\n"
        f"Dealer shows: {game.dealer[0]}"
    )

@bj.command(name="stop")
async def bj_stop(ctx):
    uid = ctx.author.id
    game = ACTIVE_GAMES.pop(uid, None)
    if not game:
        await ctx.send("No active game to stop.")
        return
    await ctx.send("Your game was stopped and removed.")

@bot.command(name="help")
async def help(ctx):
    await ctx.send(
        "**Blackjack Commands**\n"
        "`!bj start <bet (optional)>` - start a new game (default bet is semi random)\n"
        "`!bj hit` - draw a card\n"
        "`!bj stand` - end your turn, dealer plays\n"
        "`!bj hand` - show current hand\n"
        "`!bj stop` - stop and discard your game\n\n"
        "**Shiftycoin Commands**\n"
        "`!sc bal` - show your balance\n"
        "`!sc send <@user> <amount>` - send shiftycoin to another user\n"
        "`!sc request <@user> <amount>` - request shiftycoin from another user\n\n"
        "**Loan Commands**\n"
        "`!loan take <amount>` - take out a loan\n"
        "`!loan repay <amount>` - repay part or all of your loan\n"
        "`!loan info <@user>` - show your or another user's loan info\n"
        "`!loan accrue` - apply interest to your loans (admins can apply to all)\n"


    )

bot.run(TOKEN)