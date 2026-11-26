# LeadDesk: how the support team uses it

One page for the people who work the queue. Nothing is sent to a client until a person approves it.

## Every day

1. Open **Inbox**. Tickets marked **Overdue** have passed their reply deadline: do those first, then the rest by priority.
2. Open a ticket. Check three things:
   - **Category and queue**: is it the right team? If not, reassign it in Monday and add a note.
   - **Lead check** (lead complaints only): *Replace lead* means the lead failed a rule, such as being shared, having
     no consent, or being out of state. The replacement is owed. *Valid lead · coach the agent* means the lead was fine,
     and the reply explains what to do differently, usually calling sooner. *Needs review* means the record looks clean
     and the agent called quickly, so the complaint (a fax line, a fake answer) has to be checked by a person, for example
     against the call recording. These verdicts come from fixed rules, not from the AI.
   - **Drafted reply**: read it, fix anything wrong, then **Approve**. Edits are counted. A high edit rate tells us
     the drafts need work.
3. For tickets from Go High Level, approving sends the reply to the contact by SMS or email. If the send fails, the
   ticket says so: press **Retry send**, or reply in GHL by hand.
4. **Call notes**: paste a call transcript after each client call. Check the action items, then work them from the
   Monday board, where each one is a subitem.

## What each queue means

| Queue | Owner | What lands there |
|---|---|---|
| Lead ops | Lead Ops team | Lead complaints: replacements and disputes |
| Account manager | the client's account manager | Cancellations, churn risk, appointment problems, coaching on valid leads |
| Billing | Billing team | Charges, invoices, receipts, refunds |
| Campaign ops | Campaign Ops team | States, volume, pauses, targeting |
| Support | Support desk | Logins, app problems, CRM or webhook not receiving leads |
| Human review | Support lead | The AI wasn't sure, or the AI was unavailable. Decide the category yourself |

Reply deadlines by priority: urgent 1 hour, high 4 hours, normal 1 day, low 2 days.

## Changing a rule

All business rules live in one file: `config/rules.json`. It holds queue owners, reply deadlines, the churn and
confidence thresholds, the replacement window, the annuity asset minimum, and the time-saved assumptions.

1. Edit the value. Each section has a note saying what it does.
2. Restart the app: `sudo systemctl restart leaddesk-api`. If a value is invalid, such as a misspelled queue or a
   threshold above 1, the app refuses to start and says which value is wrong.
3. Ask whoever maintains the system to re-run the checks: `python -m evals.run_eval --set all` and `pytest`. A
   threshold change can move tickets between queues, and the eval shows by how much.

## When something looks wrong

- **Wrong category or queue**: send the ticket id to the maintainer. It goes into the eval set, so the fix is
  tested and stays fixed.
- **Wrong replace/valid verdict**: that's a rule, not the AI. The maintainer changes the rule and adds a test.
- **AI down**: tickets still come in. The local model guesses the category, and every such ticket goes to human
  review.
