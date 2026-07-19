# Start here 👋 (read this first)

You're going to build a tiny trading bot. If it's good, you win money — and the #1 bot trades a **real $100,000**.

**You do NOT need:**
- a finance degree
- to be a great coder
- any money, a bank login, or an API key

**You DO need:**
- about 10 minutes
- a free GitHub account
- to be willing to copy an idea and tweak it

---

## What you're actually building

One small function called `decide()`. Every day it looks at recent prices and says *"buy this, sell that."* That's the whole game.

---

## Do this first (5 minutes, just copy-paste)

```bash
git clone https://github.com/builderr-ai/builderr-trading-template
cd builderr-trading-template
cp baseline.py agent.py        # this alone is a real, valid bot
python preview.py              # runs in ~10s, prints PASS or FAIL
```

`preview.py` says **PASS** = your bot is allowed in. `baseline.py` already passes — so you have a working bot in 5 minutes, before writing a single line. Now go make it better.

---

## Pick an idea to start from

You don't need a genius idea of your own. **Steal one of these and tweak it.** (Markets move — none of these is a sure thing.)

1. **Ride the AI boom** — hold the strongest AI / chip stocks (NVDA, AMD, MU, MRVL, AVGO), and step aside when they start falling.
2. **Buy the market, with a safety switch** — hold QQQ while it's going up; move to cash when it turns down.
3. **Rotate into what's working** — each week, hold the 3 hottest sectors; skip the rest.
4. **Play defense when it gets scary** — ride the market in calm times, hide in safe stuff (XLP / XLU) when it drops.
5. **A little leverage, carefully** — small TQQQ / QLD only when things are calm; dump it the moment it gets choppy.

Want the exact *"paste into your AI"* version of each one? → **https://builderr.ai/start**

Want the full breakdown of how a strong bot is built (plain English + a complete copy-paste recipe)? → **[`ANATOMY.md`](ANATOMY.md)**

---

## The one rule that actually matters

You are **NOT** scored on who makes the most money. You're scored on making money **without a big crash.**

> +10% with a tiny dip beats +30% with a scary −25% drop.

So always give your bot a way to **step to cash** when the market drops. That one habit beats every fancy trick.

---

## 5 simple tips

- **AI and chips are hot right now** — a basket of those names is a fine place to start.
- **Always add a "go to cash" switch** for when the market falls. This is the single biggest thing you can do.
- **Don't go all-in on leverage** (TQQQ / SOXL). The rules auto-flatten you, and these can lose ~80% in a bad year.
- **Keep it simple.** Fewer rules = fewer ways to fool yourself.
- **Test before you send** — run `python preview.py` after every change.

---

## Want to build it with AI? (totally fine)

Paste **[`AGENT_BRIEF.md`](AGENT_BRIEF.md)** into Claude / ChatGPT / Cursor, describe your idea in plain English, and it writes the bot with you. It already knows all the rules.

---

## Submit it (when you're happy)

1. Push your repo to GitHub.
2. Email the link to **submit@builderr.ai** (or submit at **https://builderr.ai/trading-v0**).
3. We email your result the same day. You can **revise up to 4 times** — your first try is not your last.

---

## Stuck? Ask anything

Join the Discord — no question is too basic, and beginners are very welcome:

**https://discord.gg/SghaTDF5**

Free to enter. Good luck — go build something. 🚀
