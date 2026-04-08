import os
import random
import asyncio
import discord
import json
from discord.ext import commands
import datetime
import uuid
import time


# config
config = json.load(open('config.json'))
TOKEN = os.getenv("DISCORD_TOKEN", config.get("token"))
OID = os.getenv("OWNER_ID", config.get("owner_id"))
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.message_content = True

# deck, scoring
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]

# reaction rewards
REWARD_EMOTE = "⭐"  # emote that gives shiftycoin
PENALTY_EMOTE = "💀"  # emote that removes shiftycoin
REACTIONS_PER_SC = 1  # number of reactions needed per shiftycoin

# track reactions per message to avoid duplicate processing
PROCESSED_REACTIONS = {}

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
            w = 0
        elif d > 21:
            self.shiftycoinResult = p / 10
            w = 1
        elif p > d:
            self.shiftycoinResult = p / 10
            w = 1
        elif p < d:
            self.shiftycoinResult = (p / 10) * -1
            w = 0
        else:
            self.shiftycoinResult = 0
            w = 2
        #print (w, "w")
        #print (uid, "uid")
        #print (get_bet([uid]), "bet")
        
        if self.finished == True :
            if get_bet([uid]) != 0 and w == 1 :
                self.shiftycoinResult = get_bet([uid])
                #print (self.shiftycoinResult, "win w bet")
            elif get_bet([uid]) != 0 and w == 0 :
                self.shiftycoinResult = get_bet([uid]) * -1
                #print (self.shiftycoinResult, "lose w bet")
            elif get_bet([uid]) != 0 and w == 2 :
                self.shiftycoinResult = 0
                #print (self.shiftycoinResult, "push w bet")
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

# the great wealth redistributor 
def mass_redistribute_shiftycoin():
    shiftycoin = load_shiftycoin()
    if not shiftycoin:
        return {}

    # cents because floating point precision is bad
    total_cents = sum(int(round(float(v) * 100)) for v in shiftycoin.values())
    users = sorted(shiftycoin.keys())  # deterministic order for remainder distribution
    n = len(users)
    if n == 0:
        return {}

    share_cents = total_cents // n
    remainder = total_cents % n

    new_balances = {}
    for idx, uid in enumerate(users):
        cents = share_cents + (1 if idx < remainder else 0)
        new_balances[uid] = round(cents / 100.0, 2)

    save_shiftycoin(new_balances)
    return new_balances

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
            rec["active_count"] = max(0, rec["active_count"] - rec["active_count"])
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

#business logic

BUSINESSES_FILE = "businesses.json"

def load_businesses():
    if os.path.exists(BUSINESSES_FILE):
        try:
            with open(BUSINESSES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_businesses(data):
    try:
        with open(BUSINESSES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _normalize_name(name: str) -> str:
    return name.strip()

def create_business(owner_id, name: str, initial_deposit: float = 0.0, grant_balance: float = 0.0):
    """Create a new business. Main bank stored in shiftycoin under account_key, rest in businesses.json."""
    name = _normalize_name(name)
    if not name:
        raise ValueError("Business name cannot be empty.")
    businesses = load_businesses()
    # ensure unique name (case-insensitive)
    for b in businesses.values():
        if b.get("name", "").lower() == name.lower():
            raise ValueError("A business with that name already exists.")
    bid = str(uuid.uuid4())
    account_key = f"business:{bid}"
    rec = {
        "id": bid,
        "name": name,
        "owner": int(owner_id),
        "account_key": account_key,
        "grant_balance": round(float(grant_balance), 2),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z"
    }
    businesses[bid] = rec
    save_businesses(businesses)
    # initialize main business bank in shiftycoin file
    if initial_deposit != 0.0:
        add_balance(account_key, round(initial_deposit, 2))
    else:
        # ensure account exists with 0.0
        add_balance(account_key, 0.0)
    return rec

def find_business(identifier: str):
    """Find business by id or name (case-insensitive). Returns (business_record, business_id) or (None, None)."""
    if not identifier:
        return None, None
    businesses = load_businesses()
    # direct id match
    if identifier in businesses:
        return businesses[identifier], identifier
    # match by name
    for bid, rec in businesses.items():
        if rec.get("name", "").lower() == identifier.lower():
            return rec, bid
    return None, None

def get_business_info(identifier: str):
    rec, bid = find_business(identifier)
    if not rec:
        return None
    shiftycoin = load_shiftycoin()
    acct = rec.get("account_key")
    main_balance = round(float(shiftycoin.get(str(acct), 0.0)), 2)
    grant_balance = round(float(rec.get("grant_balance", 0.0)), 2)
    info = {
        "id": rec.get("id"),
        "name": rec.get("name"),
        "owner": rec.get("owner"),
        "account_key": acct,
        "main_balance": main_balance,
        "grant_balance": grant_balance,
        "created_at": rec.get("created_at")
    }
    return info

def pay_from_business(identifier: str, payer_id: int, to_user_id, amount: float):
    """Attempt to pay amount from business main bank to a user. Returns new main balance."""
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    rec, bid = find_business(identifier)
    if not rec:
        raise ValueError("Business not found.")
    acct = rec.get("account_key")
    shiftycoin = load_shiftycoin()
    bal = float(shiftycoin.get(str(acct), 0.0))
    if bal < amount:
        raise ValueError("Business has insufficient funds.")
    # perform transfer: subtract from business main bank, add to user
    add_balance(acct, -round(amount, 2))
    add_balance(to_user_id, round(amount, 2))
    # return new balance
    shiftycoin = load_shiftycoin()
    return round(float(shiftycoin.get(str(acct), 0.0)), 2)


# track blackjack games per user (by user id)
ACTIVE_GAMES = {}

# tax system
TAX_ACCOUNT = "irs"
TAX_INFO_FILE = "tax_info.json"

def _load_tax_info():
    if os.path.exists(TAX_INFO_FILE):
        try:
            with open(TAX_INFO_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_tax_info(info):
    try:
        with open(TAX_INFO_FILE, "w") as f:
            json.dump(info, f, indent=2)
    except Exception:
        pass

def compute_tax_rate(balance: float) -> float:
    """Return tax rate (0.0-1.0) for a given balance according to brackets."""
    b = float(balance)
    if b >= 1_000_000_000:
        return 0.99
    if b > 100_000_000:
        return 0.80
    if b > 10_000_000:
        return 0.65
    if b > 1_000_000:
        return 0.40
    if b > 500_000:
        return 0.30
    if b > 100_000:
        return 0.20
    if b > 50_000:
        return 0.10
    if b > 10_000:
        return 0.05
    if b > 1_000:
        return 0.03
    return 0.0

def compute_tax_amount(balance: float) -> float:
    """Compute tax amount (rounded to 2 decimals) for a balance."""
    rate = compute_tax_rate(balance)
    if rate <= 0.0:
        return 0.0
    tax = round(float(balance) * rate, 2)
    # never take more than the balance (guard against rounding anomalies)
    tax = min(tax, round(float(balance), 2))
    return tax

def collect_taxes(force: bool = False):
    """
    Collect taxes for all users if a month boundary has passed since last collection,
    or if force=True. Deposits collected taxes into TAX_ACCOUNT.
    Returns a summary dict: {"months": n, "total_collected": X, "per_user": {uid:tax, ...}}
    Also logs how many months have passed into TAX_INFO_FILE (for visibility).
    """
    info = _load_tax_info()
    last_iso = info.get("last_collected")
    if last_iso:
        try:
            last_date = datetime.date.fromisoformat(last_iso)
        except Exception:
            last_date = _first_of_month(_today_date())
    else:
        last_date = _first_of_month(_today_date())

    months = _months_between(last_date, _first_of_month(_today_date()))
    if months <= 0 and not force:
        # log that no collection needed, store months=0
        info["last_checked"] = _first_of_month(_today_date()).isoformat()
        info["months_since_last_collection"] = months
        _save_tax_info(info)
        return {"months": 0, "total_collected": 0.0, "per_user": {}}

    shiftycoin = load_shiftycoin()
    if not shiftycoin:
        # update last_collected anyway to avoid repeated no-op runs
        info["last_collected"] = _first_of_month(_today_date()).isoformat()
        info["months_since_last_collection"] = months if months > 0 else 0
        _save_tax_info(info)
        return {"months": months if months > 0 else 1, "total_collected": 0.0, "per_user": {}}

    total_collected = 0.0
    per_user = {}
    # iterate deterministic order to keep reproducible behavior
    for uid in sorted(shiftycoin.keys()):
        # skip the treasury account itself
        if str(uid) == str(TAX_ACCOUNT):
            continue
        try:
            bal = float(shiftycoin.get(uid, 0.0))
        except Exception:
            bal = 0.0
        if bal <= 0.0:
            continue
        tax = compute_tax_amount(bal)
        if tax <= 0.0:
            continue
        # subtract tax from user balance and accumulate
        new_user_bal = round(bal - tax, 2)
        shiftycoin[uid] = new_user_bal
        per_user[uid] = tax
        total_collected = round(total_collected + tax, 2)

    # credit treasury
    if total_collected > 0:
        treasury_bal = float(shiftycoin.get(str(TAX_ACCOUNT), 0.0))
        shiftycoin[str(TAX_ACCOUNT)] = round(treasury_bal + total_collected, 2)

    # persist new balances and update last_collected
    save_shiftycoin(shiftycoin)
    info["last_collected"] = _first_of_month(_today_date()).isoformat()
    info["months_since_last_collection"] = months if months > 0 else 1
    # append an audit entry for visibility
    audit = info.get("audit", [])
    audit_entry = {
        "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
        "months_elapsed": months if months > 0 else 1,
        "total_collected": round(total_collected, 2),
        "per_user_count": len(per_user)
    }
    audit.append(audit_entry)
    info["audit"] = audit
    _save_tax_info(info)

    # also print a concise console log (useful when running headless)
    print(f"[TAX] Collected taxes for {audit_entry['months_elapsed']} month(s): {audit_entry['total_collected']} SC (from {audit_entry['per_user_count']} users)")

    return {"months": months if months > 0 else 1, "total_collected": round(total_collected, 2), "per_user": per_user}

#logging channel stuff
LOG_CHANNELS_FILE = "log_channels.json"

def _load_log_channels():
    if os.path.exists(LOG_CHANNELS_FILE):
        try:
            with open(LOG_CHANNELS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_log_channels(mapping):
    try:
        with open(LOG_CHANNELS_FILE, "w") as f:
            json.dump(mapping, f, indent=2)
    except Exception:
        pass

# bot
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("shiftycoin broker has entered the chatroom.")
    # status
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name=config.get("status")))

'''
# process incoming reactions
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message.author.bot:
        return
    
    message_id = reaction.message.id
    if message_id not in PROCESSED_REACTIONS:
        PROCESSED_REACTIONS[message_id] = {"reward": 0, "penalty": 0}
    
    # count reactions
    if str(reaction.emoji) == REWARD_EMOTE:
        PROCESSED_REACTIONS[message_id]["reward"] = reaction.count
        sc_change = (PROCESSED_REACTIONS[message_id]["reward"] // REACTIONS_PER_SC) * 10
        if sc_change > 0:
            add_balance(reaction.message.author.id, sc_change)
    
    elif str(reaction.emoji) == PENALTY_EMOTE:
        PROCESSED_REACTIONS[message_id]["penalty"] = reaction.count
        sc_change = (PROCESSED_REACTIONS[message_id]["penalty"] // REACTIONS_PER_SC) * 20
        if sc_change > 0:
            add_balance(reaction.message.author.id, -sc_change)

# process removed reactions
@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot or reaction.message.author.bot:
        return
    
    message_id = reaction.message.id
    if message_id not in PROCESSED_REACTIONS:
        PROCESSED_REACTIONS[message_id] = {"reward": 0, "penalty": 0}
    
    # adjust counts
    if str(reaction.emoji) == REWARD_EMOTE:
        PROCESSED_REACTIONS[message_id]["reward"] = max(0, reaction.count)
    elif str(reaction.emoji) == PENALTY_EMOTE:
        PROCESSED_REACTIONS[message_id]["penalty"] = max(0, reaction.count)
'''

# new reaction system cuz the old one is messy and doesnt allow me to change the value of reactions
APPLIED_REACTIONS = {}

async def _sync_and_apply(message: discord.Message):
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
    #print(delta_reward, "delta reward")
    delta_penalty = penalty_units - prev_penalty
    #print(delta_penalty, "delta penalty")

    # apply reward delta (+10 per unit) and penalty delta (-20 per unit)
    if delta_reward != 0:
        add_balance(message.author.id, delta_reward * 10)
    if delta_penalty != 0:
        add_balance(message.author.id, delta_penalty * -20)

    APPLIED_REACTIONS[mid]["reward"] = reward_units
    APPLIED_REACTIONS[mid]["penalty"] = penalty_units

async def _on_reaction_event(reaction, user):
    if user.bot or reaction.message.author.bot:
        return
    try:
        # fetch fresh message to get accurate reaction counts which only half works but okay
        msg = await reaction.message.channel.fetch_message(reaction.message.id)
    except Exception:
        msg = reaction.message
    await _sync_and_apply(msg)

bot.add_listener(_on_reaction_event, 'on_reaction_add')
bot.add_listener(_on_reaction_event, 'on_reaction_remove')

# user surveillance

@bot.group(name="srvl", invoke_without_command=True)
async def srvl(ctx):
    """Root group for the SRVL system. Use subcommands: channelset, channelrm."""
    await ctx.send("SRVL commands: `!srvl set` `!srvl rm`")

@srvl.command(name="set")
async def add_log_channel(ctx, channel: discord.TextChannel = None):
    """Administrator command: set a channel in this guild to receive SRVL messages."""
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You do not have permission to use this command.")
        return
    if ctx.guild is None:
        await ctx.send("This command can only be used in a server.")
        return

    target = channel or ctx.channel
    if not isinstance(target, discord.TextChannel) or target.guild.id != ctx.guild.id:
        await ctx.send("Please specify a text channel from this server.")
        return

    mapping = _load_log_channels()
    mapping[str(ctx.guild.id)] = str(target.id)
    _save_log_channels(mapping)
    await ctx.send(f"SRVL channel for this server set to {target.mention}.")

    @srvl.command(name="rm")
    async def remove_log_channel(ctx, channel: discord.TextChannel = None):
        """Administrator command: remove the configured SRVL channel for this guild."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You do not have permission to use this command.")
            return
        if ctx.guild is None:
            await ctx.send("This command can only be used in a server .")
            return

        mapping = _load_log_channels()
        gid = str(ctx.guild.id)
        configured = mapping.get(gid)

        if not configured:
            await ctx.send("No SRVL channel is configured for this server.")
            return

        # If a specific channel was provided, ensure it matches the configured one.
        if channel and str(channel.id) != configured:
            await ctx.send(f"The configured SRVL channel is <#{configured}>, not {channel.mention}.")
            return

        mapping.pop(gid, None)
        _save_log_channels(mapping)
        await ctx.send("SRVL channel for this server has been removed.")

def _find_log_channel_for_guild(guild: discord.Guild):

    # try to return a configured channel
    mapping = _load_log_channels()
    gid = str(guild.id)
    ch = None

    # 1) configured channel id
    cid = mapping.get(gid)
    if cid:
        try:
            ch = guild.get_channel(int(cid))
        except Exception:
            ch = None
        # remove stale mapping if channel not found
        if not ch and gid in mapping:
            mapping.pop(gid, None)
            _save_log_channels(mapping)

    return ch

@bot.event
async def _send_log_embed(guild: discord.Guild, title: str, description: str, color: discord.Colour = discord.Colour.orange()):
    ch = _find_log_channel_for_guild(guild)
    if not ch:
        return
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.datetime.now(datetime.UTC))
    try:
        await ch.send(embed=embed)
    except Exception:
        # best-effort only
        pass

@bot.event
async def on_message_delete(message: discord.Message):
    # only log server messages
    if message.guild is None:
        return
    # ignore if the message was sent by a bot
    if message.author and message.author.bot:
        return
    author = message.author
    channel = message.channel
    content = message.content or ""
    # include attachments if present
    files_info = ""
    if message.attachments:
        urls = [a.url for a in message.attachments]
        files_info = "\nAttachments:\n" + "\n".join(urls)
    # truncate long content for embed
    if len(content) > 1500:
        content = content[:1500] + "… (truncated)"
    desc = (
        f"Message deleted in {channel.mention}\n"
        f"Author: {author.mention} (`{author.id}`)\n"
        f"Message ID: `{message.id}`\n\n"
        f"Content:\n{content}"
        f"{files_info}"
    )
    await _send_log_embed(message.guild, "Message Deleted", desc, discord.Colour.red())

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    # only log guild messages
    if before.guild is None:
        return
    # ignore if the message was sent by a bot 
    if before.author and before.author.bot:
        return
    author = before.author
    channel = before.channel
    content_before = before.content or ""
    content_after = after.content or ""
    # include attachments if present
    files_info = ""
    if before.attachments:
        urls = [a.url for a in before.attachments]
        files_info = "\nAttachments:\n" + "\n".join(urls)
    # truncate long content for embed
    if len(content_before) > 1500:
        content_before = content_before[:1500] + "… (truncated)"
    if len(content_after) > 1500:
        content_after = content_after[:1500] + "… (truncated)"
    desc = (
        f"Message edited in {channel.mention}\n"
        f"Author: {author.mention} (`{author.id}`)\n"
        f"Message ID: `{before.id}`\n\n"
        f"Before:\n{content_before}"
        f"\nAfter:\n{content_after}"
        f"{files_info}"
    )
    await _send_log_embed(before.guild, "Message Edited", desc, discord.Colour.orange())

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    # try to pull reason from audit logs (trying to at least)
    reason = None
    try:
        async for entry in guild.audit_logs(limit=6, action=discord.AuditLogAction.ban):
            if entry.target and getattr(entry.target, "id", None) == user.id:
                reason = entry.reason
                moderator = entry.user
                break
    except Exception:
        moderator = None

    desc = f"User: {user} (`{getattr(user, 'id', 'unknown')}`)\n"
    if moderator:
        desc += f"Banned by: {moderator.mention} (`{moderator.id}`)\n"
    if reason:
        desc += f"Reason: {reason}\n"
    await _send_log_embed(guild, "Member Banned", desc, discord.Colour.dark_red())

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # detect role changes related to a role named "Muted" (case-insensitive)
    before_roles = {r.id: r for r in before.roles}
    after_roles = {r.id: r for r in after.roles}

    # find any role objects named Muted in either snapshot
    muted_before = None
    muted_after = None
    for r in before.roles:
        if r.name.lower() == "muted":
            muted_before = r
            break
    for r in after.roles:
        if r.name.lower() == "muted":
            muted_after = r
            break

    # role was added -> muted
    if not muted_before and muted_after:
        # try to find moderator & reason from audit logs (role updates do not appear in audit logs reliably)
        desc = (
            f"User muted: {after.mention} (`{after.id}`)\n"
            f"Role: {muted_after.name}\n"
        )
        await _send_log_embed(after.guild, "Member Muted", desc, discord.Colour.orange())

    # role was removed -> unmuted
    if muted_before and not muted_after:
        desc = (
            f"User unmuted: {after.mention} (`{after.id}`)\n"
            f"Role removed: {muted_before.name}\n"
        )
        await _send_log_embed(after.guild, "Member Unmuted", desc, discord.Colour.green())

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    # detect nickname changes
    if before.nick != after.nick:
        desc = (
            f"User nickname changed: {after.mention} (`{after.id}`)\n"
            f"Before: {before.nick}\n"
            f"After: {after.nick}\n"
        )
        await _send_log_embed(after.guild, "Member Nickname Changed", desc, discord.Colour.blue())

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

@sc.command(name="redistribute")
async def redistribute(ctx):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("You do not have permission to use this command.")
        return
    new_balances = mass_redistribute_shiftycoin()
    if not new_balances:
        await ctx.send("there is no economy :(")
        return
    await ctx.send(f"The Great Redistribution has occurred. The playing field has been leveled for all {len(new_balances)} individuals. \n"
                   "**May the users of our Shiftycoin find renewed hope and opportunity in this new era of equality.**")

@sc.command(name="globalbal")
async def globalbal(ctx):
    shiftycoin = load_shiftycoin()
    def get_global_balance():
        shiftycoin = load_shiftycoin()
        total = sum(float(v) for v in shiftycoin.values())
        return round(total, 2)
    if not shiftycoin:
        await ctx.send("No balances recorded.")
        return

    # sort by balance descending
    items = sorted(shiftycoin.items(), key=lambda kv: -float(kv[1]))
    lines = [f"<@{uid}>: **{float(bal):.2f} SC**" for uid, bal in items]

    header = "Shiftycoin balances:\n"
    # send in chunks to avoid hitting discord message length limit
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
    """Root command for blackjack. Use subcommands: start, hit, stand, hand."""
    await ctx.send("Blackjack commands: `!bj start <custom bet (optional)>` `!bj hit` `!bj stand` `!bj hand`")

@bj.command(name="start")
async def bj_start(ctx, bet = 0):
    uid = ctx.author.id
    if bet < 0 :
        await ctx.send("Bet must be a positive number.")
        return
    if get_balance(uid) < 0 :
        await ctx.send("You do not have enough Shiftycoin to place a bet.")
        return
    if get_balance(uid) < bet :
        await ctx.send("You do not have enough Shiftycoin to place a bet.")
        return
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
'''
@bj.command(name="stop")
async def bj_stop(ctx):
    uid = ctx.author.id
    game = ACTIVE_GAMES.pop(uid, None)
    if not game:
        await ctx.send("No active game to stop.")
        return
    await ctx.send("Your game was stopped and removed.")
'''

@bot.group(name="corp", invoke_without_command=True)
async def corp(ctx):
    await ctx.send("Corporation commands: `!corp start <name>` `!corp pay <corp> <@user> <amount>` `!corp info <corp>`")

@corp.command(name="start")
async def corp_start(ctx, *, name: str):
    try:
        rec = create_business(ctx.author.id, name)
        await ctx.send(
            f"Business created: **{rec['name']}** (ID: `{rec['id']}`)\n"
            f"Owner: {ctx.author.mention}\n"
            f"Main account key: `{rec['account_key']}`\n"
            f"Bank balance: **0.00 SC**\n"
            f"Grant balance: **{rec['grant_balance']:.2f} SC**"
        )
    except Exception as e:
        await ctx.send(f"Failed to create business: {e}")

@corp.command(name="pay")
async def corp_pay(ctx, identifier: str, member: discord.Member, amount: float):
    # find business
    rec, bid = find_business(identifier)
    if not rec:
        await ctx.send("Business not found (use id or exact name).")
        return
    # permission: only business owner, server admin, or global owner may pay
    allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or ctx.author.id == OID)
    if not allowed:
        await ctx.send("You do not have permission to pay from this business.")
        return
    try:
        amount = round(float(amount), 2)
        new_bal = pay_from_business(bid, ctx.author.id, member.id, amount)
        await ctx.send(f"Paid **{amount:.2f} SC** from **{rec['name']}** to {member.mention}.\nNew shiftycoin balance: **{new_bal:.2f} SC**")
    except Exception as e:
        await ctx.send(f"Payment failed: {e}")

@corp.command(name="info")
async def corp_info(ctx, identifier: str):
    info = get_business_info(identifier)
    if not info:
        await ctx.send("Business not found (use id or exact name).")
        return
    owner = bot.get_user(int(info["owner"]))
    owner_display = owner.mention if owner else f"`{info['owner']}`"
    await ctx.send(
        f"Business: **{info['name']}** (ID: `{info['id']}`)\n"
        f"Owner: {owner_display}\n"
        f"Bank balance: **{info['main_balance']:.2f} SC**\n"
        f"Grant balance: **{info['grant_balance']:.2f} SC**\n"
        f"Created: {info.get('created_at')}"
    )

@corp.command(name="grantpay")
async def corp_grantpay(ctx, identifier: str, recipient: str, amount: float):
    """Pay from a business' grant balance to a user or another business."""
    try:
        amount = round(float(amount), 2)
    except Exception:
        await ctx.send("Invalid amount.")
        return
    if amount <= 0:
        await ctx.send("Amount must be positive.")
        return

    # find payer business
    rec, bid = find_business(identifier)
    if not rec:
        await ctx.send("Payer business not found (use id or exact name).")
        return

    # permission check (owner, server admin, or global owner)
    allowed = (ctx.author.id == int(rec.get("owner")) or ctx.author.guild_permissions.administrator or str(ctx.author.id) == str(OID))
    if not allowed:
        await ctx.send("You do not have permission to use this business' grant funds.")
        return

    # ensure sufficient grant balance
    businesses = load_businesses()
    payer = businesses.get(bid)
    if not payer:
        await ctx.send("Business record missing while processing.")
        return
    payer_grant = round(float(payer.get("grant_balance", 0.0)), 2)
    if payer_grant < amount:
        await ctx.send(f"Insufficient grant funds. Available: **{payer_grant:.2f} SC**")
        return

    # try recipient as business first
    target_rec, target_bid = find_business(recipient)
    if target_rec:
        # transfer between business grants
        businesses[bid]["grant_balance"] = round(payer_grant - amount, 2)
        businesses[target_bid]["grant_balance"] = round(float(businesses[target_bid].get("grant_balance", 0.0)) + amount, 2)
        save_businesses(businesses)
        await ctx.send(
            f"Transferred **{amount:.2f} SC** from grant of **{rec['name']}** to grant of **{target_rec['name']}**.\n"
            f"{rec['name']} grant: **{businesses[bid]['grant_balance']:.2f} SC** | "
            f"{target_rec['name']} grant: **{businesses[target_bid]['grant_balance']:.2f} SC**"
        )
        return

    # otherwise try to resolve recipient as a user id/mention/name
    uid = None
    # strip mention chars if present
    stripped = "".join(ch for ch in recipient if ch.isdigit())
    if stripped:
        try:
            uid = int(stripped)
        except Exception:
            uid = None

    # if still no uid and in guild, try to look up by name/nick
    if uid is None and ctx.guild:
        member = discord.utils.find(lambda m: m.name == recipient or (m.nick and m.nick == recipient), ctx.guild.members)
        if member:
            uid = member.id

    if uid is None:
        # as a last resort try bot.get_user by raw string (may be id)
        try:
            possible = int(recipient)
            uid = possible
        except Exception:
            uid = None

    if uid is None:
        await ctx.send("Could not resolve recipient as a business or user (use business id/name or @user).")
        return

    # perform transfer: subtract from grant, add to user balance
    businesses[bid]["grant_balance"] = round(payer_grant - amount, 2)
    save_businesses(businesses)
    new_bal = add_balance(uid, amount)
    await ctx.send(
        f"Transferred **{amount:.2f} SC** from grant of **{rec['name']}** to <@{uid}>.\n"
        f"{rec['name']} grant remaining: **{businesses[bid]['grant_balance']:.2f} SC**\n"
        f"Recipient new balance: **{new_bal:.2f} SC**"
    )

@corp.command(name="deposit")
async def corp_deposit(ctx, identifier: str, amount: float):
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
    # perform transfer
    add_balance(sender_id, -amount)
    new_acct_bal = add_balance(acct, amount)
    new_sender_bal = get_balance(sender_id)

    await ctx.send(
        f"{ctx.author.mention} deposited **{amount:.2f} SC** into **{rec['name']}**.\n"
        f"Your new balance: **{new_sender_bal:.2f} SC**\n"
        f"Business balance: **{new_acct_bal:.2f} SC**"
    )

#bureau commands

@bot.group(name="bureau", invoke_without_command=True)
async def bureau(ctx):
    """Root command for Bureau of Shiftycoin Administration interface commands. Use subcommands: collect, brackets, centralbal, grant."""
    await ctx.send("Bureau of Shiftycoin Administration commands: `!bureau collect` `!bureau brackets` `!bureau centralbal` `!bureau grant`")

@bureau.command(name="collect")
async def _collecttax(ctx, mode: str = None):
        # parse force argument
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
        # build a short response
        lines = [f"Collected taxes for {months} month(s). Total collected: **{total} SC**."]
        # show up to 8 users for brevity
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
async def taxbal(ctx):
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
async def tax_brackets(ctx):
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
async def bureau_grant(ctx, identifier: str, amount: float):
    """OID-only: move SC from TAX_ACCOUNT into a business' grant balance."""
    # only allow the configured owner to run this
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

    # ensure TAX_ACCOUNT has enough funds
    #shiftycoin = load_shiftycoin()
    #tax_bal = float(shiftycoin.get(str(TAX_ACCOUNT), 0.0))
    #if tax_bal < amount:
    #    await ctx.send(f"Treasury ({TAX_ACCOUNT}) has insufficient funds. Current: **{tax_bal:.2f} SC**")
    #    return

    # debit treasury and credit business grant_balance
    add_balance(TAX_ACCOUNT, -amount)
    # update business grant balance stored in businesses.json
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

@bot.group(name="user", invoke_without_command=True)
async def user(ctx):
    """Root command for user management functions. Use subcommands: !user kick, !user ban, !user unban, !user mute, !user unmute."""
    await ctx.send("User management commands: `!user kick <user>` `!user ban <user>` `!user unban <user>` `!user mute <user> <duration>` `!user unmute <user>`")

@user.command(name="kick")
async def kick(ctx, member: discord.Member, *, reason=None):
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("You do not have permission to kick members.")
        return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"{member.mention} has been kicked. Reason: {reason}")
    except Exception as e:
        await ctx.send(f"Failed to kick {member.mention}. Error: {e}")

@user.command(name="ban")
async def ban(ctx, member: discord.Member, *, reason=None): 
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send("You do not have permission to ban members.")
        return
    try:
        await member.ban(reason=reason)
        await ctx.send(f"{member.mention} has been banned. Reason: {reason}")
    except Exception as e:
        await ctx.send(f"Failed to ban {member.mention}. Error: {e}")

@user.command(name="mute")
async def mute(ctx, member: discord.Member, duration: int):
    if not ctx.author.guild_permissions.manage_roles:
        await ctx.send("You do not have permission to mute members.")
        return
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        # create Muted role if it doesn't exist
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
async def unmute(ctx, member: discord.Member):
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
async def unban(ctx, user: discord.User):
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send("You do not have permission to unban members.")
        return
    try:
        await ctx.guild.unban(user)
        await ctx.send(f"{user.mention} has been unbanned.")
    except Exception as e:
        await ctx.send(f"Failed to unban {user.mention}. Error: {e}")

@bot.command(name="directory")
async def directory(ctx):
    await ctx.send(
        "**Blackjack Commands**\n"
        "`!bj start <bet (optional)>` - start a new game (default bet is semi random)\n"
        "`!bj hit` - draw a card\n"
        "`!bj stand` - end your turn, dealer plays\n"
        "`!bj hand` - show current hand\n\n"
        "**Shiftycoin Commands**\n"
        "`!sc bal` - show your balance\n"
        "`!sc send <@user> <amount>` - send shiftycoin to another user\n"
        "`!sc request <@user> <amount>` - request shiftycoin from another user\n\n"
        "**Loan Commands**\n"
        "`!loan take <amount>` - take out a loan\n"
        "`!loan repay <amount>` - repay part or all of your loan\n"
        "`!loan info <@user>` - show your or another user's loan info\n"
        "`!loan accrue` - apply interest to your loans (admins can apply to all)\n\n"
        "**Business Commands**\n"
        "`!corp start <name>` - create a new business\n"
        "`!corp pay <business/@user> <amount>` - pay a user from a business account\n"
        "`!corp deposit <business> <amount>` - deposit from your balance into a business account\n"
        "`!corp info <business>` - show info about a business\n"
        "`!corp grantpay <business/@user> <recipient> <amount>` - pay from a business grant to a user or another business\n\n"
        "**User Management Commands**\n"
        "`!user kick <@user>` - kick a user from the server\n"
        "`!user ban <@user>` - ban a user from the server\n"
        "`!user unban <user id>` - unban a user from the server\n"
        "`!user mute <@user> <duration in minutes>` - mute a user for a duration\n"
        "`!user unmute <@user>` - unmute a user\n\n"
        "**SRVL Commands**\n"
        "`!srvl set <channel>` - set the SRVL channel for this server\n"
        "`!srvl rm` - remove the configured SRVL channel for this server\n\n"
        "**Bureau of Shiftycoin Administration Commands**\n"
        "`!bureau brackets` - show the configured tax brackets and rates\n"
        "`!bureau centralbal` - show the balance of the central tax collection account\n\n"
        "**Reactions with ⭐ increases recieving user's Shiftycoin balance by 10.** \n"
        "**Reactions with 💀 decreases recieving user's Shiftycoin balance by 20.**"

    )

bot.run(TOKEN)