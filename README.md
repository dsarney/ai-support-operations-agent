# AI Support Operations Agent

A local demo of an AI support agent for a fictional B2B product, **Northstar Cloud**. It triages tickets, looks up knowledge, investigates with mock tools, and only remediates when a deterministic policy says it is safe. It does not connect to Zendesk, Stripe, Slack, or any production system.

## Launch

**First time**

```bash
git clone https://github.com/dsarney/ai-support-operations-agent.git
cd ai-support-operations-agent
make setup
```

Put your OpenAI key in `.env` (`OPENAI_API_KEY=...`).

**Start the demo**

```bash
make demo
```

When the terminal prints `Dashboard: http://127.0.0.1:8000`, open that URL.

The page is ready immediately. Tickets fill in as the agent works (a minute or two). Keep the terminal open — closing it stops the server.

No OpenAI key? Use `make fake-demo` instead.

## What you will see

Open a ticket on the dashboard to follow each stage (classify, retrieve, investigate, diagnose, policy, remediate, verify, reply), plus the audit trail and any linked incident.

The agent may auto-do low-risk actions: unlock an account, resend a verification email, rotate a workspace API key (secret is never shown), retry a webhook, or clear a stale cache. It will never auto-do refunds, credits, plan changes, account deletion, data export, or admin impersonation. Legal, GDPR, billing disputes, suspected account takeover, and outages always escalate.

## More commands

```bash
make test                          # run tests (no OpenAI calls)
python -m src serve --reload       # dashboard only, no reset
python -m src seed                 # reload demo data
python -m src run-all              # run the agent on open tickets
```

If you do not have `make`, the equivalents are `python3 -m venv venv`, `source venv/bin/activate`, `pip install -r requirements.txt`, then `python -m src demo` (or `python -m src demo --fake-llm`).
