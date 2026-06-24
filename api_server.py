import uuid
import datetime
import discord
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from utils import (
    validate_token, validate_api_key,
    get_balance, add_balance, load_shiftycoin, mass_redistribute_shiftycoin,
    get_loan_record, take_loan_for_user, repay_loan_for_user, BASE_LOAN_RATE,
    create_business, find_business, get_business_info, pay_from_business,
    load_businesses, save_businesses,
    load_payrolls, save_payrolls, _process_payrolls,
    collect_taxes, TAX_ACCOUNT,
    log_transaction, get_transaction, get_transactions_for_user,
    OID,
)

app = FastAPI(title="shiftycoin broker API", version="0.2.3")
_bearer = HTTPBearer()


# ── Auth dependencies ──────────────────────────────────────────────────────────

def _require_app_key(x_api_key: str = Header(...)) -> dict:
    record = validate_api_key(x_api_key)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return record


def _current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    _app: dict = Depends(_require_app_key),
) -> str:
    discord_id = validate_token(credentials.credentials)
    if not discord_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return discord_id


def _owner_only(discord_id: str = Depends(_current_user)) -> str:
    if str(discord_id) != str(OID):
        raise HTTPException(status_code=403, detail="Owner access required.")
    return discord_id


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _loan_record(rec: dict) -> dict:
    return {
        "balance": float(rec.get("balance", 0.0)),
        "rate": float(rec.get("rate", BASE_LOAN_RATE)),
        "active_count": rec.get("active_count", 0),
        "last_accrued": rec.get("last_accrued"),
    }


def _business_detail(bid: str, rec: dict) -> dict:
    from utils import load_shiftycoin
    shiftycoin = load_shiftycoin()
    acct = rec.get("account_key")
    return {
        "id": bid,
        "name": rec["name"],
        "owner": rec.get("owner"),
        "account_key": acct,
        "bank_balance": float(shiftycoin.get(str(acct), 0.0)),
        "grant_balance": float(rec.get("grant_balance", 0.0)),
        "created_at": rec.get("created_at"),
    }


def _get_business_or_404(identifier: str) -> tuple:
    rec, bid = find_business(identifier)
    if not rec:
        raise HTTPException(status_code=404, detail="Business not found.")
    return rec, bid


def _require_business_owner(rec: dict, discord_id: str):
    if str(rec.get("owner")) != str(discord_id) and str(discord_id) != str(OID):
        raise HTTPException(status_code=403, detail="You do not own this business.")


def _resolve_recipient(recipient: str) -> tuple:
    """Resolve a recipient string to either a business account key or a user ID.
    Returns (kind, target_id) where kind is 'business' or 'user'."""
    target_rec, target_bid = find_business(recipient)
    if target_rec:
        return "business", target_rec.get("account_key"), target_bid, target_rec["name"]
    stripped = "".join(ch for ch in recipient if ch.isdigit())
    if stripped:
        return "user", stripped, None, None
    raise HTTPException(
        status_code=400,
        detail=f'Could not resolve "{recipient}" as a business name/ID or user ID.',
    )


def _user_summary(discord_id: str) -> dict:
    balance = float(get_balance(discord_id))
    loan = get_loan_record(discord_id)
    businesses = load_businesses()
    shiftycoin = load_shiftycoin()
    owned = []
    for bid, rec in businesses.items():
        try:
            if rec.get("owner") != int(discord_id):
                continue
        except (ValueError, TypeError):
            continue
        acct = rec.get("account_key")
        owned.append({
            "id": bid,
            "name": rec["name"],
            "account_key": acct,
            "bank_balance": float(shiftycoin.get(str(acct), 0.0)),
            "grant_balance": float(rec.get("grant_balance", 0.0)),
            "created_at": rec.get("created_at"),
        })
    return {
        "discord_id": discord_id,
        "balance": balance,
        "loan": _loan_record(loan),
        "businesses": owned,
    }


# ── Request models ─────────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    to_user_id: str
    amount: float = Field(gt=0)

class LoanTakeRequest(BaseModel):
    amount: float = Field(gt=0, le=500)

class LoanRepayRequest(BaseModel):
    amount: float = Field(gt=0)

class CreateBusinessRequest(BaseModel):
    name: str = Field(min_length=1)

class DepositRequest(BaseModel):
    amount: float = Field(gt=0)

class BusinessPayRequest(BaseModel):
    recipient: str = Field(description="Business name/ID or user ID")
    amount: float = Field(gt=0)

class AddPayrollRequest(BaseModel):
    recipient_id: str = Field(description="Discord user ID to pay")
    amount: float = Field(gt=0)
    source: str = Field(pattern="^(bank|grant)$", description="'bank' or 'grant'")

class CollectTaxRequest(BaseModel):
    force: bool = Field(default=False, description="Force collection even if no month has passed (OID only)")

class BureauGrantRequest(BaseModel):
    amount: float = Field(gt=0)

class DMRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000, description="Message content to DM the user")


# ── Read: self ─────────────────────────────────────────────────────────────────

@app.get("/me", summary="Your full profile")
async def get_me(discord_id: str = Depends(_current_user)):
    return _user_summary(discord_id)

@app.get("/me/balance", summary="Your SC balance")
async def get_my_balance(discord_id: str = Depends(_current_user)):
    return {"discord_id": discord_id, "balance": float(get_balance(discord_id))}

@app.get("/me/loan", summary="Your loan info")
async def get_my_loan(discord_id: str = Depends(_current_user)):
    return {"discord_id": discord_id, **_loan_record(get_loan_record(discord_id))}

@app.get("/me/businesses", summary="Businesses you own")
async def get_my_businesses(discord_id: str = Depends(_current_user)):
    return _user_summary(discord_id)["businesses"]

@app.get("/leaderboard", summary="Top 10 balances sorted descending (excludes treasury)")
async def get_leaderboard(discord_id: str = Depends(_current_user)):
    shiftycoin = load_shiftycoin()
    filtered = (
        (uid, float(bal))
        for uid, bal in shiftycoin.items()
        if str(uid) != str(TAX_ACCOUNT)
    )
    top10 = sorted(filtered, key=lambda kv: -kv[1])[:10]
    return [{"discord_id": uid, "balance": bal} for uid, bal in top10]


# ── Write: SC ─────────────────────────────────────────────────────────────────

@app.post("/me/send", summary="Send SC to another user")
async def send_sc(body: SendRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    if body.to_user_id == discord_id:
        raise HTTPException(status_code=400, detail="Cannot send SC to yourself.")
    bal = float(get_balance(discord_id))
    if bal < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient balance ({bal:.2f} SC available).")
    add_balance(discord_id, -amount)
    new_receiver_bal = add_balance(body.to_user_id, amount)
    tx_id = log_transaction("send", discord_id, body.to_user_id, amount)
    return {
        "sent": amount,
        "to_user_id": body.to_user_id,
        "your_new_balance": float(get_balance(discord_id)),
        "recipient_new_balance": float(new_receiver_bal),
        "transaction_id": tx_id,
    }


# ── Write: loans ──────────────────────────────────────────────────────────────

@app.post("/me/loan/take", summary="Take out a loan (max 500 SC)")
async def loan_take(body: LoanTakeRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    try:
        rec = take_loan_for_user(discord_id, amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "taken": amount,
        "your_new_balance": float(get_balance(discord_id)),
        "loan": _loan_record(rec),
    }

@app.post("/me/loan/repay", summary="Repay part or all of your loan")
async def loan_repay(body: LoanRepayRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    bal = float(get_balance(discord_id))
    if bal < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient balance ({bal:.2f} SC available).")
    add_balance(discord_id, -amount)
    try:
        rec, repaid, overpayment = repay_loan_for_user(discord_id, amount)
    except ValueError as e:
        add_balance(discord_id, amount)  # roll back deduction
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "repaid": repaid,
        "overpayment_returned": overpayment,
        "your_new_balance": float(get_balance(discord_id)),
        "loan": _loan_record(rec),
    }


# ── Read: businesses ──────────────────────────────────────────────────────────

@app.get("/businesses", summary="List all businesses")
async def list_businesses(discord_id: str = Depends(_current_user)):
    businesses = load_businesses()
    shiftycoin = load_shiftycoin()
    return [_business_detail(bid, rec) for bid, rec in businesses.items()]

@app.get("/businesses/{business_id}", summary="Get a business by ID or name")
async def get_business(business_id: str, discord_id: str = Depends(_current_user)):
    rec, bid = _get_business_or_404(business_id)
    return _business_detail(bid, rec)


# ── Write: businesses ─────────────────────────────────────────────────────────

@app.post("/businesses", summary="Create a new business", status_code=201)
async def create_business_endpoint(body: CreateBusinessRequest, discord_id: str = Depends(_current_user)):
    try:
        rec = create_business(discord_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _business_detail(rec["id"], rec)

@app.post("/businesses/{business_id}/deposit", summary="Deposit SC from your balance into a business")
async def business_deposit(business_id: str, body: DepositRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    rec, bid = _get_business_or_404(business_id)
    bal = float(get_balance(discord_id))
    if bal < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient balance ({bal:.2f} SC available).")
    add_balance(discord_id, -amount)
    new_acct_bal = add_balance(rec["account_key"], amount)
    log_transaction("deposit", discord_id, rec["account_key"], -amount, {"business_id": bid, "business_name": rec["name"]})
    return {
        "deposited": amount,
        "your_new_balance": float(get_balance(discord_id)),
        "business_bank_balance": float(new_acct_bal),
    }

@app.post("/businesses/{business_id}/pay", summary="Pay from a business's bank to a user or business")
async def business_pay(business_id: str, body: BusinessPayRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    rec, bid = _get_business_or_404(business_id)
    _require_business_owner(rec, discord_id)
    kind, target_id, target_bid, target_name = _resolve_recipient(body.recipient)
    try:
        new_bal = pay_from_business(bid, int(discord_id), target_id, amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = {
        "paid": amount,
        "from_business": rec["name"],
        "business_bank_balance": new_bal,
    }
    if kind == "business":
        result["to_business"] = target_name
    else:
        result["to_user_id"] = target_id
    return result

@app.post("/businesses/{business_id}/grantpay", summary="Pay from a business's grant balance to a user or business")
async def business_grantpay(business_id: str, body: BusinessPayRequest, discord_id: str = Depends(_current_user)):
    amount = round(body.amount, 2)
    rec, bid = _get_business_or_404(business_id)
    _require_business_owner(rec, discord_id)

    businesses = load_businesses()
    payer = businesses.get(bid)
    grant_bal = round(float(payer.get("grant_balance", 0.0)), 2)
    if grant_bal < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient grant funds ({grant_bal:.2f} SC available).")

    kind, target_id, target_bid, target_name = _resolve_recipient(body.recipient)

    businesses[bid]["grant_balance"] = round(grant_bal - amount, 2)
    save_businesses(businesses)

    if kind == "business":
        new_target_bal = add_balance(target_id, amount)  # target_id is account_key here
        log_transaction("grantpay", f"grant:{bid}", str(target_id), amount, {"payer_business_id": bid, "payer_business_name": rec["name"], "recipient_business": target_name})
        result = {
            "paid": amount,
            "from_business_grant": rec["name"],
            "to_business": target_name,
            "grant_remaining": businesses[bid]["grant_balance"],
            "recipient_bank_balance": float(new_target_bal),
        }
    else:
        new_user_bal = add_balance(target_id, amount)
        log_transaction("grantpay", f"grant:{bid}", str(target_id), amount, {"payer_business_id": bid, "payer_business_name": rec["name"]})
        result = {
            "paid": amount,
            "from_business_grant": rec["name"],
            "to_user_id": target_id,
            "grant_remaining": businesses[bid]["grant_balance"],
            "recipient_new_balance": float(new_user_bal),
        }
    return result


# ── Payroll ───────────────────────────────────────────────────────────────────

@app.get("/businesses/{business_id}/payroll", summary="List payroll entries for a business")
async def list_payroll(business_id: str, discord_id: str = Depends(_current_user)):
    rec, bid = _get_business_or_404(business_id)
    payrolls = load_payrolls()
    return [p for p in payrolls.values() if p.get("business_id") == bid]

@app.post("/businesses/{business_id}/payroll", summary="Add a payroll entry", status_code=201)
async def add_payroll(business_id: str, body: AddPayrollRequest, discord_id: str = Depends(_current_user)):
    rec, bid = _get_business_or_404(business_id)
    _require_business_owner(rec, discord_id)
    amount = round(body.amount, 2)
    payrolls = load_payrolls()
    pid = str(uuid.uuid4())
    payrolls[pid] = {
        "id": pid,
        "business_id": bid,
        "recipient_id": int(body.recipient_id),
        "amount": amount,
        "source": body.source,
        "last_paid": None,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    save_payrolls(payrolls)
    return payrolls[pid]

@app.delete("/businesses/{business_id}/payroll/{payroll_id}", summary="Remove a payroll entry")
async def remove_payroll(business_id: str, payroll_id: str, discord_id: str = Depends(_current_user)):
    rec, bid = _get_business_or_404(business_id)
    _require_business_owner(rec, discord_id)
    payrolls = load_payrolls()
    if payroll_id not in payrolls or payrolls[payroll_id].get("business_id") != bid:
        raise HTTPException(status_code=404, detail="Payroll entry not found.")
    del payrolls[payroll_id]
    save_payrolls(payrolls)
    return {"deleted": payroll_id}

@app.post("/businesses/{business_id}/payroll/run", summary="Run payroll for a business")
async def run_payroll(business_id: str, discord_id: str = Depends(_current_user)):
    rec, bid = _get_business_or_404(business_id)
    _require_business_owner(rec, discord_id)
    summary = await _process_payrolls()
    # filter results to this business
    processed = [p for p in summary.get("processed", []) if
                 load_payrolls().get(p["id"], {}).get("business_id") == bid]
    skipped = [s for s in summary.get("skipped", []) if
               load_payrolls().get(s["id"], {}).get("business_id") == bid]
    return {"processed": processed, "skipped": skipped}


# ── Bureau ───────────────────────────────────────────────────────────────────

TAX_BRACKETS = [
    {"min": 1_000_000_000, "label": "≥ 1,000,000,000 SC", "rate": 0.99},
    {"min": 100_000_000,   "label": "> 100,000,000 SC",   "rate": 0.80},
    {"min": 10_000_000,    "label": "> 10,000,000 SC",    "rate": 0.65},
    {"min": 1_000_000,     "label": "> 1,000,000 SC",     "rate": 0.40},
    {"min": 500_000,       "label": "> 500,000 SC",       "rate": 0.30},
    {"min": 100_000,       "label": "> 100,000 SC",       "rate": 0.20},
    {"min": 50_000,        "label": "> 50,000 SC",        "rate": 0.10},
    {"min": 10_000,        "label": "> 10,000 SC",        "rate": 0.05},
    {"min": 1_000,         "label": "> 1,000 SC",         "rate": 0.03},
    {"min": 0,             "label": "≤ 1,000 SC",         "rate": 0.00},
]

@app.get("/bureau/brackets", summary="Tax brackets and rates")
async def bureau_brackets(discord_id: str = Depends(_current_user)):
    return TAX_BRACKETS

@app.get("/bureau/balance", summary="Central treasury (IRS) balance")
async def bureau_balance(discord_id: str = Depends(_current_user)):
    shiftycoin = load_shiftycoin()
    bal = float(shiftycoin.get(str(TAX_ACCOUNT), 0.0))
    return {"account": TAX_ACCOUNT, "balance": bal}

@app.post("/bureau/collect", summary="Trigger tax collection")
async def bureau_collect(body: CollectTaxRequest, discord_id: str = Depends(_current_user)):
    if body.force and str(discord_id) != str(OID):
        raise HTTPException(status_code=403, detail="force=true requires owner access.")
    summary = collect_taxes(force=body.force)
    return summary

@app.post("/admin/bureau/grant/{business_id}", summary="Move SC from treasury to a business grant [owner only]")
async def bureau_grant(business_id: str, body: BureauGrantRequest, _: str = Depends(_owner_only)):
    amount = round(body.amount, 2)
    rec, bid = _get_business_or_404(business_id)
    shiftycoin = load_shiftycoin()
    tax_bal = float(shiftycoin.get(str(TAX_ACCOUNT), 0.0))
    if tax_bal < amount:
        raise HTTPException(status_code=400, detail=f"Treasury has insufficient funds ({tax_bal:.2f} SC available).")
    add_balance(TAX_ACCOUNT, -amount)
    log_transaction("bureau_grant", str(TAX_ACCOUNT), f"grant:{bid}", amount, {"business_id": bid, "business_name": rec["name"]})
    businesses = load_businesses()
    businesses[bid]["grant_balance"] = round(float(businesses[bid].get("grant_balance", 0.0)) + amount, 2)
    save_businesses(businesses)
    return {
        "granted": amount,
        "to_business": rec["name"],
        "business_grant_balance": businesses[bid]["grant_balance"],
        "treasury_balance": float(load_shiftycoin().get(str(TAX_ACCOUNT), 0.0)),
    }


# ── Admin ──────────────────────────────────────────────────────────────────────

@app.get("/admin/users/{user_id}", summary="Full profile for any user [owner only]")
async def admin_get_user(user_id: str, _: str = Depends(_owner_only)):
    return _user_summary(user_id)

@app.get("/admin/balances", summary="Raw SC ledger [owner only]")
async def admin_all_balances(_: str = Depends(_owner_only)):
    shiftycoin = load_shiftycoin()
    return {uid: float(bal) for uid, bal in shiftycoin.items()}

@app.post("/admin/redistribute", summary="Redistribute all SC balances equally [owner only]")
async def admin_redistribute(_: str = Depends(_owner_only)):
    new_balances = mass_redistribute_shiftycoin()
    if not new_balances:
        raise HTTPException(status_code=400, detail="No balances to redistribute.")
    return {"redistributed_to": len(new_balances), "balances": new_balances}


# ── Transaction ledger ────────────────────────────────────────────────────────

@app.get("/ledger/{tx_id}", summary="Look up a transaction by its UUID")
async def ledger_get(tx_id: str, discord_id: str = Depends(_current_user)):
    tx = get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    return tx

@app.get("/me/ledger", summary="Your recent transactions (up to 50)")
async def my_ledger(discord_id: str = Depends(_current_user)):
    return get_transactions_for_user(discord_id)

@app.get("/admin/users/{user_id}/ledger", summary="Recent transactions for any user [owner only]")
async def admin_user_ledger(user_id: str, _: str = Depends(_owner_only)):
    return get_transactions_for_user(user_id)


# ── Payroll by ID ─────────────────────────────────────────────────────────────

@app.get("/payroll/{payroll_id}", summary="Look up a payroll entry by its UUID")
async def get_payroll_by_id(payroll_id: str, discord_id: str = Depends(_current_user)):
    payrolls = load_payrolls()
    p = payrolls.get(payroll_id)
    if not p:
        raise HTTPException(status_code=404, detail="Payroll not found.")
    return p


# ── Bot DM (app-key only, no user token required) ────────────────────────────

@app.post("/dm/{user_id}", summary="Send a DM to a Shiftycoin user via the bot (app key only)")
async def send_dm(user_id: str, body: DMRequest, request: Request, _: dict = Depends(_require_app_key)):
    shiftycoin = load_shiftycoin()
    if str(user_id) not in shiftycoin:
        raise HTTPException(status_code=404, detail="User not found in Shiftycoin ledger.")

    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(status_code=503, detail="Discord bot is not attached to app state.")

    try:
        uid_int = int(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a numeric Discord ID.")

    try:
        user = bot.get_user(uid_int) or await bot.fetch_user(uid_int)
    except discord.NotFound:
        raise HTTPException(status_code=404, detail=f"Discord user {user_id} not found.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Discord user: {e}")

    try:
        await user.send(body.content)
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="User has DMs disabled or has blocked the bot.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send DM: {e}")

    return {"sent": True, "user_id": user_id}
