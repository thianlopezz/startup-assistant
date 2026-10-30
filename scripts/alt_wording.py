import asyncio, sys
from pathlib import Path
from startup_assistant.agent import Assistant
from startup_assistant.briefs import BriefStore

MSGS = [
    "what's our latest brief?",
    "btw, remember we no longer sell to agencies. We now go after B2B software companies with 100-500 people, and the Head of Customer Success is the buyer. Also keep prices out of any marketing for now.",
    "what do we charge?",
    "who do we sell to these days?",
]

async def main(d):
    async with Assistant(Path(d)) as a:
        for m in MSGS:
            r = await a.handle(m)
            print(f"\n>>> {m}\n{r.text}\nARTIFACTS={len(r.artifacts)} ACTIONS={r.actions} BRIEFS={len(BriefStore(Path(d)/'briefs.json').list())}")

asyncio.run(main(sys.argv[1]))
