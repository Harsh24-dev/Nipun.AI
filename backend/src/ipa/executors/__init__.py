"""
Executors — one per surface the agent can act on. Each conforms to the same contract:

    async def run(session: TaskSession) -> None

It reads the plan, performs the ordered actions (streaming step/log/action events onto
session.queue exactly like the web agent), honours pause/stop, and hands sensitive steps to the
user. The controller (src.ipa.controller) picks the executor by plan.surface. This is what makes
the SAME plan → one-form → live-execution → human-in-loop experience work for the web, the app,
and the device alike.
"""
