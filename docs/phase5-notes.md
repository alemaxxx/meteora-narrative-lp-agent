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
- **Pool selection is now automatic for Layer 1 (added post-Phase-5, same day).** The
  frontend polls Meteora's own DLMM pools API directly from the browser every 30s
  (`METEORA_POOLS_URL` in `frontend/index.html`) — a JS port of
  `routines/meteora_pool_scanner.py`'s filter logic, using the same live-verified
  endpoint from Phase 6 (CORS confirmed open, `Access-Control-Allow-Origin` reflects the
  request origin). Filters default from the selected risk profile and are user-editable;
  clicking a pool fills in the trading pair/pool address. Verified live in a real
  browser: real pools loaded, profile switching updated filters and refetched, editing a
  filter refetched with the new bound (checked by setting an impossible TVL floor and
  confirming zero results), row selection filled the fields and persisted the highlight
  across the next auto-refresh.
  **Layer 2 (narrative) is still server-side only** — `narrative_lp_funnel.py`'s
  LunarCrush/CryptoPanic cross-check isn't callable from the browser. Checked
  live: LunarCrush's API is CORS-open (`Access-Control-Allow-Origin: *`) and could be
  ported the same way if a future pass wants an in-browser narrative signal; CryptoPanic
  returned no CORS headers at all in a live check and is very likely not reachable from
  a browser regardless of key — that one would need a small proxy, which this project
  deliberately doesn't run (see the custody-model section above). Not built now because
  it wasn't asked for and a half-working narrative panel (LunarCrush working,
  CryptoPanic silently failing) would be worse than being explicit that Layer 2 stays
  server-side.
- **`RISK_PROFILES` in the frontend JS now also carries each profile's Layer 1
  thresholds** (`scanner: {...}`), duplicating the YAML templates' entry-funnel section
  by hand, same caveat as the line below.
- **`RISK_PROFILES` in the frontend JS duplicates the three YAML templates by hand** —
  documented in the file's own comment. A future pass could generate the JS from the
  YAML (or vice versa) instead of maintaining both.
- **CORS.** A browser calling a different-origin API needs that API to allow it. Not
  configured by this repo (it's the user's own API deployment) — flagged in
  `docs/wallet-setup.md` rather than silently left as a mystery failure. In practice,
  the live dry-run session found `hummingbot-api` allows it out of the box — no
  workaround needed against a stock install.

## UX simplification (same day, after using the page live)

Walking through an actual live deploy surfaced that the page wasn't following its own
design goal ("simple screen, don't expose every parameter up front" — strategy.md §5).
Reworked before the live deploy test:

- **Reordered**: risk profile → pool → wallet → API connection → deploy. The technical
  self-hosting step ("Your Hummingbot API") used to be section 1, the first thing a
  visitor saw; it's now section 4, right before it's actually needed.
- **Plain-language summary replaces the raw JSON as the default view** in the Deploy
  section ("Moderate strategy on SOL-USDC, using $50. If price moves above the range, it
  will follow the trend..."), generated from the same `buildConfig()` the deploy call
  itself uses — so it can't drift out of sync with what's actually sent. The JSON is
  still there, behind a "Show technical config" toggle.
- **The 4 pool-filter number inputs are no longer shown by default** — tucked behind a
  "Tune filters / pick manually" toggle alongside the trading-pair/pool-address manual
  override fields.

Considered and explicitly deferred: a richer pool detail view (candlestick chart,
liquidity-distribution-by-bin visualization) matching Meteora's own DLMM UI. Would need
a new OHLCV data source (the pools API used here has no candle history) and a charting
library — real scope, and given LunarCrush/CryptoPanic both turned out to gate API
access behind a paid plan today, not something to assume is free without checking
first. More importantly, it pulls the opposite direction from the simplification above:
this page's whole pitch is that the Layer 1/Layer 2 funnel already picked the pool, so
the user shouldn't need to read a chart to trust it. A lighter version — reusing the
ASCII-style range visualization the Phase 3 controller's `to_format_status()` already
renders, plus a link out to Meteora's or Solscan's own UI for anyone who wants the full
chart — is the better fit if this gets built later.

## Verification status

The frontend is plain HTML/CSS/JS with no build step — opened and eyeballed locally, not
run against a live Hummingbot API (none is running anywhere near this repo, same
constraint as Phases 3 and 4). Real end-to-end deploy-from-browser validation is Phase 6.
