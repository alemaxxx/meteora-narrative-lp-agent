# Wallet setup

**Your private key never goes to this project's frontend, or to any server this
project operates — because there is no such server.** You run your own Hummingbot
Gateway instance; your key is imported into and encrypted by *that* instance, on your
own machine. This doc walks through that.

See [docs/phase5-notes.md](./phase5-notes.md) for why this is the model — short version:
Gateway needs the key available to sign autonomously so the bot can rebalance without
you being online, so a "sign every transaction from your browser" flow can't deliver
unattended operation. Self-hosting your own Gateway is what keeps custody with you
instead of moving it to shared infrastructure.

## 1. Run your own Gateway (and Hummingbot API)

Follow Hummingbot's own setup — this repo doesn't bundle or fork Gateway, it targets a
standard instance you run:

- Gateway: https://hummingbot.org/gateway/installation/
- Hummingbot API (the REST layer [frontend/index.html](../frontend/index.html) talks
  to): https://hummingbot.org/hummingbot-api/installation/

## 2. Generate or import a Solana wallet, locally, into your Gateway

Gateway encrypts wallet keys at rest with your Gateway passphrase (scrypt + AES-256-GCM)
and never returns the raw key to any client, bot, or agent connected to it — including
this project's routines and frontend, which only ever see the public address.

- To generate a fresh wallet inside Gateway's own tooling, use its `pnpm wallet:create`
  script (see Gateway's docs above for the current exact command for your version).
- To import an existing wallet, use Gateway's wallet-add flow (CLI or, if you're running
  the Hummingbot client, the `gateway connect` / add-wallet prompts) — you'll be asked
  to paste the private key **once, into Gateway's own local prompt**, and set/confirm the
  Gateway passphrase that encrypts it. That's the only place a key is ever entered.

## 3. Fund the wallet

Send SOL (for rent + fees) and whatever quote asset your chosen risk profile needs
(`total_amount_quote` in the profile — see `conf/controllers/*.example.yml`) directly to
the wallet's public address, from any wallet or exchange you already use. Nothing in
this repo touches this step — it's a plain on-chain transfer to an address you now
control via your own Gateway.

## 4. Point the frontend at your own API

Open [frontend/index.html](../frontend/index.html) (locally, or hosted anywhere you
like — it's a static file with no server component), fill in:

- Your Hummingbot API URL, username, and password — these stay in your browser's
  localStorage and are sent only to the URL you typed, when you click a button on the
  page.
- Your wallet's **public** address, for display/verification only.
- A risk profile (or the advanced fields).
- The trading pair and pool address you want to deploy against.

Click "Deploy controller." The page calls your own API directly — this project never
sees the request.

## If the browser call fails with a CORS error

Your Hummingbot API needs to allow cross-origin requests from wherever you're opening
`frontend/index.html`. Either enable CORS on your API deployment for that origin, or
serve `frontend/index.html` from the same origin as the API (simplest for a local
single-user setup). Not configured by default in this repo — see
[docs/phase5-notes.md](./phase5-notes.md).
