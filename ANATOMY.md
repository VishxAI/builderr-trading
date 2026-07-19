# Anatomy of a strong trading bot 🧠

*Plain English. No quant background needed. Steal this, tweak it, make it yours.*

---

**A note from the person who put up the money:**

I'm not a genius quant. My own bots couldn't beat the market — so I did the obvious thing: I found smart people I trust, borrowed the ideas that actually work, and opened it up to everyone. You can do the exact same thing. You don't need a secret edge. You need a few solid moves, put together with discipline. Here's the whole anatomy. Go beat it. — *Soham*

---

## What a strong bot actually does — 4 moves

1. **Hold what's working.** Each day (or week), rank a basket of stocks by recent return and hold the strongest few. Winners tend to keep winning for a while.
2. **Get out when it breaks.** The single most important move. If the market falls below its long-term average, step aside into cash. This one rule does more for your score than any clever signal.
3. **Size by calm, not by hope.** Put more money into steady names, less into jumpy ones. When the whole market gets volatile, shrink everything.
4. **Never bet the farm.** Keep each position small, keep leverage low. (The contest auto-flattens you if you break the caps anyway — so build inside them from the start.)

## The one rule that matters

You are **not** scored on who makes the most money. You're scored on making money **without a big crash** (return ÷ your worst drop).

> +10% with a tiny dip beats +30% with a scary −25% drop.

So always give your bot a way to **step to cash**. That habit beats every fancy trick.

---

## A complete recipe you can copy — the AI play

Bet on the AI boom, but don't get caught when it turns. You can say the whole thing in one sentence: **hold the strongest AI & chip stocks while they're going up, and move to cash when the market rolls over.**

- **What you hold:** the AI / chip leaders — NVDA, AMD, MU, MRVL, AVGO, SMH. (Believe in something else — robotics, nuclear, whatever? Swap in your own basket.)
- **Every day:** keep the **3–4 strongest** (biggest gain over the last 3 months), split evenly, **max 25% each** — but only the ones still **trending up** (trading above their recent average, not falling).
- **The safety switch:** if the overall market (QQQ) drops **below its long-term average**, go to **100% cash**. Full stop. This is the part that saves you in a crash — and it's exactly what the scoring rewards.
- **Keep it calm:** rebalance about once a week (not every minute), no heavy leverage, long-only.

That's the whole thing. Pick a theme you believe in, ride the winners, and always keep a way out.

## Paste this into your AI to build it

Open Claude / ChatGPT / Cursor and paste this, along with `AGENT_BRIEF.md`:

> Build me a `decide()` function for the builderr trading challenge. Each day, rank NVDA, AMD, MU, MRVL, AVGO, SMH by their 3-month return and hold the top 4 equally (max 25% each) — but only the ones above their 50-day moving average; the rest in cash. Add a safety switch: if QQQ is below its 100-day average, hold 100% cash regardless. Rebalance weekly, keep beta-adjusted gross under 1.4×, long-only, no LLM calls — plain Python. Follow the rules in AGENT_BRIEF.md exactly.

Then run `python preview.py`. A green **PASS** means you're in.

---

## Why I'm happy to give this away

This recipe isn't a secret — it's a simple, well-known approach anyone can find. The edge was never the recipe; it's the discipline and the small, smart choices you add on top. There's plenty of room to do better. That's the whole point — **go build something that beats it.**

## What NOT to do (the traps)

- **Don't chase the biggest return** — chase the smoothest. Survival wins.
- **Don't go all-in on leverage** (TQQQ / SOXL). It gets auto-flattened, and it quietly bleeds in choppy markets.
- **Don't curve-fit** until the backtest looks perfect. A perfect backtest dies live.
- **Don't overcomplicate.** Fewer knobs = fewer ways to fool yourself.

---

## Go

- **Fork the template:** https://github.com/builderr-ai/builderr-trading-template
- **Read this first if you're new:** [`START_HERE.md`](START_HERE.md)
- **Stuck? Ask anything:** https://discord.gg/SghaTDF5
- **Enter the challenge:** https://builderr.ai/trading-v0

Free to enter. No money, no API key. You can revise up to 4 times — your first try isn't your last. 🚀
