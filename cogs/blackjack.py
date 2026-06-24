from discord.ext import commands
from utils import (
    BlackjackGame, score_hand, hand_str, get_balance, add_balance, add_bet, get_bet,
    log_transaction,
)

ACTIVE_GAMES = {}


class BlackjackCog(commands.Cog, name="Blackjack"):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="bj", invoke_without_command=True)
    async def bj(self, ctx):
        """Root command for blackjack. Use subcommands: start, hit, stand, hand."""
        await ctx.send("Blackjack commands: `!bj start <custom bet (optional)>` `!bj hit` `!bj stand` `!bj hand`")

    @bj.command(name="start")
    async def bj_start(self, ctx, bet=0):
        uid = ctx.author.id
        if bet < 0:
            await ctx.send("Bet must be a positive number.")
            return
        if get_balance(uid) < 0:
            await ctx.send("You do not have enough Shiftycoin to place a bet.")
            return
        if get_balance(uid) < bet:
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
        dealer_up = game.dealer[0]
        desc = (
            f"Dealt. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
            f"Dealer shows: {dealer_up}\n"
            "Use `!bj hit` to draw or `!bj stand` to stand."
        )
        if pscore == 21:
            game.dealer_play()
            result = game.evaluate()
            desc += f"\n\nBlackjack! Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: {result.upper()}"
        await ctx.send(desc)
        if game.evaluateSC(uid) != 0:
            scChange = game.evaluateSC(uid)
            newBalance = add_balance(uid, scChange)
            if scChange > 0:
                log_transaction("blackjack", "system:blackjack", str(uid), scChange, {"result": "win"})
            else:
                log_transaction("blackjack", str(uid), "system:blackjack", -abs(scChange), {"result": "loss"})
            await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")

    @bj.command(name="hit")
    async def bj_hit(self, ctx):
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
                if scChange > 0:
                    log_transaction("blackjack", "system:blackjack", str(uid), scChange, {"result": "win"})
                else:
                    log_transaction("blackjack", str(uid), "system:blackjack", -abs(scChange), {"result": "loss"})
                await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")
        elif pscore == 21:
            game.dealer_play()
            result = game.evaluate()
            await ctx.send(
                f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
                f"Dealer: {hand_str(game.dealer)} (Total: {score_hand(game.dealer)})\nResult: {result.upper()}"
            )
            if game.evaluateSC(uid) != 0:
                scChange = game.evaluateSC(uid)
                newBalance = add_balance(uid, scChange)
                if scChange > 0:
                    log_transaction("blackjack", "system:blackjack", str(uid), scChange, {"result": "win"})
                else:
                    log_transaction("blackjack", str(uid), "system:blackjack", -abs(scChange), {"result": "loss"})
                await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")
        else:
            await ctx.send(
                f"You drew {card}. Your hand: {hand_str(game.player)} (Total: {pscore})\n"
                "Use `!bj hit` or `!bj stand`."
            )

    @bj.command(name="stand")
    async def bj_stand(self, ctx):
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
            if scChange > 0:
                log_transaction("blackjack", "system:blackjack", str(uid), scChange, {"result": "win"})
            else:
                log_transaction("blackjack", str(uid), "system:blackjack", -abs(scChange), {"result": "loss"})
            await ctx.send(f"SC earned/lost: {scChange}. New balance: {newBalance} SC")

    @bj.command(name="hand")
    async def bj_hand(self, ctx):
        uid = ctx.author.id
        game = ACTIVE_GAMES.get(uid)
        if not game or game.finished:
            await ctx.send("No active game.")
            return
        await ctx.send(
            f"Your hand: {hand_str(game.player)} (Total: {score_hand(game.player)})\n"
            f"Dealer shows: {game.dealer[0]}"
        )


async def setup(bot):
    await bot.add_cog(BlackjackCog(bot))
