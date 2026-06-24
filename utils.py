import os
import random
import json
import datetime
import uuid
import time
import secrets

# config
config = json.load(open('config.json'))
OID = os.getenv("OWNER_ID", config.get("owner_id"))

BOT_START = time.time()

def _format_duration(seconds: float) -> str:
    td = datetime.timedelta(seconds=int(seconds))
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)

# deck, scoring
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠", "♥", "♦", "♣"]

# reaction rewards
REWARD_EMOTE = "⭐"
PENALTY_EMOTE = "💀"
REACTIONS_PER_SC = 1

def new_deck(shuffle=True):
    deck = [f"{r}{s}" for r in RANKS for s in SUITS]
    if shuffle:
        random.shuffle(deck)
    return deck

def card_value(card):
    rank = card[:-1]
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)

def score_hand(cards):
    total = 0
    aces = 0
    for c in cards:
        v = card_value(c)
        total += v
        if c[:-1] == "A":
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

def hand_str(cards, hide_first=False):
    if hide_first and cards:
        return "?? " + " ".join(cards[1:])
    return " ".join(cards)

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

def mass_redistribute_shiftycoin():
    shiftycoin = load_shiftycoin()
    if not shiftycoin:
        return {}
    total_cents = sum(int(round(float(v) * 100)) for v in shiftycoin.values())
    users = sorted(shiftycoin.keys())
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
    log_transactions_batch([
        {"type": "redistribution", "from_id": "system:redistribution", "to_id": uid, "amount": bal}
        for uid, bal in new_balances.items()
    ])
    return new_balances

# betting json logic for bj (renamed from 'bet' to avoid collision with the bet command group)
_bj_bet_amounts = {}

def add_bet(user_id, amount):
    user_id = str(user_id)
    _bj_bet_amounts[user_id] = amount
    return _bj_bet_amounts[user_id]

def get_bet(user_id):
    user_id = str(user_id)
    return _bj_bet_amounts.get(user_id, 0.0)

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

        if self.finished == True:
            if get_bet([uid]) != 0 and w == 1:
                self.shiftycoinResult = get_bet([uid])
            elif get_bet([uid]) != 0 and w == 0:
                self.shiftycoinResult = get_bet([uid]) * -1
            elif get_bet([uid]) != 0 and w == 2:
                self.shiftycoinResult = 0
            return self.shiftycoinResult
        else:
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

# loans logic
BASE_LOAN_RATE = 0.02
RATE_STEP_PER_LOAN = 0.005

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
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)

def _today_iso():
    return _today_date().isoformat()

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
        last_date = _first_of_month(_today_date())

    today_first = _first_of_month(_today_date())
    months = _months_between(last_date, today_first)
    if months <= 0:
        return 0, 0.0

    rate = float(rec.get("rate", compute_rate_for_count(rec.get("active_count", 0))))
    interest_total = 0.0
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
    accrue_interest_for_user(user_id)
    rec = get_loan_record(user_id)
    rec["active_count"] = rec.get("active_count", 0) + 1
    rec["rate"] = compute_rate_for_count(rec["active_count"])
    rec["balance"] = round(float(rec.get("balance", 0.0)) + round(amount, 2), 2)
    rec["last_accrued"] = _first_of_month(_today_date()).isoformat()
    set_loan_record(user_id, rec)
    add_balance(user_id, amount)
    log_transaction("loan_take", "system:bank", str(user_id), round(amount, 2))
    return rec

def repay_loan_for_user(user_id, amount):
    """Repay part or all of a loan. Returns (new_record, repaid_amount, overpayment_returned)."""
    if amount <= 0:
        raise ValueError("Repay amount must be positive.")
    rec = get_loan_record(user_id)
    accrue_interest_for_user(user_id)
    rec = get_loan_record(user_id)
    balance = float(rec.get("balance", 0.0))
    if balance <= 0:
        return rec, 0.0, round(amount, 2)

    repay = round(amount, 2)
    if repay >= balance:
        over = round(repay - balance, 2)
        repaid = balance
        rec["balance"] = 0.0
        if rec.get("active_count", 0) > 0:
            rec["active_count"] = max(0, rec["active_count"] - rec["active_count"])
        rec["rate"] = compute_rate_for_count(rec.get("active_count", 0))
        set_loan_record(user_id, rec)
        if over > 0:
            add_balance(user_id, over)
        log_transaction("loan_repay", str(user_id), "system:bank", -round(repaid, 2))
        return rec, round(repaid, 2), over
    else:
        rec["balance"] = round(balance - repay, 2)
        set_loan_record(user_id, rec)
        log_transaction("loan_repay", str(user_id), "system:bank", -repay)
        return rec, repay, 0.0

def accrue_interest_all():
    loans = load_loans()
    results = {}
    for uid, rec in loans.items():
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

# business logic
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
    if initial_deposit != 0.0:
        add_balance(account_key, round(initial_deposit, 2))
    else:
        add_balance(account_key, 0.0)
    return rec

def find_business(identifier: str):
    """Find business by id or name (case-insensitive). Returns (business_record, business_id) or (None, None)."""
    if not identifier:
        return None, None
    businesses = load_businesses()
    if identifier in businesses:
        return businesses[identifier], identifier
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
    add_balance(acct, -round(amount, 2))
    add_balance(to_user_id, round(amount, 2))
    log_transaction("business_pay", str(acct), str(to_user_id), amount, {"business_id": bid, "business_name": rec.get("name")})
    shiftycoin = load_shiftycoin()
    return round(float(shiftycoin.get(str(acct), 0.0)), 2)

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
        info["last_checked"] = _first_of_month(_today_date()).isoformat()
        info["months_since_last_collection"] = months
        _save_tax_info(info)
        return {"months": 0, "total_collected": 0.0, "per_user": {}}

    shiftycoin = load_shiftycoin()
    if not shiftycoin:
        info["last_collected"] = _first_of_month(_today_date()).isoformat()
        info["months_since_last_collection"] = months if months > 0 else 0
        _save_tax_info(info)
        return {"months": months if months > 0 else 1, "total_collected": 0.0, "per_user": {}}

    total_collected = 0.0
    per_user = {}
    tax_log_entries = []
    for uid in sorted(shiftycoin.keys()):
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
        new_user_bal = round(bal - tax, 2)
        shiftycoin[uid] = new_user_bal
        per_user[uid] = tax
        total_collected = round(total_collected + tax, 2)
        tax_log_entries.append({"type": "tax", "from_id": uid, "to_id": TAX_ACCOUNT, "amount": -tax})

    if total_collected > 0:
        treasury_bal = float(shiftycoin.get(str(TAX_ACCOUNT), 0.0))
        shiftycoin[str(TAX_ACCOUNT)] = round(treasury_bal + total_collected, 2)

    save_shiftycoin(shiftycoin)
    if tax_log_entries:
        log_transactions_batch(tax_log_entries)
    info["last_collected"] = _first_of_month(_today_date()).isoformat()
    info["months_since_last_collection"] = months if months > 0 else 1
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
    print(f"[TAX] Collected taxes for {audit_entry['months_elapsed']} month(s): {audit_entry['total_collected']} SC (from {audit_entry['per_user_count']} users)")
    return {"months": months if months > 0 else 1, "total_collected": round(total_collected, 2), "per_user": per_user}

# logging channel stuff
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

# bet file mgmt
BETS_FILE = "bets.json"
BET_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")

def load_bets():
    """Load bets from JSON file. Return dict keyed by int(message_id)."""
    if os.path.exists(BETS_FILE):
        try:
            with open(BETS_FILE, "r") as f:
                raw = json.load(f)
        except Exception:
            return {}
        out = {}
        for k, v in raw.items():
            try:
                mid = int(k)
            except Exception:
                continue
            out[mid] = v
        return out
    return {}

def save_bets(bets: dict):
    """Save bets dict (keys int) to JSON file (keys as strings)."""
    try:
        serial = {str(k): v for k, v in bets.items()}
        with open(BETS_FILE, "w") as f:
            json.dump(serial, f, indent=2)
    except Exception:
        pass

async def check_message_reactions(channel, message_id: int) -> dict:
    """
    Fetch the message and return a summary of current reactions.
    """
    msg = await channel.fetch_message(message_id)

    reactions = {}
    reaction_users = {}
    reward_count = 0
    penalty_count = 0
    reward_user_ids = []
    penalty_user_ids = []

    for r in msg.reactions:
        emoji_str = str(r.emoji)
        reactions[emoji_str] = r.count

        users_list = []
        try:
            async for u in r.users():
                if getattr(u, "bot", False):
                    continue
                uid = getattr(u, "id", None)
                if uid is not None:
                    users_list.append(uid)
        except Exception:
            users_list = []

        reaction_users[emoji_str] = users_list

        if emoji_str == REWARD_EMOTE:
            reward_count = r.count
            reward_user_ids = users_list.copy()
        elif emoji_str == PENALTY_EMOTE:
            penalty_count = r.count
            penalty_user_ids = users_list.copy()

    reward_units = reward_count // REACTIONS_PER_SC
    penalty_units = penalty_count // REACTIONS_PER_SC

    return {
        "message_id": msg.id,
        "author_id": getattr(msg.author, "id", None),
        "reactions": reactions,
        "reaction_users": reaction_users,
        "reward_count": reward_count,
        "penalty_count": penalty_count,
        "reward_units": reward_units,
        "penalty_units": penalty_units,
        "reward_user_ids": reward_user_ids,
        "penalty_user_ids": penalty_user_ids
    }

# payrolls
PAYROLLS_FILE = "payrolls.json"

def load_payrolls():
    if os.path.exists(PAYROLLS_FILE):
        try:
            with open(PAYROLLS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_payrolls(data):
    try:
        with open(PAYROLLS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _parse_user_identifier(ctx, recipient: str):
    """Try to resolve a recipient string to a user id (int) or return None."""
    import discord
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
    return uid

async def _process_payrolls():
    """Process all payrolls due since last_paid (daily). Returns summary dict."""
    payrolls = load_payrolls()
    if not payrolls:
        return {"processed": [], "skipped": []}
    businesses = load_businesses()
    shifty = load_shiftycoin()
    today = _today_date()
    processed = []
    skipped = []

    for pid, p in list(payrolls.items()):
        bid = p.get("business_id")
        biz = businesses.get(bid)
        if not biz:
            skipped.append({"id": pid, "reason": "business_not_found"})
            continue
        last_iso = p.get("last_paid")
        if last_iso:
            try:
                last_date = datetime.date.fromisoformat(last_iso)
            except Exception:
                last_date = _today_date() - datetime.timedelta(days=1)
        else:
            last_date = today - datetime.timedelta(days=1)

        days_due = (today - last_date).days
        if days_due <= 0:
            continue

        total_due = round(p.get("amount", 0.0) * days_due, 2)
        recipient = p.get("recipient_id")
        source = p.get("source")
        if source == "bank":
            acct = biz.get("account_key")
            acct_bal = float(shifty.get(str(acct), 0.0))
            if acct_bal < total_due:
                skipped.append({"id": pid, "reason": "insufficient_bank_funds", "need": total_due, "have": acct_bal})
                continue
            add_balance(acct, -total_due)
            add_balance(recipient, total_due)
            p["last_paid"] = today.isoformat()
            payrolls[pid] = p
            processed.append({"id": pid, "paid": total_due, "days": days_due})
            log_transaction("payroll", str(acct), str(recipient), total_due, {"payroll_id": pid, "business_id": bid, "days": days_due})
        else:  # grant
            grant_bal = round(float(biz.get("grant_balance", 0.0)), 2)
            if grant_bal < total_due:
                skipped.append({"id": pid, "reason": "insufficient_grant_funds", "need": total_due, "have": grant_bal})
                continue
            businesses[bid]["grant_balance"] = round(grant_bal - total_due, 2)
            save_businesses(businesses)
            add_balance(recipient, total_due)
            p["last_paid"] = today.isoformat()
            payrolls[pid] = p
            processed.append({"id": pid, "paid": total_due, "days": days_due})
            log_transaction("payroll", f"grant:{bid}", str(recipient), total_due, {"payroll_id": pid, "business_id": bid, "days": days_due})

    save_payrolls(payrolls)
    return {"processed": processed, "skipped": skipped}


# API token management
USER_TOKENS_FILE = "user_tokens.json"
TOKEN_TTL_HOURS = 24 * 365  # 1 year


def load_user_tokens():
    if os.path.exists(USER_TOKENS_FILE):
        try:
            with open(USER_TOKENS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_user_tokens(data):
    try:
        with open(USER_TOKENS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def create_user_token(discord_id: str, ttl_hours: int = TOKEN_TTL_HOURS):
    """Generate a new API token for a Discord user. Revokes any existing token first."""
    tokens = load_user_tokens()
    # remove any existing token for this user
    tokens = {t: d for t, d in tokens.items() if str(d.get("discord_id")) != str(discord_id)}
    token = secrets.token_urlsafe(32)
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(hours=ttl_hours)
    tokens[token] = {
        "discord_id": str(discord_id),
        "created_at": now.isoformat() + "Z",
        "expires_at": expires_at.isoformat() + "Z",
    }
    save_user_tokens(tokens)
    return token, expires_at.isoformat() + "Z"


def validate_token(token: str):
    """Return the discord_id string if the token is valid and not expired, else None."""
    tokens = load_user_tokens()
    entry = tokens.get(token)
    if not entry:
        return None
    try:
        expires_at = datetime.datetime.fromisoformat(entry["expires_at"].rstrip("Z"))
        if datetime.datetime.utcnow() > expires_at:
            return None
    except Exception:
        return None
    return str(entry["discord_id"])


def revoke_user_token(discord_id: str) -> bool:
    """Revoke the token for a Discord user. Returns True if a token was found and removed."""
    tokens = load_user_tokens()
    pruned = {t: d for t, d in tokens.items() if str(d.get("discord_id")) != str(discord_id)}
    if len(pruned) == len(tokens):
        return False
    save_user_tokens(pruned)
    return True


def get_token_info(discord_id: str):
    """Return token metadata for a user (not the token itself), or None if no token exists."""
    tokens = load_user_tokens()
    for data in tokens.values():
        if str(data.get("discord_id")) == str(discord_id):
            try:
                expires_at = datetime.datetime.fromisoformat(data["expires_at"].rstrip("Z"))
                expired = datetime.datetime.utcnow() > expires_at
            except Exception:
                expired = True
            return {
                "created_at": data.get("created_at"),
                "expires_at": data.get("expires_at"),
                "expired": expired,
            }
    return None


# API app-key management
API_KEYS_FILE = "api_keys.json"


def load_api_keys():
    if os.path.exists(API_KEYS_FILE):
        try:
            with open(API_KEYS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_api_keys(data):
    try:
        with open(API_KEYS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def create_api_key(name: str):
    """Create a named app key. Names must be unique. Returns (key, record)."""
    name = name.strip()
    if not name:
        raise ValueError("Key name cannot be empty.")
    keys = load_api_keys()
    for rec in keys.values():
        if rec.get("name", "").lower() == name.lower():
            raise ValueError(f'An app key named "{name}" already exists.')
    key = secrets.token_urlsafe(32)
    record = {
        "name": name,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    keys[key] = record
    save_api_keys(keys)
    return key, record


def validate_api_key(key: str):
    """Return the key record if the key exists, else None."""
    return load_api_keys().get(key)


def revoke_api_key(name: str) -> bool:
    """Revoke an app key by name. Returns True if a key was found and removed."""
    keys = load_api_keys()
    target = next((k for k, v in keys.items() if v.get("name", "").lower() == name.lower()), None)
    if target is None:
        return False
    del keys[target]
    save_api_keys(keys)
    return True


def list_api_keys() -> list:
    """Return summary records (name, created_at, key_preview) for all app keys."""
    keys = load_api_keys()
    return [
        {
            "name": rec["name"],
            "created_at": rec["created_at"],
            "key_preview": key[:8] + "...",
        }
        for key, rec in keys.items()
    ]


# transaction ledger
LEDGER_FILE = "ledger.json"


def load_ledger() -> dict:
    if os.path.exists(LEDGER_FILE):
        try:
            with open(LEDGER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_ledger(data: dict):
    try:
        with open(LEDGER_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def log_transaction(tx_type: str, from_id, to_id, amount: float, metadata: dict = None) -> str:
    """Append a transaction to the ledger and return its UUID."""
    tx_id = str(uuid.uuid4())
    ledger = load_ledger()
    entry = {
        "id": tx_id,
        "type": tx_type,
        "from_id": str(from_id) if from_id is not None else None,
        "to_id": str(to_id) if to_id is not None else None,
        "amount": round(float(amount), 2),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    if metadata:
        entry["metadata"] = metadata
    ledger[tx_id] = entry
    save_ledger(ledger)
    return tx_id


def log_transactions_batch(entries: list) -> list:
    """Log multiple transactions in a single file read/write. Returns list of tx_ids."""
    if not entries:
        return []
    ledger = load_ledger()
    tx_ids = []
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for e in entries:
        tx_id = str(uuid.uuid4())
        record = {
            "id": tx_id,
            "type": e["type"],
            "from_id": str(e["from_id"]) if e.get("from_id") is not None else None,
            "to_id": str(e["to_id"]) if e.get("to_id") is not None else None,
            "amount": round(float(e["amount"]), 2),
            "timestamp": now,
        }
        if e.get("metadata"):
            record["metadata"] = e["metadata"]
        ledger[tx_id] = record
        tx_ids.append(tx_id)
    save_ledger(ledger)
    return tx_ids


def get_transaction(tx_id: str) -> dict | None:
    return load_ledger().get(tx_id)


def get_transactions_for_user(user_id: str, limit: int = 50) -> list:
    """Return up to `limit` transactions involving user_id, most recent first."""
    uid = str(user_id)
    ledger = load_ledger()
    results = [
        tx for tx in ledger.values()
        if str(tx.get("from_id")) == uid or str(tx.get("to_id")) == uid
    ]
    results.sort(key=lambda tx: tx.get("timestamp", ""), reverse=True)
    return results[:limit]
