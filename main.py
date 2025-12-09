import os
import random
import asyncio
import discord
import json
from discord.ext import commands


# Configuration 
config = json.load(open('config.json'))
TOKEN = os.getenv("DISCORD_TOKEN", config.get("token"))
PREFIX = "!"
INTENTS = discord.Intents.default()
INTENTS.message_content = True

# Utilities: deck, scoring
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

    def evaluate(self):
        p = score_hand(self.player)
        d = score_hand(self.dealer)
        if p > 21:
            self.result = "lose"
            self.shiftycoinResult = (p / 10) * -1
        elif d > 21:
            self.result = "win"
            self.shiftycoinResult = p / 10
        elif p > d:
            self.result = "win"
            self.shiftycoinResult = p / 10
        elif p < d:
            self.result = "lose"
            self.shiftycoinResult = (p / 10) * -1
        else:
            self.result = "push"
        self.finished = True
        return self.result

# track games per user (by user id)
ACTIVE_GAMES = {}

# bot
bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS, help_command=None)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("shiftycoin broker has entered the chatroom.")

@bot.group(name="bj", invoke_without_command=True)
async def bj(ctx):
    """Root command for blackjack. Use subcommands: start, hit, stand, hand, stop."""
    await ctx.send("Blackjack commands: `!bj start` `!bj hit` `!bj stand` `!bj hand` `!bj stop`")

@bj.command(name="start")
async def bj_start(ctx):
    uid = ctx.author.id
    if uid in ACTIVE_GAMES and not ACTIVE_GAMES[uid].finished:
        await ctx.send("You already have an active game. Use `!bj hit` or `!bj stand`.")
        return
    game = BlackjackGame()
    game.deal_initial()
    ACTIVE_GAMES[uid] = game
    pscore = score_hand(game.player)
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
    elif pscore == 21:
        # auto stand behavior
        game.dealer_play()
        result = game.evaluate()
        await ctx.send(
            f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
            f"Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: {result.upper()}"
        )
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
    shiftycoinResult = game.evaluate()
    await ctx.send(
        f"You stand. Your hand: {hand_str(game.player)} (Total: {score_hand(game.player)})\n"
        f"Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\n"
        f"Result: {result.upper()}"
        f"Shiftycoin earned/lost: {shiftycoinResult}"
    )

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

@bot.command(name="bjhelp")
async def bjhelp(ctx):
    await ctx.send(
        "`!bj start` - start a new game\n"
        "`!bj hit` - draw a card\n"
        "`!bj stand` - end your turn, dealer plays\n"
        "`!bj hand` - show current hand\n"
        "`!bj stop` - stop and discard your game"
    )

bot.run(TOKEN)