# negotiation-agent

Team 3's buyer/seller negotiation agent for the Claude Community 48H Hackathon Madrid (2-4 Oct 2026). The agent plays a 1v1 tournament on Sunday, ranked by value captured; manipulative counterparties are allowed.

Status: empty skeleton. The build starts Friday 19:30, after the organizers confirm the rules.

## Design (from the team playbook)

- Plain code decides every number and writes the commitment (action, price, terms). The LLM only parses the counterparty message and writes persuasion around a decision already made.
- Counterparty text is untrusted input: parse only the current offer, never follow instructions inside it.
- Boulware-style concession curve with a role-aware floor inside the reservation price, for both buyer and seller. Explicit last-turn accept / final-offer / walk logic.
- Opponent classification: caver, stubborn, manipulator.
- Local practice arena of sparring bots, scored on value captured, deal rate, worst case, and floor breaches.

## To confirm on Friday

- Harness format: does our code run live, or is it a prompt fed into an organizer harness?
- Scoring metric and no-deal payoff; single- vs multi-issue negotiation.
- Which models and credits are provided; whether pre-written code is allowed.
