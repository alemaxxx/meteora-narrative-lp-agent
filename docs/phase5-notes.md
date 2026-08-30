# Phase 5 notes — multi-user / connect wallet

## A correction to strategy.md's original framing, made before writing any code

strategy.md §6 originally said users "connect their own wallet (client-side signing) —
no private key is ever held server-side," implying a Phantom/Solflare-style
"Connect Wallet" button that signs each transaction live from the browser. Before
building that, I checked how Hummingbot Gateway actually handles wallets (see
[docs/research-phase1-notes.md](./research-phase1-notes.md)'s sibling check for this
phase): Gateway imports a private key and encrypts it at rest (scrypt + AES-256-GCM),
then signs autonomously using that stored key — it does not have a stock "external
signer" flow where a browser wallet co-signs each transaction live.

That's not a Gateway shortcoming, it's a real constraint of the requirement: **the bot
has to rebalance without a human online to approve each transaction** (the hackathon's
own "runs without human intervention during the final" rule). A pure client-side signing
model — the user's wallet extension approving every rebalance in real time — can't
deliver that; the signing key has to be available to *something* that runs unattended.

## The model this phase actually implements

Custody stays with the user by keeping the signer **entirely on infrastructure they run
themselves** — their own Gateway + Hummingbot API instance, not a shared backend this
project operates:

- [`frontend/index.html`](../frontend/index.html) is a single static file, no server
  component of ours. It asks for the user's *own* API URL/credentials and their wallet's
  *public* address — never a private key — and calls their API directly from the browser.
- [`docs/wallet-setup.md`](./wallet-setup.md) walks through importing a key into the
  user's own Gateway instance, the one place a key is ever entered, encrypted locally by
  Gateway's own passphrase.
- This project — the repo, the frontend, the routines — never runs infrastructure that
  holds, transmits, or could leak a user's key. That's the honest scope of "non-custodial"
  achievable on top of Gateway's real architecture: self-hosting moves custody to the
  user, it doesn't invent client-side signing Gateway doesn't have.

strategy.md §6 has been updated to say this precisely instead of the original,
inaccurate framing.

## What's genuinely multi-user vs. what still needs work

- **Multi-user today** means: any number of people can each run their own copy of this
  stack (Gateway + API + this repo's controller/routines + this frontend) against their
  own wallet. Nothing in the code assumes a single fixed user.
- **Not built:** a shared, hosted version of this project where many users show up to
  one URL and each gets an isolated deployment without personally standing up Gateway —
  that would need real backend infrastructure (per-user credential isolation, likely the
  Privy-server-wallet-style policy-controlled signing hummingbot/gateway has an open
  issue for, not shipped yet) and is out of scope for this phase.
- **Pool selection is manual in the frontend.** `narrative_lp_funnel.py` (Phase 4) does
  automatic Layer 1 + Layer 2 discovery server-side, but the frontend doesn't call it —
  it deploys against a `trading_pair`/`pool_address` the user pastes in. Wiring the
  frontend to trigger and display funnel results is a natural next step, not built here.
- **`RISK_PROFILES` in the frontend JS duplicates the three YAML templates by hand** —
  documented in the file's own comment. A future pass could generate the JS from the
  YAML (or vice versa) instead of maintaining both.
- **CORS.** A browser calling a different-origin API needs that API to allow it. Not
  configured by this repo (it's the user's own API deployment) — flagged in
  `docs/wallet-setup.md` rather than silently left as a mystery failure.

## Verification status

The frontend is plain HTML/CSS/JS with no build step — opened and eyeballed locally, not
run against a live Hummingbot API (none is running anywhere near this repo, same
constraint as Phases 3 and 4). Real end-to-end deploy-from-browser validation is Phase 6.
